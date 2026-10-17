"""Read-only Calendar reconciliation for artist-scoped desktop sync."""

import os
from datetime import datetime
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import requests
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from catalogapp.artprice_artist_links import artist_identity_key
from catalogapp.watchlist_sync import CalendarArtistInventory, CalendarSyncError, fetch_calendar_inventory
from secondstateapp.models import AuctionWatchArtist, AuctionWatchLot


@override_settings(CALENDAR_TIME_ZONE="America/New_York")
@patch.dict(os.environ, {"CATALOG_API_KEY": "inventory-test-key"})
class CalendarArtistInventoryTests(TestCase):
    def setUp(self):
        self.endpoint = reverse("auction_calendar_inventory")
        self.artist = AuctionWatchArtist.objects.create(
            name="Will Barnet", normalized_name=artist_identity_key("Will Barnet"),
        )

    def lot(self, source_lot_id, **overrides):
        values = dict(
            source="Invaluable", source_lot_id=source_lot_id,
            artist="Will Barnet", artist_watchlist_name="Will Barnet",
            watchlist_artist=self.artist,
            event_at=datetime(2026, 10, 20, tzinfo=ZoneInfo("UTC")),
        )
        values.update(overrides)
        return AuctionWatchLot.objects.create(**values)

    def inventory(self):
        return self.client.get(self.endpoint, HTTP_X_API_KEY="inventory-test-key")

    def test_requires_catalog_key_even_for_signed_in_staff(self):
        from django.contrib.auth import get_user_model
        staff = get_user_model().objects.create_user(username="inventory-admin", is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(self.endpoint).status_code, 401)
        self.assertEqual(self.client.get(self.endpoint, HTTP_X_API_KEY="wrong").status_code, 401)
        with patch.dict(os.environ, {"CATALOG_API_KEY": ""}):
            self.assertEqual(self.inventory().status_code, 401)

    def test_only_get_is_supported_and_response_is_not_cached(self):
        self.assertEqual(self.client.post(self.endpoint, HTTP_X_API_KEY="inventory-test-key").status_code, 405)
        response = self.inventory()
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response.headers["Cache-Control"])

    @patch("secondstateapp.calendar_views.timezone.now", return_value=datetime(2026, 10, 17, 14, tzinfo=ZoneInfo("UTC")))
    def test_counts_sources_and_calendar_day_without_changing_records(self, _now):
        self.lot("upcoming")
        self.lot("today", event_at=datetime(2026, 10, 17, 5, tzinfo=ZoneInfo("UTC")))
        self.lot("yesterday-local", event_at=datetime(2026, 10, 17, 2, tzinfo=ZoneInfo("UTC")))
        self.lot("ended", active=False)
        self.lot("undated", event_at=None)
        self.lot("other-source", source="Heritage")
        replacement = self.lot("replacement")
        self.lot("superseded", superseded_by=replacement, active=False)
        before = list(AuctionWatchLot.objects.order_by("pk").values())

        with self.assertNumQueries(2):
            response = self.inventory()

        self.assertEqual(response.status_code, 200)
        rows = {row["source"]: row for row in response.json()["artists"]}
        self.assertEqual(rows["Invaluable"], {
            "name": "Will Barnet", "normalized_name": "barnet will", "source": "Invaluable",
            "lot_count": 6, "upcoming_count": 3,
            "last_synced_at": replacement.synced_at.isoformat(),
        })
        self.assertEqual(rows["Heritage"]["lot_count"], 1)
        self.assertEqual(rows["Heritage"]["upcoming_count"], 1)
        self.assertEqual(list(AuctionWatchLot.objects.order_by("pk").values()), before)

    def test_merges_legacy_names_and_keeps_artists_with_zero_lots(self):
        self.lot("legacy", watchlist_artist=None, artist_watchlist_name="BARNET, WILL")
        self.lot("canonical")
        self.lot("another-label", watchlist_artist=None, artist_watchlist_name="", artist="Barnet, Will")
        AuctionWatchArtist.objects.create(name="Joan Miró", normalized_name="joan miro")
        response = self.inventory()
        rows = {row["name"]: row for row in response.json()["artists"]}
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows["Will Barnet"]["lot_count"], 3)
        self.assertEqual(rows["Joan Miró"], {
            "name": "Joan Miró", "normalized_name": "joan miro", "source": "",
            "lot_count": 0, "upcoming_count": 0, "last_synced_at": "",
        })


class DesktopCalendarInventoryTests(SimpleTestCase):
    def record(self, **overrides):
        row = dict(name="Will Barnet", normalized_name="barnet will", source="Invaluable",
                   lot_count=5, upcoming_count=2, last_synced_at="2026-10-17T14:00:00+00:00")
        row.update(overrides)
        return row

    def session(self, payload, status=200):
        response = Mock(status_code=status)
        response.json.return_value = payload
        session = Mock()
        session.get.return_value = response
        return session

    def test_reads_counts_with_key_without_uploading_or_following_redirects(self):
        session = self.session({"ok": True, "artists": [self.record()]})
        result = fetch_calendar_inventory(base_url="https://secondstate.art/", api_key="key", session=session)
        self.assertEqual(result, [CalendarArtistInventory(**self.record())])
        session.get.assert_called_once_with(
            "https://secondstate.art/calendar/inventory/",
            headers={"X-API-KEY": "key", "Accept": "application/json"},
            timeout=(10, 30), allow_redirects=False,
        )
        session.post.assert_not_called()

    def test_known_empty_inventory_is_distinct_from_unavailable(self):
        self.assertEqual(fetch_calendar_inventory(
            base_url="https://secondstate.art", api_key="key",
            session=self.session({"ok": True, "artists": []}),
        ), [])
        with self.assertRaisesRegex(CalendarSyncError, "Deploy"):
            fetch_calendar_inventory(base_url="https://secondstate.art", api_key="key", session=self.session({}, 404))

    def test_invalid_inventory_is_never_presented_as_zero_lots(self):
        payloads = [
            {}, {"ok": True}, {"ok": True, "artists": {}},
            {"ok": True, "artists": [self.record(lot_count=-1)]},
            {"ok": True, "artists": [self.record(lot_count=True)]},
            {"ok": True, "artists": [self.record(upcoming_count=6)]},
            {"ok": True, "artists": [self.record(normalized_name="unrelated")]},
            {"ok": True, "artists": [self.record(), self.record()]},
        ]
        for payload in payloads:
            with self.subTest(payload=payload), self.assertRaises(CalendarSyncError):
                fetch_calendar_inventory(base_url="https://secondstate.art", api_key="key", session=self.session(payload))

    def test_network_and_auth_failures_leave_local_scan_available(self):
        session = Mock()
        session.get.side_effect = requests.ConnectionError("unavailable")
        with self.assertRaisesRegex(CalendarSyncError, "local artists"):
            fetch_calendar_inventory(base_url="https://secondstate.art", api_key="key", session=session)
        for status in (301, 401, 403, 500):
            with self.subTest(status=status), self.assertRaisesRegex(CalendarSyncError, str(status)):
                fetch_calendar_inventory(base_url="https://secondstate.art", api_key="key", session=self.session({}, status))

    def test_requires_configured_key_and_https(self):
        session = Mock()
        for url, key in (("https://secondstate.art", ""), ("http://secondstate.art", "key")):
            with self.assertRaises(CalendarSyncError):
                fetch_calendar_inventory(base_url=url, api_key=key, session=session)
        session.get.assert_not_called()
