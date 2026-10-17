"""Keep usable catalog pages when a later Invaluable request fails."""

import json
from datetime import datetime, timedelta, timezone
from unittest import TestCase
from unittest.mock import Mock, patch
from urllib.parse import urlencode

from catalogapp.bookmark_watchlist import BookmarkEntry
from catalogapp.watchlist_adapters import InvaluableAdapter
from catalogapp.watchlist_cache import WatchlistCache
from catalogapp.watchlist_fetch import SourceAccessBlocked, SourceAccessError, WatchlistStopped
from catalogapp.watchlist_service import WatchlistService


NOW = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)
PREVIOUS = NOW - timedelta(days=1)


def entry(number):
    artist = f"Artist {number}"
    return BookmarkEntry(
        folder_path=("ARTISTS INVALUABLE",), title=artist, artist=artist, source="Invaluable",
        url="https://www.invaluable.com/search?" + urlencode({"artistName": artist}),
    )


def hit(artist, identity=None, bid=100):
    identity = identity or artist.replace(" ", "")
    return {
        "objectID": identity, "lotRef": identity, "lotNumber": "1", "artistName": artist,
        "lotTitle": f"{artist} screenprint", "lotDescription": "Color screenprint on paper",
        "houseName": "Auction House", "currencyCode": "USD", "currentBid": bid,
        "dateTimeUTCUnix": int((NOW + timedelta(days=2)).timestamp()),
    }


def response(hits=(), page=0, pages=1):
    return {"results": [{"hits": list(hits), "page": page, "nbPages": pages}]}


class CatalogFetcher:
    def __init__(self, handler):
        self.handler = handler
        self.calls = []
        self.pages_fetched = 0
        self.fetch = Mock(side_effect=AssertionError("Unexpected lot-page request"))

    def post_json(self, url, payload, *, referer=""):
        params = payload["requests"][0]["params"]
        artists = [value.split(":", 1)[1] for value in params["facetFilters"][0]]
        self.calls.append((artists, params["page"]))
        result = self.handler(artists, params["page"])
        self.pages_fetched += 1
        return result


class InvaluableBatchRecoveryTests(TestCase):
    def setUp(self):
        self.adapter = InvaluableAdapter()
        self.entries = [entry(index) for index in range(54)]

    def fetch(self, fetcher, entries=None, **kwargs):
        return self.adapter.fetch_search_batch(
            [(item.url, item.artist) for item in (entries or self.entries)], fetcher, **kwargs,
        )

    def test_fifty_four_artists_receive_separate_bounded_groups(self):
        fetcher = CatalogFetcher(lambda artists, page: response([hit(artist) for artist in artists]))

        pages = self.fetch(fetcher)

        self.assertEqual([len(artists) for artists, _page in fetcher.calls], [8, 8, 8, 8, 8, 8, 6])
        for item in self.entries:
            page = pages[item.url]
            self.assertTrue(page.complete)
            self.assertFalse(page.error)
            lots = self.adapter.parse_search_page(page.page, item.url, item.artist)
            self.assertEqual([lot.artist for lot in lots], [item.artist])

    def test_later_transient_failure_keeps_page_one_and_other_groups_can_complete(self):
        def handler(artists, page):
            if artists[0] == "Artist 0":
                if page == 1:
                    raise SourceAccessError("HTTP 503")
                return response([hit(artists[0])], pages=2)
            return response([hit(artists[0])])

        fetcher = CatalogFetcher(handler)
        pages = self.fetch(fetcher, self.entries[:9])

        self.assertEqual(len(fetcher.calls), 3)
        first = pages[self.entries[0].url]
        self.assertFalse(first.complete)
        self.assertIn("HTTP 503", first.error)
        self.assertFalse(first.access_blocked)
        self.assertEqual(len(json.loads(first.page)["results"][0]["hits"]), 1)
        self.assertTrue(pages[self.entries[8].url].complete)

    def test_page_two_access_block_retains_page_one_and_stops_remaining_groups(self):
        def handler(artists, page):
            if page == 1:
                raise SourceAccessBlocked("HTTP 202")
            return response([hit(artists[0])], pages=2)

        fetcher = CatalogFetcher(handler)
        pages = self.fetch(fetcher)

        self.assertEqual(len(fetcher.calls), 2)
        self.assertEqual(len(pages), 54)
        self.assertTrue(all(not page.complete and page.access_blocked for page in pages.values()))
        self.assertEqual(len(json.loads(pages[self.entries[0].url].page)["results"][0]["hits"]), 1)
        self.assertEqual(json.loads(pages[self.entries[-1].url].page)["results"][0]["hits"], [])

    def test_later_group_access_block_preserves_completed_group(self):
        def handler(artists, page):
            if artists[0] == "Artist 8":
                raise SourceAccessBlocked("HTTP 403")
            return response([hit(artist) for artist in artists])

        fetcher = CatalogFetcher(handler)
        pages = self.fetch(fetcher, self.entries[:17])

        self.assertEqual(len(fetcher.calls), 2)
        self.assertTrue(all(pages[item.url].complete for item in self.entries[:8]))
        self.assertTrue(all(pages[item.url].access_blocked for item in self.entries[8:17]))

    def test_first_access_block_makes_only_one_request(self):
        def blocked(_artists, _page):
            raise SourceAccessBlocked("HTTP 429")

        fetcher = CatalogFetcher(blocked)
        pages = self.fetch(fetcher)

        self.assertEqual(len(fetcher.calls), 1)
        self.assertTrue(all(page.access_blocked and "HTTP 429" in page.error for page in pages.values()))

    def test_page_limit_is_reported_without_blocking_the_next_group(self):
        fetcher = CatalogFetcher(lambda artists, page: response([hit(artists[0])], pages=2))

        pages = self.fetch(fetcher, self.entries[:9], max_pages=1)

        self.assertEqual(len(fetcher.calls), 2)
        self.assertTrue(all(not page.complete and not page.access_blocked for page in pages.values()))
        self.assertIn("1-page limit", pages[self.entries[0].url].error)

    def test_wrong_repeated_or_malformed_later_page_retains_earlier_hits(self):
        for failure in ("wrong", "repeated", "malformed"):
            with self.subTest(failure=failure):
                def handler(artists, page):
                    if page == 0:
                        return response([hit(artists[0])], pages=2)
                    if failure == "wrong":
                        return response([hit(artists[1])], page=0, pages=2)
                    if failure == "repeated":
                        return response([hit(artists[0])], page=1, pages=2)
                    return response([None], page=1, pages=2)

                pages = self.fetch(CatalogFetcher(handler), self.entries[:2])

                first = pages[self.entries[0].url]
                self.assertFalse(first.complete)
                self.assertTrue(first.error)
                self.assertFalse(first.access_blocked)
                self.assertEqual(len(json.loads(first.page)["results"][0]["hits"]), 1)

    def test_user_stop_is_not_converted_to_partial_success(self):
        def stopped(_artists, _page):
            raise WatchlistStopped("Stopped")

        with self.assertRaises(WatchlistStopped):
            self.fetch(CatalogFetcher(stopped))


class WatchlistBatchRecoveryTests(TestCase):
    def setUp(self):
        self.cache = WatchlistCache(":memory:")
        self.addCleanup(self.cache.close)
        self.adapter = InvaluableAdapter()
        self.entries = [entry(index) for index in range(17)]

    def seed(self, item, identity=None):
        lot = self.adapter.parse_search_page(
            json.dumps(response([hit(item.artist, identity)])), item.url, item.artist,
        )[0]
        self.cache.upsert(lot, watch_url=item.url, search_hash=lot.content_hash, observed_at=PREVIOUS)
        self.cache.record_source_success(item.url, PREVIOUS)
        return lot

    def refresh(self, fetcher, entries=None, max_pages=10, **kwargs):
        entries = entries or self.entries[:2]
        with patch("catalogapp.watchlist_service.adapter_for_url", return_value=self.adapter):
            return WatchlistService(
                self.cache, fetcher=fetcher, now=lambda: NOW, max_pages_per_bookmark=max_pages,
            ).refresh(entries, selected_artists=[item.artist for item in entries], horizon_days=30, **kwargs)

    def test_partial_batch_updates_fresh_lot_and_preserves_unseen_cache_and_source_error(self):
        fresh = self.seed(self.entries[0])
        retained = self.seed(self.entries[1])

        def handler(artists, page):
            if page == 1:
                raise SourceAccessBlocked("HTTP 202")
            return response([hit(artists[0], bid=200)], pages=2)

        fetcher = CatalogFetcher(handler)
        result = self.refresh(fetcher)

        self.assertEqual(len(fetcher.calls), 2)
        fetcher.fetch.assert_not_called()
        self.assertEqual({lot.cache_key for lot in result.lots}, {fresh.cache_key, retained.cache_key})
        self.assertEqual(result.fallback_lot_keys, {retained.cache_key})
        self.assertEqual(self.cache.get(fresh.cache_key).last_seen_at, NOW.isoformat())
        self.assertEqual(self.cache.get(fresh.cache_key).current_bid, 200)
        self.assertEqual(self.cache.get(retained.cache_key).to_dict(), retained.to_dict())
        self.assertEqual(result.metrics.ended_lots, 0)
        self.assertIn("HTTP 202", result.errors[0])
        self.assertIn("Retained 1 cached lot", result.errors[0])
        for item in self.entries[:2]:
            row = self.cache.connection.execute("SELECT * FROM source_runs WHERE watch_url = ?", (item.url,)).fetchone()
            self.assertEqual(row["last_success_at"], PREVIOUS.isoformat())
            self.assertEqual(row["last_error_at"], NOW.isoformat())
            self.assertIn("HTTP 202", row["last_error"])

    def test_cap_preserves_unobserved_cache_for_batch_and_single_search(self):
        for batched in (True, False):
            with self.subTest(batched=batched), WatchlistCache(":memory:") as cache:
                self.cache = cache
                fresh = self.seed(self.entries[0])
                retained = self.seed(self.entries[0], "unseen")
                entries = self.entries[:2] if batched else self.entries[:1]
                if batched:
                    self.seed(self.entries[1])
                fetcher = CatalogFetcher(lambda artists, page: response([hit("Artist 0", bid=200)], pages=2))

                result = self.refresh(fetcher, entries, max_pages=1)

                self.assertIn(retained.cache_key, result.fallback_lot_keys)
                self.assertNotIn(fresh.cache_key, result.fallback_lot_keys)
                self.assertEqual(cache.get(retained.cache_key).last_seen_at, PREVIOUS.isoformat())
                self.assertEqual(result.metrics.ended_lots, 0)
                self.assertTrue(any("page limit" in error or "-page limit" in error for error in result.errors))
                row = cache.connection.execute("SELECT * FROM source_runs WHERE watch_url = ?", (entries[0].url,)).fetchone()
                self.assertEqual(row["last_success_at"], PREVIOUS.isoformat())
                self.assertTrue(row["last_error"])

    def test_uncached_artist_is_requested_before_cached_artists(self):
        for item in self.entries[:8]:
            self.seed(item)
        fetcher = CatalogFetcher(lambda artists, page: response([hit(artist) for artist in artists]))

        self.refresh(fetcher, self.entries[:9])

        self.assertEqual(fetcher.calls[0][0][0], "Artist 8")

    def test_blocked_first_group_retains_every_cache_without_detail_requests(self):
        cached = [self.seed(item) for item in self.entries]

        def blocked(_artists, _page):
            raise SourceAccessBlocked("HTTP 403")

        fetcher = CatalogFetcher(blocked)
        result = self.refresh(fetcher, self.entries)

        self.assertEqual(len(fetcher.calls), 1)
        fetcher.fetch.assert_not_called()
        self.assertEqual(result.fallback_lot_keys, {lot.cache_key for lot in cached})
        self.assertEqual(len(result.lots), 17)
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(result.metrics.ended_lots, 0)

    def test_later_group_block_keeps_first_group_fresh_and_remaining_groups_cached(self):
        cached = [self.seed(item) for item in self.entries]

        def handler(artists, page):
            if artists[0] == "Artist 8":
                raise SourceAccessBlocked("HTTP 202")
            return response([hit(artist, bid=200) for artist in artists])

        fetcher = CatalogFetcher(handler)
        result = self.refresh(fetcher, self.entries)

        self.assertEqual(len(fetcher.calls), 2)
        self.assertEqual(result.fallback_lot_keys, {lot.cache_key for lot in cached[8:]})
        self.assertEqual(result.metrics.changed_lots, 8)
        self.assertEqual(len(result.lots), 17)
        self.assertTrue(all(self.cache.get(lot.cache_key).last_seen_at == NOW.isoformat() for lot in cached[:8]))
        self.assertTrue(all(self.cache.get(lot.cache_key).last_seen_at == PREVIOUS.isoformat() for lot in cached[8:]))

    def test_new_changed_filter_excludes_unobserved_cached_changes(self):
        self.seed(self.entries[0])
        retained = self.seed(self.entries[1])
        fetcher = CatalogFetcher(lambda artists, page: response([hit("Artist 0", bid=200)], pages=2))

        result = self.refresh(fetcher, max_pages=1, new_changed_only=True)

        self.assertEqual([lot.artist for lot in result.lots], ["Artist 0"])
        self.assertEqual(result.fallback_lot_keys, set())
        self.assertEqual(self.cache.get(retained.cache_key).last_seen_at, PREVIOUS.isoformat())
