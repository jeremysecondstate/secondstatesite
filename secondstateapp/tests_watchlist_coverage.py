"""Coverage persists independently of lot counts and drives targeted recovery."""

from datetime import timedelta
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from catalogapp.watchlist_adapters import InvaluableAdapter
from catalogapp.watchlist_cache import WatchlistCache
from catalogapp.watchlist_fetch import SourceAccessBlocked, SourceAccessError
from catalogapp.watchlist_service import WatchlistService
from secondstateapp.tests_watchlist_batch_recovery import NOW, PREVIOUS, CatalogFetcher, entry, hit, response


class WatchlistCoverageTests(TestCase):
    def setUp(self):
        self.cache = WatchlistCache(":memory:")
        self.addCleanup(self.cache.close)
        self.adapter = InvaluableAdapter()
        self.entries = [entry(number) for number in range(4)]

    def refresh(self, fetcher, *, entries=None, now=NOW, **kwargs):
        entries = self.entries if entries is None else entries
        with patch("catalogapp.watchlist_service.adapter_for_url", return_value=self.adapter):
            return WatchlistService(self.cache, fetcher=fetcher, now=lambda: now).refresh(
                entries, selected_artists=[item.artist for item in entries], horizon_days=30, **kwargs,
            )

    def seed(self, item):
        lot = self.adapter.parse_search_page(json.dumps(response([hit(item.artist)])), item.url, item.artist)[0]
        self.cache.upsert(lot, watch_url=item.url, search_hash=lot.content_hash, observed_at=PREVIOUS)
        return lot

    def test_complete_zero_is_verified_and_not_retried_as_missing(self):
        fetcher = CatalogFetcher(lambda artists, page: response())
        result = self.refresh(fetcher, entries=self.entries[:1], pending_only=True)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.coverage[0].state, "empty")
        self.assertEqual(result.coverage[0].lot_count, 0)
        self.assertEqual(result.coverage[0].checked_at, NOW.isoformat())

        later = CatalogFetcher(lambda artists, page: self.fail("A complete zero must be skipped"))
        again = self.refresh(later, entries=self.entries[:1], pending_only=True)
        self.assertEqual(later.calls, [])
        self.assertEqual(again.coverage[0].state, "empty")

    def test_cache_without_catalog_evidence_is_pending_and_survives_restart(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "cache.sqlite3"
            with WatchlistCache(path) as cache:
                self.assertEqual(cache.coverage_for_entries(self.entries)[0].state, "pending")
                cache.record_source_success(self.entries[0].url, PREVIOUS)
                # Legacy source success may include detail/snapshot history; do
                # not infer complete catalog coverage during schema migration.
                self.assertEqual(cache.coverage_for_entries(self.entries)[0].state, "pending")
                cache.record_watch_coverage(self.entries[0].url, "empty", observed_at=NOW)
            with WatchlistCache(path) as cache:
                saved = cache.coverage_for_entries(self.entries)
                self.assertEqual(saved[0].state, "empty")
                self.assertEqual(saved[0].checked_at, NOW.isoformat())
                self.assertEqual(saved[1].state, "pending")

    def test_pending_recovery_fetches_individually_and_merges_verified_cached_lots(self):
        cached = self.seed(self.entries[0])
        self.cache.record_watch_coverage(self.entries[0].url, "verified", observed_at=NOW)
        self.cache.record_watch_coverage(self.entries[1].url, "empty", observed_at=NOW)
        fetcher = CatalogFetcher(lambda artists, page: response([hit(artists[0])]))

        result = self.refresh(fetcher, pending_only=True)

        self.assertEqual(fetcher.calls, [(["Artist 2"], 0), (["Artist 3"], 0)])
        self.assertEqual(len(result.lots), 3)
        self.assertEqual(result.fallback_lot_keys, {cached.cache_key})
        self.assertEqual(self.cache.get(cached.cache_key).last_seen_at, PREVIOUS.isoformat())
        self.assertEqual([item.state for item in result.coverage], ["verified", "empty", "verified", "verified"])
        self.assertEqual(result.metrics.ended_lots, 0)

    def test_access_block_stops_requests_and_next_explicit_recovery_advances_queue(self):
        cached = [self.seed(item) for item in self.entries]
        def blocked(artists, page):
            raise SourceAccessBlocked("HTTP 202")
        first = CatalogFetcher(blocked)
        result = self.refresh(first, pending_only=True)
        self.assertEqual(first.calls, [(["Artist 0"], 0)])
        self.assertEqual([item.state for item in result.coverage], ["blocked"] * 4)
        self.assertEqual(result.coverage[0].checked_at, NOW.isoformat())
        self.assertTrue(all(not item.checked_at for item in result.coverage[1:]))
        self.assertEqual(result.fallback_lot_keys, {lot.cache_key for lot in cached})
        self.assertEqual(result.metrics.ended_lots, 0)

        second = CatalogFetcher(blocked)
        next_result = self.refresh(second, now=NOW + timedelta(minutes=2), pending_only=True)
        self.assertEqual(second.calls, [(["Artist 1"], 0)])
        self.assertEqual(next_result.coverage[0].checked_at, NOW.isoformat())
        self.assertEqual(next_result.coverage[1].checked_at, (NOW + timedelta(minutes=2)).isoformat())

    def test_partial_artist_never_ends_unseen_lots_and_keeps_received_page(self):
        prior = self.seed(self.entries[0])
        def handler(artists, page):
            if page:
                raise SourceAccessBlocked("HTTP 202")
            return response([hit(artists[0], "new-lot")], pages=2)
        result = self.refresh(CatalogFetcher(handler), entries=self.entries[:1], pending_only=True)
        self.assertEqual(result.coverage[0].state, "blocked")
        self.assertEqual(result.coverage[0].lot_count, 2)
        self.assertEqual(len(result.lots), 2)
        self.assertEqual(result.metrics.ended_lots, 0)
        self.assertEqual(result.fallback_lot_keys, {prior.cache_key})
        self.assertEqual(self.cache.get(prior.cache_key).last_seen_at, PREVIOUS.isoformat())

    def test_optional_detail_error_does_not_turn_complete_catalog_into_pending(self):
        raw = hit("Artist 0")
        raw["houseName"] = ""
        fetcher = CatalogFetcher(lambda artists, page: response([raw]))
        fetcher.fetch.side_effect = SourceAccessError("Lot detail unavailable")
        result = self.refresh(fetcher, entries=self.entries[:1], pending_only=True)
        self.assertTrue(result.errors)
        self.assertEqual(result.coverage[0].state, "verified")
        self.assertEqual(result.coverage[0].lot_count, 1)
        row = self.cache.connection.execute("SELECT last_error FROM source_runs").fetchone()
        self.assertIn("Lot detail unavailable", row["last_error"])

    def test_unreadable_nonempty_catalog_is_not_verified_empty(self):
        fetcher = CatalogFetcher(lambda artists, page: response([{"objectID": "no-title"}]))
        result = self.refresh(fetcher, entries=self.entries[:1], pending_only=True)
        self.assertNotEqual(result.coverage[0].state, "empty")
        self.assertTrue(result.errors)

    def test_full_refresh_checks_verified_empty_again(self):
        self.cache.record_watch_coverage(self.entries[0].url, "empty", observed_at=PREVIOUS)
        result = self.refresh(CatalogFetcher(lambda artists, page: response([hit(artists[0])])), entries=self.entries[:1])
        self.assertEqual(result.coverage[0].state, "verified")
        self.assertEqual(len(result.lots), 1)

    def test_incomplete_pagination_metadata_never_verifies_or_ends_cached_lots(self):
        variants = [
            {"hits": []},
            {"hits": [], "page": 0},
            {"hits": [], "page": 0, "nbPages": False},
            {"hits": [], "page": 1, "nbPages": 2},
            {"hits": [], "page": 0, "nbPages": 2},
            {"hits": [], "page": 0, "nbPages": 0, "nbHits": 1},
            {"hits": [hit("Artist 0")], "page": 0, "nbPages": 1,
             "nbHits": 2, "hitsPerPage": 96},
        ]
        prior = self.seed(self.entries[0])
        for variant in variants:
            with self.subTest(variant=variant):
                fetcher = CatalogFetcher(lambda artists, page: {"results": [variant]})
                result = self.refresh(fetcher, entries=self.entries[:1], pending_only=True)
                self.assertNotIn(result.coverage[0].state, {"verified", "empty"})
                self.assertEqual(result.metrics.ended_lots, 0)
                self.assertEqual(result.fallback_lot_keys, {prior.cache_key})
                self.assertEqual(self.cache.get(prior.cache_key).last_seen_at, PREVIOUS.isoformat())

    def test_malformed_later_page_retains_earlier_page_for_individual_and_batch(self):
        for individual in (True, False):
            with self.subTest(individual=individual), WatchlistCache(":memory:") as cache:
                original_cache = self.cache
                self.cache = cache
                try:
                    prior = self.seed(self.entries[0])
                    def handler(artists, page):
                        if page:
                            return {"results": [{"hits": [], "page": page}]}
                        return response([hit(artists[0], "new-lot")], pages=2)
                    result = self.refresh(
                        CatalogFetcher(handler), entries=self.entries[:2], pending_only=individual,
                    )
                    self.assertEqual(result.coverage[0].state, "partial")
                    self.assertEqual(result.metrics.ended_lots, 0)
                    self.assertIn(prior.cache_key, result.fallback_lot_keys)
                    self.assertIn("invaluable:new-lot", {lot.cache_key for lot in result.lots})
                    self.assertEqual(self.cache.get(prior.cache_key).last_seen_at, PREVIOUS.isoformat())
                finally:
                    self.cache = original_cache
