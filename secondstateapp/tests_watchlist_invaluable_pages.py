"""Saved upcoming searches add dated lots without inventing completeness."""

from dataclasses import replace
from datetime import datetime, timezone
import html
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from catalogapp.bookmark_watchlist import BookmarkEntry
from catalogapp.watchlist_adapters import InvaluableAdapter
from catalogapp.watchlist_cache import WatchlistCache
from catalogapp.watchlist_invaluable_pages import import_saved_invaluable_pages
from catalogapp.watchlist_models import NormalizedLot


NOW = datetime(2026, 10, 16, 20, tzinfo=timezone.utc)
OLD = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)
ENTRY = BookmarkEntry(folder_path=("ARTISTS INVALUABLE",), title="Calder", artist="Alexander Calder", source="Invaluable", url="https://www.invaluable.com/search?artistName=Alexander+Calder")
OTHER = replace(ENTRY, title="Warhol", artist="Andy Warhol", url="https://www.invaluable.com/search?artistName=Andy+Warhol")


def card(number="116", *, artist="Alexander Calder", day="2026-10-22T15:00:00-04:00", bid="$1,500", ref=None, image="https://image.invaluable.com/housePhotos/art.jpg"):
    return f'''<article class="lot-card" data-lot-id="{number}">
      <a class="lot-title" href="/auction-lot/print-{number}-c-{ref or 'synthetic' + number}">Print {number}</a>
      <span class="artist">{artist}</span><span class="medium">Lithograph</span>
      <span class="lot-number">{number}</span><span class="auction-house">Example House</span>
      <span class="estimate">$2,000 - $3,000</span><span class="current-bid">{bid}</span>
      <time datetime="{day}">October 22</time><img src="{image}">
    </article>'''


class SavedInvaluablePagesTests(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.cache = WatchlistCache(":memory:")
        self.addCleanup(self.cache.close)

    def page(self, name="search.html", content=None, *, origin=ENTRY.url, canonical=None):
        path = Path(self.directory.name) / name
        identity = f'<!-- saved from url=(0123){html.escape(origin)} -->' if origin else ""
        # Browser comments do not HTML-escape source URLs.
        identity = identity.replace("&amp;", "&")
        if canonical:
            identity += f'<link rel="canonical" href="{html.escape(canonical)}">'
        path.write_text(f'<html>{identity}<body>PRIVATE ACCOUNT NAME {content if content is not None else card()}<script>cookie="PRIVATE-SESSION"</script></body></html>', encoding="utf-8")
        return path

    def snapshot(self, name="snapshot.json", *, artist="Alexander Calder", origin=ENTRY.url, captured_at=NOW.isoformat(), **overrides):
        hit = {"objectID": "205299116", "lotRef": "synthetic116", "lotNumber": "116", "lotTitle": "Print 116", "artistName": artist,
               "houseName": "Example House", "currencyCode": "USD", "currentBid": 1500, "estimateLow": 2000, "estimateHigh": 3000,
               "dateTimeUTCUnix": datetime(2026, 10, 22, 19, tzinfo=timezone.utc).timestamp(), "photoPath": "example/art.jpg"}
        hit.update(overrides)
        payload = {"source_url": origin, "captured_at": captured_at, "results": [{"hits": [hit], "page": 0, "nbPages": 2, "nbHits": 2}]}
        path = Path(self.directory.name) / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def run_import(self, paths, entries=(ENTRY,), **kwargs):
        return import_saved_invaluable_pages(paths, entries, self.cache, now=NOW, **kwargs)

    def seed(self, number="999", *, source_id=None, ref=None, seen=OLD):
        lot = InvaluableAdapter().parse_search_page(card(number, ref=ref), ENTRY.url, ENTRY.artist)[0]
        lot.source_lot_id = source_id or f"numeric-{number}"
        lot.content_hash = lot.calculate_content_hash()
        self.cache.upsert(lot, watch_url=ENTRY.url, search_hash=lot.content_hash, observed_at=seen)
        return lot

    def test_html_import_is_offline_deduplicates_and_retains_no_private_page_data(self):
        first = self.page(content=card("116") + card("117"))
        second = self.page("page2.html", card("117") + card("118"))
        with (patch.object(InvaluableAdapter, "fetch_search_page", side_effect=AssertionError("No network")),
              patch.object(InvaluableAdapter, "fetch_lot_detail", side_effect=AssertionError("No network"))):
            result = self.run_import([first, second, first])
        self.assertEqual(result.metrics.new_lots, 3)
        self.assertEqual({lot.source_lot_id for lot in result.lots}, {"synthetic116", "synthetic117", "synthetic118"})
        self.assertEqual(result.metrics.pages_fetched, 0)
        stored = "\n".join(self.cache.connection.iterdump())
        for secret in ("PRIVATE ACCOUNT", "PRIVATE-SESSION", "<html>", str(first)):
            self.assertNotIn(secret, stored)
        self.assertIn("partial snapshots", " ".join(result.notices))

    def test_partial_import_preserves_absent_cache_and_live_error(self):
        old = self.seed()
        before = self.cache.get(old.cache_key).to_dict()
        self.cache.record_source_error(ENTRY.url, "HTTP 202", OLD)
        with patch.object(self.cache, "mark_missing_ended", side_effect=AssertionError("Partial snapshot")):
            result = self.run_import([self.page()])
        self.assertEqual(result.fallback_lot_keys, {old.cache_key})
        self.assertEqual(self.cache.get(old.cache_key).to_dict(), before)
        self.assertEqual(result.metrics.ended_lots, 0)
        self.assertEqual(len(self.cache.active_lots_for_watch_url(ENTRY.url)), 2)
        self.assertEqual(self.cache.connection.execute("SELECT last_error FROM source_runs").fetchone()[0], "HTTP 202")

    def test_same_displayed_lot_number_from_different_auctions_keeps_both_source_references(self):
        for attributes in (True, False):
            with self.subTest(data_lot_id=attributes):
                content = card("116", ref="houseone116") + card("116", ref="housetwo116")
                if not attributes:
                    content = content.replace(' data-lot-id="116"', "")
                result = self.run_import([self.page(content=content)])
                self.assertEqual({lot.source_lot_id for lot in result.lots}, {"houseone116", "housetwo116"})
                self.assertEqual(len(result.lots), 2)
                self.assertEqual(result.errors, [])

    def test_html_reuses_cached_numeric_feed_id_even_after_slug_changes(self):
        old = self.seed("116", source_id="205299116")
        self.cache.connection.execute("UPDATE lots SET canonical_url = ? WHERE cache_key = ?", (old.lot_url.replace("print-116", "old-title-116"), old.cache_key))
        old.lot_url = old.lot_url.replace("print-116", "old-title-116")
        self.cache.update_payload(old)
        result = self.run_import([self.page(content=card(bid="$1,800"))])
        self.assertEqual(len(result.lots), 1)
        self.assertEqual(result.lots[0].source_lot_id, "205299116")
        self.assertEqual(result.lots[0].lot_url, old.lot_url)
        self.assertEqual(result.lots[0].current_bid, 1800)
        self.assertEqual(self.cache.connection.execute("SELECT COUNT(*) FROM lots").fetchone()[0], 1)

    def test_two_artists_attach_to_their_own_selected_bookmarks(self):
        result = self.run_import([self.page(), self.page("warhol.html", card("117", artist="Andy Warhol"), origin=OTHER.url)], entries=(ENTRY, OTHER))
        self.assertEqual(result.metrics.new_lots, 2)
        self.assertEqual([lot.artist for lot in self.cache.active_lots_for_watch_url(ENTRY.url)], [ENTRY.artist])
        self.assertEqual([lot.artist for lot in self.cache.active_lots_for_watch_url(OTHER.url)], [OTHER.artist])

    def test_unknown_missing_and_spoofed_artist_origins_are_rejected(self):
        for origin in (None, OTHER.url, "https://invaluable.com.evil.example/search?artistName=Alexander+Calder", "https://user:password@www.invaluable.com/search?artistName=Alexander+Calder", "https://www.invaluable.com/search?q=Alexander+Calder"):
            with self.subTest(origin=origin):
                result = self.run_import([self.page(origin=origin)])
                self.assertEqual(result.lots, [])
                self.assertTrue(result.errors)
        self.assertEqual(self.cache.active_lots_for_watch_url(ENTRY.url), [])

    def test_generic_canonical_allows_verified_saved_search_but_conflicting_artist_does_not(self):
        result = self.run_import([self.page(canonical="https://www.invaluable.com/search")])
        self.assertEqual(len(result.lots), 1)
        result = self.run_import([self.page(canonical=OTHER.url)])
        self.assertTrue(result.errors)
        self.assertEqual(result.fallback_lot_keys, {result.lots[0].cache_key})

    def test_related_hidden_and_embedded_recommendations_are_not_imported(self):
        content = card() + '<div class="recommended-lots">' + card("117") + '</div>'
        content += '<div hidden>' + card("118") + '</div>'
        content += '<script type="application/json">' + json.dumps({"lots": [{"lotId": "fake", "lotUrl": "/auction-lot/fake-119-c-fake119", "title": "Fake", "artistName": ENTRY.artist, "endAt": "2026-10-22"}]}) + '</script>'
        result = self.run_import([self.page(content=content + card("120", artist=OTHER.artist))])
        self.assertEqual([lot.lot_number for lot in result.lots], ["116"])

    def test_undated_invalid_date_and_external_lot_cannot_be_new_calendar_records(self):
        content = card(day="") + card("117", day="Oct 31, 5:00 AM EDT") + card("118", day="2026-99-99")
        content += card("119").replace('/auction-lot/print-119-c-synthetic119', 'https://other.example/auction-lot/fake')
        result = self.run_import([self.page(content=content)])
        self.assertEqual(result.lots, [])
        self.assertIn("3 Invaluable lot cards had no verified sale date", " ".join(result.notices))
        self.assertEqual(self.cache.active_lots_for_watch_url(ENTRY.url), [])

    def test_cached_date_and_artwork_survive_a_less_detailed_saved_card(self):
        old = self.seed("116", source_id="205299116")
        old.saved_image_base64 = "sanitized-artwork"
        self.cache.update_payload(old)
        result = self.run_import([self.page(content=card(day="", image="Search_files/image.jpg"))])
        lot = result.lots[0]
        self.assertEqual(lot.end_at, old.end_at)
        self.assertEqual(lot.image_url, old.image_url)
        self.assertEqual(lot.saved_image_base64, old.saved_image_base64)
        self.assertEqual(result.fallback_lot_keys, set())

    def test_snapshot_generic_print_retains_known_technique_and_same_image_but_refreshes_bids_and_date(self):
        old = self.seed("116", source_id="205299116")
        old.medium = "Color lithograph on paper"
        old.saved_image_base64 = "sanitized-original-artwork"
        old.content_hash = old.calculate_content_hash()
        self.cache.update_payload(old)
        source_date = datetime(2026, 10, 23, 19, tzinfo=timezone.utc)
        result = self.run_import([self.snapshot(currentBid=1900, bidCount=7, photoPath=old.image_url,
                                               dateTimeUTCUnix=source_date.timestamp())])
        lot = result.lots[0]
        self.assertEqual(lot.medium, "Color lithograph on paper")
        self.assertEqual(lot.saved_image_base64, "sanitized-original-artwork")
        self.assertEqual(lot.image_url, old.image_url)
        self.assertEqual((lot.current_bid, lot.bid_count), (1900, 7))
        self.assertEqual(lot.end_at, source_date.isoformat())
        self.assertEqual((lot.source_lot_id, lot.lot_url), (old.source_lot_id, old.lot_url))

    def test_snapshot_new_primary_image_replaces_old_pixels_without_losing_fresh_details(self):
        old = self.seed("116", source_id="205299116")
        old.saved_image_base64 = "sanitized-old-artwork"
        old.content_hash = old.calculate_content_hash()
        self.cache.update_payload(old)
        result = self.run_import([self.snapshot(photoPath="changed/primary.jpg", lotTitle="New artwork", lotDescription="Etching",
                                               currentBid=2100, bidCount=9)])
        lot = result.lots[0]
        self.assertEqual(lot.image_url, "https://image.invaluable.com/housePhotos/changed/primary.jpg")
        self.assertEqual(lot.saved_image_base64, "")
        self.assertEqual(lot.medium, "Etching")
        self.assertEqual((lot.current_bid, lot.bid_count), (2100, 9))
        self.assertEqual(lot.source_lot_id, old.source_lot_id)
        self.assertEqual(self.cache.get(old.cache_key).saved_image_base64, "")

    def test_local_image_path_is_never_retained_as_a_public_image(self):
        result = self.run_import([self.page(content=card(image="Search_files/image.jpg"))])
        self.assertEqual(result.lots[0].image_url, "")

    def test_modern_visible_card_requires_absolute_year_and_ignores_converted_price(self):
        content = '''<div class="ais-Hits-item"><div class="content-holder">
          <div class="text-holder"><span class="bold text-live">Oct 22, 2026, 3:00 PM EDT</span></div>
          <div class="text-holder"><a class="lot-title" href="/auction-lot/print-116-c-synthetic116?objectID=205299116">Print 116</a></div>
          <div class="text-holder">Example House</div>
          <div class="text-holder">Est: 600 CAD - 850 CAD</div>
          <div class="text-holder"><span class="bold text-large">500 CAD<span class="converted-price">360 USD</span></span></div>
        </div></div>'''
        result = self.run_import([self.page(content=content)])
        self.assertEqual(len(result.lots), 1)
        lot = result.lots[0]
        self.assertEqual(lot.end_at, "2026-10-22T15:00:00-04:00")
        self.assertEqual((lot.estimate_low, lot.estimate_high, lot.current_bid, lot.currency), (600, 850, 500, "CAD"))
        self.assertEqual(lot.auction_house, "Example House")
        self.cache.close()
        self.cache = WatchlistCache(":memory:")
        self.addCleanup(self.cache.close)
        result = self.run_import([self.page(content=content.replace("Oct 22, 2026, 3:00 PM EDT", "4 Days Left"))])
        self.assertEqual(result.lots, [])
        self.assertIn("no verified sale date", " ".join(result.notices))

    def test_repeated_snapshot_and_changed_bid_have_expected_transitions(self):
        page = self.page()
        self.run_import([page])
        self.assertEqual(self.run_import([page]).metrics.unchanged_lots, 1)
        page = self.page(content=card(bid="$1,800"))
        result = self.run_import([page])
        self.assertEqual(result.metrics.changed_lots, 1)
        self.assertEqual(result.lots[0].current_bid, 1800)

    def test_conflicting_files_leave_that_lot_unchanged_but_import_independent_lot(self):
        old = self.seed("116", source_id="205299116")
        before = self.cache.get(old.cache_key).to_dict()
        result = self.run_import([self.page(content=card(bid="$1,800") + card("117")), self.page("conflict.html", card(bid="$1,900"))])
        self.assertEqual(result.metrics.new_lots, 1)
        self.assertEqual(self.cache.get(old.cache_key).to_dict(), before)
        self.assertIn(old.cache_key, result.fallback_lot_keys)
        self.assertIn("conflicting snapshots", " ".join(result.errors))

    def test_horizon_and_changed_filter_do_not_remove_cached_membership(self):
        old = self.seed()
        result = self.run_import([self.page(content=card(day="2026-12-22"))], new_changed_only=True)
        self.assertEqual(result.lots, [])
        self.assertEqual(len(self.cache.active_lots_for_watch_url(ENTRY.url)), 2)
        self.assertEqual(self.cache.get(old.cache_key).last_seen_at, OLD.isoformat())

    def test_native_snapshot_preserves_object_id_and_capture_time(self):
        result = self.run_import([self.snapshot(captured_at=OLD.isoformat())])
        self.assertEqual(result.metrics.new_lots, 1)
        lot = result.lots[0]
        self.assertEqual(lot.source_lot_id, "205299116")
        self.assertEqual(lot.last_seen_at, OLD.isoformat())
        self.assertEqual(lot.end_at, "2026-10-22T19:00:00+00:00")
        self.assertEqual(lot.image_url, "https://image.invaluable.com/housePhotos/example/art.jpg")

    def test_snapshot_category_and_query_scope_must_match_the_selected_bookmark(self):
        prints = replace(ENTRY, url=ENTRY.url + "&Fine+Art=Prints&query=red")
        for suffix in ("&Fine+Art=Sculpture&query=red", "&Fine+Art=Prints&query=blue", "&Fine+Art=Prints", ""):
            with self.subTest(suffix=suffix):
                result = self.run_import([self.snapshot(origin=ENTRY.url + suffix)], entries=(prints,))
                self.assertEqual(result.metrics.new_lots, 0)
                self.assertIn("category, or search-query filters", " ".join(result.errors))
        self.assertEqual(self.cache.active_lots_for_watch_url(prints.url), [])

    def test_scope_accepts_page_sort_and_query_alias_changes_without_adding_other_membership(self):
        prints = replace(ENTRY, url=ENTRY.url + "&Fine+Art=Prints&query=red")
        sculpture = replace(ENTRY, url=ENTRY.url + "&Fine+Art=Sculpture&query=red")
        source = ENTRY.url + "&Fine+Art=Prints&q=red&page=2&sort=enddateasc&hitsPerPage=96"
        result = self.run_import([self.snapshot(origin=source)], entries=(prints, sculpture))
        self.assertEqual(result.metrics.new_lots, 1)
        self.assertEqual(len(self.cache.active_lots_for_watch_url(prints.url)), 1)
        self.assertEqual(self.cache.active_lots_for_watch_url(sculpture.url), [])

    def test_snapshot_explicit_category_metadata_cannot_contradict_its_url(self):
        prints = replace(ENTRY, url=ENTRY.url + "&Fine+Art=Prints")
        for metadata in ({"supercategoryName": "Fine Art", "subcategoryName": "Sculpture"},
                         {"supercategoryName": "Decorative Art", "subcategoryName": "Prints"}):
            with self.subTest(metadata=metadata):
                result = self.run_import([self.snapshot(origin=prints.url, **metadata)], entries=(prints,))
                self.assertEqual(result.lots, [])
                self.assertIn("artist/category filters", " ".join(result.notices))
        result = self.run_import([self.snapshot(origin=prints.url, supercategoryName="Fine Art", subcategoryName="Prints")], entries=(prints,))
        self.assertEqual(result.metrics.new_lots, 1)

    def test_html_search_scope_cannot_attach_sculpture_to_prints(self):
        prints = replace(ENTRY, url=ENTRY.url + "&Fine+Art=Prints")
        result = self.run_import([self.page(origin=ENTRY.url + "&Fine+Art=Sculpture")], entries=(prints,))
        self.assertEqual(result.lots, [])
        self.assertTrue(result.errors)

    def test_valid_empty_snapshot_reports_zero_and_preserves_cached_lots(self):
        old = self.seed()
        path = self.snapshot()
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["results"][0].update(hits=[], nbHits=0, nbPages=0)
        path.write_text(json.dumps(payload), encoding="utf-8")
        with patch.object(self.cache, "mark_missing_ended", side_effect=AssertionError("Partial snapshot")):
            result = self.run_import([path])
        self.assertEqual(result.fallback_lot_keys, {old.cache_key})
        self.assertEqual(self.cache.get(old.cache_key).last_seen_at, OLD.isoformat())
        self.assertEqual(result.metrics.ended_lots, 0)
        self.assertIn("reported zero matching lots", " ".join(result.notices))
        self.assertNotIn("Webpage", " ".join(result.notices))

    def test_snapshot_rejects_missing_artist_invalid_source_or_capture_time(self):
        for options in ({"artist": ""}, {"origin": "https://example.com/search?artistName=Alexander+Calder"}, {"captured_at": "2026-10-16T18:00:00"}, {"captured_at": "2027-01-01T00:00:00Z"}, {"captured_at": "not a date"}):
            with self.subTest(options=options):
                result = self.run_import([self.snapshot(**options)])
                self.assertEqual(result.lots, [])
                self.assertTrue(result.errors)

    def test_old_native_snapshot_does_not_overwrite_newer_cached_bid(self):
        old = self.seed("116", source_id="205299116", seen=NOW)
        before = self.cache.get(old.cache_key).to_dict()
        result = self.run_import([self.snapshot(captured_at=OLD.isoformat(), currentBid=500)])
        self.assertEqual(self.cache.get(old.cache_key).to_dict(), before)
        self.assertEqual(result.fallback_lot_keys, {old.cache_key})
        self.assertIn("older snapshot", " ".join(result.notices))

    def test_sold_lot_does_not_reactivate_from_saved_upcoming_page(self):
        old = self.seed("116", source_id="205299116")
        old.sold_price = 3000
        old.content_hash = old.calculate_content_hash()
        self.cache.upsert(old, watch_url=ENTRY.url, search_hash=old.content_hash, observed_at=OLD, active=False)
        result = self.run_import([self.page()])
        self.assertEqual(result.lots, [])
        self.assertEqual(self.cache.active_lots_for_watch_url(ENTRY.url), [])
        self.assertEqual(self.cache.get(old.cache_key).sold_price, 3000)

    def test_invalid_files_and_access_page_do_not_remove_existing_lots(self):
        old = self.seed()
        paths = [Path(self.directory.name) / "missing.html", self.page("invalid.txt"), self.page("blocked.html", "<h1>Verify you are human</h1>"), self.page("empty.html", "No visible cards")]
        result = self.run_import(paths)
        self.assertEqual(result.fallback_lot_keys, {old.cache_key})
        self.assertEqual(len(result.errors), 3)
        self.assertTrue(result.notices)

    def test_requires_selected_invaluable_artists_and_files(self):
        with self.assertRaises(ValueError):
            self.run_import([self.page()], entries=(replace(ENTRY, source="Heritage"),))
        with self.assertRaises(ValueError):
            self.run_import([])
