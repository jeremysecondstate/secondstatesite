"""Portable watchlist recovery must not re-fetch sources or rewrite provenance."""

import json
import os
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from catalogapp.watchlist_models import NormalizedLot
from secondstateapp.models import AuctionWatchArtist, AuctionWatchLot, SharedArtistWatchlist


NOW = datetime(2026, 10, 17, 18, tzinfo=ZoneInfo("UTC"))
KEY = "shared-watchlist-test-key"


@override_settings(CALENDAR_TIME_ZONE="America/New_York")
@patch.dict(os.environ, {"CATALOG_API_KEY": KEY})
@patch("secondstateapp.watchlist_shared_views.timezone.now", return_value=NOW)
class SharedArtistWatchlistTests(TestCase):
    def setUp(self):
        self.endpoint = reverse("shared_artist_watchlist")

    def entry(self, name="Will Barnet", **overrides):
        result = {
            "folder_path": ["Artists"], "title": name, "artist": name,
            "url": f"https://www.invaluable.com/search?artistName={name.replace(' ', '+')}",
            "source": "Invaluable", "add_date": "", "enabled": True,
        }
        result.update(overrides)
        return result

    def coverage(self, entry=None, **overrides):
        result = {
            "watch_url": (entry or self.entry())["url"], "state": "verified",
            "checked_at": "2026-10-17T14:00:00+00:00", "covered_until": "2026-10-24T14:00:00+00:00",
        }
        result.update(overrides)
        return result

    def post(self, payload):
        return self.client.post(self.endpoint, json.dumps(payload), content_type="application/json", HTTP_X_API_KEY=KEY)

    def get(self, **params):
        return self.client.get(self.endpoint, params, HTTP_X_API_KEY=KEY)

    def lot(self, source_id, **overrides):
        values = {
            "source": "Invaluable", "source_lot_id": source_id, "artist": "Will Barnet",
            "artist_watchlist_name": "Will Barnet", "title": "A print", "event_at": NOW + timedelta(days=3),
            "source_first_seen_at": NOW - timedelta(days=6), "source_last_seen_at": NOW - timedelta(days=2),
        }
        values.update(overrides)
        return AuctionWatchLot.objects.create(**values)

    def test_api_key_required_for_both_methods_even_for_staff(self, _now):
        staff = get_user_model().objects.create_user(username="watchlist-staff", is_staff=True)
        self.client.force_login(staff)
        for method in (self.client.get, self.client.post):
            self.assertEqual(method(self.endpoint).status_code, 401)
            self.assertEqual(method(self.endpoint, HTTP_X_API_KEY="wrong").status_code, 401)
        with patch.dict(os.environ, {"CATALOG_API_KEY": ""}):
            self.assertEqual(self.get().status_code, 401)
        self.assertFalse(SharedArtistWatchlist.objects.exists())

    def test_empty_get_is_read_only_and_not_cached(self, _now):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "ok": True, "version": 1, "entries": [], "artist_artprice_links": {}, "coverage": [],
            "calendar_lot_keys": [], "lots": [], "next_cursor": None, "updated_at": "",
        })
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertFalse(SharedArtistWatchlist.objects.exists())
        self.assertEqual(self.client.delete(self.endpoint, HTTP_X_API_KEY=KEY).status_code, 405)

    def test_two_pcs_merge_entries_without_stale_overwrite_or_delete(self, _now):
        first = self.entry(enabled=False)
        second = self.entry("Joan Miro")
        response = self.post({"entries": [first, second]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["entries_received"], 2)
        stale = self.entry(title="Older title", enabled=True)
        self.assertEqual(self.post({"entries": [stale]}).status_code, 200)
        self.assertEqual(self.post({"entries": []}).status_code, 200)
        data = self.get().json()
        self.assertEqual(len(data["entries"]), 2)
        self.assertEqual(data["entries"][0]["title"], "Will Barnet")
        self.assertFalse(data["entries"][0]["enabled"])

    def test_canonical_urls_do_not_duplicate_bookmarks(self, _now):
        self.post({"entries": [self.entry()]})
        response = self.post({"entries": [self.entry(url=self.entry()["url"] + "&utm_source=test#top")]})
        self.assertEqual(len(response.json()["entries"]), 1)

    def test_unknown_machine_settings_and_coverage_details_never_persist(self, _now):
        entry = self.entry()
        entry.update(bookmark_path="C:/Users/private/Bookmarks", cookies="secret")
        row = self.coverage(detail="C:/Users/private/cache", artist="Wrong", source="Wrong", api_key="secret")
        response = self.post({
            "entries": [entry], "coverage": [row], "browser_profile_path": "C:/Users/private",
            "api_key": "secret", "lots": [{"source": "untrusted"}],
        })
        data = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("private", json.dumps(data))
        self.assertNotIn("secret", json.dumps(data))
        self.assertNotIn("detail", data["coverage"][0])
        self.assertEqual(data["coverage"][0]["artist"], "Will Barnet")
        self.assertEqual(data["coverage"][0]["source"], "Invaluable")
        self.assertFalse(AuctionWatchLot.objects.exists())

    def test_newer_actual_coverage_wins_over_stale_or_unattempted_default(self, _now):
        self.post({"entries": [self.entry()], "coverage": [self.coverage()]})
        self.post({"coverage": [self.coverage(state="blocked", checked_at="2026-10-17T10:00:00+00:00")]})
        self.post({"coverage": [self.coverage(state="pending", checked_at="")]})
        self.assertEqual(self.get().json()["coverage"][0]["state"], "verified")
        response = self.post({"coverage": [self.coverage(state="partial", checked_at="2026-10-17T16:00:00+00:00")]})
        self.assertEqual(response.json()["coverage"][0]["state"], "partial")

    def test_coverage_comparison_uses_timezone_not_string_order(self, _now):
        self.post({"entries": [self.entry()], "coverage": [self.coverage()]})
        response = self.post({"coverage": [self.coverage(state="empty", checked_at="2026-10-17T11:00:00-04:00")]})
        self.assertEqual(response.json()["coverage"][0]["state"], "empty")

    def test_coverage_without_a_curated_entry_is_ignored(self, _now):
        response = self.post({"coverage": [self.coverage()]})
        self.assertEqual(response.json()["coverage"], [])

    def test_artist_links_only_belong_to_curated_artists_and_site_edits_win(self, _now):
        old_url = "https://www.artprice.com/artist/123/will-barnet"
        site_url = "https://www.artprice.com/artist/456/will-barnet"
        self.post({"entries": [self.entry()], "artist_artprice_links": {"Will Barnet": old_url, "Other": old_url}})
        artist = AuctionWatchArtist.objects.create(name="Will Barnet", normalized_name="barnet will", artprice_url=site_url)
        self.assertEqual(self.get().json()["artist_artprice_links"], {"Will Barnet": site_url})
        artist.refresh_from_db()
        self.assertEqual(artist.artprice_url, site_url)

    def test_validation_is_atomic(self, _now):
        bad_payloads = [
            [], {"version": 2}, {"entries": {}}, {"artist_artprice_links": []}, {"coverage": {}},
            {"entries": [self.entry(), self.entry(url="file:///C:/private")]},
            {"entries": [self.entry(url="https://user:pass@www.invaluable.com/search")]},
            {"entries": [self.entry(url="https://www.invaluable.com/search?access_token=secret")]},
            {"entries": [self.entry(url="https://unrelated.example/search")]},
            {"entries": [self.entry(enabled="yes")]},
            {"entries": [self.entry()], "coverage": [self.coverage(state="invalid")]},
            {"entries": [self.entry()], "coverage": [self.coverage(checked_at="2026-10-17T14:00:00")]},
            {"artist_artprice_links": {"Will Barnet": "https://www.artprice.com/artist/123/will-barnet?token=secret"}},
        ]
        for payload in bad_payloads:
            with self.subTest(payload=payload):
                self.assertEqual(self.post(payload).status_code, 400)
                self.assertFalse(SharedArtistWatchlist.objects.exists())

    def test_invalid_or_oversized_json_is_rejected(self, _now):
        response = self.client.post(self.endpoint, "not-json", content_type="application/json", HTTP_X_API_KEY=KEY)
        self.assertEqual(response.status_code, 400)
        with patch("secondstateapp.watchlist_shared_views.MAX_SHARED_BYTES", 5):
            self.assertEqual(self.post({"entries": [self.entry()]}).status_code, 413)

    def test_download_preserves_original_source_evidence_and_never_updates_lots(self, _now):
        lot = self.lot("1", estimate_low=Decimal("1200.50"), estimate_high=Decimal("2000.00"), current_bid=Decimal("800"),
                       image_url="https://www.invaluable.com/image/1.jpg", lot_url="https://www.invaluable.com/auction-lot/1")
        before = list(AuctionWatchLot.objects.values())
        row = self.get().json()["lots"][0]
        normalized = NormalizedLot.from_dict(row)
        self.assertEqual(normalized.last_seen_at, lot.source_last_seen_at.isoformat())
        self.assertEqual(normalized.first_seen_at, lot.source_first_seen_at.isoformat())
        self.assertEqual(normalized.end_at, lot.event_at.isoformat())
        self.assertEqual(normalized.estimate_low, 1200.5)
        self.assertEqual(normalized.current_bid, 800)
        self.assertEqual(normalized.image_url, lot.image_url)
        self.assertEqual(list(AuctionWatchLot.objects.values()), before)
        self.assertFalse(SharedArtistWatchlist.objects.exists())

    def test_all_day_end_date_is_in_calendar_timezone_and_ended_state_preserved(self, _now):
        self.lot("all-day", event_at=datetime(2026, 10, 20, 4, tzinfo=ZoneInfo("UTC")), is_all_day=True,
                 active=False, sold_price=Decimal("600"), sold_currency="USD")
        row = self.get().json()["lots"][0]
        self.assertEqual(row["end_at"], "2026-10-20")
        self.assertEqual(row["status"], "ended")
        self.assertEqual(row["sold_price"], 600)
        self.assertEqual(row["sold_currency"], "USD")

    def test_saved_image_uses_site_url_and_legacy_blank_labels_are_normalized(self, _now):
        self.lot("saved", image_url="/media/calendar/lot.jpg", title="", source_status="")
        row = self.get(cursor="").json()["lots"][0]
        self.assertEqual(row["image_url"], "http://testserver/media/calendar/lot.jpg")
        self.assertEqual(row["title"], "Untitled lot")
        self.assertEqual(row["status"], "unchanged")

    def test_recent_window_uses_local_days_includes_undated_and_excludes_superseded(self, _now):
        self.lot("old", event_at=datetime(2026, 10, 10, 3, 59, tzinfo=ZoneInfo("UTC")))
        self.lot("recent", event_at=datetime(2026, 10, 10, 4, tzinfo=ZoneInfo("UTC")), active=False)
        self.lot("last-day", event_at=datetime(2026, 10, 25, 3, 59, tzinfo=ZoneInfo("UTC")))
        self.lot("too-future", event_at=datetime(2026, 10, 25, 4, tzinfo=ZoneInfo("UTC")))
        self.lot("undated", event_at=None)
        replacement = self.lot("replacement")
        self.lot("superseded", superseded_by=replacement, active=False)
        rows = {row["source_lot_id"] for row in self.get().json()["lots"]}
        self.assertEqual(rows, {"recent", "last-day", "undated", "replacement"})
        shorter = {row["source_lot_id"] for row in self.get(horizon_days=3).json()["lots"]}
        self.assertEqual(shorter, {"recent", "undated", "replacement"})

    def test_calendar_identity_keys_cover_all_dates_but_never_superseded_lots(self, _now):
        self.lot("older", event_at=NOW - timedelta(days=90), active=False)
        self.lot("future", event_at=NOW + timedelta(days=90))
        replacement = self.lot("current")
        self.lot("superseded", superseded_by=replacement)
        payload = self.get().json()
        self.assertEqual({row["source_lot_id"] for row in payload["lots"]}, {"current"})
        self.assertEqual(set(payload["calendar_lot_keys"]), {"invaluable:older", "invaluable:future", "invaluable:current"})

    def test_calendar_identity_url_aliases_match_fallback_ids_without_duplicate_keys(self, _now):
        url = "https://www.invaluable.com/auction-lot/will-barnet-print-123?utm_source=bookmark#details"
        canonical = "https://www.invaluable.com/auction-lot/will-barnet-print-123"
        self.lot("generated-old-id", event_at=NOW - timedelta(days=90), lot_url=url, active=False)
        replacement = self.lot("123", lot_url=canonical)
        self.lot("superseded", lot_url="https://www.invaluable.com/auction-lot/withdrawn", superseded_by=replacement)
        payload = self.get().json()
        self.assertEqual(payload["calendar_lot_keys"], [
            "invaluable:generated-old-id", f"invaluable:{canonical}", "invaluable:123",
        ])
        self.assertEqual([row["source_lot_id"] for row in payload["lots"]], ["123"])

    def test_pagination_reads_every_lot_once_and_retains_metadata(self, _now):
        self.post({"entries": [self.entry()]})
        for index in range(5):
            self.lot(str(index))
        ids, cursor = [], 0
        for _ in range(3):
            response = self.get(cursor=cursor, page_size=2).json()
            self.assertEqual(len(response["entries"]), 1)
            ids.extend(row["source_lot_id"] for row in response["lots"])
            cursor = response["next_cursor"]
        self.assertIsNone(cursor)
        self.assertEqual(ids, ["0", "1", "2", "3", "4"])

    def test_pagination_and_horizon_parameters_are_bounded(self, _now):
        for params in ({"cursor": -1}, {"cursor": "bad"}, {"cursor": 2**64}, {"page_size": 501},
                       {"page_size": 0}, {"horizon_days": 4}):
            with self.subTest(params=params):
                self.assertEqual(self.get(**params).status_code, 400)
