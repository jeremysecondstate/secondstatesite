"""Scan bookmarks locally, compare Calendar counts, and select missing artists."""

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

import tkinter as tk

from catalogapp.watchlist_artist_inventory import ArtistInventoryRow
from catalogapp.watchlist_registry import load_watchlist
from secondstateapp import tests_studio_watchlist as studio_tests


class StudioArtistScanTests(TestCase):
    setUp = studio_tests.StudioWatchlistControllerTests.setUp
    immediate_thread = staticmethod(studio_tests.StudioWatchlistControllerTests.immediate_thread)

    def prepare_scan(self):
        self.panel._registry_path = self.directory / "watchlist.json"
        self.panel.load_bookmarks(self.path)
        self.panel._show_lot_view = Mock()
        self.panel.scan_artists_button = Mock()
        self.panel.scan_html_button = Mock()
        self.panel.artist_view_button = Mock()
        self.extra = self.directory / "additional-artists.html"
        self.extra.write_text(studio_tests.bookmarks("Calder", "Matisse", "Will Barnet"), encoding="utf-8")

    def remember_extra(self):
        import json
        settings = self.panel._read_settings()
        settings["scan_html_path"] = str(self.extra)
        self.panel._settings_path.write_text(json.dumps(settings), encoding="utf-8")

    def test_scan_merges_new_artist_and_reads_counts_without_fetching_or_uploading_lots(self):
        self.prepare_scan()
        self.remember_extra()
        with patch("catalogapp.watchlist_ui.fetch_calendar_inventory", return_value=[]) as inventory:
            self.panel.scan_artists()
        self.assertEqual({entry.watch_label for entry in self.panel.active_entries}, {"Calder", "Matisse", "Will Barnet"})
        self.assertEqual(self.panel._calendar_inventory, [])
        inventory.assert_called_once_with(base_url="https://calendar.example", api_key="offline-test-key")
        self.service.assert_not_called()
        self.panel.calendar_syncer.assert_not_called()
        self.public_browser.assert_not_called()
        self.panel._show_lot_view.assert_called_once_with("artists")
        self.assertFalse(self.panel._busy)

    def test_supplement_keeps_connected_source_existing_exclusions_and_registry(self):
        self.prepare_scan()
        self.panel.selected_artists.remove("Matisse")
        source_before = self.panel.bookmark_path_var.get()
        self.assertTrue(self.panel._merge_scan_html(str(self.extra)))
        self.assertEqual(self.panel.bookmark_path_var.get(), source_before)
        self.assertEqual(self.panel.selected_artists, {"Calder", "Will Barnet"})
        self.assertFalse(self.panel.folder_vars["OTHER"].get())
        saved, _ = load_watchlist(self.panel._registry_path)
        self.assertIn("Will Barnet", {entry.watch_label for entry in saved})
        self.service.assert_not_called()

    def test_scan_does_not_reenable_intentionally_deselected_folders(self):
        self.prepare_scan()
        for variable in self.panel.folder_vars.values():
            variable.set(False)
        self.panel._update_active_entries()
        self.panel._merge_scan_html(str(self.extra))
        self.assertFalse(any(variable.get() for variable in self.panel.folder_vars.values()))
        self.assertEqual(self.panel.active_entries, [])
        self.assertEqual(self.panel.selected_artists, set())

    def test_saved_supplement_survives_reloading_original_source_and_missing_extra_file(self):
        self.prepare_scan()
        self.panel._merge_scan_html(str(self.extra))
        self.remember_extra()
        self.extra.unlink()
        self.panel.all_entries = []
        self.panel.active_entries = []
        with patch("catalogapp.watchlist_ui.fetch_calendar_inventory", return_value=[]):
            self.panel.scan_artists()
        self.assertIn("Will Barnet", {entry.watch_label for entry in self.panel.active_entries})
        self.assertIn("saved artists were retained", self.panel.sync_status_var.get())
        self.panel.calendar_syncer.assert_not_called()

    def test_failed_calendar_read_is_unknown_and_disables_selected_sync_until_rescanned(self):
        self.prepare_scan()
        self.panel._calendar_inventory = []
        self.panel.sync_selected_button = Mock()
        self.panel._selected_sync_artist = "Calder"
        with patch("catalogapp.watchlist_ui.fetch_calendar_inventory", side_effect=RuntimeError("Inventory unavailable")):
            self.panel.scan_artists()
        self.assertIsNone(self.panel._calendar_inventory)
        self.assertIn("Calendar comparison incomplete", self.panel.sync_status_var.get())
        self.assertIn("Sync selected requires a successful Calendar comparison", self.panel.sync_status_var.get())
        self.assertFalse(self.panel._busy)
        self.panel.scan_artists_button.configure.assert_called_with(state=tk.NORMAL)
        self.panel.sync_selected_button.configure.assert_called_with(state=tk.DISABLED)
        self.panel.sync_selected()
        self.service.assert_not_called()
        self.panel.calendar_syncer.assert_not_called()

    def test_scan_stops_while_another_operation_is_running(self):
        self.prepare_scan()
        self.panel._busy = True
        with patch("catalogapp.watchlist_ui.fetch_calendar_inventory") as inventory:
            self.panel.scan_artists()
        inventory.assert_not_called()
        self.panel._show_lot_view.assert_not_called()

    def test_choosing_extra_html_remembers_it_without_switching_source(self):
        self.prepare_scan()
        source_before = self.panel.bookmark_path_var.get()
        with patch("catalogapp.watchlist_ui.filedialog.askopenfilename", return_value=str(self.extra)), \
                patch("catalogapp.watchlist_ui.fetch_calendar_inventory", return_value=[]):
            self.panel.choose_scan_html()
        self.assertEqual(self.panel._read_settings()["scan_html_path"], str(self.extra.resolve()))
        self.assertEqual(self.panel.bookmark_path_var.get(), source_before)
        self.assertIn("Will Barnet", self.panel.selected_artists)

    def test_lot_sync_requires_sync_column_and_passes_watchlist_artist(self):
        self.panel.upcoming_tree = Mock()
        self.panel.upcoming_tree.identify_row.return_value = "lot-0"
        self.panel._lots_by_iid = {"lot-0": self.lot}
        self.panel.sync_artist = Mock()
        event = SimpleNamespace(x=1, y=2, widget=self.panel.upcoming_tree)
        self.panel.upcoming_tree.identify_column.return_value = "#2"
        self.panel._lot_sync_click(event)
        self.panel.sync_artist.assert_not_called()
        self.panel.upcoming_tree.identify_column.return_value = "#3"
        self.panel._lot_sync_click(event)
        self.panel.sync_artist.assert_called_once_with(self.lot.artist_watchlist_name)

    def test_double_click_artwork_column_opens_lot_without_syncing(self):
        self.panel.upcoming_tree = Mock()
        self.panel.upcoming_tree.identify_column.return_value = "#3"
        self.panel.upcoming_tree.selection.return_value = ("lot-0",)
        self.panel._lot_urls = {"lot-0": "https://www.invaluable.com/auction-lot/example"}
        with patch("catalogapp.watchlist_ui.webbrowser.open") as open_url:
            self.panel._open_selected_lot(SimpleNamespace(x=1, widget=self.panel.upcoming_tree))
        open_url.assert_called_once_with("https://www.invaluable.com/auction-lot/example")
        self.service.assert_not_called()
        self.panel.calendar_syncer.assert_not_called()

    def test_inventory_row_sync_requires_action_cell_and_bookmark(self):
        tree = self.panel.artist_inventory_tree = Mock()
        tree.identify_row.return_value = "inventory-0"
        row = ArtistInventoryRow("Will Barnet", "Invaluable", 0, 0, 0, "pending", True)
        self.panel._inventory_rows = {"inventory-0": row}
        self.panel.sync_artist = Mock()
        event = SimpleNamespace(x=1, y=2)
        tree.identify_column.return_value = "#1"
        self.panel._inventory_sync_click(event)
        self.panel.sync_artist.assert_not_called()
        tree.identify_column.return_value = "#6"
        self.panel._inventory_sync_click(event)
        self.panel.sync_artist.assert_called_once_with("Will Barnet")
        self.panel.sync_artist.reset_mock()
        self.panel._inventory_rows["inventory-0"] = ArtistInventoryRow("Will Barnet", "Invaluable", 0, 1, 1, "calendar_only", False)
        self.panel._inventory_sync_click(event)
        self.panel.sync_artist.assert_not_called()

