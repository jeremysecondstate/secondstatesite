"""Reviewed API reconciliation is authenticated, atomic and safely repeatable."""

from datetime import timedelta
from decimal import Decimal
import gzip
import json
import os
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .calendar_duplicates import fingerprint, rollback_receipt
from .models import (AuctionEmailBatch, AuctionEmailBatchItem, AuctionLotReconciliation,
                     AuctionLotSupersessionReceipt, AuctionWatchLot)
from .tests_calendar import stored_analysis, watch_lot


KEY = "calendar-reconciliation-test-key"


@patch.dict(os.environ, {"CATALOG_API_KEY": KEY})
class CalendarReconciliationTests(TestCase):
    def setUp(self):
        self.endpoint = reverse("calendar_reconciliation")

    def pair(self, suffix="", **old_overrides):
        keep = watch_lot(source_lot_id=f"preferred{suffix}",
                         lot_url=f"https://www.invaluable.com/auction-lot/test-1-c-abc{suffix or '123'}")
        old = watch_lot(source="Drouot", source_lot_id=f"duplicate{suffix}",
                        lot_url=f"https://drouot.com/en/l/123{suffix}-test", **old_overrides)
        return keep, old

    def plan(self, *pairs, operation="test-run"):
        return {"version": 1, "operation": operation, "reviewed": True, "pairs": [
            {"keep_id": keep.pk, "remove_id": old.pk,
             "keep_fingerprint": fingerprint(keep), "remove_fingerprint": fingerprint(old),
             "reason": "Verified same sale and catalogue lot, matching work details."}
            for keep, old in pairs
        ]}

    def post(self, payload):
        return self.client.post(self.endpoint, json.dumps(payload), content_type="application/json", HTTP_X_API_KEY=KEY)

    def get(self, **params):
        return self.client.get(self.endpoint, params, HTTP_X_API_KEY=KEY)

    def test_both_methods_require_the_existing_key_even_for_staff(self):
        staff = get_user_model().objects.create_user(username="reconciliation-staff", is_staff=True)
        self.client.force_login(staff)
        for method in (self.client.get, self.client.post):
            self.assertEqual(method(self.endpoint).status_code, 401)
            self.assertEqual(method(self.endpoint, HTTP_X_API_KEY="wrong").status_code, 401)
        with patch.dict(os.environ, {"CATALOG_API_KEY": ""}):
            self.assertEqual(self.get().status_code, 401)
        self.assertFalse(AuctionLotReconciliation.objects.exists())

    def test_public_readback_includes_future_hidden_rows_but_no_staff_state(self):
        keep, old = self.pair(current_bid=Decimal("120.75"), bid_count=3,
                              won_by_us=True, artprice_url="https://www.artprice.com/artist/1")
        old.superseded_by = keep
        old.active = False
        old.event_at = keep.event_at + timedelta(days=120)
        old.save()
        watch_lot(source="Heritage", source_lot_id="unrelated-source")
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response.headers["Cache-Control"])
        rows = {row["id"]: row for row in response.json()["lots"]}
        self.assertEqual(set(rows), {keep.pk, old.pk})
        self.assertEqual(rows[old.pk]["current_bid"], "120.75")
        self.assertEqual(rows[old.pk]["bid_count"], 3)
        self.assertEqual(rows[old.pk]["superseded_by_id"], keep.pk)
        self.assertEqual(rows[old.pk]["fingerprint"], fingerprint(old))
        self.assertFalse({"won_by_us", "artprice_url", "research", "email_batch_items"} & rows[old.pk].keys())
        self.assertFalse(AuctionLotReconciliation.objects.exists())

    def test_pagination_and_specific_ids_are_complete(self):
        keep, old = self.pair()
        first = self.get(page_size=1).json()
        second = self.get(page_size=1, cursor=first["next_cursor"]).json()
        self.assertEqual([first["lots"][0]["id"], second["lots"][0]["id"]], [keep.pk, old.pk])
        self.assertIsNone(second["next_cursor"])
        self.assertEqual([row["id"] for row in self.get(ids=str(old.pk)).json()["lots"]], [old.pk])
        for params in ({"cursor": "-1"}, {"ids": "0"}, {"page_size": "501"}, {"start": "not-a-date"}):
            self.assertEqual(self.get(**params).status_code, 400)

    def test_gzip_is_negotiated_only_for_readback(self):
        keep, old = self.pair()
        headers = {"HTTP_X_API_KEY": KEY, "HTTP_ACCEPT_ENCODING": "gzip"}
        with patch("django.utils.timezone.now", return_value=keep.event_at):
            plain = self.get()
            compressed = self.client.get(self.endpoint, **headers)
        self.assertNotIn("Content-Encoding", plain.headers)
        self.assertEqual(compressed.headers["Content-Encoding"], "gzip")
        self.assertIn("Accept-Encoding", compressed.headers["Vary"])
        self.assertIn("no-store", compressed.headers["Cache-Control"])
        self.assertEqual(gzip.decompress(compressed.content), plain.content)
        receipt = self.client.post(self.endpoint, self.plan((keep, old)), content_type="application/json", **headers)
        self.assertTrue(receipt.json()["ok"])
        self.assertNotIn("Content-Encoding", receipt.headers)

    def test_audit_is_bounded_and_never_applies_candidates(self):
        keep, old = self.pair()
        self.assertEqual(self.get(mode="audit").status_code, 400)
        result = self.get(mode="audit", ids=f"{keep.pk},{old.pk}").json()
        self.assertEqual(result["audit"]["pairs"][0]["keep_id"], keep.pk)
        old.refresh_from_db()
        self.assertIsNone(old.superseded_by_id)

    def test_apply_preserves_source_fields_research_and_tray_and_can_be_rolled_back(self):
        keep, old = self.pair(current_bid=Decimal("200"), bid_count=4, won_by_us=True)
        analysis = stored_analysis(old)
        tray = AuctionEmailBatchItem.objects.create(batch=AuctionEmailBatch.objects.create(), lot=old)
        result = self.post(self.plan((keep, old)))
        self.assertEqual(result.status_code, 200, result.content)
        old.refresh_from_db(); analysis.refresh_from_db(); tray.refresh_from_db()
        self.assertEqual(old.superseded_by_id, keep.pk)
        self.assertFalse(old.active)
        self.assertEqual((old.current_bid, old.bid_count, old.won_by_us), (Decimal("200"), 4, True))
        self.assertEqual((analysis.lot_id, tray.lot_id), (old.pk, old.pk))
        self.assertEqual(AuctionWatchLot.objects.count(), 2)
        receipt = result.json()["receipt"]
        self.assertEqual(AuctionLotReconciliation.objects.get().receipt, receipt)
        self.assertEqual(AuctionLotSupersessionReceipt.objects.get().lot_id, old.pk)
        self.assertEqual(rollback_receipt(receipt), 1)
        old.refresh_from_db()
        self.assertIsNone(old.superseded_by_id)
        self.assertTrue(old.active)

    def test_retry_returns_original_receipt_and_changed_plan_conflicts(self):
        keep, old = self.pair()
        plan = self.plan((keep, old))
        first = self.post(plan).json()
        retry = self.post(plan)
        self.assertEqual(retry.status_code, 200)
        self.assertTrue(retry.json()["replayed"])
        self.assertEqual(first["receipt"], retry.json()["receipt"])
        self.assertEqual(AuctionLotSupersessionReceipt.objects.count(), 1)
        plan["pairs"][0]["reason"] = "Changed explanation"
        self.assertEqual(self.post(plan).status_code, 409)
        saved = self.get(operation="test-run").json()
        self.assertEqual(saved["receipt"], first["receipt"])
        self.assertEqual(self.get(operation="missing").status_code, 404)

    def test_merge_into_regular_survivor_retires_and_rollback_restores_only_independent_membership(self):
        keep, old = self.pair(random_lot=True, artist="Off-roster artist", artist_watchlist_name="")
        other = watch_lot(source_lot_id="separate-impression", random_lot=True,
                          artist="Unidentified printmaker", artist_watchlist_name="")
        result = self.post(self.plan((keep, old)))
        self.assertEqual(result.status_code, 200, result.content)
        old.refresh_from_db()
        self.assertEqual((old.superseded_by_id, old.random_lot), (keep.pk, False))
        self.client.force_login(get_user_model().objects.create_user("catalog-reviewer", is_staff=True))
        day = {"day": "2026-07-25"}
        random_url = reverse("auction_calendar_random_lots")
        self.assertEqual([r["id"] for r in self.client.get(random_url, day).json()["lots"]], [other.pk])
        self.assertEqual([r["id"] for r in self.client.get(reverse("auction_calendar_day_lots"), day).json()["lots"]],
                         [keep.pk])
        self.assertEqual(rollback_receipt(result.json()["receipt"]), 1)
        old.refresh_from_db()
        self.assertIsNone(old.superseded_by_id)
        self.assertTrue(old.random_lot)
        self.assertEqual({r["id"] for r in self.client.get(random_url, day).json()["lots"]}, {old.pk, other.pk})

    def test_stale_pair_rejects_entire_plan_and_operation_record(self):
        keep, old = self.pair()
        keep2, old2 = self.pair("2")
        plan = self.plan((keep, old), (keep2, old2))
        AuctionWatchLot.objects.filter(pk=old2.pk).update(title="A different edition")
        response = self.post(plan)
        self.assertEqual(response.status_code, 409)
        self.assertFalse(AuctionWatchLot.objects.filter(superseded_by__isnull=False).exists())
        self.assertFalse(AuctionLotReconciliation.objects.exists())
        self.assertFalse(AuctionLotSupersessionReceipt.objects.exists())

    def test_receipt_failure_rolls_back_suppressions(self):
        keep, old = self.pair()
        with patch("secondstateapp.calendar_reconciliation_views.AuctionLotSupersessionReceipt.objects.create",
                   side_effect=ValueError("Receipt write failed")):
            self.assertEqual(self.post(self.plan((keep, old))).status_code, 409)
        old.refresh_from_db()
        self.assertIsNone(old.superseded_by_id)
        self.assertFalse(AuctionLotReconciliation.objects.exists())

    def test_reverse_preference_and_other_providers_are_rejected(self):
        keep, old = self.pair()
        self.assertEqual(self.post(self.plan((old, keep))).status_code, 409)
        old.source = "Forum"
        old.save()
        self.assertEqual(self.post(self.plan((keep, old))).status_code, 409)

    def test_existing_children_and_repeat_removals_are_rejected(self):
        keep, old = self.pair()
        child = watch_lot(source_lot_id="retained-child", superseded_by=old, active=False)
        self.assertEqual(self.post(self.plan((keep, old))).status_code, 409)
        child.superseded_by = None
        child.save()
        self.assertEqual(self.post(self.plan((keep, old), (keep, old))).status_code, 409)

    def test_unreviewed_malformed_and_oversized_payloads_cannot_mutate(self):
        keep, old = self.pair()
        plan = self.plan((keep, old))
        for mutate in (lambda p: p.update(reviewed=False), lambda p: p.update(operation="../bad"),
                       lambda p: p["pairs"][0].update(keep_id=True),
                       lambda p: p["pairs"][0].update(remove_fingerprint="stale")):
            bad = json.loads(json.dumps(plan))
            mutate(bad)
            self.assertEqual(self.post(bad).status_code, 400)
        response = self.client.post(self.endpoint, "x" * 1_000_001,
                                    content_type="application/json", HTTP_X_API_KEY=KEY)
        self.assertEqual(response.status_code, 413)
        old.refresh_from_db()
        self.assertIsNone(old.superseded_by_id)
