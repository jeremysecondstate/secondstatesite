import os
from datetime import datetime, timezone
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from .models import AuctionWatchLot


@override_settings(CALENDAR_TIME_ZONE="America/Los_Angeles")
@patch.dict(os.environ, {"CATALOG_API_KEY": "sale-time-test-key"})
class CalendarSaleTimeSyncTests(TestCase):
    reported = datetime(2026, 12, 3, 2, tzinfo=timezone.utc)
    published = datetime(2026, 12, 3, 14, tzinfo=timezone.utc)

    def sync(self, **overrides):
        record = {
            "source": "Drouot",
            "source_lot_id": "36132725",
            "auction_house": "Templum Fine art Auction",
            "sale_url": "https://drouot.com/en/v/188631",
            "lot_url": "https://drouot.com/en/l/36132725-andy-warhol-pittsburgh-1928-new-york-1987-the-marx-brothers",
            "lot_number": "959",
            "end_at": self.reported.isoformat(),
            **overrides,
        }
        response = self.client.post(
            reverse("auction_calendar_sync"), {"lots": [record]},
            content_type="application/json", HTTP_X_API_KEY="sale-time-test-key",
        )
        self.assertEqual(response.status_code, 200, response.content)
        return AuctionWatchLot.objects.get(source=record["source"], source_lot_id=record["source_lot_id"])

    def test_creation_and_localized_catalog_refresh_keep_published_time(self):
        lot = self.sync()
        self.assertEqual(lot.event_at, self.published)
        self.assertFalse(lot.is_all_day)
        refreshed = self.sync(
            sale_url="https://drouot.com/fr/v/188631-subasta-especial-navidad",
            end_at="2026-12-03T03:00:00+01:00",
        )
        self.assertEqual(refreshed.pk, lot.pk)
        self.assertEqual(refreshed.event_at, self.published)
        self.assertEqual(refreshed.sale_url, "https://drouot.com/fr/v/188631-subasta-especial-navidad")

    def test_refresh_corrects_hidden_copy_without_changing_its_saved_work_or_survivor(self):
        survivor = AuctionWatchLot.objects.create(source="Invaluable", source_lot_id="canonical", event_at=self.published)
        child = AuctionWatchLot.objects.create(
            source="Drouot", source_lot_id="36132725", event_at=self.reported, active=False,
            superseded_by=survivor, artprice_url="https://www.artprice.com/artist/1",
        )
        refreshed = self.sync(active=True)
        self.assertEqual(refreshed.pk, child.pk)
        self.assertEqual(refreshed.event_at, self.published)
        self.assertFalse(refreshed.active)
        self.assertEqual(refreshed.superseded_by_id, survivor.pk)
        self.assertEqual(refreshed.artprice_url, child.artprice_url)
        survivor.refresh_from_db()
        self.assertEqual(survivor.event_at, self.published)

    def test_other_sales_providers_and_new_provider_times_keep_their_observation(self):
        changed_time = datetime(2026, 12, 3, 15, tzinfo=timezone.utc)
        cases = [
            ({"sale_url": "https://drouot.com/en/v/1886310"}, self.reported, False),
            ({"sale_url": "https://example.org/en/v/188631"}, self.reported, False),
            ({"auction_house": "Another auction house"}, self.reported, False),
            ({"source": "Invaluable"}, self.reported, False),
            ({"end_at": changed_time.isoformat()}, changed_time, False),
            ({"is_all_day": True}, self.reported, True),
            ({"end_at": "2026-12-03"}, datetime(2026, 12, 3, 8, tzinfo=timezone.utc), True),
        ]
        for fields, expected, all_day in cases:
            with self.subTest(fields=fields):
                lot = self.sync(**fields)
                self.assertEqual(lot.event_at, expected)
                self.assertEqual(lot.is_all_day, all_day)

    def test_cached_bad_time_cannot_replace_a_newer_source_schedule(self):
        new_time = datetime(2026, 12, 3, 15, tzinfo=timezone.utc)
        self.sync(end_at=new_time.isoformat(), last_seen_at="2026-11-21T18:00:00Z")
        stale = self.sync(last_seen_at="2026-11-21T16:00:00Z")
        self.assertEqual(stale.event_at, new_time)
