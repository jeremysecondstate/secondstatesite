"""Narrow live requests without turning future cached lots into ended sales."""

from datetime import timedelta
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from catalogapp.watchlist_adapters import InvaluableAdapter
from catalogapp.watchlist_cache import WatchlistCache
from catalogapp.watchlist_service import WatchlistService
from secondstateapp.tests_watchlist_batch_recovery import NOW, PREVIOUS, CatalogFetcher, entry, hit, response


class SevenDayCatalogTests(TestCase):
    def setUp(self):
        self.cache = WatchlistCache(":memory:")
        self.addCleanup(self.cache.close)
        self.adapter = InvaluableAdapter()
        self.entries = [entry(index) for index in range(2)]

    def refresh(self, fetcher, *, entries=None, now=NOW, horizon_days=7, **kwargs):
        entries = self.entries if entries is None else entries
        with patch("catalogapp.watchlist_service.adapter_for_url", return_value=self.adapter):
            return WatchlistService(self.cache, fetcher=fetcher, now=lambda: now).refresh(
                entries, selected_artists=[item.artist for item in entries], horizon_days=horizon_days, **kwargs,
            )

    def seed(self, identity, *, when=NOW + timedelta(days=2), watch=None):
        watch = watch or self.entries[0]
        raw = hit(watch.artist, identity)
        raw["dateTimeUTCUnix"] = int(when.timestamp()) if when else 0
        lot = self.adapter.parse_search_page(json.dumps(response([raw])), watch.url, watch.artist)[0]
        self.cache.upsert(lot, watch_url=watch.url, search_hash=lot.content_hash, observed_at=PREVIOUS)
        return lot

    def test_individual_and_batch_requests_apply_same_seven_day_source_filter(self):
        cutoff = int((NOW + timedelta(days=7)).timestamp())
        for individual in (True, False):
            with self.subTest(individual=individual):
                fetcher = CatalogFetcher(lambda artists, page: response())
                original = fetcher.post_json
                payloads = []

                def capture(url, payload, **kwargs):
                    payloads.append(payload)
                    return original(url, payload, **kwargs)

                fetcher.post_json = capture
                self.refresh(fetcher, entries=self.entries[:1] if individual else self.entries)
                self.assertTrue(payloads)
                for payload in payloads:
                    filters = payload["requests"][0]["params"]["filters"]
                    self.assertIn(f"(dateTimeUTCUnix <= {cutoff} OR endTimeUTCUnix:1 TO {cutoff})", filters)
                    self.assertNotIn("dateTimeUTCUnix >=", filters)
        self.assertIsNone(self.adapter.catalog_end)

    def test_narrow_complete_search_preserves_later_and_undated_cached_lots(self):
        within = self.seed("within")
        future = self.seed("future", when=NOW + timedelta(days=10))
        undated = self.seed("undated", when=None)
        result = self.refresh(CatalogFetcher(lambda artists, page: response()), entries=self.entries[:1])
        self.assertEqual(result.metrics.ended_lots, 1)
        self.assertEqual(self.cache.get(within.cache_key).status, "ended")
        self.assertEqual(self.cache.get(future.cache_key).last_seen_at, PREVIOUS.isoformat())
        self.assertNotEqual(self.cache.get(future.cache_key).status, "ended")
        self.assertNotEqual(self.cache.get(undated.cache_key).status, "ended")
        self.assertEqual({lot.cache_key for lot in self.cache.active_lots_for_watch_url(self.entries[0].url)},
                         {future.cache_key, undated.cache_key})

    def test_future_cache_does_not_turn_complete_window_zero_into_nonempty(self):
        self.seed("future", when=NOW + timedelta(days=10))
        result = self.refresh(CatalogFetcher(lambda artists, page: response()), entries=self.entries[:1])
        self.assertEqual(result.coverage[0].state, "empty")
        self.assertEqual(result.coverage[0].lot_count, 0)
        self.assertEqual(result.coverage[0].covered_until, (NOW + timedelta(days=7)).isoformat())
        self.assertIn("next 7 days", result.coverage[0].detail)

    def test_same_day_recovery_skips_complete_window_but_next_day_checks_again(self):
        self.refresh(CatalogFetcher(lambda artists, page: response()), entries=self.entries[:1])
        same_day = CatalogFetcher(lambda artists, page: self.fail("No redundant same-day check"))
        self.refresh(same_day, entries=self.entries[:1], now=NOW + timedelta(minutes=2), pending_only=True)
        self.assertEqual(same_day.calls, [])
        next_day = CatalogFetcher(lambda artists, page: response([hit(artists[0])]))
        result = self.refresh(next_day, entries=self.entries[:1], now=NOW + timedelta(days=1), pending_only=True)
        self.assertEqual(len(next_day.calls), 1)
        self.assertEqual(result.coverage[0].state, "verified")

    def test_expanded_horizon_is_pending_and_refetched(self):
        self.refresh(CatalogFetcher(lambda artists, page: response()), entries=self.entries[:1])
        expanded = CatalogFetcher(lambda artists, page: response())
        self.refresh(expanded, entries=self.entries[:1], horizon_days=30, pending_only=True)
        self.assertEqual(len(expanded.calls), 1)

    def test_new_uncached_artist_runs_before_older_cached_pending_artist(self):
        self.seed("cached")
        fetcher = CatalogFetcher(lambda artists, page: response())
        self.refresh(fetcher, pending_only=True)
        self.assertEqual(fetcher.calls, [(["Artist 1"], 0), (["Artist 0"], 0)])

    def test_window_scope_survives_restart(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "cache.sqlite3"
            with WatchlistCache(path) as cache:
                cache.record_watch_coverage(self.entries[0].url, "empty", observed_at=NOW,
                                            covered_until=NOW + timedelta(days=7))
            with WatchlistCache(path) as cache:
                saved = cache.coverage_for_entries(self.entries[:1], observed_at=NOW, horizon_days=7)[0]
                self.assertEqual(saved.state, "empty")
                self.assertEqual(saved.covered_until, (NOW + timedelta(days=7)).isoformat())
                later = cache.coverage_for_entries(self.entries[:1], observed_at=NOW + timedelta(days=1), horizon_days=7)[0]
                self.assertTrue(later.needs_recovery)

    def test_legacy_coverage_schema_gains_scope_without_losing_evidence(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "cache.sqlite3"
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute("CREATE TABLE watch_coverage (watch_url TEXT PRIMARY KEY, state TEXT, last_attempt_at TEXT, detail TEXT)")
                connection.execute("INSERT INTO watch_coverage VALUES (?, ?, ?, ?)",
                                   (self.entries[0].url, "empty", NOW.isoformat(), "Complete legacy catalog"))
            with WatchlistCache(path) as cache:
                saved = cache.coverage_for_entries(self.entries[:1], observed_at=NOW, horizon_days=7)[0]
                self.assertEqual(saved.state, "empty")
                self.assertEqual(saved.covered_until, "")
                self.assertEqual(saved.detail, "Complete legacy catalog")

    def test_source_scope_includes_closing_time_even_when_auction_time_is_later(self):
        scoped = self.adapter.with_catalog_end(NOW + timedelta(days=7))
        cutoff = int((NOW + timedelta(days=7)).timestamp())
        params = scoped._catalog_request_payload(self.entries[0].url)["requests"][0]["params"]
        self.assertIn(f"OR endTimeUTCUnix:1 TO {cutoff}", params["filters"])
        raw = hit(self.entries[0].artist, "closing")
        raw["dateTimeUTCUnix"] = int((NOW + timedelta(days=12)).timestamp())
        raw["endTimeUTCUnix"] = int((NOW + timedelta(days=2)).timestamp())
        result = self.refresh(CatalogFetcher(lambda artists, page: response([raw])), entries=self.entries[:1])
        self.assertEqual(len(result.lots), 1)
        self.assertEqual(result.lots[0].end_at, (NOW + timedelta(days=2)).isoformat())
