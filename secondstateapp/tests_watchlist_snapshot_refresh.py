"""Saved-page lots retain one identity and rich metadata on a live refresh."""

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from catalogapp.bookmark_watchlist import BookmarkEntry
from catalogapp.watchlist_cache import WatchlistCache
from catalogapp.watchlist_invaluable_pages import import_saved_invaluable_pages
from catalogapp.watchlist_models import NormalizedLot
from catalogapp.watchlist_service import WatchlistService


OLD = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)
NOW = datetime(2026, 10, 16, 20, tzinfo=timezone.utc)
ENTRY = BookmarkEntry(folder_path=("ARTISTS INVALUABLE",), title="Calder", artist="Alexander Calder", source="Invaluable", url="https://www.invaluable.com/search?artistName=Alexander+Calder")


class CatalogFetcher:
    def __init__(self, **overrides):
        self.pages_fetched = 0
        self.hit = {"objectID": "205299116", "lotRef": "synthetic116", "lotNumber": "116", "lotTitle": "Print",
                    "artistName": "Alexander Calder", "houseName": "Example House", "currencyCode": "USD",
                    "currentBid": 1800, "bidCount": 5, "estimateLow": 2000, "estimateHigh": 3000,
                    "dateTimeUTCUnix": datetime(2026, 10, 22, 19, tzinfo=timezone.utc).timestamp()}
        self.hit.update(overrides)

    def post_json(self, _url, _payload, *, referer=""):
        self.pages_fetched += 1
        return {"results": [{"hits": [self.hit], "page": 0, "nbPages": 1, "nbHits": 1}]}

    def fetch(self, _url):
        raise AssertionError("Complete catalog cards should not request lot details")


class SnapshotLiveRefreshTests(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.cache = WatchlistCache(":memory:")
        self.addCleanup(self.cache.close)

    def import_html(self):
        path = Path(self.directory.name) / "saved.html"
        path.write_text(f'''<html><!-- saved from url=(0123){ENTRY.url} --><body>
          <article class="lot-card" data-lot-id="116">
            <a class="lot-title" href="/auction-lot/print-116-c-synthetic116">Print</a>
            <span class="artist">Alexander Calder</span><span class="medium">Color lithograph</span>
            <span class="auction-house">Example House</span><span class="lot-number">116</span>
            <span class="sale-title">Autumn Editions</span><a class="sale-link" href="/catalog/autumn-editions">Sale</a>
            <span class="estimate">$2,000 - $3,000</span><span class="current-bid">$1,500</span><span class="bid-count">4 bids</span>
            <time datetime="2026-10-22T19:00:00+00:00">October 22</time>
            <img src="https://image.invaluable.com/housePhotos/original.jpg">
          </article></body></html>''', encoding="utf-8")
        imported = import_saved_invaluable_pages([path], [ENTRY], self.cache, now=OLD)
        lot = imported.lots[0]
        lot.location = "New York, US"
        lot.saved_image_base64 = "sanitized-artwork"
        lot.content_hash = lot.calculate_content_hash()
        self.cache.update_payload(lot)
        return lot

    def refresh(self, fetcher):
        return WatchlistService(self.cache, fetcher=fetcher, now=lambda: NOW).refresh(
            [ENTRY], selected_artists=[ENTRY.artist], horizon_days=30, zero_ai=True,
        )

    def test_html_then_live_numeric_object_id_updates_one_lot_without_false_ending(self):
        old = self.import_html()
        self.assertEqual(old.source_lot_id, "synthetic116")
        result = self.refresh(CatalogFetcher())
        self.assertEqual(result.errors, [])
        self.assertEqual(result.metrics.new_lots, 0)
        self.assertEqual(result.metrics.ended_lots, 0)
        self.assertEqual(result.metrics.changed_lots, 1)
        self.assertEqual(len(result.lots), 1)
        lot = result.lots[0]
        self.assertEqual(lot.cache_key, old.cache_key)
        self.assertEqual(lot.lot_url, old.lot_url)
        self.assertEqual((lot.current_bid, lot.bid_count), (1800, 5))
        self.assertEqual(lot.first_seen_at, OLD.isoformat())
        self.assertEqual(lot.last_seen_at, NOW.isoformat())
        self.assertEqual(self.cache.connection.execute("SELECT COUNT(*) FROM lots").fetchone()[0], 1)
        self.assertEqual(len(self.cache.active_lots_for_watch_url(ENTRY.url)), 1)

    def test_changed_source_slug_matches_scoped_saved_reference_before_marking_missing(self):
        old = self.import_html()
        result = self.refresh(CatalogFetcher(lotTitle="Updated print title"))
        self.assertEqual(result.errors, [])
        self.assertEqual(result.metrics.ended_lots, 0)
        self.assertEqual(len(result.lots), 1)
        self.assertEqual(result.lots[0].cache_key, old.cache_key)
        self.assertEqual(result.lots[0].lot_url, old.lot_url)
        self.assertEqual(result.lots[0].title, "Updated print title")

    def test_live_bids_change_while_missing_static_metadata_is_retained(self):
        old = self.import_html()
        fetcher = CatalogFetcher()
        result = self.refresh(fetcher)
        lot = result.lots[0]
        for field in ("sale_title", "sale_url", "location", "medium", "image_url", "saved_image_base64"):
            self.assertEqual(getattr(lot, field), getattr(old, field), field)
        self.assertEqual((lot.current_bid, lot.bid_count), (1800, 5))
        repeat = self.refresh(fetcher)
        self.assertEqual(repeat.metrics.unchanged_lots, 1)
        self.assertEqual(repeat.metrics.changed_lots, 0)
        fetcher.hit.update(currentBid=2300, bidCount=9)
        changed = self.refresh(fetcher)
        self.assertEqual(changed.metrics.changed_lots, 1)
        self.assertEqual((changed.lots[0].current_bid, changed.lots[0].bid_count), (2300, 9))
        self.assertEqual(changed.lots[0].sale_url, old.sale_url)

    def test_missing_current_bid_does_not_reuse_the_previous_price(self):
        self.import_html()
        result = self.refresh(CatalogFetcher(currentBid=None, bidCount=None))
        self.assertIsNone(result.lots[0].current_bid)
        self.assertIsNone(result.lots[0].bid_count)
        self.assertEqual(result.lots[0].sale_title, "Autumn Editions")

    def test_new_static_metadata_and_primary_image_replace_previous_values(self):
        self.import_html()
        result = self.refresh(CatalogFetcher(catalogRef="new-sale", location="Paris", lotTitle="New artwork", lotDescription="Etching", photoPath="new/image.jpg"))
        lot = result.lots[0]
        self.assertEqual(lot.sale_url, "https://www.invaluable.com/catalog/new-sale")
        self.assertEqual(lot.location, "Paris")
        self.assertEqual(lot.medium, "Etching")
        self.assertEqual(lot.image_url, "https://image.invaluable.com/housePhotos/new/image.jpg")
        self.assertEqual(lot.saved_image_base64, "")

    def test_repeated_numeric_identity_keeps_existing_url_when_title_changes(self):
        old = NormalizedLot(source="Invaluable", source_lot_id="205299116", artist=ENTRY.artist,
                            artist_watchlist_name=ENTRY.artist, title="Old title", medium="Lithograph", auction_house="Example House",
                            lot_number="116", end_at="2026-10-22T19:00:00+00:00", lot_url="https://www.invaluable.com/auction-lot/old-title-116-c-synthetic116")
        self.cache.upsert(old, watch_url=ENTRY.url, search_hash=old.content_hash, observed_at=OLD)
        result = self.refresh(CatalogFetcher(lotTitle="New title"))
        self.assertEqual(result.errors, [])
        self.assertEqual(result.lots[0].source_lot_id, "205299116")
        self.assertEqual(result.lots[0].lot_url, old.lot_url)
        self.assertEqual(result.lots[0].title, "New title")
        self.assertEqual(result.metrics.ended_lots, 0)

    def test_same_displayed_number_but_different_reference_is_a_distinct_lot(self):
        old = self.import_html()
        result = self.refresh(CatalogFetcher(lotRef="otherhouse116"))
        self.assertEqual(result.errors, [])
        self.assertEqual(result.metrics.new_lots, 1)
        self.assertEqual(result.metrics.ended_lots, 1)
        self.assertEqual({lot.cache_key for lot in result.lots}, {old.cache_key, "invaluable:205299116"})

    def test_ambiguous_matching_references_retain_cache_and_report_incomplete(self):
        old = self.import_html()
        duplicate = NormalizedLot.from_dict(old.to_dict())
        duplicate.source_lot_id = "other-id"
        duplicate.lot_url = old.lot_url.replace("/print-116-", "/older-title-116-")
        duplicate.content_hash = duplicate.calculate_content_hash()
        self.cache.upsert(duplicate, watch_url=ENTRY.url, search_hash=duplicate.content_hash, observed_at=OLD)
        result = self.refresh(CatalogFetcher(lotTitle="Another updated title"))
        self.assertIn("multiple cached identities", " ".join(result.errors))
        self.assertEqual(result.metrics.ended_lots, 0)
        self.assertEqual(result.fallback_lot_keys, {old.cache_key, duplicate.cache_key})
