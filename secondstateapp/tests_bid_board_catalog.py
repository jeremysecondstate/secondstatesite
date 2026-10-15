"""Saved Bid Board catalog data and per-lot email opt-in regressions."""

import json
from copy import deepcopy
from datetime import datetime, timezone as datetime_timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .bid_board_snapshot import saved_board_snapshot, saved_board_summary
from .calendar_views import _lot_json
from .models import (
    AuctionBidBoardAnalysis,
    AuctionEmailBatch,
    AuctionEmailBatchItem,
    AuctionWatchLot,
    LiveArtResaleAnalysis,
)


@override_settings(CALENDAR_TIME_ZONE="UTC", AUCTION_EMAIL_SENDING_ENABLED=False)
class SavedBidBoardCatalogTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user("saved-board-staff", is_staff=True)
        self.client.force_login(self.staff)
        self.lot = self.create_lot("saved-board")
        self.edit_url = reverse("auction_lot_bid_board", args=(self.lot.pk,))
        self.saved_url = reverse("auction_lot_saved_bid_board", args=(self.lot.pk,))
        self.email_url = reverse("auction_lot_bid_board_email", args=(self.lot.pk,))

    def create_lot(self, source_id, *, month=10):
        return AuctionWatchLot.objects.create(
            source="test", source_lot_id=source_id, artist="Artist", title="Print",
            currency="USD", current_bid="1000", bid_count=1,
            event_at=datetime(2026, month, 15, 15, tzinfo=datetime_timezone.utc),
        )

    def save_board(self, *, lot=None, selected_bid="1400", selected_case="working", assumptions=None):
        response = self.client.post(
            reverse("auction_lot_bid_board", args=((lot or self.lot).pk,)),
            json.dumps({
                "action": "save", "selected_bid": selected_bid, "selected_case": selected_case,
                "assumptions": {
                    "starting_hammer": "1000", "starting_basis": "opening",
                    "buyer_premium_pct": "25", "acquisition_costs": "200",
                    "minimum_profit": "500", "minimum_return_pct": "20",
                    "resale_overrides": {"conservative": "2400", "working": "3000", "optimistic": "4000"},
                    **(assumptions or {}),
                },
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        return AuctionBidBoardAnalysis.objects.get(lot=lot or self.lot)

    def set_email_preference(self, include):
        return self.client.post(
            self.email_url, json.dumps({"include_in_email": include}), content_type="application/json",
        )

    def test_saved_endpoint_preserves_financial_and_evidence_snapshot_after_source_changes(self):
        record = self.save_board()
        original_analysis = deepcopy(record.analysis)
        original_evidence = deepcopy(record.evidence_snapshot)
        original_assumptions = deepcopy(record.assumptions)
        # Live research and the source price may change independently of a save.
        AuctionWatchLot.objects.filter(pk=self.lot.pk).update(current_bid="9000", currency="GBP")
        LiveArtResaleAnalysis.objects.filter(lot=self.lot).update(
            candidates=[{"id": "new-comp", "hammer_usd": "90000"}],
            selected_ids=["new-comp"], source_summary={"combined_comp_count": 1},
        )
        with patch("secondstateapp.bid_board_views.build_board") as rebuild, patch(
            "secondstateapp.bid_board_views._evidence"
        ) as evidence_lookup, patch("secondstateapp.calendar_views._research_liveart_lot") as paid_lookup:
            response = self.client.get(self.saved_url)
        self.assertEqual(response.status_code, 200)
        snapshot = response.json()["board"]
        expected = {
            **original_analysis, "saved": True, "updated_at": record.updated_at.isoformat(),
            "evidence_changed_since_save": False,
        }
        self.assertEqual(snapshot["analysis"], expected)
        self.assertEqual(snapshot["assumptions"], original_assumptions)
        self.assertEqual(snapshot["evidence_snapshot"], original_evidence)
        self.assertEqual(snapshot["selected_ids"], record.selected_ids)
        rebuild.assert_not_called()
        evidence_lookup.assert_not_called()
        paid_lookup.assert_not_called()
        self.assertIn("no-store", response.headers["Cache-Control"])
        record.refresh_from_db()
        self.assertEqual(record.analysis, original_analysis)

    def test_summary_reports_selected_case_ceiling_separately_from_chosen_bid(self):
        record = self.save_board()
        summary = self.client.get(self.saved_url).json()["board"]["summary"]
        self.assertEqual(summary["selected_bid"], "1400.00")
        self.assertEqual(summary["qualifying_bid"], "1800.00")
        self.assertEqual(summary["selected_case"], "working")
        self.assertEqual(summary["selected_case_label"], "Working")
        self.assertTrue(summary["qualifies"])
        self.assertFalse(summary["include_in_email"])
        record = self.save_board(selected_case="conservative", selected_bid="1200")
        summary = saved_board_summary(record)
        self.assertEqual(summary["qualifying_bid"], "1300.00")
        self.assertEqual(summary["selected_bid"], "1200.00")
        self.assertEqual(summary["selected_case"], "conservative")

    def test_nonqualifying_selection_is_not_presented_as_the_qualifying_ceiling(self):
        self.save_board(selected_bid="2000")
        summary = self.client.get(self.saved_url).json()["board"]["summary"]
        self.assertIs(summary["qualifies"], False)
        self.assertEqual(summary["selected_bid"], "2000.00")
        self.assertEqual(summary["qualifying_bid"], "1800.00")

    def test_unavailable_evidence_and_no_qualifying_bid_remain_null(self):
        record = self.save_board(assumptions={"resale_overrides": {}})
        summary = saved_board_summary(record)
        self.assertIsNone(summary["qualifies"])
        self.assertIsNone(summary["qualifying_bid"])
        self.assertIsNone(summary["detail"])
        record = self.save_board(assumptions={"minimum_profit": "10000"})
        summary = saved_board_summary(record)
        self.assertIs(summary["qualifies"], False)
        self.assertIsNone(summary["qualifying_bid"])

    def test_snapshot_copies_do_not_mutate_the_stored_record_in_memory(self):
        record = self.save_board()
        original_analysis = deepcopy(record.analysis)
        snapshot = saved_board_snapshot(record)
        snapshot["analysis"]["rows"].clear()
        snapshot["summary"]["detail"]["net_profit"] = "0.00"
        snapshot["assumptions"]["minimum_profit"] = "0.00"
        snapshot["evidence_snapshot"]["selected_records"].append({"id": "injected"})
        self.assertEqual(record.analysis, original_analysis)
        self.assertEqual(record.assumptions["minimum_profit"], "500.00")
        self.assertEqual(record.evidence_snapshot["selected_records"], [])

    def test_missing_saved_board_and_unknown_lot_return_404(self):
        for lot_id in (self.lot.pk, self.lot.pk + 10000):
            with self.subTest(lot_id=lot_id):
                response = self.client.get(reverse("auction_lot_saved_bid_board", args=(lot_id,)))
                self.assertEqual(response.status_code, 404)
                self.assertFalse(response.json()["ok"])
                response = self.client.post(
                    reverse("auction_lot_bid_board_email", args=(lot_id,)),
                    '{"include_in_email":true}', content_type="application/json",
                )
                self.assertEqual(response.status_code, 404)
        self.assertFalse(AuctionBidBoardAnalysis.objects.exists())

    def test_saved_endpoints_require_staff_and_mutation_requires_csrf(self):
        self.save_board()
        ordinary = get_user_model().objects.create_user("saved-board-ordinary")
        for user in (None, ordinary):
            self.client.logout()
            if user:
                self.client.force_login(user)
            self.assertEqual(self.client.get(self.saved_url).status_code, 302)
            self.assertEqual(self.set_email_preference(True).status_code, 302)
        guarded = Client(enforce_csrf_checks=True)
        guarded.force_login(self.staff)
        self.assertEqual(guarded.get(self.saved_url).status_code, 200)
        self.assertEqual(guarded.post(
            self.email_url, '{"include_in_email":true}', content_type="application/json",
        ).status_code, 403)
        record = AuctionBidBoardAnalysis.objects.get(lot=self.lot)
        self.assertFalse(record.include_in_email)

    def test_saved_read_and_preference_reject_wrong_http_methods(self):
        self.save_board()
        self.assertEqual(self.client.post(self.saved_url).status_code, 405)
        self.assertEqual(self.client.get(self.email_url).status_code, 405)

    def test_email_preference_is_strict_boolean_for_json(self):
        record = self.save_board()
        for value in ("true", "false", 1, 0, None, [], {}):
            with self.subTest(value=value):
                self.assertEqual(self.set_email_preference(value).status_code, 400)
        for body in ("{}", "[]", "true", "invalid JSON"):
            with self.subTest(body=body):
                self.assertEqual(self.client.post(self.email_url, body, content_type="application/json").status_code, 400)
        record.refresh_from_db()
        self.assertFalse(record.include_in_email)

    def test_preference_preserves_saved_analysis_timestamp_and_survives_resaving(self):
        record = self.save_board()
        original = (record.analysis, record.assumptions, record.evidence_snapshot, record.updated_at, record.updated_by_id)
        response = self.set_email_preference(True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["saved_board"]["include_in_email"])
        record.refresh_from_db()
        self.assertEqual(
            (record.analysis, record.assumptions, record.evidence_snapshot, record.updated_at, record.updated_by_id),
            original,
        )
        self.assertTrue(self.client.get(self.saved_url).json()["board"]["include_in_email"])
        record = self.save_board(selected_bid="1500")
        self.assertTrue(record.include_in_email)
        self.assertEqual(record.analysis["selected_bid"], "1500.00")
        self.assertEqual(self.set_email_preference(False).status_code, 200)
        record.refresh_from_db()
        self.assertFalse(record.include_in_email)

    def test_form_preferences_redirect_to_tray_and_unchecked_means_false(self):
        self.save_board()
        response = self.client.post(self.email_url, {"include_in_email": "on"})
        self.assertRedirects(response, reverse("auction_email_tray"), fetch_redirect_response=False)
        self.assertTrue(AuctionBidBoardAnalysis.objects.get(lot=self.lot).include_in_email)
        response = self.client.post(self.email_url, {})
        self.assertRedirects(response, reverse("auction_email_tray"), fetch_redirect_response=False)
        self.assertFalse(AuctionBidBoardAnalysis.objects.get(lot=self.lot).include_in_email)

    def test_sending_batch_blocks_its_lot_preference_but_not_an_unrelated_lot(self):
        self.save_board()
        batch = AuctionEmailBatch.objects.create(status=AuctionEmailBatch.Status.SENDING)
        AuctionEmailBatchItem.objects.create(batch=batch, lot=self.lot, selected_by=self.staff)
        response = self.set_email_preference(True)
        self.assertEqual(response.status_code, 409)
        self.assertFalse(AuctionBidBoardAnalysis.objects.get(lot=self.lot).include_in_email)
        unrelated = self.create_lot("unrelated")
        self.save_board(lot=unrelated)
        response = self.client.post(
            reverse("auction_lot_bid_board_email", args=(unrelated.pk,)),
            '{"include_in_email":true}', content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        batch.status = AuctionEmailBatch.Status.DRAFT
        batch.save(update_fields=["status"])
        self.assertEqual(self.set_email_preference(True).status_code, 200)

    def test_catalog_serialization_is_compact_and_uses_prefetched_record(self):
        record = self.save_board()
        no_board = self.create_lot("without-board")
        lots = list(AuctionWatchLot.objects.select_related("watchlist_artist", "bid_board_analysis").order_by("pk"))
        with self.assertNumQueries(0):
            data = [_lot_json(lot, ZoneInfo("UTC")) for lot in lots]
        with_board = next(item for item in data if item["id"] == self.lot.pk)
        self.assertEqual(with_board["saved_bid_board"], saved_board_summary(record))
        self.assertEqual(with_board["saved_bid_board_url"], self.saved_url)
        self.assertEqual(with_board["bid_board_email_url"], self.email_url)
        self.assertNotIn("evidence_snapshot", with_board["saved_bid_board"])
        self.assertNotIn("analysis", with_board["saved_bid_board"])
        self.assertIsNone(next(item for item in data if item["id"] == no_board.pk)["saved_bid_board"])

    def test_calendar_loads_saved_boards_without_one_query_per_month_lot(self):
        self.assert_calendar_board_queries(month=10, expected_board_queries=1)

    def test_calendar_loads_saved_boards_without_one_query_per_upcoming_day_lot(self):
        self.assert_calendar_board_queries(month=11, expected_board_queries=2)

    def assert_calendar_board_queries(self, *, month, expected_board_queries):
        self.lot.event_at = datetime(2026, month, 15, 15, tzinfo=datetime_timezone.utc)
        self.lot.save(update_fields=["event_at"])
        self.save_board()
        other = self.create_lot("calendar-other", month=month)
        self.save_board(lot=other)
        no_board = self.create_lot("calendar-no-board", month=month)
        with patch("secondstateapp.calendar_views.timezone.now", return_value=datetime(
            2026, 10, 15, 12, tzinfo=datetime_timezone.utc,
        )), CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse("auction_calendar"), {"month": "2026-10", "view": "catalog"})
        self.assertEqual(response.status_code, 200)
        day_data = response.context["calendar_data"][f"2026-{month:02d}-15"]
        self.assertEqual(len(day_data), 3)
        for item in day_data:
            if item["id"] == no_board.pk:
                self.assertIsNone(item["saved_bid_board"])
            else:
                self.assertEqual(item["saved_bid_board"]["qualifying_bid"], "1800.00")
        board_queries = [query["sql"] for query in queries if "secondstateapp_auctionbidboardanalysis" in query["sql"]]
        self.assertEqual(len(board_queries), expected_board_queries, board_queries)
        self.assertTrue(all("JOIN" in sql for sql in board_queries), board_queries)
