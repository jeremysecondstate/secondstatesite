"""Saved sold-result pages can update only an existing selected watched lot."""

from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from catalogapp.bookmark_watchlist import BookmarkEntry
from catalogapp.watchlist_adapters import InvaluableAdapter
from catalogapp.watchlist_cache import WatchlistCache
from catalogapp.watchlist_models import NormalizedLot
from catalogapp.watchlist_sold_pages import import_saved_sold_pages


NOW = datetime(2026, 10, 14, 20, tzinfo=timezone.utc)
OLD = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)
LOT_URL = "https://www.invaluable.com/auction-lot/alexander-calder-nid-daraignee-116-c-synthetic116"
ENTRY = BookmarkEntry(folder_path=("ARTISTS INVALUABLE",), title="Calder", artist="Alexander Calder", source="Invaluable", url="https://www.invaluable.com/search?artistName=Alexander+Calder")
OTHER_ENTRY = BookmarkEntry(folder_path=ENTRY.folder_path, title="Warhol", artist="Andy Warhol", source="Invaluable", url="https://www.invaluable.com/search?artistName=Andy+Warhol")


class SavedInvaluableSoldPagesTests(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.cache = WatchlistCache(":memory:")
        self.addCleanup(self.cache.close)
        self.lot = NormalizedLot(source="Invaluable", source_lot_id="205299116", artist="Alexander Calder", artist_watchlist_name="Alexander Calder", title="Nid d'araignee", medium="Lithograph", auction_house="Rago", lot_number="116", end_at="2026-10-14T15:00:00-04:00", estimate_low=3000, estimate_high=5000, current_bid=6000, currency="USD", lot_url=LOT_URL, image_url="https://image.invaluable.com/housePhotos/original.jpg", saved_image_base64="sanitized-cached-artwork")
        self.cache.upsert(self.lot, watch_url=ENTRY.url, search_hash="original-search-hash", observed_at=OLD)

    def page(self, name="sold.html", *, url=LOT_URL, sold="Sold: $11,000 USD", identity="canonical", raw=None, body=""):
        path = Path(self.directory.name) / name
        if identity == "canonical":
            source = f'<link rel="canonical" href="{url}">'
        elif identity == "social":
            source = f'<meta property="og:url" content="{url}">'
        elif identity == "saved-origin":
            source = f'<!-- saved from url=(0123){url} -->'
        else:
            source = ""
        metadata = f'<script type="application/ld+json">{json.dumps(raw)}</script>' if raw else ""
        path.write_text(f'<html>{source}{metadata}<body>Private User Name <h1>Lot 116: Calder lithograph</h1><p>{sold}</p>{body}<script>cookie="PRIVATE-SESSION-TOKEN"</script></body></html>', encoding="utf-8")
        return path

    def run_import(self, paths, entries=(ENTRY,), **kwargs):
        return import_saved_sold_pages(paths, entries=entries, cache=self.cache, now=NOW, **kwargs)

    def test_import_uses_no_network_and_preserves_cached_identity_and_artwork(self):
        path = self.page(raw={"lotId": "synthetic116", "url": LOT_URL, "title": "Altered title", "artist": "Other artist", "image": "https://elsewhere.example/private.jpg", "estimateLow": 1, "endAt": "2030-01-01", "currentBid": 1})
        with patch.object(InvaluableAdapter, "fetch_lot_detail", side_effect=AssertionError("No network")):
            result = self.run_import([path])
        self.assertEqual(result.metrics.changed_lots, 1)
        self.assertEqual(result.metrics.pages_fetched, 0)
        imported = result.lots[0]
        self.assertEqual(imported.sold_price, 11000)
        self.assertEqual(imported.sold_currency, "USD")
        for field in ("source_lot_id", "lot_url", "artist", "title", "image_url", "saved_image_base64", "estimate_low", "end_at", "current_bid", "first_seen_at"):
            self.assertEqual(getattr(imported, field), getattr(self.lot, field))
        self.assertEqual(imported.last_seen_at, NOW.isoformat())
        self.assertEqual(self.cache.lookup(imported).search_hash, "original-search-hash")
        self.assertEqual(self.cache.active_lots_for_watch_url(ENTRY.url), [])
        stored = "\n".join(self.cache.connection.iterdump())
        self.assertNotIn("PRIVATE-SESSION-TOKEN", stored)
        self.assertNotIn("Private User Name", stored)
        self.assertNotIn("<html>", stored)
        self.assertNotIn("elsewhere.example", stored)

    def test_repeated_result_is_unchanged_and_changed_posted_amount_updates(self):
        path = self.page()
        self.run_import([path])
        repeated = self.run_import([path])
        self.assertEqual(repeated.metrics.unchanged_lots, 1)
        newer = self.page("corrected.html", sold="Sold: $12,000 USD")
        corrected = self.run_import([newer])
        self.assertEqual(corrected.metrics.changed_lots, 1)
        self.assertEqual(corrected.lots[0].sold_price, 12000)

    def test_ended_memberships_can_receive_late_posted_results(self):
        self.cache.mark_missing_ended(ENTRY.url, [], observed_at=OLD)
        result = self.run_import([self.page()])
        self.assertEqual(result.lots[0].sold_price, 11000)
        self.assertEqual(self.cache.active_lots_for_watch_url(ENTRY.url), [])

    def test_import_cannot_update_a_lot_outside_selected_artist_memberships(self):
        before = self.cache.get(self.lot.cache_key).to_dict()
        result = self.run_import([self.page()], entries=(OTHER_ENTRY,))
        self.assertEqual(result.lots, [])
        self.assertTrue(result.notices)
        self.assertEqual(self.cache.get(self.lot.cache_key).to_dict(), before)

    def test_unmatched_identity_never_matches_by_title_artist_or_lot_number(self):
        result = self.run_import([self.page(url=LOT_URL.replace("synthetic116", "another116"))])
        self.assertEqual(result.lots, [])
        self.assertTrue(result.notices)
        self.assertIsNone(self.cache.get(self.lot.cache_key).sold_price)

    def test_changed_title_slug_matches_the_same_invaluable_reference(self):
        result = self.run_import([self.page(url="https://www.invaluable.com/auction-lot/updated-title-116-c-synthetic116")])
        self.assertEqual(result.lots[0].source_lot_id, self.lot.source_lot_id)
        self.assertEqual(result.lots[0].lot_url, LOT_URL)

    def test_gated_result_leaves_existing_record_completely_unchanged(self):
        before = self.cache.get(self.lot.cache_key).to_dict()
        result = self.run_import([self.page(sold="Sold: Log in to view", body="<p>Estimate: $3,000 - $5,000</p>")])
        self.assertEqual(result.lots, [])
        self.assertIn("no posted Sold price", result.notices[0])
        self.assertEqual(self.cache.get(self.lot.cache_key).to_dict(), before)

    def test_missing_invalid_and_unallowed_origin_are_ignored(self):
        for identity, url in (("none", LOT_URL), ("canonical", "https://invaluable.com.evil.example/auction-lot/fake"), ("canonical", "https://www.invaluable.com/search?artistName=Calder"), ("canonical", "https://user:password@www.invaluable.com/auction-lot/fake")):
            with self.subTest(identity=identity, url=url):
                result = self.run_import([self.page(identity=identity, url=url)])
                self.assertEqual(result.lots, [])
                self.assertTrue(result.notices)

    def test_saved_origin_and_social_page_identity_are_supported(self):
        for identity in ("social", "saved-origin"):
            with self.subTest(identity=identity):
                result = self.run_import([self.page(identity=identity)])
                self.assertEqual(result.lots[0].sold_price, 11000)

    def test_independent_valid_page_is_imported_alongside_unmatched_page(self):
        result = self.run_import([self.page(), self.page("unknown.html", url=LOT_URL.replace("synthetic116", "unknown"))])
        self.assertEqual(len(result.lots), 1)
        self.assertEqual(len(result.notices), 1)

    def test_conflicting_results_do_not_change_cached_lot(self):
        before = self.cache.get(self.lot.cache_key).to_dict()
        result = self.run_import([self.page(), self.page("conflict.html", sold="Sold: $12,000 USD")])
        self.assertEqual(result.lots, [])
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(self.cache.get(self.lot.cache_key).to_dict(), before)

    def test_unreadable_or_non_html_files_report_errors_without_changes(self):
        result = self.run_import([Path(self.directory.name) / "missing.html", self.page("sold.txt")])
        self.assertEqual(result.lots, [])
        self.assertEqual(len(result.errors), 2)
        self.assertIsNone(self.cache.get(self.lot.cache_key).sold_price)
