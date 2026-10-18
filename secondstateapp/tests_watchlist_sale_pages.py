"""Whole-sale imports keep unbookmarked artists and preserve newer observations."""

from datetime import datetime, timezone
import json
import os
from unittest import TestCase
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from catalogapp.bookmark_watchlist import parse_bookmarks_html
from catalogapp.watchlist_cache import WatchlistCache
from catalogapp.watchlist_models import NormalizedLot
from catalogapp.watchlist_sale_pages import import_saved_sale_pages
from django.test import TestCase as DjangoTestCase
from secondstateapp.models import AuctionWatchLot


DOYLE = "https://doyle.com/auction/search/?au=9224&pn=1"
PHILLIPS = "https://www.phillips.com/auction/NY030726/browse"
NOW = datetime(2026, 10, 17, 22, tzinfo=timezone.utc)


def bookmark(url, title="Sale"):
    return parse_bookmarks_html(f'<DL><DT><A HREF="{url}">{title}</A></DL>')[0]


def snapshot(number="101", observed="2026-10-17T20:00:00+00:00", bid=None):
    return NormalizedLot(
        source="Phillips", source_lot_id=f"NY030726-{number}",
        artist="Unbookmarked Artist", artist_watchlist_name="Unbookmarked Artist",
        title=f"Artwork {number}", lot_number=number, auction_house="Phillips",
        start_at="2026-10-22T17:00:00-04:00", current_bid=bid,
        lot_url=f"https://www.phillips.com/detail/artist/{number}", sale_url=PHILLIPS,
        first_seen_at=observed, last_seen_at=observed,
    )


class SaleBookmarkTests(TestCase):
    def test_both_sales_are_selectable_without_becoming_artists(self):
        for source, url in (("Doyle", DOYLE), ("Phillips", PHILLIPS)):
            entry = bookmark(url, f"{source} October sale")
            self.assertTrue(entry.is_sale)
            self.assertEqual(entry.source, source)
            self.assertEqual(entry.artist, "")
            self.assertEqual(entry.watch_label, f"{source} October sale")

    def test_lookalike_hosts_remain_excluded(self):
        for url in (DOYLE.replace("doyle.com", "doyle.com.evil.test"),
                    PHILLIPS.replace("phillips.com", "phillips.com.evil.test")):
            self.assertEqual(parse_bookmarks_html(f'<A HREF="{url}">sale</A>'), [])

    def test_whole_sale_watch_always_starts_at_first_doyle_page(self):
        from catalogapp.watchlist_registry import _entry
        entry = bookmark(DOYLE.replace("pn=1", "pn=2"))
        self.assertEqual(parse_qs(urlsplit(entry.url).query)["pn"], ["1"])
        restored = _entry({"url": DOYLE.replace("pn=1", "pn=2"), "title": "Doyle"})
        self.assertEqual(restored.url, entry.url)


class SavedSaleCacheTests(TestCase):
    def setUp(self):
        self.cache = WatchlistCache(":memory:")
        self.addCleanup(self.cache.close)
        self.entry = bookmark(PHILLIPS)

    def run_import(self, lots):
        with patch("catalogapp.watchlist_sale_pages.read_saved_sale_pages", return_value=(lots, [])):
            return import_saved_sale_pages(["sale.html"], self.entry, self.cache, now=NOW)

    def test_all_artists_import_and_reimport_keeps_identity_and_snapshot_time(self):
        first = self.run_import([snapshot()])
        repeated = self.run_import([snapshot()])
        self.assertEqual(first.metrics.new_lots, 1)
        self.assertEqual(repeated.metrics.unchanged_lots, 1)
        self.assertEqual(repeated.lots[0].artist, "Unbookmarked Artist")
        self.assertEqual(repeated.lots[0].last_seen_at, "2026-10-17T20:00:00+00:00")
        self.assertEqual(len(self.cache.active_lots_for_watch_url(PHILLIPS)), 1)

    def test_partial_snapshot_never_ends_absent_lots(self):
        self.run_import([snapshot("101"), snapshot("102")])
        with patch.object(self.cache, "mark_missing_ended", side_effect=AssertionError("Partial snapshot")):
            result = self.run_import([snapshot("101")])
        self.assertEqual({lot.lot_number for lot in result.lots}, {"101", "102"})
        self.assertIn("phillips:NY030726-102", result.fallback_lot_keys)
        self.assertEqual(self.cache.get("phillips:NY030726-102").last_seen_at, "2026-10-17T20:00:00+00:00")

    def test_new_changed_only_excludes_unobserved_cached_lots(self):
        self.run_import([snapshot("101"), snapshot("102")])
        with patch("catalogapp.watchlist_sale_pages.read_saved_sale_pages", return_value=([snapshot("101")], [])):
            result = import_saved_sale_pages(["sale.html"], self.entry, self.cache, now=NOW, new_changed_only=True)
        self.assertEqual(result.lots, [])

    def test_old_snapshot_cannot_overwrite_newer_bid(self):
        self.run_import([snapshot(observed="2026-10-17T21:00:00+00:00", bid=500)])
        result = self.run_import([snapshot(bid=100)])
        self.assertEqual(result.lots[0].current_bid, 500)
        self.assertEqual(result.lots[0].last_seen_at, "2026-10-17T21:00:00+00:00")
        self.assertEqual(result.metrics.cache_hits, 1)

    def test_source_error_leaves_existing_memberships_untouched(self):
        self.run_import([snapshot()])
        with patch("catalogapp.watchlist_sale_pages.read_saved_sale_pages", side_effect=ValueError("wrong sale")):
            with self.assertRaisesRegex(ValueError, "wrong sale"):
                import_saved_sale_pages(["wrong.html"], self.entry, self.cache, now=NOW)
        self.assertEqual(len(self.cache.active_lots_for_watch_url(PHILLIPS)), 1)

    def test_newer_doyle_grid_keeps_previously_verified_artwork_title(self):
        self.entry = bookmark(DOYLE)
        detailed = snapshot()
        detailed.source = "Doyle"
        detailed.title = "Verified artwork title"
        detailed.content_hash = detailed.calculate_content_hash()
        self.run_import([detailed])
        grid = NormalizedLot.from_dict(detailed.to_dict())
        grid.title = f"Lot {grid.lot_number}"
        grid.last_seen_at = "2026-10-17T21:00:00+00:00"
        grid.content_hash = grid.calculate_content_hash()
        result = self.run_import([grid])
        self.assertEqual(result.lots[0].title, "Verified artwork title")

    def test_shared_cache_import_preserves_doyle_title_on_newer_grid(self):
        detailed = snapshot()
        detailed.source = "Doyle"
        detailed.title = "Verified artwork title"
        self.cache.import_shared_lot(detailed, watch_urls=[DOYLE])
        grid = NormalizedLot.from_dict(detailed.to_dict())
        grid.title = f"Lot {grid.lot_number}"
        grid.last_seen_at = "2026-10-17T21:00:00+00:00"
        self.cache.import_shared_lot(grid, watch_urls=[DOYLE])
        self.assertEqual(self.cache.get(grid.cache_key).title, "Verified artwork title")


class SaleCalendarSyncTests(DjangoTestCase):
    @patch.dict(os.environ, {"CATALOG_API_KEY": "sale-sync-test"})
    def test_doyle_grid_resync_keeps_verified_title_and_saved_research(self):
        lot = AuctionWatchLot.objects.create(
            source="Doyle", source_lot_id="9224-123", artist="Example Artist",
            lot_number="12", title="Verified artwork title",
            artprice_url="https://www.artprice.com/lots/search?keyword=example",
            source_last_seen_at=datetime(2026, 10, 16, tzinfo=timezone.utc),
        )
        response = self.client.post("/calendar/sync/", json.dumps({"lots": [{
            "source": "Doyle", "source_lot_id": "9224-123", "artist": "Example Artist",
            "title": "Lot 12", "lot_number": "12", "start_at": "2026-10-20",
            "last_seen_at": "2026-10-17T20:00:00+00:00",
        }]}), content_type="application/json", HTTP_X_API_KEY="sale-sync-test")
        self.assertEqual(response.status_code, 200)
        lot.refresh_from_db()
        self.assertEqual(lot.title, "Verified artwork title")
        self.assertEqual(lot.artprice_url, "https://www.artprice.com/lots/search?keyword=example")
