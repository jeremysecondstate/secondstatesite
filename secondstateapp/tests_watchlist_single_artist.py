"""A one-artist refresh must leave every other watch and Calendar lot alone."""

from datetime import timedelta
import json
from unittest import TestCase
from unittest.mock import Mock, patch

from catalogapp.bookmark_watchlist import parse_bookmarks_html
from catalogapp.watchlist_adapters import InvaluableAdapter
from catalogapp.watchlist_cache import WatchlistCache
from catalogapp.watchlist_fetch import SourceAccessBlocked
from catalogapp.watchlist_service import WatchlistService
from catalogapp.watchlist_sync import sync_watchlist_lots
from secondstateapp.tests_watchlist_batch_recovery import (
    NOW, PREVIOUS, CatalogFetcher, entry, hit, response,
)


class SingleArtistRefreshTests(TestCase):
    def setUp(self):
        self.cache = WatchlistCache(":memory:")
        self.addCleanup(self.cache.close)
        self.adapter = InvaluableAdapter()
        self.target = parse_bookmarks_html(
            '<DL><DT><A HREF="https://www.invaluable.com/search?'
            'artistName=Will%2520Barnet&amp;sort=endDateAsc">'
            'Barnett, Will: Invaluable — Prints</A></DL>'
        )[0]
        self.other = entry(0)
        self.entries = [self.other, self.target, entry(1)]
        self.other_lot = self.seed(self.other, "untouched")
        self.cache.record_source_success(self.other.url, PREVIOUS)
        self.cache.record_watch_coverage(
            self.other.url, "verified", observed_at=PREVIOUS,
            covered_until=NOW + timedelta(days=7), detail="Previously checked catalog",
        )
        self.other_before = self.other_state()

    def seed(self, watch, identity):
        lot = self.adapter.parse_search_page(
            json.dumps(response([hit(watch.artist, identity)])), watch.url, watch.artist,
        )[0]
        self.cache.upsert(lot, watch_url=watch.url, search_hash=lot.content_hash, observed_at=PREVIOUS)
        return lot

    def other_state(self):
        return (
            self.cache.get(self.other_lot.cache_key).to_dict(),
            self.cache.coverage_for_entries([self.other]),
            tuple(self.cache.connection.execute(
                "SELECT * FROM source_runs WHERE watch_url = ?", (self.other.url,),
            ).fetchone()),
            [tuple(row) for row in self.cache.connection.execute(
                "SELECT * FROM watch_memberships WHERE watch_url = ?", (self.other.url,),
            ).fetchall()],
        )

    def refresh(self, fetcher):
        with patch("catalogapp.watchlist_service.adapter_for_url", return_value=self.adapter):
            return WatchlistService(self.cache, fetcher=fetcher, now=lambda: NOW).refresh(
                self.entries, selected_artists={self.target.watch_label}, horizon_days=7,
            )

    def test_new_artist_uses_bookmark_url_identity_and_uploads_only_its_lots(self):
        self.assertEqual(self.target.watch_label, "Will Barnet")
        fetcher = CatalogFetcher(lambda artists, page: response([hit(artists[0], "will-one")]))

        result = self.refresh(fetcher)

        self.assertEqual(fetcher.calls, [(["Will Barnet"], 0)])
        self.assertEqual([lot.artist_watchlist_name for lot in result.lots], ["Will Barnet"])
        self.assertEqual([row.watch_url for row in result.coverage], [self.target.url])
        self.assertEqual(result.metrics.artists, 1)
        self.assertEqual(result.metrics.bookmark_urls, 1)
        self.assertEqual(self.other_state(), self.other_before)
        session = Mock()
        session.post.return_value.status_code = 200
        session.post.return_value.json.return_value = {
            "ok": True, "received": 1, "created": 1, "updated": 0, "ended": 0,
        }
        artprice = "https://www.artprice.com/artist/1474/will-r-barnet"

        synced = sync_watchlist_lots(
            result.lots, base_url="https://secondstate.art", api_key="test-key",
            artist_artprice_links={self.target.watch_label: artprice}, session=session,
        )

        self.assertEqual(synced.received, 1)
        session.post.assert_called_once()
        uploaded = session.post.call_args.kwargs["json"]
        self.assertEqual([lot["source_lot_id"] for lot in uploaded["lots"]], ["will-one"])
        self.assertEqual(uploaded["artist_links"], [{"name": "Will Barnet", "artprice_url": artprice}])

    def test_blocked_artist_retains_only_its_cached_lots_with_original_observation(self):
        cached = self.seed(self.target, "will-cached")
        fetcher = CatalogFetcher(Mock(side_effect=SourceAccessBlocked("HTTP 202")))

        result = self.refresh(fetcher)

        self.assertEqual(fetcher.calls, [(["Will Barnet"], 0)])
        self.assertEqual([lot.cache_key for lot in result.lots], [cached.cache_key])
        self.assertEqual(result.fallback_lot_keys, {cached.cache_key})
        self.assertEqual(result.lots[0].last_seen_at, PREVIOUS.isoformat())
        self.assertEqual(result.coverage[0].state, "blocked")
        self.assertEqual(self.other_state(), self.other_before)

    def test_new_blocked_artist_does_not_replace_missing_data_with_other_artists(self):
        fetcher = CatalogFetcher(Mock(side_effect=SourceAccessBlocked("HTTP 202")))

        result = self.refresh(fetcher)

        self.assertEqual(result.lots, [])
        self.assertEqual(result.coverage[0].state, "blocked")
        self.assertTrue(any("No cached lots" in error and "Will Barnet" in error for error in result.errors))
        self.assertEqual(self.other_state(), self.other_before)

    def test_complete_empty_artist_search_ends_only_that_artists_missing_lot(self):
        cached = self.seed(self.target, "will-missing")

        result = self.refresh(CatalogFetcher(lambda artists, page: response()))

        self.assertEqual([lot.cache_key for lot in result.lots], [cached.cache_key])
        self.assertEqual(result.lots[0].status, "ended")
        self.assertEqual(result.metrics.ended_lots, 1)
        self.assertEqual(result.coverage[0].state, "empty")
        self.assertEqual(self.other_state(), self.other_before)

    def test_empty_artist_selection_never_fetches_or_returns_other_cached_lots(self):
        fetcher = CatalogFetcher(Mock(side_effect=AssertionError("No artist was requested")))

        result = WatchlistService(self.cache, fetcher=fetcher, now=lambda: NOW).refresh(
            self.entries, selected_artists=set(),
        )

        self.assertEqual(fetcher.calls, [])
        self.assertEqual(result.lots, [])
        self.assertEqual(result.coverage, [])
        self.assertEqual(self.other_state(), self.other_before)
