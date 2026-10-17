"""A second PC's older cached upload cannot roll back newer Calendar evidence."""

import json
import os
from datetime import datetime
from decimal import Decimal
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from secondstateapp.models import AuctionWatchLot
from catalogapp.watchlist_models import NormalizedLot
from catalogapp.watchlist_sync import CalendarSyncResult, sync_watchlist_lots


@override_settings(CALENDAR_TIME_ZONE="America/New_York")
@patch.dict(os.environ, {"CATALOG_API_KEY": "stale-sync-test-key"})
class CalendarStaleSyncTests(TestCase):
    def setUp(self):
        self.endpoint = reverse("auction_calendar_sync")
        self.observed = datetime(2026, 10, 17, 18, tzinfo=ZoneInfo("UTC"))
        self.lot = AuctionWatchLot.objects.create(
            source="Invaluable", source_lot_id="123", artist="Will Barnet", artist_watchlist_name="Will Barnet",
            title="Corrected title", event_at=datetime(2026, 10, 24, 18, tzinfo=ZoneInfo("UTC")),
            current_bid=Decimal("350"), sold_price=Decimal("500"), sold_currency="USD", active=False,
            source_status="ended", source_first_seen_at=datetime(2026, 10, 10, 18, tzinfo=ZoneInfo("UTC")),
            source_last_seen_at=self.observed, image_url="https://www.invaluable.com/image/new.jpg",
        )

    def record(self, **overrides):
        record = {
            "source": "Invaluable", "source_lot_id": "123", "artist": "Will Barnet",
            "artist_watchlist_name": "Will Barnet", "title": "Old cached title", "current_bid": 100,
            "end_at": "2026-10-23T18:00:00Z", "first_seen_at": "2026-10-15T18:00:00Z",
            "last_seen_at": "2026-10-16T18:00:00Z", "status": "unchanged",
            "image_url": "https://www.invaluable.com/image/old.jpg", "sold_price": 200, "sold_currency": "EUR",
        }
        record.update(overrides)
        return record

    def sync(self, *records):
        return self.client.post(self.endpoint, json.dumps({"lots": list(records)}),
                                content_type="application/json", HTTP_X_API_KEY="stale-sync-test-key")

    def test_stale_cached_observation_preserves_all_fresher_lot_fields_and_times(self):
        before = AuctionWatchLot.objects.filter(pk=self.lot.pk).values().get()
        response = self.sync(self.record())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["received"], 1)
        self.assertEqual(response.json()["updated"], 0)
        self.assertEqual(response.json()["stale_preserved"], 1)
        self.assertEqual(response.json()["sold_prices_received"], 1)
        self.assertEqual(AuctionWatchLot.objects.filter(pk=self.lot.pk).values().get(), before)

    def test_missing_source_time_cannot_overwrite_a_dated_observation(self):
        before = AuctionWatchLot.objects.filter(pk=self.lot.pk).values().get()
        response = self.sync(self.record(last_seen_at=""))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["stale_preserved"], 1)
        self.assertEqual(AuctionWatchLot.objects.filter(pk=self.lot.pk).values().get(), before)

    def test_newer_and_equal_observations_still_accept_source_corrections(self):
        for observed in ("2026-10-17T18:00:00Z", "2026-10-18T18:00:00Z"):
            with self.subTest(observed=observed):
                response = self.sync(self.record(title="New source correction", last_seen_at=observed, sold_price=600))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["updated"], 1)
                self.assertEqual(response.json()["stale_preserved"], 0)
                self.lot.refresh_from_db()
                self.assertEqual(self.lot.title, "New source correction")
                self.assertEqual(self.lot.sold_price, Decimal("600"))

    def test_one_stale_record_does_not_prevent_a_new_lot_in_the_same_upload(self):
        response = self.sync(self.record(), self.record(source_lot_id="456"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["received"], 2)
        self.assertEqual(response.json()["created"], 1)
        self.assertEqual(response.json()["updated"], 0)
        self.assertEqual(response.json()["stale_preserved"], 1)
        self.assertEqual(AuctionWatchLot.objects.get(source_lot_id="123").title, "Corrected title")
        self.assertEqual(AuctionWatchLot.objects.get(source_lot_id="456").title, "Old cached title")

    def test_legacy_undated_observation_can_be_updated(self):
        AuctionWatchLot.objects.filter(pk=self.lot.pk).update(source_last_seen_at=None)
        response = self.sync(self.record())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["updated"], 1)
        self.assertEqual(response.json()["stale_preserved"], 0)


class StaleSyncReceiptTests(SimpleTestCase):
    def test_receipt_explains_retained_calendar_observations_without_claiming_image_changes(self):
        result = CalendarSyncResult(received=2, created=1, updated=0, ended=1,
                                    images_received=1, sold_prices_received=1, stale_preserved=1)
        self.assertEqual(result.summary(),
            "Website calendar synced: 2 lots (1 new, 0 updated, 1 ended). "
            "Preserved 1 newer Calendar observation. 1 saved artwork images received. 1 sold price received.")

    def test_legacy_api_receipt_defaults_to_no_stale_records(self):
        response = Mock(status_code=200)
        response.json.return_value = {"ok": True, "received": 1, "created": 1, "updated": 0, "ended": 0}
        transport = Mock()
        transport.post.return_value = response
        result = sync_watchlist_lots([NormalizedLot("Invaluable", "1", "Will Barnet", "Will Barnet", "Print")],
                                    base_url="https://secondstate.art", api_key="test", session=transport)
        self.assertEqual(result.stale_preserved, 0)
        self.assertEqual(result.summary(), "Website calendar synced: 1 lots (1 new, 0 updated, 0 ended).")

    def test_stale_receipt_counts_accumulate_across_upload_batches(self):
        responses = []
        for received, created, stale in ((1000, 0, 1000), (1, 1, 0)):
            response = Mock(status_code=200)
            response.json.return_value = {"ok": True, "received": received, "created": created,
                                          "updated": 0, "ended": 0, "stale_preserved": stale}
            responses.append(response)
        transport = Mock()
        transport.post.side_effect = responses
        lots = [NormalizedLot("Invaluable", str(index), "Will Barnet", "Will Barnet", "Print") for index in range(1001)]
        result = sync_watchlist_lots(lots, base_url="https://secondstate.art", api_key="test", session=transport)
        self.assertEqual((result.received, result.created, result.stale_preserved), (1001, 1, 1000))
        self.assertIn("Preserved 1000 newer Calendar observations.", result.summary())
