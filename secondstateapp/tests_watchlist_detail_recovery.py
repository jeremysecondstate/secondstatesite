"""Optional lot pages must not discard dated lots from a successful search."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import threading
from unittest import TestCase
from unittest.mock import Mock, patch

from catalogapp.bookmark_watchlist import BookmarkEntry
from catalogapp.watchlist_adapters import BookmarkSourceAdapter
from catalogapp.watchlist_cache import WatchlistCache
from catalogapp.watchlist_fetch import SourceAccessBlocked, SourceAccessError, WatchlistStopped
from catalogapp.watchlist_models import NormalizedLot
from catalogapp.watchlist_service import WatchlistService


NOW = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)
ENTRY = BookmarkEntry(
    folder_path=("ARTISTS INVALUABLE",), title="John Nieto", artist="John Nieto",
    source="Invaluable", url="https://www.invaluable.com/search?artistName=John%20Nieto",
)


class DetailAdapter:
    source = "Invaluable"
    needs_detail = BookmarkSourceAdapter.needs_detail
    merge_detail = BookmarkSourceAdapter.merge_detail

    def __init__(self, pages, details):
        self.pages = pages
        self.details = details
        self.detail_calls = []

    def fetch_search_page(self, url, _fetcher):
        return self.pages[url]

    def parse_search_page(self, page, _url, _artist):
        return [replace(lot) for lot in page]

    def extract_next_page_url(self, _page, _url):
        return ""

    def fetch_lot_detail(self, url, _fetcher):
        self.detail_calls.append(url)
        value = self.details[url]
        if isinstance(value, Exception):
            raise value
        return value

    def parse_lot_detail(self, page, _url, _artist):
        return replace(page) if page is not None else None


class WatchlistDetailRecoveryTests(TestCase):
    def setUp(self):
        self.cache = WatchlistCache(":memory:")
        self.addCleanup(self.cache.close)
        self.card = NormalizedLot(
            source="Invaluable", source_lot_id="nieto-101", artist="John Nieto",
            artist_watchlist_name="John Nieto", title="Wolf", start_at="2026-10-22",
            auction_house="Example Auctions", lot_number="101", medium="",
            estimate_low=1000, estimate_high=2000, current_bid=500, bid_count=1,
            currency="USD", lot_url="https://www.invaluable.com/auction-lot/wolf-101-c-abc101",
        )
        self.second = replace(
            self.card, source_lot_id="nieto-102", title="Eagle", lot_number="102",
            lot_url="https://www.invaluable.com/auction-lot/eagle-102-c-abc102", content_hash="",
        )

    def seed(self, lot, watch_url=ENTRY.url):
        self.cache.upsert(
            lot, watch_url=watch_url, search_hash=lot.content_hash,
            observed_at=NOW - timedelta(days=1),
        )

    def refresh(self, adapter, entries=None, **kwargs):
        entries = entries or [ENTRY]
        service = WatchlistService(self.cache, fetcher=Mock(pages_fetched=0), now=lambda: NOW)
        with patch("catalogapp.watchlist_service.adapter_for_url", return_value=adapter):
            return service.refresh(
                entries, selected_artists=[entry.watch_label for entry in entries],
                horizon_days=30, **kwargs,
            )

    def test_failed_optional_detail_retains_new_lot_and_continues_remaining_cards(self):
        adapter = DetailAdapter({ENTRY.url: [self.card, self.second]}, {
            self.card.lot_url: SourceAccessError("HTTP 503"),
            self.second.lot_url: replace(self.second, medium="Serigraph", content_hash=""),
        })

        result = self.refresh(adapter, new_changed_only=True)

        self.assertEqual({lot.cache_key for lot in result.lots}, {self.card.cache_key, self.second.cache_key})
        self.assertEqual(result.metrics.new_lots, 2)
        self.assertEqual(result.metrics.detail_pages_fetched, 1)
        self.assertEqual(result.fallback_lot_keys, set())
        self.assertEqual(adapter.detail_calls, [self.card.lot_url, self.second.lot_url])
        retained = self.cache.get(self.card.cache_key)
        self.assertEqual(retained.last_seen_at, NOW.isoformat())
        self.assertEqual(retained.medium, "")
        self.assertEqual(retained.current_bid, 500)
        self.assertEqual(self.cache.get(self.second.cache_key).medium, "Serigraph")
        self.assertEqual(len(result.errors), 1)
        self.assertIn("lot-page details could not be verified: HTTP 503", result.errors[0])
        self.assertIn("dated search result was retained for calendar sync", result.errors[0])

    def test_source_block_skips_later_details_across_artists_and_retries_next_refresh(self):
        second_entry = replace(ENTRY, title="Another artist", artist="Another artist", url=ENTRY.url + "&other=1")
        adapter = DetailAdapter({ENTRY.url: [self.card], second_entry.url: [self.second]}, {
            self.card.lot_url: SourceAccessBlocked("HTTP 202 challenge"),
            self.second.lot_url: replace(self.second, medium="Serigraph", content_hash=""),
        })

        failed = self.refresh(adapter, [ENTRY, second_entry])

        self.assertEqual(len(failed.lots), 2)
        self.assertEqual(adapter.detail_calls, [self.card.lot_url])
        self.assertEqual(len(failed.errors), 1)
        self.assertEqual(len(failed.notices), 1)
        self.assertIn("lot-page details remain unverified", failed.notices[0])
        source_runs = self.cache.connection.execute(
            "SELECT watch_url, last_success_at, last_error FROM source_runs ORDER BY watch_url"
        ).fetchall()
        self.assertEqual(len(source_runs), 2)
        self.assertTrue(all(row["last_success_at"] is None for row in source_runs))
        self.assertTrue(all(row["last_error"] for row in source_runs))

        adapter.details[self.card.lot_url] = replace(self.card, medium="Lithograph", content_hash="")
        recovered = self.refresh(adapter, [ENTRY, second_entry])

        self.assertEqual(adapter.detail_calls, [self.card.lot_url, self.card.lot_url, self.second.lot_url])
        self.assertEqual(recovered.errors, [])
        self.assertEqual(recovered.notices, [])
        self.assertEqual({lot.medium for lot in recovered.lots}, {"Lithograph", "Serigraph"})
        source_runs = self.cache.connection.execute("SELECT last_success_at, last_error FROM source_runs").fetchall()
        self.assertTrue(all(row["last_success_at"] == NOW.isoformat() for row in source_runs))
        self.assertTrue(all(row["last_error"] == "" for row in source_runs))

    def test_unrecognizable_detail_keeps_dated_card_and_is_retried(self):
        adapter = DetailAdapter({ENTRY.url: [self.card]}, {self.card.lot_url: None})

        first = self.refresh(adapter)
        second = self.refresh(adapter)

        self.assertEqual(len(first.lots), 1)
        self.assertEqual(len(second.lots), 1)
        self.assertEqual(adapter.detail_calls, [self.card.lot_url] * 2)
        self.assertIn("did not contain recognizable auction details", first.errors[0])

    def test_unusable_card_failure_preserves_cached_observation_and_missing_lots(self):
        self.seed(self.card)
        self.seed(self.second)
        for changes in ({"start_at": ""}, {"start_at": "2026-99-99"}, {"start_at": "unknown"}):
            with self.subTest(changes=changes):
                unusable = replace(self.card, **changes, content_hash="")
                adapter = DetailAdapter({ENTRY.url: [unusable]}, {
                    self.card.lot_url: SourceAccessError("HTTP 503"),
                })

                result = self.refresh(adapter)

                self.assertEqual(result.fallback_lot_keys, {self.card.cache_key, self.second.cache_key})
                self.assertEqual(result.metrics.new_lots, 0)
                self.assertEqual(result.metrics.ended_lots, 0)
                self.assertEqual(self.cache.get(self.card.cache_key).last_seen_at, (NOW - timedelta(days=1)).isoformat())
                self.assertEqual(self.cache.get(self.card.cache_key).start_at, self.card.start_at)

    def test_blocked_details_do_not_admit_later_undated_card(self):
        undated = replace(self.second, start_at="", content_hash="")
        adapter = DetailAdapter({ENTRY.url: [self.card, undated]}, {
            self.card.lot_url: SourceAccessBlocked("HTTP 202 challenge"),
        })

        result = self.refresh(adapter)

        self.assertEqual([lot.cache_key for lot in result.lots], [self.card.cache_key])
        self.assertIsNone(self.cache.get(undated.cache_key))
        self.assertEqual(adapter.detail_calls, [self.card.lot_url])
        self.assertTrue(any("no usable title or auction date" in error for error in result.errors))

    def test_cached_description_and_confirmed_result_survive_without_stale_bid(self):
        previous = replace(
            self.card, medium="Serigraph", lot_number="", image_url="https://example.com/wolf.jpg",
            sold_price=750, sold_currency="USD", content_hash="",
        )
        self.seed(previous)
        card = replace(self.card, lot_number="", current_bid=None, bid_count=None, content_hash="")
        adapter = DetailAdapter({ENTRY.url: [card]}, {
            card.lot_url: SourceAccessError("HTTP 503"),
        })

        result = self.refresh(adapter)

        self.assertEqual(len(result.lots), 1)
        lot = result.lots[0]
        self.assertEqual(lot.medium, "Serigraph")
        self.assertEqual(lot.image_url, previous.image_url)
        self.assertEqual(lot.sold_price, 750)
        self.assertEqual(lot.sold_currency, "USD")
        self.assertIsNone(lot.current_bid)
        self.assertIsNone(lot.bid_count)

    def test_past_card_detail_failure_is_not_retried_for_sold_result_in_same_refresh(self):
        past = replace(self.card, start_at=NOW.isoformat(), content_hash="")
        adapter = DetailAdapter({ENTRY.url: [past]}, {
            past.lot_url: SourceAccessError("HTTP 503"),
        })

        result = self.refresh(adapter)

        self.assertEqual(adapter.detail_calls, [past.lot_url])
        self.assertEqual(len(result.errors), 1)
        self.assertIsNone(result.lots[0].sold_price)

    def test_user_stop_is_not_converted_to_optional_detail_error(self):
        adapter = DetailAdapter({ENTRY.url: [self.card]}, {
            self.card.lot_url: WatchlistStopped("Stopped"),
        })

        result = self.refresh(adapter)

        self.assertTrue(result.stopped)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.lots, [])
        self.assertIsNone(self.cache.get(self.card.cache_key))

    def test_cancellation_during_failed_detail_does_not_write_or_end_lots(self):
        for source in ("Invaluable", "Heritage"):
            with self.subTest(source=source):
                entry = replace(ENTRY, source=source, url=ENTRY.url + "&source=" + source)
                card = replace(self.card, source=source, content_hash="")
                previous = replace(self.second, source=source, content_hash="")
                self.seed(previous, watch_url=entry.url)
                stop = threading.Event()
                adapter = DetailAdapter({entry.url: [card]}, {})
                adapter.source = source

                def stop_during_fetch(_url, _fetcher):
                    stop.set()
                    raise SourceAccessError("Connection interrupted")

                adapter.fetch_lot_detail = stop_during_fetch

                result = self.refresh(adapter, [entry], stop_event=stop)

                self.assertTrue(result.stopped)
                self.assertEqual(result.errors, [])
                self.assertEqual(result.metrics.ended_lots, 0)
                self.assertIsNone(self.cache.get(card.cache_key))
                self.assertEqual(self.cache.get(previous.cache_key).status, "new")
                self.assertEqual(self.cache.get(previous.cache_key).last_seen_at, (NOW - timedelta(days=1)).isoformat())

    def test_cancellation_after_card_processing_does_not_mark_missing_lots_ended(self):
        entry = replace(ENTRY, source="Heritage")
        card = replace(self.card, source="Heritage", medium="Serigraph", content_hash="")
        previous = replace(self.second, source="Heritage", content_hash="")
        self.seed(previous)
        stop = threading.Event()
        adapter = DetailAdapter({entry.url: [card]}, {})
        adapter.source = "Heritage"

        def stop_after_search_page(_page, _url):
            stop.set()
            return ""

        adapter.extract_next_page_url = stop_after_search_page

        result = self.refresh(adapter, [entry], stop_event=stop)

        self.assertTrue(result.stopped)
        self.assertEqual(result.metrics.ended_lots, 0)
        self.assertEqual(self.cache.get(previous.cache_key).status, "new")

    def test_cancellation_during_final_posted_result_check_does_not_end_missing_lot(self):
        past = replace(self.card, start_at=(NOW - timedelta(days=1)).isoformat(), content_hash="")
        self.seed(past)
        stop = threading.Event()
        adapter = DetailAdapter({ENTRY.url: []}, {})

        def stop_during_fetch(_url, _fetcher):
            stop.set()
            raise SourceAccessError("Connection interrupted")

        adapter.fetch_lot_detail = stop_during_fetch

        result = self.refresh(adapter, stop_event=stop)

        self.assertTrue(result.stopped)
        self.assertEqual(result.metrics.ended_lots, 0)
        self.assertEqual(self.cache.get(past.cache_key).status, "new")
        self.assertEqual(self.cache.get(past.cache_key).last_seen_at, (NOW - timedelta(days=1)).isoformat())
