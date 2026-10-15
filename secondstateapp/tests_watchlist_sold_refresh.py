"""Refresh known auction lots after their date so posted sale results reach sync."""

import csv
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from io import StringIO
import threading
from unittest import TestCase
from unittest.mock import Mock, patch

from catalogapp.bookmark_watchlist import BookmarkEntry
from catalogapp.watchlist_adapters import BatchedSearchPage, BookmarkSourceAdapter
from catalogapp.watchlist_cache import WatchlistCache
from catalogapp.watchlist_enrichment import EnrichmentMetrics
from catalogapp.watchlist_exports import render_csv, render_ics, render_markdown
from catalogapp.watchlist_fetch import SourceAccessBlocked, SourceAccessError
from catalogapp.watchlist_models import NormalizedLot
from catalogapp.watchlist_service import WatchlistService
from catalogapp.watchlist_sync import CalendarSyncError, sync_watchlist_lots


NOW = datetime(2026, 10, 14, 16, tzinfo=timezone.utc)
PREVIOUS = NOW - timedelta(days=3)
ENTRY = BookmarkEntry(
    folder_path=("ARTISTS INVALUABLE",), title="Alexander Calder",
    artist="Alexander Calder", source="Invaluable",
    url="https://www.invaluable.com/search?artistName=Alexander%20Calder",
)


class OfflineInvaluableAdapter:
    source = "Invaluable"
    merge_detail = BookmarkSourceAdapter.merge_detail

    def __init__(self, pages, details=None):
        self.pages = pages
        self.details = details or {}
        self.search_calls = []
        self.detail_calls = []

    def fetch_search_page(self, url, _fetcher):
        self.search_calls.append(url)
        value = self.pages[url]
        if isinstance(value, Exception):
            raise value
        return value

    def parse_search_page(self, page, _url, _artist):
        return [replace(lot) for lot in page["lots"]]

    def needs_detail(self, _lot):
        # These cards already have full catalog metadata. Any detail request in
        # these tests must be caused by checking for a posted auction result.
        return False

    def extract_next_page_url(self, page, _url):
        return page.get("next", "")

    def fetch_lot_detail(self, url, _fetcher):
        self.detail_calls.append(url)
        value = self.details[url]
        if isinstance(value, Exception):
            raise value
        return value

    def parse_lot_detail(self, page, _url, _artist):
        return replace(page) if page is not None else None


class CountingOfflineFetcher:
    def __init__(self, pages, *, initial_pages=0):
        self.pages = pages
        self.pages_fetched = initial_pages
        self.calls = []

    def fetch(self, url):
        self.calls.append(url)
        page = self.pages[url]
        if isinstance(page, Exception):
            raise page
        self.pages_fetched += 1
        return page


class FetcherUsingAdapter(OfflineInvaluableAdapter):
    def fetch_search_page(self, url, fetcher):
        return fetcher.fetch(url)

    def fetch_lot_detail(self, url, fetcher):
        return fetcher.fetch(url)


class WatchlistSoldRefreshTests(TestCase):
    def setUp(self):
        self.cache = WatchlistCache(":memory:")
        self.addCleanup(self.cache.close)
        self.lot = NormalizedLot(
            source="Invaluable", source_lot_id="calder-116",
            artist="Alexander Calder", artist_watchlist_name="Alexander Calder",
            title="Nid d'araignee", medium="Lithograph",
            auction_house="Rago Arts and Auction Center", lot_number="116",
            start_at="2026-10-12T12:00:00+00:00", currency="USD",
            estimate_low=3000, estimate_high=5000, current_bid=100, bid_count=0,
            lot_url="https://www.invaluable.com/auction-lot/calder-nid-116",
        )
        self.seed(self.lot)

    def seed(self, lot):
        self.cache.upsert(
            lot, watch_url=ENTRY.url, search_hash=lot.content_hash,
            observed_at=PREVIOUS,
        )

    def sold_detail(self, lot=None):
        return replace(lot or self.lot, sold_price=11000, sold_currency="USD", content_hash="")

    def refresh(self, adapter, **kwargs):
        fetcher = kwargs.pop("fetcher", None)
        if fetcher is None:
            fetcher = Mock(pages_fetched=0)
            fetcher.fetch.side_effect = AssertionError("This test must remain offline")
            fetcher.post_json.side_effect = AssertionError("This test must remain offline")
        enricher = Mock(enabled=True)
        enricher.enrich.return_value = EnrichmentMetrics()
        max_pages = kwargs.pop("max_pages_per_bookmark", 10)
        entries = kwargs.pop("entries", [ENTRY])
        service = WatchlistService(
            self.cache, fetcher=fetcher, enricher=enricher, now=lambda: NOW,
            invaluable_fetcher=kwargs.pop("invaluable_fetcher", None),
            max_pages_per_bookmark=max_pages,
        )
        with patch("catalogapp.watchlist_service.adapter_for_url", return_value=adapter):
            return service.refresh(
                entries, selected_artists=[entry.watch_label for entry in entries],
                horizon_days=7, **kwargs,
            )

    def test_missing_past_lot_is_checked_and_posted_price_is_returned(self):
        adapter = OfflineInvaluableAdapter(
            {ENTRY.url: {"lots": []}}, {self.lot.lot_url: self.sold_detail()},
        )

        result = self.refresh(adapter)

        self.assertEqual(adapter.detail_calls, [self.lot.lot_url])
        self.assertEqual(result.errors, [])
        self.assertEqual(len(result.lots), 1)
        self.assertEqual(result.lots[0].sold_price, 11000)
        self.assertEqual(result.lots[0].sold_currency, "USD")
        self.assertEqual(self.cache.get(self.lot.cache_key).sold_price, 11000)

    def test_previously_ended_lot_remains_eligible_for_result_check(self):
        self.cache.mark_missing_ended(ENTRY.url, [], PREVIOUS)
        self.assertEqual(self.cache.active_lots_for_watch_url(ENTRY.url), [])
        adapter = OfflineInvaluableAdapter(
            {ENTRY.url: {"lots": []}}, {self.lot.lot_url: self.sold_detail()},
        )

        result = self.refresh(adapter)

        self.assertEqual(adapter.detail_calls, [self.lot.lot_url])
        self.assertEqual(result.lots[0].sold_price, 11000)
        self.assertEqual(self.cache.get(self.lot.cache_key).sold_currency, "USD")

    def test_unchanged_past_search_card_is_checked_despite_catalog_cache_hit(self):
        adapter = OfflineInvaluableAdapter(
            {ENTRY.url: {"lots": [self.lot]}},
            {self.lot.lot_url: self.sold_detail()},
        )

        result = self.refresh(adapter)

        self.assertEqual(adapter.detail_calls, [self.lot.lot_url])
        self.assertEqual(result.lots[0].sold_price, 11000)
        self.assertEqual(self.cache.get(self.lot.cache_key).sold_price, 11000)

    def test_unposted_result_is_retried_without_treating_last_bid_as_sale_price(self):
        unposted = replace(self.lot, current_bid=10000, bid_count=3, content_hash="")
        adapter = OfflineInvaluableAdapter(
            {ENTRY.url: {"lots": []}}, {self.lot.lot_url: unposted},
        )

        self.refresh(adapter)
        self.refresh(adapter)

        self.assertEqual(adapter.detail_calls, [self.lot.lot_url] * 2)
        self.assertIsNone(self.cache.get(self.lot.cache_key).sold_price)
        adapter.details[self.lot.lot_url] = self.sold_detail()
        posted = self.refresh(adapter)
        self.assertEqual(posted.lots[0].sold_price, 11000)
        self.refresh(adapter)
        self.assertEqual(adapter.detail_calls, [self.lot.lot_url] * 3)
        self.assertEqual(self.cache.get(self.lot.cache_key).sold_price, 11000)

    def test_missing_future_or_old_lot_does_not_trigger_result_fetch(self):
        for date in (NOW + timedelta(days=1), NOW - timedelta(days=31)):
            with self.subTest(date=date):
                lot = replace(self.lot, start_at=date.isoformat(), content_hash="")
                self.seed(lot)
                adapter = OfflineInvaluableAdapter({ENTRY.url: {"lots": []}})

                result = self.refresh(adapter)

                self.assertEqual(adapter.detail_calls, [])
                self.assertEqual(result.lots[0].status, "ended")
                self.assertIsNone(result.lots[0].sold_price)
                self.assertIsNone(self.cache.get(lot.cache_key).sold_price)

    def test_incomplete_search_does_not_check_or_end_missing_lots(self):
        adapter = OfflineInvaluableAdapter(
            {ENTRY.url: {"lots": [], "next": "page-two"}},
            {self.lot.lot_url: self.sold_detail()},
        )

        result = self.refresh(adapter, max_pages_per_bookmark=1)

        self.assertEqual(adapter.detail_calls, [])
        self.assertEqual(result.metrics.ended_lots, 0)
        self.assertEqual(len(self.cache.active_lots_for_watch_url(ENTRY.url)), 1)
        self.assertIsNone(self.cache.get(self.lot.cache_key).sold_price)

    def test_future_end_date_takes_precedence_over_past_start_date(self):
        lot = replace(
            self.lot, end_at=(NOW + timedelta(days=1)).isoformat(), content_hash="",
        )
        self.seed(lot)
        adapter = OfflineInvaluableAdapter({ENTRY.url: {"lots": [lot]}})

        result = self.refresh(adapter)

        self.assertEqual(adapter.detail_calls, [])
        self.assertIsNone(result.lots[0].sold_price)

    def test_detail_failure_preserves_known_data_and_later_refresh_retries(self):
        adapter = OfflineInvaluableAdapter(
            {ENTRY.url: {"lots": []}},
            {self.lot.lot_url: SourceAccessError("HTTP 503 result unavailable")},
        )

        failed = self.refresh(adapter)

        self.assertTrue(any("HTTP 503" in error for error in failed.errors))
        retained = self.cache.get(self.lot.cache_key)
        self.assertEqual(retained.current_bid, 100)
        self.assertEqual(retained.estimate_high, 5000)
        self.assertIsNone(retained.sold_price)
        adapter.details[self.lot.lot_url] = self.sold_detail()
        succeeded = self.refresh(adapter)
        self.assertEqual(adapter.detail_calls, [self.lot.lot_url] * 2)
        self.assertEqual(succeeded.lots[0].sold_price, 11000)

    def test_confirmed_result_survives_changed_search_card_without_sold_fields(self):
        self.seed(self.sold_detail())
        # A later upcoming-feed response can still carry an old card or omit its
        # result fields. Changing an estimate bypasses ordinary search-hash reuse.
        card = replace(self.lot, estimate_high=6000, content_hash="")
        adapter = OfflineInvaluableAdapter({ENTRY.url: {"lots": [card]}})

        result = self.refresh(adapter)

        self.assertEqual(adapter.detail_calls, [])
        self.assertEqual(result.lots[0].sold_price, 11000)
        self.assertEqual(result.lots[0].sold_currency, "USD")
        self.assertEqual(self.cache.get(self.lot.cache_key).sold_price, 11000)

    def test_confirmed_old_or_undated_result_is_available_for_sync_retry(self):
        for date in ((NOW - timedelta(days=45)).isoformat(), ""):
            with self.subTest(date=date):
                sold = replace(self.sold_detail(), start_at=date, content_hash="")
                self.seed(sold)
                adapter = OfflineInvaluableAdapter({ENTRY.url: {"lots": []}})

                result = self.refresh(adapter)

                self.assertEqual(adapter.detail_calls, [])
                self.assertEqual(len(result.lots), 1)
                self.assertEqual(result.lots[0].sold_price, 11000)
                self.assertEqual(result.lots[0].status, "unchanged")
                self.assertEqual(self.cache.get(sold.cache_key).sold_price, 11000)

    def test_repeated_unresolved_ended_lot_is_hidden_by_new_changed_filter(self):
        adapter = OfflineInvaluableAdapter(
            {ENTRY.url: {"lots": []}}, {self.lot.lot_url: self.lot},
        )

        first = self.refresh(adapter, new_changed_only=True)
        repeated = self.refresh(adapter, new_changed_only=True)

        self.assertEqual(len(first.lots), 1)
        self.assertEqual(first.lots[0].status, "ended")
        self.assertEqual(repeated.lots, [])
        self.assertEqual(adapter.detail_calls, [self.lot.lot_url] * 2)
        self.assertEqual(self.cache.get(self.lot.cache_key).status, "ended")
        adapter.details[self.lot.lot_url] = self.sold_detail()
        posted = self.refresh(adapter, new_changed_only=True)
        self.assertEqual(len(posted.lots), 1)
        self.assertEqual(posted.lots[0].sold_price, 11000)

    def test_initial_metadata_detail_is_reused_for_result_check_in_same_refresh(self):
        adapter = OfflineInvaluableAdapter(
            {ENTRY.url: {"lots": [self.lot]}}, {self.lot.lot_url: self.lot},
        )
        adapter.needs_detail = Mock(return_value=True)

        result = self.refresh(adapter)

        self.assertEqual(adapter.detail_calls, [self.lot.lot_url])
        self.assertEqual(result.metrics.detail_pages_fetched, 1)
        self.assertIsNone(self.cache.get(self.lot.cache_key).sold_price)

    def test_newly_posted_result_passes_new_changed_filter_outside_date_horizon(self):
        lot = replace(self.lot, start_at=(NOW - timedelta(days=10)).isoformat(), content_hash="")
        self.seed(lot)
        adapter = OfflineInvaluableAdapter(
            {ENTRY.url: {"lots": []}}, {lot.lot_url: self.sold_detail(lot)},
        )

        result = self.refresh(adapter, new_changed_only=True)

        self.assertEqual(len(result.lots), 1)
        self.assertEqual(result.lots[0].sold_price, 11000)
        self.assertIn(result.lots[0].status, {"changed", "ended"})
        self.assertEqual(result.fallback_lot_keys, set())

    def test_failed_artist_search_does_not_trigger_result_fetch(self):
        adapter = OfflineInvaluableAdapter(
            {ENTRY.url: SourceAccessError("HTTP 403")},
            {self.lot.lot_url: self.sold_detail()},
        )

        result = self.refresh(adapter)

        self.assertEqual(adapter.detail_calls, [])
        self.assertTrue(any("HTTP 403" in error for error in result.errors))
        self.assertIsNone(self.cache.get(self.lot.cache_key).sold_price)

    def test_failed_search_rechecks_known_ended_lot_independently(self):
        self.cache.mark_missing_ended(ENTRY.url, [], PREVIOUS)
        adapter = OfflineInvaluableAdapter(
            {ENTRY.url: SourceAccessError("Catalog unavailable")},
            {self.lot.lot_url: self.sold_detail()},
        )

        result = self.refresh(adapter, new_changed_only=True)

        self.assertEqual(adapter.detail_calls, [self.lot.lot_url])
        self.assertEqual(len(result.lots), 1)
        self.assertEqual(result.lots[0].sold_price, 11000)
        self.assertEqual(result.fallback_lot_keys, set())
        self.assertEqual(result.metrics.changed_lots, 1)
        self.assertEqual(self.cache.active_lots_for_watch_url(ENTRY.url), [])
        self.assertTrue(any("Catalog unavailable" in error for error in result.errors))

    def test_catalog_failure_keeps_old_ended_and_confirmed_sold_history(self):
        old = replace(self.lot, start_at=(NOW - timedelta(days=45)).isoformat(), content_hash="")
        self.seed(old)
        self.cache.mark_missing_ended(ENTRY.url, [], PREVIOUS)
        sold = replace(self.sold_detail(), source_lot_id="calder-117", lot_number="117", content_hash="")
        self.seed(sold)
        before = {lot.cache_key: lot.to_dict() for lot in self.cache.lots_for_watch_url(ENTRY.url)}
        adapter = OfflineInvaluableAdapter({ENTRY.url: SourceAccessError("Catalog unavailable")})

        result = self.refresh(adapter)

        self.assertEqual(adapter.detail_calls, [])
        self.assertEqual({lot.cache_key for lot in result.lots}, set(before))
        self.assertEqual(result.fallback_lot_keys, set(before))
        self.assertEqual({lot.cache_key: lot.to_dict() for lot in self.cache.lots_for_watch_url(ENTRY.url)}, before)

    def test_batch_failure_rechecks_shared_ended_lot_once(self):
        second = replace(ENTRY, url=ENTRY.url + "&subcategory=prints")
        self.cache.upsert(replace(self.lot), watch_url=second.url, search_hash=self.lot.content_hash, observed_at=PREVIOUS)
        self.cache.mark_missing_ended(ENTRY.url, [], PREVIOUS)
        self.cache.mark_missing_ended(second.url, [], PREVIOUS)
        adapter = OfflineInvaluableAdapter({}, {self.lot.lot_url: self.sold_detail()})
        adapter.fetch_search_batch = Mock(side_effect=SourceAccessError("Catalog unavailable"))

        result = self.refresh(adapter, entries=[ENTRY, second])

        adapter.fetch_search_batch.assert_called_once()
        self.assertEqual(adapter.search_calls, [])
        self.assertEqual(adapter.detail_calls, [self.lot.lot_url])
        self.assertEqual(len(result.lots), 1)
        self.assertEqual(result.lots[0].sold_price, 11000)
        self.assertEqual(result.fallback_lot_keys, set())

    def test_login_gate_is_one_actionable_notice_and_stops_other_artist_probes(self):
        second_entry = replace(ENTRY, artist="Joan Miro", title="Joan Miro", url=ENTRY.url + "&other=miro")
        second = replace(self.lot, source_lot_id="miro-117", lot_url=self.lot.lot_url + "-other", content_hash="")
        self.cache.upsert(second, watch_url=second_entry.url, search_hash=second.content_hash, observed_at=PREVIOUS)
        gated = replace(self.lot, ambiguities=["sold_price_login"], content_hash="")
        adapter = OfflineInvaluableAdapter(
            {ENTRY.url: {"lots": []}, second_entry.url: {"lots": []}},
            {self.lot.lot_url: gated, second.lot_url: self.sold_detail(second)},
        )

        result = self.refresh(adapter, entries=[ENTRY, second_entry])

        self.assertEqual(adapter.detail_calls, [self.lot.lot_url])
        self.assertEqual(result.errors, [])
        self.assertEqual(len(result.notices), 1)
        self.assertIn("Connect Invaluable", result.notices[0])
        self.assertEqual(len(result.lots), 2)
        self.assertTrue(all(lot.sold_price is None for lot in result.lots))

    def test_result_access_failure_stops_other_lots_but_retains_every_ended_lot(self):
        second = replace(self.lot, source_lot_id="calder-117", lot_url=self.lot.lot_url + "-other", content_hash="")
        self.seed(second)
        self.cache.mark_missing_ended(ENTRY.url, [], PREVIOUS)
        adapter = OfflineInvaluableAdapter(
            {ENTRY.url: {"lots": []}},
            {self.lot.lot_url: SourceAccessBlocked("HTTP 403"), second.lot_url: self.sold_detail(second)},
        )

        result = self.refresh(adapter)

        self.assertEqual(adapter.detail_calls, [self.lot.lot_url])
        self.assertEqual(len(result.errors), 1)
        self.assertEqual({lot.cache_key for lot in result.lots}, {self.lot.cache_key, second.cache_key})
        self.assertTrue(all(lot.sold_price is None for lot in result.lots))

    def test_broken_lot_and_unrecognized_page_do_not_block_other_sold_results(self):
        malformed = replace(self.lot, source_lot_id="calder-117", lot_url=self.lot.lot_url + "-malformed", content_hash="")
        available = replace(self.lot, source_lot_id="calder-118", lot_url=self.lot.lot_url + "-available", content_hash="")
        self.seed(malformed)
        self.seed(available)
        self.cache.mark_missing_ended(ENTRY.url, [], PREVIOUS)
        adapter = OfflineInvaluableAdapter(
            {ENTRY.url: {"lots": []}},
            {self.lot.lot_url: SourceAccessError("HTTP 404"), malformed.lot_url: None, available.lot_url: self.sold_detail(available)},
        )

        result = self.refresh(adapter)

        self.assertEqual(adapter.detail_calls, [self.lot.lot_url, malformed.lot_url, available.lot_url])
        self.assertEqual(len(result.errors), 2)
        self.assertEqual(self.cache.get(available.cache_key).sold_price, 11000)
        self.assertIsNone(self.cache.get(self.lot.cache_key).sold_price)
        self.assertIsNone(self.cache.get(malformed.cache_key).sold_price)
        self.assertEqual(len(result.lots), 3)

    def test_catalog_authentication_block_prevents_detail_probes_and_retains_history(self):
        self.cache.mark_missing_ended(ENTRY.url, [], PREVIOUS)
        adapter = OfflineInvaluableAdapter(
            {ENTRY.url: SourceAccessBlocked("HTTP 403")},
            {self.lot.lot_url: self.sold_detail()},
        )

        result = self.refresh(adapter)

        self.assertEqual(adapter.detail_calls, [])
        self.assertEqual(len(result.lots), 1)
        self.assertEqual(result.fallback_lot_keys, {self.lot.cache_key})
        self.assertIsNone(result.lots[0].sold_price)

    def test_initial_detail_login_gate_is_reported_without_repeat_result_probe(self):
        gated = replace(self.lot, ambiguities=["sold_price_login"], content_hash="")
        adapter = OfflineInvaluableAdapter({ENTRY.url: {"lots": [self.lot]}}, {self.lot.lot_url: gated})
        adapter.needs_detail = Mock(return_value=True)

        result = self.refresh(adapter)

        self.assertEqual(adapter.detail_calls, [self.lot.lot_url])
        self.assertEqual(len(result.notices), 1)
        self.assertIn("Connect Invaluable", result.notices[0])

    def test_invaluable_fetcher_is_isolated_and_page_metrics_sum_both_sources(self):
        other_entry = replace(ENTRY, source="Heritage", artist="Miro", title="Miro", url="https://fineart.ha.com/catalog")
        other_lot = replace(self.lot, source="Heritage", source_lot_id="heritage-117", start_at=(NOW + timedelta(days=1)).isoformat(), content_hash="")
        public = CountingOfflineFetcher({other_entry.url: {"lots": [other_lot]}}, initial_pages=5)
        signed_in = CountingOfflineFetcher({ENTRY.url: {"lots": [self.lot]}, self.lot.lot_url: self.sold_detail()}, initial_pages=12)
        invaluable = FetcherUsingAdapter({})
        heritage = FetcherUsingAdapter({})
        heritage.source = "Heritage"
        service = WatchlistService(self.cache, fetcher=public, invaluable_fetcher=signed_in, now=lambda: NOW)

        with patch("catalogapp.watchlist_service.adapter_for_url", side_effect=lambda url: invaluable if url == ENTRY.url else heritage):
            result = service.refresh([ENTRY, other_entry], selected_artists=[ENTRY.watch_label, other_entry.watch_label])

        self.assertEqual(public.calls, [other_entry.url])
        self.assertEqual(signed_in.calls, [ENTRY.url, self.lot.lot_url])
        self.assertEqual(result.metrics.pages_fetched, 3)
        self.assertEqual(result.metrics.detail_pages_fetched, 1)
        self.assertEqual(len(result.lots), 2)

    def test_batched_catalog_uses_invaluable_fetcher_and_shared_counter_is_not_doubled(self):
        second = replace(ENTRY, url=ENTRY.url + "&subcategory=prints")
        fetcher = CountingOfflineFetcher({"batch": {}, self.lot.lot_url: self.sold_detail()}, initial_pages=7)
        adapter = FetcherUsingAdapter({})

        def batch(searches, chosen_fetcher, **_kwargs):
            self.assertIs(chosen_fetcher, fetcher)
            chosen_fetcher.fetch("batch")
            return {url: BatchedSearchPage({"lots": []}) for url, _artist in searches}

        adapter.fetch_search_batch = Mock(side_effect=batch)
        result = self.refresh(adapter, entries=[ENTRY, second], fetcher=fetcher, invaluable_fetcher=fetcher)

        self.assertEqual(fetcher.calls, ["batch", self.lot.lot_url])
        self.assertEqual(result.metrics.pages_fetched, 2)
        self.assertEqual(result.lots[0].sold_price, 11000)

    def test_two_watch_urls_check_missing_lot_once_and_preserve_sold_transition(self):
        second = replace(ENTRY, url=ENTRY.url + "&subcategory=prints")
        self.cache.upsert(
            replace(self.lot), watch_url=second.url,
            search_hash=self.lot.content_hash, observed_at=PREVIOUS,
        )
        adapter = OfflineInvaluableAdapter(
            {ENTRY.url: {"lots": []}, second.url: {"lots": []}},
            {self.lot.lot_url: self.sold_detail()},
        )

        result = self.refresh(adapter, entries=[ENTRY, second], new_changed_only=True)

        self.assertEqual(adapter.detail_calls, [self.lot.lot_url])
        self.assertEqual(len(result.lots), 1)
        self.assertEqual(result.lots[0].sold_price, 11000)
        self.assertEqual(result.lots[0].status, "changed")
        cached = self.cache.get(self.lot.cache_key)
        self.assertEqual(cached.sold_price, 11000)
        self.assertEqual(cached.status, result.lots[0].status)

    def test_latest_sold_card_across_watch_urls_matches_cache(self):
        second = replace(ENTRY, url=ENTRY.url + "&subcategory=prints")
        first_card = self.sold_detail()
        last_card = replace(first_card, sold_price=12000, content_hash="")
        adapter = OfflineInvaluableAdapter({
            ENTRY.url: {"lots": [first_card]},
            second.url: {"lots": [last_card]},
        })

        result = self.refresh(adapter, entries=[ENTRY, second])

        self.assertEqual(adapter.detail_calls, [])
        self.assertEqual(len(result.lots), 1)
        self.assertEqual(result.lots[0].sold_price, 12000)
        self.assertEqual(self.cache.get(self.lot.cache_key).sold_price, 12000)

    def test_stop_during_search_prevents_cached_sold_result_and_calendar_sync(self):
        from catalogapp.watchlist_ui import ArtistWatchlistPanel

        sold = self.sold_detail()
        self.seed(sold)
        stop_event = threading.Event()
        adapter = OfflineInvaluableAdapter({ENTRY.url: {"lots": []}})
        initial_fetch = adapter.fetch_search_page

        def stop_while_fetching(url, fetcher):
            page = initial_fetch(url, fetcher)
            stop_event.set()
            return page

        adapter.fetch_search_page = stop_while_fetching
        result = self.refresh(adapter, stop_event=stop_event)

        self.assertTrue(result.stopped)
        self.assertEqual(result.lots, [])
        self.assertEqual(adapter.detail_calls, [])
        self.assertEqual(self.cache.get(sold.cache_key).sold_price, 11000)
        panel = Mock()
        panel.after.side_effect = lambda _delay, callback: callback()
        panel._calendar_sync_configured.return_value = True
        # The UI must respect cancellation even if a preceding bookmark left
        # already-observed lots in a partially completed result.
        partial = replace(result, lots=[sold])
        ArtistWatchlistPanel._sync_and_finish_result(panel, partial)
        panel.calendar_syncer.assert_not_called()
        panel._finish_refresh.assert_called_once_with(
            partial, sync_result=None, sync_error="", sync_setup_message="",
        )


class WatchlistSoldPresentationTests(TestCase):
    def setUp(self):
        self.lot = NormalizedLot(
            source="Invaluable", source_lot_id="sold-calder-116",
            artist="Alexander Calder", artist_watchlist_name="Alexander Calder",
            title="Sold Calder print", auction_house="Rago", lot_number="116",
            start_at="2026-10-14T12:00:00+00:00", estimate_low=3000,
            estimate_high=5000, currency="USD", current_bid=100, bid_count=0,
            sold_price=11000, sold_currency="EUR", status="changed",
            lot_url="https://www.invaluable.com/auction-lot/sold-calder-116",
        )

    def test_sold_label_overrides_no_bids_and_uses_result_currency(self):
        self.assertEqual(self.lot.bid_label, "Sold: 11,000 EUR")
        cents = replace(self.lot, sold_price=11000.5, sold_currency="", content_hash="")
        self.assertEqual(cents.bid_label, "Sold: 11,000.5 USD")

    def test_legacy_payload_defaults_and_posted_result_changes_hash(self):
        legacy_payload = self.lot.to_dict()
        legacy_payload.pop("sold_price")
        legacy_payload.pop("sold_currency")
        legacy_payload["content_hash"] = ""
        unsold = NormalizedLot.from_dict(legacy_payload)

        self.assertIsNone(unsold.sold_price)
        self.assertEqual(unsold.sold_currency, "")
        self.assertEqual(unsold.bid_label, "No bids")
        self.assertNotIn("sold_price", unsold.visible_content())
        self.assertNotIn("sold_currency", unsold.visible_content())
        self.assertNotEqual(unsold.content_hash, self.lot.content_hash)

    def test_markdown_preserves_estimate_alongside_posted_price(self):
        markdown = render_markdown([self.lot])

        self.assertIn("estimate 3,000–5,000 USD", markdown)
        self.assertIn("Sold: 11,000 EUR", markdown)
        self.assertNotIn("bid 100 USD", markdown)

    def test_csv_keeps_sale_result_separate_from_bid_and_estimate(self):
        unsold = replace(
            self.lot, source_lot_id="unsold-117", lot_number="117",
            sold_price=None, sold_currency="", content_hash="",
        )
        rows = list(csv.DictReader(StringIO(render_csv([self.lot, unsold]))))

        self.assertEqual(rows[0]["sold_price"], "11000")
        self.assertEqual(rows[0]["sold_currency"], "EUR")
        self.assertEqual(rows[0]["currency"], "USD")
        self.assertEqual(rows[0]["current_bid"], "100")
        self.assertEqual(rows[0]["bid_count"], "0")
        self.assertEqual(rows[0]["estimate_low"], "3000")
        self.assertEqual(rows[0]["estimate_high"], "5000")
        self.assertEqual(rows[1]["sold_price"], "")
        self.assertEqual(rows[1]["sold_currency"], "")

    def test_ics_excludes_sold_lot_even_without_ended_status(self):
        upcoming = replace(
            self.lot, source_lot_id="upcoming-117", title="Upcoming Calder print",
            lot_number="117", start_at=(NOW + timedelta(days=1)).isoformat(),
            sold_price=None, sold_currency="", content_hash="",
        )
        for event_per_lot in (False, True):
            with self.subTest(event_per_lot=event_per_lot):
                calendar = render_ics(
                    [self.lot, upcoming], event_per_lot=event_per_lot,
                    include_reminders=True, generated_at=NOW,
                ).replace("\r\n ", "")

                self.assertEqual(calendar.count("BEGIN:VEVENT"), 1)
                self.assertNotIn("Sold Calder print", calendar)
                self.assertIn("Upcoming Calder print", calendar)

    def test_website_sync_payload_includes_result_and_keeps_existing_amounts(self):
        session = Mock()
        response = Mock(status_code=200)
        response.json.return_value = {
            "ok": True, "received": 1, "created": 0, "updated": 1,
            "ended": 0, "images_received": 0, "sold_prices_received": 1,
        }
        session.post.return_value = response
        result = sync_watchlist_lots(
            [self.lot], base_url="https://secondstate.art", api_key="test",
            session=session,
        )

        self.assertEqual(result.updated, 1)
        self.assertEqual(result.sold_prices_received, 1)
        payload = session.post.call_args.kwargs["json"]["lots"][0]
        self.assertEqual(payload["sold_price"], 11000)
        self.assertEqual(payload["sold_currency"], "EUR")
        self.assertEqual(payload["current_bid"], 100)
        self.assertEqual(payload["bid_count"], 0)
        self.assertEqual(payload["estimate_low"], 3000)
        self.assertEqual(payload["estimate_high"], 5000)
        self.assertEqual(payload["currency"], "USD")
        self.assertNotIn("content_hash", payload)

    def test_old_server_cannot_silently_claim_sold_price_sync_success(self):
        for confirmation in ({}, {"sold_prices_received": 0}):
            with self.subTest(confirmation=confirmation):
                session = Mock()
                response = Mock(status_code=200)
                response.json.return_value = {
                    "ok": True, "received": 1, "created": 0, "updated": 1,
                    "ended": 0, "images_received": 0, **confirmation,
                }
                session.post.return_value = response

                with self.assertRaisesRegex(CalendarSyncError, "sold prices were not confirmed"):
                    sync_watchlist_lots(
                        [self.lot], base_url="https://secondstate.art", api_key="test",
                        session=session,
                    )
