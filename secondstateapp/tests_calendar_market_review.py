import json
import os
from datetime import date, datetime, time, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import AuctionLotMarketReview, AuctionWatchLot
from .tests_calendar import CALENDAR_ZONE, watch_lot


KEY = "test-market-review-key"


@patch.dict(os.environ, {"CATALOG_API_KEY": KEY})
class CalendarMarketReviewTests(TestCase):
    def setUp(self):
        self.endpoint = reverse("calendar_market_review")
        self.today = date(2026, 11, 20)
        self.start = datetime.combine(self.today, time.min, tzinfo=CALENDAR_ZONE)
        self.clock = self.enterContext(patch("django.utils.timezone.now", return_value=self.start + timedelta(hours=12)))
        self.lot = watch_lot(source="Whyte's", source_lot_id="ie-1", event_at=self.start,
                             location="Dublin, Ireland", artist="Rufino Tamayo", artist_watchlist_name="Rufino Tamayo")

    def get(self, **params):
        return self.client.get(self.endpoint, params, HTTP_X_API_KEY=KEY)

    def plan(self, lot=None, status="mismatch"):
        row = self.get(ids=str((lot or self.lot).pk)).json()["lots"][0]
        result = {key: row[key] for key in ("id", "fingerprint", "revision")}
        result.update(status=status, reason="Venue's regional buyer base and recent sales of comparable editions.")
        if status == "mismatch":
            result.update(sale_market="Regional Irish art auctions", stronger_market="New York Latin American prints",
                          sources=[{"label": "Current catalog", "url": "https://example.com/catalog/1"},
                                   {"label": "Auction results", "url": "https://example.com/results/5"}])
        return result

    def post(self, *reviews):
        return self.client.post(self.endpoint, json.dumps({"reviews": reviews}),
                                content_type="application/json", HTTP_X_API_KEY=KEY)

    def day_row(self):
        rows = self.client.get(reverse("auction_calendar_day_lots"), {"day": self.today.isoformat()}).json()["lots"]
        return next(row for row in rows if row["id"] == self.lot.pk)

    def login_staff(self):
        self.client.force_login(get_user_model().objects.create_user("market-staff", is_staff=True))

    def test_api_requires_key_and_prioritizes_upcoming_lots_from_all_sources(self):
        self.login_staff()
        self.assertEqual(self.client.get(self.endpoint).status_code, 401)
        self.assertEqual(self.client.post(self.endpoint).status_code, 401)
        inactive = watch_lot(source_lot_id="inactive", event_at=self.start + timedelta(days=200), active=False)
        for name, values in (
            ("yesterday", {"event_at": self.start - timedelta(seconds=1)}),
            ("undated", {"event_at": None}),
            ("replaced", {"event_at": self.start, "superseded_by": self.lot}),
        ):
            watch_lot(source_lot_id=name, **values)
        response = self.get(limit=1)
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response.headers["Cache-Control"])
        page = response.json()
        self.assertEqual((page["pending_count"], page["eligible_count"]), (2, 2))
        self.assertEqual((page["upcoming_pending_count"], page["archive_pending_count"]), (2, 0))
        self.assertEqual((page["oldest_pending_day"], page["oldest_pending_day_count"]), (self.today.isoformat(), 1))
        self.assertEqual([row["id"] for row in page["lots"]], [self.lot.pk])
        self.assertEqual((page["lots"][0]["source"], page["lots"][0]["sale_country"]), ("Whyte's", "IE"))
        self.assertEqual(self.post(self.plan(status="clear")).status_code, 200)
        self.assertEqual([row["id"] for row in self.get(limit=1).json()["lots"]], [inactive.pk])
        self.assertIsNone(self.day_row()["market_mismatch"])
        self.assertEqual(self.day_row()["market_review_status"], "clear")

    def test_launch_floor_and_rolling_local_midnight_keep_prior_findings_inspectable(self):
        prelaunch = watch_lot(source_lot_id="prelaunch", event_at=self.start - timedelta(seconds=1), is_all_day=True)
        next_day = watch_lot(source_lot_id="next-day", event_at=self.start + timedelta(days=1))
        self.clock.return_value = self.start - timedelta(seconds=1)
        self.assertEqual([row["id"] for row in self.get().json()["lots"]], [self.lot.pk, next_day.pk])
        self.assertEqual(self.post(self.plan(prelaunch)).status_code, 409)
        self.clock.return_value = self.start + timedelta(days=1, seconds=-1)
        self.assertEqual(self.post(self.plan()).status_code, 200)
        self.login_staff()
        saved = self.day_row()["market_mismatch"]
        self.assertEqual(saved["sale_market"], "Regional Irish art auctions")
        self.clock.return_value = self.start + timedelta(days=1)
        page = self.get(limit=200).json()
        self.assertEqual((page["pending_count"], page["eligible_count"]), (1, 1))
        self.assertEqual(page["lots"][0]["id"], next_day.pk)
        past = self.get(ids=str(self.lot.pk)).json()["lots"][0]
        self.assertFalse(past["eligible"])
        self.assertTrue(past["review"]["current"])
        self.assertEqual(self.post(self.plan(status="clear")).status_code, 409)
        self.assertEqual(self.day_row()["market_mismatch"], saved)
        catalog = self.client.get(reverse("auction_calendar"), {"day": self.today.isoformat(), "view": "catalog"})
        self.assertEqual(catalog.context["market_review_start"], self.today.isoformat())
        self.assertEqual(catalog.context["calendar_data"][self.today.isoformat()][0]["market_mismatch"], saved)
        self.assertEqual(catalog.context["calendar_data"][self.today.isoformat()][0]["market_review_status"], "mismatch")

    def test_counts_full_earliest_day_including_changed_rows_even_if_page_is_smaller(self):
        tomorrow = watch_lot(source_lot_id="tomorrow", event_at=self.start + timedelta(days=1))
        later_today = watch_lot(source_lot_id="later-today", event_at=self.start + timedelta(hours=23))
        watch_lot(source_lot_id="prior-day", event_at=self.start - timedelta(hours=1))
        self.assertEqual(self.post(self.plan(lot=self.lot, status="clear")).status_code, 200)
        AuctionWatchLot.objects.filter(pk=self.lot.pk).update(title="Changed edition")
        first = self.get(limit=1).json()
        self.assertEqual((first["oldest_pending_day"], first["oldest_pending_day_count"]), (self.today.isoformat(), 2))
        self.assertEqual([row["id"] for row in self.get().json()["lots"]], [self.lot.pk, later_today.pk, tomorrow.pk])
        self.assertEqual(self.post(*(self.plan(lot=lot, status="clear") for lot in (self.lot, later_today, tomorrow))).status_code, 200)
        done = self.get().json()
        self.assertEqual((done["oldest_pending_day"], done["oldest_pending_day_count"], done["pending_count"]), (None, 0, 0))

    def test_review_displays_evidence_only_while_catalog_facts_match(self):
        self.login_staff()
        plan = self.plan()
        result = self.post(plan)
        self.assertEqual(result.status_code, 200, result.content)
        summary = self.day_row()["market_mismatch"]
        self.assertEqual(summary["stronger_market"], plan["stronger_market"])
        self.assertEqual(summary["sources"], plan["sources"])
        self.assertTrue(summary["reviewed_at"])
        AuctionWatchLot.objects.filter(pk=self.lot.pk).update(current_bid=200, active=False, source_status="changed")
        self.assertEqual(self.get().json()["pending_count"], 0)
        self.assertEqual(self.day_row()["market_mismatch"], summary)
        AuctionWatchLot.objects.filter(pk=self.lot.pk).update(location="London, UK")
        self.assertIsNone(self.day_row()["market_mismatch"])
        self.assertEqual(self.day_row()["market_review_status"], "unreviewed")
        changed = self.get().json()["lots"][0]
        self.assertNotEqual(changed["fingerprint"], plan["fingerprint"])
        self.assertEqual(changed["revision"], 1)
        reread = self.get(ids=str(self.lot.pk)).json()["lots"][0]
        self.assertFalse(reread["review"]["current"])
        self.assertEqual(self.post(plan).status_code, 409)
        self.assertEqual(self.post(self.plan(status="clear")).status_code, 200)
        self.assertEqual(self.get().json()["pending_count"], 0)
        self.assertIsNone(self.day_row()["market_mismatch"])

    def test_superseded_attribution_change_invalidates_review_in_worker_and_calendar(self):
        self.login_staff()
        self.assertEqual(self.post(self.plan()).status_code, 200)
        watch_lot(source_lot_id="superseded", artist="After Rufino Tamayo",
                  event_at=self.start, superseded_by=self.lot)
        self.assertEqual(self.get().json()["lots"][0]["attribution_label"], "After")
        self.assertIsNone(self.day_row()["market_mismatch"])

    def test_uncertainty_waits_one_week_and_equivalent_retry_preserves_review_date(self):
        self.login_staff()
        plan = self.plan(status="uncertain")
        first = self.post(plan)
        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(self.day_row()["market_review_status"], "uncertain")
        self.assertFalse(self.get().json()["lots"])
        old = timezone.now() - timedelta(days=8)
        AuctionLotMarketReview.objects.filter(lot=self.lot).update(reviewed_at=old)
        replay = self.post(plan)
        self.assertEqual(replay.json()["reviews"], first.json()["reviews"])
        self.assertEqual(AuctionLotMarketReview.objects.get().reviewed_at, old)
        self.assertEqual(self.get().json()["lots"][0]["revision"], 1)
        self.assertEqual(self.post(self.plan(status="uncertain")).status_code, 200)
        self.assertFalse(self.get().json()["lots"])

    def test_stale_reviewer_cannot_overwrite_newer_decision_and_batch_is_atomic(self):
        second = watch_lot(source_lot_id="second", event_at=self.start + timedelta(days=1))
        outdated = self.plan(lot=second, status="clear")
        self.assertEqual(self.post(self.plan(lot=second)).status_code, 200)
        self.assertEqual(self.post(self.plan(), outdated).status_code, 409)
        self.assertFalse(AuctionLotMarketReview.objects.filter(lot=self.lot).exists())
        self.assertEqual(AuctionLotMarketReview.objects.get().status, "mismatch")

    def test_validates_positive_evidence_and_rejects_out_of_scope_writes(self):
        plan = self.plan()
        for bad in (
            {**plan, "sources": []}, {**plan, "sale_market": ""}, {**plan, "revision": False},
            {**plan, "sources": [plan["sources"][0], plan["sources"][0]]},
            {**plan, "sources": [{"label": "Invalid source", "url": "javascript:alert(1)"}, plan["sources"][0]]},
        ):
            self.assertEqual(self.post(bad).status_code, 400)
        for params in ({"ids": "-1"}, {"ids": "1,1"}, {"limit": 201}):
            self.assertEqual(self.get(**params).status_code, 400)
        AuctionWatchLot.objects.filter(pk=self.lot.pk).update(event_at=None)
        undated = self.get(ids=str(self.lot.pk)).json()["lots"][0]
        self.assertFalse(undated["eligible"])
        self.assertEqual(self.post(self.plan()).status_code, 409)
        self.assertFalse(AuctionLotMarketReview.objects.exists())
