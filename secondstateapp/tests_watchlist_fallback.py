"""A failed live refresh must not present historical changes as new observations."""

from dataclasses import replace
from datetime import datetime, timezone
from unittest import TestCase
from unittest.mock import Mock, patch

from catalogapp.bookmark_watchlist import BookmarkEntry
from catalogapp.watchlist_cache import WatchlistCache
from catalogapp.watchlist_enrichment import EnrichmentMetrics
from catalogapp.watchlist_fetch import SourceAccessError
from catalogapp.watchlist_models import NormalizedLot
from catalogapp.watchlist_service import WatchlistService


NOW = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)
PREVIOUS = datetime(2026, 10, 9, 12, tzinfo=timezone.utc)
ENTRY = BookmarkEntry(
    folder_path=("HERITAGE",), title="10-22 SALE", source="Heritage",
    url="https://fineart.ha.com/c/search/results.zx?auction_name=8280&dept=1544&mode=live",
)


class OfflineAdapter:
    source = "Heritage"

    def __init__(self, pages):
        self.pages = pages

    def fetch_search_page(self, url, _fetcher):
        value = self.pages[url]
        if isinstance(value, Exception):
            raise value
        return value

    def parse_search_page(self, page, _url, _artist):
        return [replace(lot) for lot in page["lots"]]

    def needs_detail(self, _lot):
        return False

    def extract_next_page_url(self, page, _url):
        return page.get("next", "")


class WatchlistFallbackTests(TestCase):
    def setUp(self):
        self.cache = WatchlistCache(":memory:")
        self.addCleanup(self.cache.close)
        self.lot = NormalizedLot(
            source="Heritage", source_lot_id="8280-65001", artist="Pablo Picasso",
            artist_watchlist_name="Pablo Picasso", title="Portrait", start_at="2026-10-22",
            lot_url="https://fineart.ha.com/itm/prints/work/a/8280-65001.s", current_bid=100,
        )
        self.cache.upsert(self.lot, watch_url=ENTRY.url, search_hash=self.lot.content_hash, observed_at=PREVIOUS)
        self.lot = replace(self.lot, current_bid=200, content_hash="")
        self.cache.upsert(self.lot, watch_url=ENTRY.url, search_hash=self.lot.content_hash, observed_at=PREVIOUS)
        self.assertEqual(self.lot.status, "changed")

    def refresh(self, pages, **kwargs):
        adapter = OfflineAdapter(pages)
        enricher = Mock(enabled=True)
        enricher.enrich.return_value = EnrichmentMetrics()
        service = WatchlistService(self.cache, fetcher=Mock(pages_fetched=0), enricher=enricher, now=lambda: NOW)
        with patch("catalogapp.watchlist_service.adapter_for_url", return_value=adapter):
            result = service.refresh([ENTRY], selected_artists=[ENTRY.watch_label], horizon_days=30, **kwargs)
        return result, enricher

    def test_single_source_failure_marks_cached_provenance_without_rewriting_observation(self):
        with patch.object(self.cache, "update_payload", wraps=self.cache.update_payload) as update:
            result, enricher = self.refresh({ENTRY.url: SourceAccessError("HTTP 403")}, zero_ai=False)
        self.assertEqual(result.fallback_lot_keys, {self.lot.cache_key})
        self.assertEqual(result.lots[0].status, "changed")
        self.assertEqual(result.lots[0].last_seen_at, PREVIOUS.isoformat())
        stored = self.cache.get(self.lot.cache_key)
        self.assertEqual(stored.last_seen_at, PREVIOUS.isoformat())
        self.assertEqual(stored.status, "changed")
        self.assertEqual(result.metrics.changed_lots, 0)
        self.assertIn("live data was not verified", result.errors[0])
        enricher.enrich.assert_called_once_with([], zero_ai=False)
        update.assert_not_called()

    def test_new_changed_filter_excludes_historical_change_from_failed_source(self):
        result, _ = self.refresh({ENTRY.url: SourceAccessError("HTTP 403")}, new_changed_only=True)
        self.assertEqual(result.lots, [])
        self.assertEqual(result.fallback_lot_keys, set())
        self.assertIn("Hidden by New/changed only", result.errors[0])
        self.assertEqual(len(self.cache.active_lots_for_watch_url(ENTRY.url)), 1)

    def test_page_two_failure_marks_only_lots_not_successfully_observed_on_page_one(self):
        another = replace(self.lot, source_lot_id="8280-65002", title="Another print", content_hash="")
        self.cache.upsert(another, watch_url=ENTRY.url, search_hash=another.content_hash, observed_at=PREVIOUS)
        fresh = replace(self.lot, current_bid=300, content_hash="")
        result, _ = self.refresh({
            ENTRY.url: {"lots": [fresh], "next": "page-two"},
            "page-two": SourceAccessError("HTTP 503"),
        })
        self.assertEqual(result.fallback_lot_keys, {another.cache_key})
        lots = {lot.cache_key: lot for lot in result.lots}
        self.assertEqual(lots[self.lot.cache_key].last_seen_at, NOW.isoformat())
        self.assertEqual(lots[another.cache_key].last_seen_at, PREVIOUS.isoformat())
        self.assertEqual(result.metrics.changed_lots, 1)

    def test_successful_cached_detail_reuse_is_still_a_fresh_observation(self):
        result, _ = self.refresh({ENTRY.url: {"lots": [self.lot]}})
        self.assertEqual(result.fallback_lot_keys, set())
        self.assertEqual(result.lots[0].status, "unchanged")
        self.assertEqual(result.lots[0].last_seen_at, NOW.isoformat())

    def test_batch_failure_marks_provenance_for_every_retained_lot(self):
        second_entry = replace(ENTRY, title="Another artist", artist="Keith Haring", url=ENTRY.url + "&artist=Haring")
        adapter = OfflineAdapter({})
        adapter.fetch_search_batch = Mock(side_effect=SourceAccessError("HTTP 403"))
        service = WatchlistService(self.cache, fetcher=Mock(pages_fetched=0), now=lambda: NOW)
        with patch("catalogapp.watchlist_service.adapter_for_url", return_value=adapter):
            result = service.refresh(
                [ENTRY, second_entry], selected_artists=[ENTRY.watch_label, second_entry.watch_label], horizon_days=30
            )
        self.assertEqual(result.fallback_lot_keys, {self.lot.cache_key})
        self.assertEqual(result.lots[0].last_seen_at, PREVIOUS.isoformat())
        adapter.fetch_search_batch.assert_called_once()
