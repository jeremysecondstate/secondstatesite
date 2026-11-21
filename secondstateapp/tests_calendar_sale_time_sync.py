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

    def test_drouot_sync_uses_the_published_catalog_and_session_for_each_lot(self):
        # Check both ends of each published range. Adjacent sessions in a
        # combined Drouot catalog must continue to use their own start time.
        sales = [
            ("Dawson's Auctioneers", "187924", "2026-11-26T09:30Z", "2026-11-26T11:00Z", ("16",), ()),
            ("Kruso Art", "188068", "2026-11-25T10:00Z", "2026-11-25T15:00Z", ("201", "278"), ("200", "279")),
            ("Lempertz", "187112", "2026-12-05T10:00Z", "2026-12-05T13:00Z", ("400", "585"), ("399", "586")),
            ("Mallet Auction", "188574", "2026-12-10T03:00Z", "2026-12-10T06:00Z", ("1", "90"), ("91", "1001", "1091")),
        ]
        for house, catalog, reported, published, in_session, outside_session in sales:
            for number in (*in_session, *outside_session):
                with self.subTest(house=house, lot=number):
                    identity = catalog + number
                    lot = self.sync(
                        source_lot_id=identity, lot_url=f"https://drouot.com/en/l/{identity}",
                        auction_house=house, sale_url=f"https://drouot.com/fr/v/{catalog}-sale",
                        lot_number=number, end_at=reported,
                    )
                    self.assertEqual(lot.event_at, datetime.fromisoformat(published if number in in_session else reported))

    def test_drouot_new_source_time_and_unverified_catalogs_are_preserved(self):
        fields = {
            "auction_house": "Mallet Auction", "sale_url": "https://drouot.com/en/v/188574",
            "lot_number": "64", "source_lot_id": "36103234", "lot_url": "https://drouot.com/en/l/36103234",
            "end_at": "2026-12-10T03:00Z",
        }
        for change in (
            {"auction_house": "Another house"},
            {"sale_url": "https://drouot.com/en/v/188575"},
            {"sale_url": ""},
            {"lot_number": "64bis"},
            {"end_at": "2026-12-10T07:15Z"},
            {"is_all_day": True},
        ):
            with self.subTest(change=change):
                observation = {**fields, **change}
                lot = self.sync(**observation)
                self.assertEqual(lot.event_at, datetime.fromisoformat(observation["end_at"]))

    def test_mallet_refresh_preserves_retained_lot_work_and_source_identity(self):
        published = datetime(2026, 12, 10, 6, tzinfo=timezone.utc)
        survivor = AuctionWatchLot.objects.create(source="Invaluable", source_lot_id="survivor", event_at=published)
        retained = AuctionWatchLot.objects.create(
            source="Drouot", source_lot_id="36103234", superseded_by=survivor, active=False,
            event_at=datetime(2026, 12, 10, 3, tzinfo=timezone.utc),
            artprice_url="https://www.artprice.com/artist/1",
        )
        lot = self.sync(
            source_lot_id=retained.source_lot_id, auction_house="Mallet Auction", lot_number="64",
            sale_url="https://drouot.com/en/v/188574", lot_url="https://drouot.com/en/l/36103234",
            end_at="2026-12-10T03:00Z", active=True,
        )
        self.assertEqual(lot.pk, retained.pk)
        self.assertEqual(lot.event_at, published)
        self.assertEqual(lot.superseded_by_id, survivor.pk)
        self.assertFalse(lot.active)
        self.assertEqual(lot.artprice_url, retained.artprice_url)

    def test_invaluable_karl_faber_uses_verified_lots_and_their_own_sessions(self):
        for identity, number, token, reported, published in (
            ("207499898", "644", "f8628dfc29", "2026-12-04T13:00Z", "2026-12-04T10:00Z"),
            ("207499957", "703", "6eabd7e3c6", "2026-12-04T13:00Z", "2026-12-04T10:00Z"),
            ("207500019", "819", "29dac3d36a", "2026-12-04T15:00Z", "2026-12-04T13:00Z"),
            ("207500042", "842", "84aaf8f09d", "2026-12-04T15:00Z", "2026-12-04T13:00Z"),
        ):
            with self.subTest(number=number):
                lot = self.sync(
                    source="Invaluable", auction_house="Karl & Faber", sale_url="",
                    source_lot_id=identity, lot_number=number, end_at=reported,
                    lot_url=f"https://www.invaluable.com/auction-lot/revised-title-{number}-c-{token}",
                )
                self.assertEqual(lot.event_at, datetime.fromisoformat(published))

    def test_invaluable_karl_faber_rejects_conflicting_lot_identity_or_time(self):
        fields = {
            "source": "Invaluable", "auction_house": "Karl & Faber", "sale_url": "",
            "source_lot_id": "207499898", "lot_number": "644", "end_at": "2026-12-04T13:00Z",
            "lot_url": "https://www.invaluable.com/auction-lot/am-walchensee-644-c-f8628dfc29",
        }
        for change in (
            {"source_lot_id": "207499899"}, {"lot_number": "645"}, {"auction_house": "Another house"},
            {"end_at": "2026-12-04T12:30Z"}, {"is_all_day": True},
        ):
            with self.subTest(change=change):
                observation = {**fields, **change}
                lot = self.sync(**observation)
                self.assertEqual(lot.event_at, datetime.fromisoformat(observation["end_at"]))

    def test_new_karl_faber_capture_requires_matching_catalog_image_and_public_lot_number(self):
        reported = "2026-12-04T13:00Z"
        published = "2026-12-04T10:00Z"
        for identity, image_catalog, public_number, expected in (
            ("208000001", "821434", "608", published),
            ("208000002", "821435", "608", reported),
            ("208000003", "821434", "609", reported),
        ):
            with self.subTest(image_catalog=image_catalog, public_number=public_number):
                lot = self.sync(
                    source="Invaluable", auction_house="Karl & Faber", sale_url="", source_lot_id=identity,
                    lot_number="608", end_at=reported,
                    lot_url=f"https://www.invaluable.com/auction-lot/new-work-{public_number}-c-94ac5810c0",
                    image_url=f"https://image.invaluable.com/housePhotos/Karl-Faber/34/{image_catalog}/H0636-Valid123.jpg",
                )
                self.assertEqual(lot.event_at, datetime.fromisoformat(expected))
