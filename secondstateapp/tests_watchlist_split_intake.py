"""The four current bookmark searches supersede archived bulk selections."""

from dataclasses import replace
from html import escape
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from urllib.parse import parse_qsl, urlencode, urlsplit

from catalogapp.bookmark_watchlist import (
    BookmarkEntry, INVALUABLE_INTAKE_BULK_TITLES, canonicalize_bookmark_url,
    invaluable_search_artists, parse_bookmarks_html, parse_netscape_bookmarks,
    select_invaluable_intake_entries,
)
from catalogapp.watchlist_adapters import InvaluableAdapter
from catalogapp.watchlist_bookmark_source import load_bookmark_source
from catalogapp.watchlist_cache import WatchlistCache
from catalogapp.watchlist_invaluable_pages import import_saved_invaluable_pages
from secondstateapp.tests_watchlist_capture_bundle import NOW, bundle, hit, snapshot


ROOT = Path(__file__).resolve().parents[1]
MEDIA = ("Prints", "Drawings", "Mixed Media")


def search(title, *artists, media=MEDIA, folder="Current"):
    query = [("artistName", artist) for artist in artists]
    query.extend(("Fine Art", medium) for medium in media)
    query.extend((("query", "fine art"), ("keyword", "fine art"), ("sort", "endDateAsc")))
    return BookmarkEntry(folder_path=(folder,), title=title,
                         url="https://www.invaluable.com/search?" + urlencode(query))


def html(entries):
    return "<DL>" + "".join(
        f'<DT><H3>{escape(entry.folder)}</H3><DL><DT><A HREF="{escape(entry.url, quote=True)}">'
        f'{escape(entry.title)}</A></DL>' for entry in entries
    ) + "</DL>"


class SplitIntakeSelectionTests(TestCase):
    def setUp(self):
        self.split = [search(title, f"Artist {index}A", f"Artist {index}B", folder=f"Group {index}")
                      for index, title in enumerate(INVALUABLE_INTAKE_BULK_TITLES)]

    def test_complete_split_excludes_old_bulks_but_preserves_singles_and_research(self):
        old = search("BULK 1", "Archived A", "Archived B", folder="OLD")
        single = search("Single", "Individual Artist", media=("Prints",))
        research = BookmarkEntry(folder_path=("ARTPRICE",), title="Research", url="https://www.artprice.com/artist/1/example")
        selected = select_invaluable_intake_entries([old, single, *self.split, research])
        self.assertEqual(selected, [single, *self.split, research])
        expanded = parse_bookmarks_html(html([old, single, *self.split, research]))
        self.assertEqual({entry.artist for entry in expanded},
                         {"Individual Artist", *(f"Artist {index}{suffix}" for index in range(4) for suffix in "AB")})
        self.assertTrue(all(len(invaluable_search_artists(entry.url)) == 1 for entry in expanded))

    def test_partial_invalid_and_conflicting_named_sets_fail_without_legacy_fallback(self):
        old = search("BULK 1", "Archived A", "Archived B")
        with self.assertRaisesRegex(ValueError, "missing BULK-2B"):
            parse_bookmarks_html(html([*self.split[:-1], old]))
        with self.assertRaisesRegex(ValueError, "BULK-1A must contain"):
            parse_bookmarks_html(html([replace(self.split[0], url="https://www.invaluable.com/search?artistName=One"), *self.split[1:]]))
        with self.assertRaisesRegex(ValueError, "conflicting searches named BULK-1A"):
            parse_bookmarks_html(html([*self.split, search("BULK-1A", "Different", "Artists")]))
        self.assertEqual(len(parse_bookmarks_html(html([*self.split, self.split[0]]))), 8)

    def test_folder_choice_happens_after_complete_set_validation(self):
        entries = parse_bookmarks_html(html(self.split), selected_folders=["Group 0"])
        self.assertEqual({entry.artist for entry in entries}, {"Artist 0A", "Artist 0B"})

    def test_all_invalid_reserved_urls_cannot_fall_back_to_valid_archived_bulk(self):
        old = search("BULK 1", "Archived A", "Archived B")
        for invalid in ("not-a-url", "https://example.com/search?artistName=A&artistName=B",
                        "https://user:private@www.invaluable.com/search?artistName=A&artistName=B"):
            entries = [*(replace(entry, url=invalid) for entry in self.split), old]
            with self.subTest(url=invalid):
                with self.assertRaisesRegex(ValueError, "BULK-1A must contain"):
                    parse_bookmarks_html(html(entries))
                with TemporaryDirectory() as directory:
                    path = Path(directory) / "bookmarks.html"
                    path.write_text(html(entries), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "BULK-1A must contain"):
                        load_bookmark_source(path)
                    browser = Path(directory) / "Bookmarks"
                    browser.write_text(json.dumps({"roots": {"bookmark_bar": {
                        "type": "folder", "name": "Bookmarks bar", "children": [
                            {"type": "url", "name": entry.title, "url": entry.url} for entry in entries
                        ],
                    }}}), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "BULK-1A must contain"):
                        load_bookmark_source(browser)

    def test_legacy_two_bulk_and_single_exports_keep_existing_behavior(self):
        legacy = [search("BULK 1", "Artist A", "Artist B", media=("Prints",)),
                  search("BULK 2", "Artist C", "Artist D", media=("Prints",))]
        self.assertEqual(select_invaluable_intake_entries(legacy), legacy)
        self.assertEqual({entry.artist for entry in parse_bookmarks_html(html(legacy))},
                         {"Artist A", "Artist B", "Artist C", "Artist D"})
        single = search("Single", "Artist E", media=("Prints",))
        self.assertEqual([entry.artist for entry in parse_bookmarks_html(html([single]))], ["Artist E"])

    def test_actual_export_retains_all_original_artists_and_22_additions_in_four_disjoint_searches(self):
        raw = parse_netscape_bookmarks((ROOT / "docs/artist-links.html").read_text(encoding="utf-8-sig"))
        selected = select_invaluable_intake_entries(raw)
        bulks = [entry for entry in selected if len(invaluable_search_artists(entry.url)) > 1]
        self.assertEqual([entry.title for entry in bulks], list(INVALUABLE_INTAKE_BULK_TITLES))
        self.assertEqual([len(invaluable_search_artists(entry.url)) for entry in bulks], [22, 23, 33, 26])
        artists = {artist for entry in bulks for artist in invaluable_search_artists(entry.url)}
        self.assertEqual(len(artists), 104)
        old = [entry for entry in raw if entry.title in {"BULK 1", "BULK 2"}
               and "OLD" in entry.folder_path]
        self.assertEqual([entry.title for entry in old], ["BULK 1", "BULK 2"])
        old_artists = {artist for entry in old if len(invaluable_search_artists(entry.url)) > 1
                       for artist in invaluable_search_artists(entry.url)}
        self.assertEqual(len(old_artists), 82)
        self.assertTrue(old_artists <= artists)
        self.assertEqual(len(artists - old_artists), 22)
        for entry in bulks:
            filters = parse_qsl(urlsplit(canonicalize_bookmark_url(entry.url)).query)
            self.assertEqual({value for key, value in filters if key == "Fine Art"}, set(MEDIA))
        entries, _ = load_bookmark_source(ROOT / "docs/artist-links.html")
        self.assertEqual({entry.artist for entry in entries if entry.source == "Invaluable"}, artists)


class SplitIntakeCategoryTests(TestCase):
    def test_catalog_request_groups_same_category_choices_as_or_and_preserves_other_groups(self):
        entry = search("Multi media", "Artist A", media=(*MEDIA, "Prints"))
        url = canonicalize_bookmark_url(entry.url + "&Jewelry=Rings")
        facets = InvaluableAdapter()._catalog_request_payload(url)["requests"][0]["params"]["facetFilters"]
        self.assertEqual(facets, [["artistName:Artist A"],
                                 ["Fine Art:Drawings", "Fine Art:Mixed Media", "Fine Art:Prints"],
                                 ["Jewelry:Rings"]])

    def test_mixed_media_capture_routes_once_per_lot_and_preserves_exact_scope(self):
        entry = search("Bulk", "Artist A", "Artist B")
        narrow = search("Prints only", "Artist A", media=("Prints",))
        entries = parse_bookmarks_html(html([entry, narrow]))
        hits = [hit(str(index), artist="Artist A", categoryName=medium) for index, medium in enumerate(MEDIA)]
        hits.append(hit("excluded", artist="Artist A", categoryName="Paintings"))
        with TemporaryDirectory() as directory, WatchlistCache(":memory:") as cache:
            path = Path(directory) / "capture.json"
            path.write_text(json.dumps(bundle([snapshot(hits, entry=entry)])), encoding="utf-8")
            with patch("requests.sessions.Session.request", side_effect=AssertionError("Offline import")):
                result = import_saved_invaluable_pages([path], entries, cache, now=NOW)
            self.assertEqual(result.errors, [])
            self.assertEqual(result.metrics.new_lots, 3)
            self.assertEqual(len(result.lots), 3)
            self.assertEqual(cache.lots_for_watch_url(canonicalize_bookmark_url(narrow.url)), [])
            self.assertIsNone(cache.get("invaluable:excluded"))
            # A print-only saved watch cannot claim coverage of this broader capture.
            with WatchlistCache(":memory:") as narrow_cache:
                rejected = import_saved_invaluable_pages([path], parse_bookmarks_html(html([narrow])), narrow_cache, now=NOW)
                self.assertIn("filters do not match", " ".join(rejected.errors))
                self.assertEqual(rejected.metrics.new_lots, 0)
