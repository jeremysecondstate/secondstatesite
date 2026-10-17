"""Recover public HTTP 202 catalogs without repeating completed artists."""

from datetime import timedelta
import json
import threading
from unittest import TestCase
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from catalogapp.watchlist_adapters import InvaluableAdapter
from catalogapp.watchlist_cache import WatchlistCache
from catalogapp.watchlist_fetch import SourceAccessBlocked, SourceAccessError, WatchlistStopped
from catalogapp.watchlist_service import WatchlistService
from secondstateapp.tests_watchlist_batch_recovery import NOW, PREVIOUS, CatalogFetcher, entry, hit, response


class PublicCatalogFetcher:
    uses_natural_catalog_requests = True

    def __init__(self, handler):
        self.handler = handler
        self.calls = []
        self.pages_fetched = 0
        self.fetch = Mock(side_effect=AssertionError("Optional detail requests are not calendar recovery"))

    def fetch_search_page(self, url):
        query = parse_qs(urlsplit(url).query)
        artist = query["artistName"][0]
        page = int(query.get("page", [1])[0]) - 1
        self.calls.append((artist, page))
        value = self.handler(artist, page)
        self.pages_fetched += 1
        return json.dumps(value)


class AutomaticBrowserRecoveryTests(TestCase):
    def setUp(self):
        self.cache = WatchlistCache(":memory:")
        self.addCleanup(self.cache.close)
        self.adapter = InvaluableAdapter()
        self.entries = [entry(index) for index in range(17)]

    def seed(self, watched, identity=None, *, when=None):
        raw = hit(watched.artist, identity)
        if when is not None:
            raw["dateTimeUTCUnix"] = int(when.timestamp())
        lot = self.adapter.parse_search_page(json.dumps(response([raw])), watched.url, watched.artist)[0]
        self.cache.upsert(lot, watch_url=watched.url, search_hash=lot.content_hash, observed_at=PREVIOUS)
        self.cache.record_source_success(watched.url, PREVIOUS)
        return lot

    def refresh(self, http, browser=None, *, entries=None, factory=None, max_pages=10, **kwargs):
        entries = self.entries if entries is None else entries
        self.factory = factory or Mock(return_value=browser)
        with patch("catalogapp.watchlist_service.adapter_for_url", return_value=self.adapter):
            return WatchlistService(
                self.cache, fetcher=http, invaluable_recovery_factory=self.factory, now=lambda: NOW,
                max_pages_per_bookmark=max_pages,
            ).refresh(entries, selected_artists=[item.artist for item in entries], **kwargs)

    @staticmethod
    def blocked(_artists, _page):
        raise SourceAccessBlocked("Invaluable returned an access page (HTTP 202).")

    def test_successful_http_never_constructs_browser(self):
        http = CatalogFetcher(lambda artists, page: response([hit(artist) for artist in artists]))
        result = self.refresh(http)
        self.factory.assert_not_called()
        self.assertEqual(result.errors, [])
        self.assertEqual(len(result.lots), 17)

    def test_recovers_only_blocked_groups_and_preserves_completed_lot_provenance(self):
        seeded = [self.seed(item) for item in self.entries]

        def handler(artists, page):
            if artists[0] == "Artist 8":
                return self.blocked(artists, page)
            return response([hit(artist, bid=200) for artist in artists])

        http = CatalogFetcher(handler)
        browser = PublicCatalogFetcher(lambda artist, page: response([hit(artist, bid=200)]))
        result = self.refresh(http, browser)

        self.assertEqual(len(http.calls), 2)
        self.assertEqual(browser.calls, [(f"Artist {index}", 0) for index in range(8, 17)])
        self.factory.assert_called_once_with()
        self.assertEqual(result.errors, [])
        self.assertEqual(result.fallback_lot_keys, set())
        self.assertEqual(result.metrics.changed_lots, 17)
        self.assertEqual(result.metrics.pages_fetched, 10)
        self.assertTrue(all(item.state == "verified" for item in result.coverage))
        self.assertTrue(all(self.cache.get(lot.cache_key).last_seen_at == NOW.isoformat() for lot in seeded))

    def test_partial_http_cards_survive_browser_block_without_ending_unseen_lots(self):
        prior = self.seed(self.entries[0], "unseen")
        other = self.seed(self.entries[1])

        def handler(artists, page):
            if page:
                return self.blocked(artists, page)
            return response([hit(artists[0], "fresh")], pages=2)

        browser = PublicCatalogFetcher(lambda artist, page: self.blocked(artist, page))
        result = self.refresh(CatalogFetcher(handler), browser, entries=self.entries[:2])

        self.assertEqual(browser.calls, [("Artist 0", 0)])
        self.assertEqual({lot.source_lot_id for lot in result.lots}, {"fresh", "unseen", "Artist1"})
        self.assertEqual(result.fallback_lot_keys, {prior.cache_key, other.cache_key})
        self.assertEqual(self.cache.get("invaluable:fresh").last_seen_at, NOW.isoformat())
        self.assertEqual(self.cache.get(prior.cache_key).last_seen_at, PREVIOUS.isoformat())
        self.assertEqual(result.metrics.ended_lots, 0)
        self.assertTrue(all(item.needs_recovery for item in result.coverage))

    def test_repeated_partial_cards_count_once_and_complete_browser_can_end_missing_lots(self):
        prior = self.seed(self.entries[0], "unseen")

        def handler(artists, page):
            if page:
                return self.blocked(artists, page)
            return response([hit(artists[0], "fresh")], pages=2)

        browser = PublicCatalogFetcher(lambda artist, page: response([hit(artist, "fresh")] if artist == "Artist 0" else []))
        result = self.refresh(CatalogFetcher(handler), browser, entries=self.entries[:2])

        self.assertEqual(result.errors, [])
        self.assertEqual(result.metrics.new_lots, 1)
        self.assertEqual(result.metrics.unchanged_lots, 0)
        self.assertEqual(result.metrics.ended_lots, 1)
        self.assertEqual(self.cache.get(prior.cache_key).status, "ended")
        self.assertEqual(self.cache.get("invaluable:fresh").status, "new")
        self.assertEqual(result.fallback_lot_keys, set())

    def test_browser_zero_retires_only_covered_lots_and_records_empty(self):
        within = self.seed(self.entries[0], "within")
        future = self.seed(self.entries[0], "future", when=NOW + timedelta(days=10))
        browser = PublicCatalogFetcher(lambda artist, page: response())
        result = self.refresh(CatalogFetcher(self.blocked), browser, entries=self.entries[:1])
        self.assertEqual(result.errors, [])
        self.assertEqual(result.coverage[0].state, "empty")
        self.assertEqual(self.cache.get(within.cache_key).status, "ended")
        self.assertNotEqual(self.cache.get(future.cache_key).status, "ended")
        self.assertEqual(self.cache.get(future.cache_key).last_seen_at, PREVIOUS.isoformat())

    def test_complete_browser_zero_supersedes_earlier_partial_http_cards(self):
        def http_handler(artists, page):
            if page:
                return self.blocked(artists, page)
            return response([hit(artists[0], "disappeared")], pages=2)

        result = self.refresh(
            CatalogFetcher(http_handler), PublicCatalogFetcher(lambda artist, page: response()),
            entries=self.entries[:2],
        )
        self.assertEqual(result.errors, [])
        self.assertEqual(result.coverage[0].state, "empty")
        self.assertEqual(self.cache.get("invaluable:disappeared").status, "ended")
        self.assertEqual(next(lot.status for lot in result.lots if lot.source_lot_id == "disappeared"), "ended")

    def test_successful_browser_recovery_preserves_unrelated_http_group_error(self):
        prior = [self.seed(watched) for watched in self.entries][0]

        def http_handler(artists, page):
            if artists[0] == "Artist 0":
                raise SourceAccessError("HTTP 503")
            return self.blocked(artists, page)

        # Give every watch the same prior coverage so batch order stays stable.
        for watched in self.entries:
            self.cache.record_watch_coverage(watched.url, "verified", observed_at=NOW)
        browser = PublicCatalogFetcher(lambda artist, page: response([hit(artist)]))
        result = self.refresh(CatalogFetcher(http_handler), browser)
        self.assertTrue(any("HTTP 503" in error for error in result.errors))
        self.assertFalse(any("HTTP 202" in error for error in result.errors))
        self.assertIn(prior.cache_key, result.fallback_lot_keys)
        self.assertEqual(self.cache.get(prior.cache_key).last_seen_at, PREVIOUS.isoformat())

    def test_single_search_and_pending_recovery_switch_once_without_more_http(self):
        for pending in (True, False):
            with self.subTest(pending=pending):
                entries = self.entries[:2] if pending else self.entries[:1]
                browser = PublicCatalogFetcher(lambda artist, page: response([hit(artist)]))
                http = CatalogFetcher(self.blocked)
                result = self.refresh(http, browser, entries=entries, pending_only=pending)
                self.assertEqual(len(http.calls), 1)
                self.assertEqual(browser.calls, [(item.artist, 0) for item in entries])
                self.assertEqual(result.errors, [])

    def test_single_search_later_page_202_recovers_from_page_one(self):
        prior = self.seed(self.entries[0], "unseen")

        def handler(artists, page):
            if page:
                return self.blocked(artists, page)
            return response([hit(artists[0], "fresh")], pages=2)

        browser = PublicCatalogFetcher(lambda artist, page: response([hit(artist, "fresh"), hit(artist, "unseen")]))
        result = self.refresh(CatalogFetcher(handler), browser, entries=self.entries[:1])
        self.assertEqual(browser.calls, [("Artist 0", 0)])
        self.assertEqual(result.errors, [])
        self.assertEqual(result.metrics.new_lots, 1)
        self.assertEqual(result.metrics.unchanged_lots, 1)
        self.assertEqual(result.metrics.ended_lots, 0)
        self.assertEqual(result.fallback_lot_keys, set())
        self.assertEqual(self.cache.get(prior.cache_key).last_seen_at, NOW.isoformat())

    def test_denials_rate_limits_and_generic_failures_do_not_start_browser(self):
        for error in (SourceAccessBlocked("HTTP 403"), SourceAccessBlocked("HTTP 401"),
                      SourceAccessBlocked("HTTP 429"), SourceAccessBlocked("Access unavailable"),
                      SourceAccessError("HTTP 202"), SourceAccessError("HTTP 503")):
            for entries in (self.entries[:1], self.entries[:2]):
                with self.subTest(error=error, artists=len(entries)):
                    http = CatalogFetcher(Mock(side_effect=error))
                    result = self.refresh(http, entries=entries)
                    self.factory.assert_not_called()
                    self.assertTrue(result.errors)

    def test_factory_and_lazy_startup_failures_are_attempted_once(self):
        for lazy in (False, True):
            with self.subTest(lazy=lazy):
                browser = PublicCatalogFetcher(Mock(side_effect=SourceAccessError("Browser dependency missing")))
                factory = Mock(return_value=browser) if lazy else Mock(side_effect=SourceAccessError("Browser dependency missing"))
                result = self.refresh(CatalogFetcher(self.blocked), browser, entries=self.entries[:3], factory=factory)
                factory.assert_called_once_with()
                self.assertEqual(len(browser.calls), 1 if lazy else 0)
                self.assertTrue(result.errors)
                self.assertTrue(all(item.needs_recovery for item in result.coverage))

    def test_closed_browser_after_success_preserves_results_and_skips_remaining_searches(self):
        watched = self.entries[:3]
        seeded = [self.seed(item) for item in watched]

        def browser_handler(artist, page):
            if artist == watched[0].artist:
                return response([hit(artist, bid=200)])
            raise SourceAccessBlocked("The Invaluable retry browser was closed. Use my browser.")

        browser = PublicCatalogFetcher(browser_handler)
        result = self.refresh(CatalogFetcher(self.blocked), browser, entries=watched)

        self.assertFalse(result.stopped)
        self.assertEqual(browser.calls, [(watched[0].artist, 0), (watched[1].artist, 0)])
        self.assertEqual({lot.cache_key for lot in result.lots}, {lot.cache_key for lot in seeded})
        self.assertEqual(result.fallback_lot_keys, {lot.cache_key for lot in seeded[1:]})
        self.assertEqual(result.metrics.ended_lots, 0)
        self.assertEqual(self.cache.get(seeded[0].cache_key).last_seen_at, NOW.isoformat())
        for lot in seeded[1:]:
            self.assertEqual(self.cache.get(lot.cache_key).last_seen_at, PREVIOUS.isoformat())
        self.assertEqual(result.coverage[0].state, "verified")
        self.assertTrue(all(item.needs_recovery for item in result.coverage[1:]))

    def test_browser_later_page_failure_preserves_both_http_and_browser_observations(self):
        prior = self.seed(self.entries[0], "unseen")

        def http_handler(artists, page):
            if page:
                return self.blocked(artists, page)
            return response([hit(artists[0], "http-fresh")], pages=2)

        def browser_handler(artist, page):
            if page:
                raise SourceAccessBlocked("Browser access unavailable")
            return response([hit(artist, "browser-fresh")], pages=2)

        browser = PublicCatalogFetcher(browser_handler)
        result = self.refresh(CatalogFetcher(http_handler), browser, entries=self.entries[:1])
        self.assertEqual({lot.source_lot_id for lot in result.lots}, {"unseen", "http-fresh", "browser-fresh"})
        self.assertEqual(result.fallback_lot_keys, {prior.cache_key})
        self.assertEqual(result.metrics.ended_lots, 0)
        self.assertTrue(result.errors)
        self.assertEqual(self.cache.get(prior.cache_key).last_seen_at, PREVIOUS.isoformat())

    def test_partial_browser_results_replace_earlier_http_fields(self):
        prior = self.seed(self.entries[0], "unseen")

        def http_handler(artists, page):
            if page:
                return self.blocked(artists, page)
            return response([hit(artists[0], "fresh", bid=100)], pages=2)

        def browser_handler(artist, page):
            return response([hit(artist, "fresh" if not page else "second", bid=200)], page=page, pages=3)

        result = self.refresh(
            CatalogFetcher(http_handler), PublicCatalogFetcher(browser_handler),
            entries=self.entries[:1], max_pages=2,
        )
        self.assertEqual(next(lot.current_bid for lot in result.lots if lot.source_lot_id == "fresh"), 200)
        self.assertEqual(self.cache.get("invaluable:fresh").current_bid, 200)
        self.assertEqual(result.fallback_lot_keys, {prior.cache_key})
        self.assertEqual(result.metrics.ended_lots, 0)
        self.assertTrue(result.coverage[0].needs_recovery)

    def test_stop_during_factory_or_browser_returns_cancelled_result(self):
        for factory_stop in (True, False):
            with self.subTest(factory_stop=factory_stop):
                browser = PublicCatalogFetcher(Mock(side_effect=WatchlistStopped("User stopped")))
                factory = Mock(side_effect=WatchlistStopped("User stopped")) if factory_stop else Mock(return_value=browser)
                result = self.refresh(CatalogFetcher(self.blocked), browser, entries=self.entries[:2], factory=factory)
                self.assertTrue(result.stopped)
                self.assertEqual(result.metrics.ended_lots, 0)

    def test_stop_event_after_http_failure_prevents_browser_creation(self):
        stop = threading.Event()

        def http_handler(artists, page):
            stop.set()
            return self.blocked(artists, page)

        result = self.refresh(CatalogFetcher(http_handler), entries=self.entries[:2], stop_event=stop)
        self.assertTrue(result.stopped)
        self.factory.assert_not_called()

    def test_public_browser_skips_optional_details_and_posted_sold_checks(self):
        ended = self.seed(self.entries[0], "ended", when=NOW - timedelta(days=1))
        self.cache.mark_missing_ended(self.entries[0].url, set(), PREVIOUS)
        raw = hit("Artist 0")
        raw["houseName"] = ""
        browser = PublicCatalogFetcher(lambda artist, page: response([raw]))
        result = self.refresh(CatalogFetcher(self.blocked), browser, entries=self.entries[:1])
        browser.fetch.assert_not_called()
        self.assertEqual(result.errors, [])
        self.assertIn(ended.cache_key, {lot.cache_key for lot in result.lots})
        self.assertEqual(result.coverage[0].state, "verified")

    def test_required_http_detail_202_does_not_trigger_catalog_recovery(self):
        raw = hit("Artist 0")
        raw.pop("dateTimeUTCUnix")
        http = CatalogFetcher(lambda artists, page: response([raw]))
        http.fetch.side_effect = SourceAccessBlocked("HTTP 202")
        result = self.refresh(http, entries=self.entries[:1])
        self.factory.assert_not_called()
        self.assertTrue(result.errors)
        self.assertEqual(result.lots, [])

    def test_undated_browser_card_still_requires_a_readable_detail(self):
        raw = hit("Artist 0")
        raw.pop("dateTimeUTCUnix")
        browser = PublicCatalogFetcher(lambda artist, page: response([raw]))
        browser.fetch.side_effect = SourceAccessBlocked("HTTP 202")
        result = self.refresh(CatalogFetcher(self.blocked), browser, entries=self.entries[:1])
        browser.fetch.assert_called_once()
        self.assertTrue(result.errors)
        self.assertEqual(result.lots, [])
        self.assertNotEqual(result.coverage[0].state, "empty")
