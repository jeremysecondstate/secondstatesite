"""Bulk captures preserve individual artist and search-scope membership."""

from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from html import escape
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from catalogapp.bookmark_watchlist import (
    expand_invaluable_bulk_entries, invaluable_search_artists,
    parse_bookmarks_html, parse_netscape_bookmarks,
)
from catalogapp.watchlist_bookmark_source import load_bookmark_source
from catalogapp.watchlist_cache import WatchlistCache
from catalogapp.watchlist_invaluable_pages import import_saved_invaluable_pages
from scripts import import_invaluable_capture as cli
from secondstateapp.tests_watchlist_capture_bundle import CALDER, WARHOL, NOW, OLD, bundle, hit, snapshot


ROOT = Path(__file__).resolve().parents[1]
BOOKMARKS_PATH = ROOT / "docs" / "artist-links.html"


def legacy_bookmarks():
    """Exercise the preserved two-list intake without a second export file."""
    raw = parse_netscape_bookmarks(BOOKMARKS_PATH.read_text(encoding="utf-8-sig"))
    searches = [entry for entry in raw if entry.title in {"BULK 1", "BULK 2"}
                and "OLD" in entry.folder_path]
    singles = [entry for entry in raw if "ARTISTS INVALUABLE" in entry.folder_path]
    return searches, singles


def bookmark_html(entries):
    return "<DL>" + "".join(
        f'<DT><H3>{escape(entry.folder)}</H3><DL>'
        f'<DT><A HREF="{escape(entry.url, quote=True)}">{escape(entry.title)}</A></DL>'
        for entry in entries
    ) + "</DL>"


def bulk_entry(*artists):
    parts = urlsplit(CALDER.url)
    filters = [(key, value) for key, value in parse_qsl(parts.query) if key != "artistName"]
    return replace(CALDER, title="Bulk", artist="", url=urlunsplit((
        parts.scheme, parts.netloc, parts.path, urlencode([*(('artistName', name) for name in artists), *filters]), "",
    )))


class BulkCaptureTests(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.cache = WatchlistCache(":memory:")
        self.addCleanup(self.cache.close)

    def run_import(self, payload, entries):
        path = Path(self.directory.name) / "bulk.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return import_saved_invaluable_pages([path], entries, self.cache, now=NOW, horizon_days=3)

    def test_archived_two_bulk_bookmarks_expand_to_all_82_artists_and_keep_both_brainwash_scopes(self):
        searches, singles = legacy_bookmarks()
        self.assertEqual([entry.title for entry in searches], ["BULK 1", "BULK 2"])
        self.assertEqual([len(invaluable_search_artists(entry.url)) for entry in searches], [46, 36])
        legacy_html = bookmark_html([*searches, *singles])
        entries = parse_bookmarks_html(legacy_html)
        selected = [entry for entry in entries if entry.source == "Invaluable"]
        original = parse_bookmarks_html(bookmark_html(singles))
        old_artists = {entry.artist for entry in original if entry.source == "Invaluable"}
        artists = {entry.artist for entry in selected}
        self.assertEqual(len(artists), 82)
        self.assertTrue(old_artists <= artists)
        self.assertEqual(len(artists - old_artists), 15)
        self.assertTrue(all(len(invaluable_search_artists(entry.url)) == 1 for entry in selected))
        self.assertEqual(expand_invaluable_bulk_entries(entries), entries)
        brainwash = [entry for entry in selected if entry.artist == "Mr Brainwash"]
        self.assertEqual(len(brainwash), 2)
        self.assertEqual({dict(parse_qsl(urlsplit(entry.url).query)).get("Fine Art") for entry in brainwash}, {None, "Prints"})
        self.assertEqual(parse_bookmarks_html(legacy_html, selected_folders=["NO SUCH FOLDER"]), [])

    def test_actual_bulk_pages_route_all_82_hits_to_their_individual_watches_offline(self):
        searches, singles = legacy_bookmarks()
        entries = parse_bookmarks_html(bookmark_html([*searches, *singles]))
        pages = [snapshot([hit(f"{index}-{number}", artist=artist)
                           for number, artist in enumerate(invaluable_search_artists(entry.url))], entry=entry)
                 for index, entry in enumerate(searches)]
        with patch("requests.sessions.Session.request", side_effect=AssertionError("Offline import")):
            result = self.run_import(bundle(pages), entries)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.metrics.new_lots, 82)
        self.assertEqual(len(result.lots), 82)
        self.assertEqual({lot.last_seen_at for lot in result.lots}, {OLD.isoformat()})
        self.assertTrue(all(lot.artist == lot.artist_watchlist_name for lot in result.lots))
        for entry in entries:
            if entry.source == "Invaluable":
                self.assertTrue(all(lot.artist == invaluable_search_artists(entry.url)[0]
                                    for lot in self.cache.lots_for_watch_url(entry.url)))
        brainwash_broad = next(entry for entry in entries if entry.artist == "Mr Brainwash"
                              and "Fine Art" not in dict(parse_qsl(urlsplit(entry.url).query)))
        self.assertEqual(self.cache.lots_for_watch_url(brainwash_broad.url), [])
        again = self.run_import(bundle(pages), entries)
        self.assertEqual(again.metrics.unchanged_lots, 82)
        self.assertEqual(again.metrics.new_lots, 0)

    def test_selected_subset_never_imports_unselected_artists_or_uses_bulk_label(self):
        entry = bulk_entry(CALDER.artist, WARHOL.artist, "New Artist")
        page = snapshot([hit("a"), hit("b", artist=WARHOL.artist), hit("c", artist="New Artist")], entry=entry)
        result = self.run_import(bundle([page]), [WARHOL])
        self.assertEqual(result.errors, [])
        self.assertEqual([(lot.source_lot_id, lot.artist_watchlist_name) for lot in result.lots], [("b", WARHOL.artist)])
        self.assertIsNone(self.cache.get("invaluable:a"))
        self.assertIsNone(self.cache.get("invaluable:c"))
        self.assertEqual(len(self.cache.lots_for_watch_url(WARHOL.url)), 1)

    def test_original_67_artist_folder_only_accepts_its_66_matching_bulk_scopes(self):
        searches, singles = legacy_bookmarks()
        original = parse_bookmarks_html(bookmark_html(singles))
        original_artists = {entry.artist for entry in original if entry.source == "Invaluable"}
        pages = [snapshot([hit(f"{index}-{number}", artist=artist)
                           for number, artist in enumerate(invaluable_search_artists(entry.url))], entry=entry)
                 for index, entry in enumerate(searches)]
        result = self.run_import(bundle(pages), original)
        self.assertEqual(result.errors, [])
        self.assertEqual({lot.artist for lot in result.lots}, original_artists - {"Mr Brainwash"})
        self.assertEqual(result.metrics.new_lots, 66)

    def test_direct_bulk_entries_expand_with_every_nonartist_filter_preserved(self):
        entry = bulk_entry(CALDER.artist, WARHOL.artist)
        entry = replace(entry, url=entry.url + "&auctionType=timed&dateType=Custom&dateTimeUTCUnix%5Bmax%5D=1")
        expanded = expand_invaluable_bulk_entries([entry])
        filters = lambda url: {(key, value) for key, value in parse_qsl(urlsplit(url).query) if key != "artistName"}
        self.assertEqual({item.artist for item in expanded}, {CALDER.artist, WARHOL.artist})
        self.assertTrue(all(filters(item.url) == filters(entry.url) for item in expanded))
        result = self.run_import(bundle([snapshot([hit(), hit("2", artist=WARHOL.artist)], entry=entry)]), [entry])
        self.assertEqual(result.errors, [])
        self.assertEqual(result.metrics.new_lots, 2)
        self.assertEqual(self.cache.lots_for_watch_url(entry.url), [])

    def test_missing_or_foreign_artist_rejects_whole_page_before_writes(self):
        entry = bulk_entry(CALDER.artist, WARHOL.artist)
        for artist in (None, "", "Unknown", "Alexander Calder, Andy Warhol"):
            with self.subTest(artist=artist):
                page = snapshot([hit(), hit("bad", artist=artist)], entry=entry)
                result = self.run_import(bundle([page]), [CALDER, WARHOL])
                self.assertTrue(result.errors)
                self.assertEqual(result.lots, [])
                self.assertEqual(result.metrics.new_lots, 0)
        self.assertEqual(self.cache.connection.execute("SELECT COUNT(*) FROM lots").fetchone()[0], 0)

    def test_bulk_category_query_and_other_membership_filters_still_match_strictly(self):
        entry = bulk_entry(CALDER.artist, WARHOL.artist)
        for url in (entry.url.replace("Prints", "Sculpture"), entry.url.replace("fine+art", "other"),
                    entry.url + "&auctionType=timed"):
            with self.subTest(url=url):
                result = self.run_import(bundle([snapshot([hit()], entry=replace(entry, url=url))]), [CALDER, WARHOL])
                self.assertIn("filters do not match", " ".join(result.errors))
                self.assertEqual(result.metrics.new_lots, 0)

    def test_page_identity_includes_whole_artist_set_and_order_does_not_matter(self):
        ab = bulk_entry(CALDER.artist, WARHOL.artist)
        ac = bulk_entry(CALDER.artist, "New Artist")
        pages = [snapshot([hit("b", artist=WARHOL.artist)], entry=ab), snapshot([hit("a")], entry=ac)]
        result = self.run_import(bundle(pages), [CALDER, WARHOL])
        self.assertEqual(result.errors, [])
        self.assertEqual({lot.source_lot_id for lot in result.lots}, {"a", "b"})
        reversed_page = snapshot([hit("b", artist=WARHOL.artist, currentBid=300)],
                                 entry=bulk_entry(WARHOL.artist, CALDER.artist), captured=OLD + timedelta(hours=1))
        again = self.run_import(bundle([pages[0], reversed_page]), [CALDER, WARHOL])
        self.assertEqual(again.errors, [])
        self.assertEqual(next(lot.current_bid for lot in again.lots if lot.source_lot_id == "b"), 300)
        tied = deepcopy(reversed_page)
        tied["results"][0]["hits"][0]["currentBid"] = 400
        conflict = self.run_import(bundle([reversed_page, tied]), [CALDER, WARHOL])
        self.assertIn("contradictory captures", " ".join(conflict.errors))
        self.assertEqual(self.cache.get("invaluable:b").current_bid, 300)

    def test_cross_page_artist_conflict_does_not_reassign_existing_lot(self):
        self.run_import(bundle([snapshot()]), [CALDER])
        before = self.cache.get("invaluable:1").to_dict()
        entry = bulk_entry(CALDER.artist, WARHOL.artist)
        pages = [snapshot([hit()], entry=entry, total=2, size=1),
                 snapshot([hit(artist=WARHOL.artist)], entry=entry, page=1, total=2, size=1)]
        result = self.run_import(bundle(pages), [CALDER, WARHOL])
        self.assertIn("conflicting snapshots", " ".join(result.errors))
        self.assertEqual(self.cache.get("invaluable:1").to_dict(), before)
        self.assertEqual(self.cache.lots_for_watch_url(WARHOL.url), [])

    def test_legacy_bulk_stays_rejected_and_legacy_single_stays_supported(self):
        entry = bulk_entry(CALDER.artist, WARHOL.artist)
        rejected = self.run_import(snapshot([hit()], entry=entry), [CALDER, WARHOL])
        self.assertTrue(rejected.errors)
        self.assertEqual(rejected.lots, [])
        accepted = self.run_import(snapshot([hit(when="2026-10-22T12:00:00Z")]), [CALDER])
        self.assertEqual(accepted.errors, [])
        self.assertEqual(accepted.metrics.new_lots, 1)

    def test_cli_preview_expands_bulk_bookmarks_without_creating_real_cache(self):
        entry = bulk_entry(CALDER.artist, WARHOL.artist)
        bookmarks = Path(self.directory.name) / "bookmarks.html"
        bookmarks.write_text(f'<DL><DT><A HREF="{entry.url}">BULK</A></DL>', encoding="utf-8")
        entries, _ = load_bookmark_source(bookmarks)
        path = Path(self.directory.name) / "capture.json"
        path.write_text(json.dumps(bundle([snapshot([hit(), hit("2", artist=WARHOL.artist)], entry=entry)])), encoding="utf-8")
        target = Path(self.directory.name) / "untouched.sqlite3"
        original = import_saved_invaluable_pages
        with patch.object(cli, "import_saved_invaluable_pages", side_effect=lambda *args, **kwargs: original(*args, now=NOW, **kwargs)):
            result = cli.preview_capture([path], entries, target)
        self.assertEqual(result.errors, [])
        self.assertEqual(len(cli.observed_lots(result)), 2)
        self.assertFalse(target.exists())
