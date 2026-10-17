from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from catalogapp.bookmark_watchlist import (
    artist_source_counts,
    folder_counts,
    parse_bookmarks_html,
)
from catalogapp.watchlist_models import NormalizedLot
from catalogapp.watchlist_service import WatchlistMetrics, WatchlistResult
from catalogapp.watchlist_ui import ArtistWatchlistPanel


SALE_URL = "https://fineart.ha.com/c/search/results.zx?dept=1544&mode=live&auction_name=8280"


def sale_bookmarks(*links):
    return '<DL><DT><H3>HERITAGE</H3><DL>' + "".join(
        f'<DT><A HREF="{url}">{title}</A>' for title, url in links
    ) + "</DL></DL>"


class HeritageBookmarkTests(TestCase):
    def test_sale_is_selectable_without_becoming_an_artist(self):
        entries = parse_bookmarks_html(sale_bookmarks(("10-22 SALE", SALE_URL)))

        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry.source, "Heritage")
        self.assertTrue(entry.is_sale)
        self.assertEqual(entry.artist, "")
        self.assertEqual(entry.watch_label, "10-22 SALE")
        self.assertEqual(artist_source_counts(entries), {"10-22 SALE": {"Heritage": 1}})
        self.assertEqual(folder_counts(entries), {"HERITAGE": 1})

    def test_sale_title_is_preserved_and_duplicate_urls_are_removed(self):
        title = "2026 Prints & Multiples - Heritage Auctions"
        entries = parse_bookmarks_html(sale_bookmarks(
            (title, SALE_URL),
            ("Duplicate", SALE_URL + "&utm_source=email#results"),
        ))

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].watch_label, title)
        self.assertIn("auction_name=8280", entries[0].url)
        self.assertIn("dept=1544", entries[0].url)
        self.assertIn("mode=live", entries[0].url)

    def test_heritage_auction_home_link_is_a_sale(self):
        entry = parse_bookmarks_html(sale_bookmarks(
            ("Prints", "https://fineart.ha.com/c/auction-home.zx?saleNo=8280"),
        ))[0]

        self.assertTrue(entry.is_sale)
        self.assertEqual(entry.artist, "")
        self.assertEqual(entry.watch_label, "Prints")

    def test_spoofed_heritage_hosts_and_unselected_folders_are_rejected(self):
        html = sale_bookmarks(
            ("Valid", SALE_URL),
            ("Spoofed", "https://fineart.ha.com.evil.example/c/search/results.zx?auction_name=8280"),
            ("Suffix", "https://fakeha.com/c/search/results.zx?auction_name=8280"),
        )
        self.assertEqual(len(parse_bookmarks_html(html, selected_folders=["HERITAGE"])), 1)
        self.assertEqual(parse_bookmarks_html(html, selected_folders=["ARTISTS INVALUABLE"]), [])

    def test_artist_search_retains_artist_identity(self):
        entry = parse_bookmarks_html(sale_bookmarks(
            ("Search", "https://fineart.ha.com/c/search/results.zx?keyword=Andy+Warhol"),
        ))[0]

        self.assertFalse(entry.is_sale)
        self.assertEqual(entry.artist, "Andy Warhol")
        self.assertEqual(entry.watch_label, "Andy Warhol")


class SavedHeritageImportUiTests(TestCase):
    def test_import_preserves_other_sources_and_replaces_matching_lots_before_sync(self):
        entry = parse_bookmarks_html(sale_bookmarks(("10-22 SALE", SALE_URL)))[0]
        fields = {"artist": "Andy Warhol", "artist_watchlist_name": "Andy Warhol", "title": "Print"}
        other = NormalizedLot(source="Invaluable", source_lot_id="existing", **fields)
        previous = NormalizedLot(source="Heritage", source_lot_id="8280-65001", current_bid=100, **fields)
        updated = NormalizedLot(source="Heritage", source_lot_id="8280-65001", current_bid=200, **fields)
        imported = WatchlistResult([updated], WatchlistMetrics(new_lots=1))
        panel = object.__new__(ArtistWatchlistPanel)
        panel.worker = None
        panel.active_entries = [entry]
        panel.selected_artists = {entry.watch_label, "Andy Warhol"}
        panel.current_lots = [other, previous]
        panel.fallback_lot_keys = set()
        panel.horizon_var = Mock(get=lambda: 30)
        panel.new_changed_var = Mock(get=lambda: False)
        panel.refresh_button = Mock()
        panel.import_saved_button = Mock()
        panel._set_status = Mock()
        panel._sync_and_finish_result = Mock()

        with TemporaryDirectory() as directory:
            panel._cache_path = Path(directory) / "cache.sqlite3"
            with (
                patch("catalogapp.watchlist_ui.local_watchlist_directory", return_value=Path(directory)),
                patch("catalogapp.watchlist_ui.filedialog.askopenfilenames", return_value=("saved.html",)),
                patch("catalogapp.watchlist_ui.import_saved_heritage_pages", return_value=imported) as importer,
                patch("catalogapp.watchlist_ui.threading.Thread", side_effect=lambda target, **kwargs: SimpleNamespace(start=target)),
            ):
                panel.import_saved_heritage_pages()

        importer.assert_called_once()
        self.assertEqual(importer.call_args.args[:2], (("saved.html",), entry))
        self.assertEqual(importer.call_args.kwargs, {"horizon_days": 7, "new_changed_only": False})
        panel._sync_and_finish_result.assert_called_once_with(imported, preserve_source_errors=True)
        self.assertEqual({lot.cache_key for lot in imported.lots}, {other.cache_key, updated.cache_key})
        self.assertEqual(next(lot for lot in imported.lots if lot.source == "Heritage").current_bid, 200)

    def test_import_requires_a_single_selected_heritage_sale(self):
        panel = object.__new__(ArtistWatchlistPanel)
        panel.worker = None
        panel.active_entries = []
        panel.selected_artists = set()

        with (
            patch("catalogapp.watchlist_ui.messagebox.showwarning") as warning,
            patch("catalogapp.watchlist_ui.filedialog.askopenfilenames") as dialog,
        ):
            panel.import_saved_heritage_pages()

        warning.assert_called_once()
        dialog.assert_not_called()
