"""Offline checks for snapshots captured in the user's ordinary browser."""

from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import tkinter as tk
from tkinter import ttk
from unittest import TestCase
from unittest.mock import Mock, patch

from catalogapp.bookmark_watchlist import BookmarkEntry
from catalogapp.watchlist_browser_helper import SNAPSHOT_HELPER, recovery_searches, show_browser_helper
from catalogapp.watchlist_coverage import WatchCoverage
from secondstateapp import tests_studio_watchlist as studio_tests


def artist(name):
    return BookmarkEntry(
        folder_path=("ARTISTS INVALUABLE",), title=name, artist=name, source="Invaluable",
        url=f"https://www.invaluable.com/search?artistName={name}",
    )


class RecoverySearchSelectionTests(TestCase):
    def test_selected_pending_searches_precede_completed_searches(self):
        entries = [artist(name) for name in ("Calder", "Zuniga", "Corinth", "Matisse", "Excluded")]
        coverage = [
            WatchCoverage("Calder", "Invaluable", entries[0].url, state="verified"),
            WatchCoverage("Zuniga", "Invaluable", entries[1].url, state="blocked"),
            WatchCoverage("Matisse", "Invaluable", entries[3].url, state="empty"),
        ]

        selected = recovery_searches(entries, {"CALDER", "Zuniga", "Corinth", "Matisse"}, coverage)

        self.assertEqual([entry.artist for entry in selected], ["Corinth", "Zuniga", "Calder", "Matisse"])

    def test_only_safe_invaluable_artist_search_urls_are_offered(self):
        valid = artist("Calder")
        unsafe_urls = (
            "http://www.invaluable.com/search?artistName=Calder",
            "https://www.invaluable.com.evil.example/search?artistName=Calder",
            "https://user:password@www.invaluable.com/search?artistName=Calder",
            "https://www.invaluable.com:444/search?artistName=Calder",
            "https://www.invaluable.com/auction-lot/calder-1-c-abc",
            "https://example.com/search?artistName=Calder",
            "javascript:alert(1)",
            "https://[invalid/search?artistName=Calder",
            valid.url + "\n",
            "https://www.invaluable.com/search?artistName=Calder\\other",
        )
        entries = [replace(valid, url=url) for url in unsafe_urls]
        entries.extend([replace(valid, source="Heritage"), valid])

        self.assertEqual(recovery_searches(entries, {"Calder"}, []), [valid])


class RegularBrowserControllerTests(TestCase):
    setUp = studio_tests.StudioWatchlistControllerTests.setUp
    immediate_thread = staticmethod(studio_tests.StudioWatchlistControllerTests.immediate_thread)

    def test_helper_rereads_bookmarks_preserves_exclusions_and_defers_import(self):
        self.panel.load_bookmarks(self.path)
        self.panel.selected_artists.remove("Matisse")
        calder = next(entry for entry in self.panel.active_entries if entry.artist == "Calder")
        self.panel.artist_coverage = [WatchCoverage("Calder", "Invaluable", calder.url, state="verified")]
        self.path.write_text(studio_tests.bookmarks("Calder", "Matisse", "Zuniga"), encoding="utf-8")
        self.panel.import_saved_invaluable_pages = Mock()

        with patch("catalogapp.watchlist_ui.show_browser_helper") as helper:
            self.panel.use_regular_browser()

        self.assertEqual(self.panel.selected_artists, {"Calder", "Zuniga"})
        helper.assert_called_once()
        parent, entries = helper.call_args.args
        self.assertIs(parent, self.panel)
        self.assertEqual([entry.artist for entry in entries], ["Zuniga", "Calder"])
        self.assertIs(helper.call_args.kwargs["import_snapshots"], self.panel.import_saved_invaluable_pages)
        self.panel.import_saved_invaluable_pages.assert_not_called()
        self.panel.calendar_syncer.assert_not_called()
        self.service.assert_not_called()
        self.browser.assert_not_called()
        self.public_browser.assert_not_called()

    def test_no_selected_searches_warns_without_opening_or_uploading(self):
        self.panel.load_bookmarks(self.path)
        self.panel.selected_artists.clear()

        with patch("catalogapp.watchlist_ui.show_browser_helper") as helper:
            self.panel.use_regular_browser()

        helper.assert_not_called()
        self.assertEqual(self.warning.call_args.args[0], "No Invaluable searches")
        self.service.assert_not_called()
        self.panel.calendar_syncer.assert_not_called()

    def test_busy_or_unreadable_source_does_not_open_helper(self):
        for busy in (True, False):
            with self.subTest(busy=busy):
                self.panel._busy = busy
                with (
                    patch.object(self.panel, "_load_watchlist_for_update", return_value=False) as load,
                    patch("catalogapp.watchlist_ui.show_browser_helper") as helper,
                ):
                    self.panel.use_regular_browser()
                helper.assert_not_called()
                if busy:
                    load.assert_not_called()
                else:
                    load.assert_called_once()
        self.service.assert_not_called()
        self.panel.calendar_syncer.assert_not_called()


class RegularBrowserHelperDialogTests(TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display is unavailable: {exc}")
        self.addCleanup(self.root.destroy)
        self.root.withdraw()
        self.entries = [artist("Calder"), artist("Matisse")]
        self.import_snapshots = Mock()
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.network = stack.enter_context(patch("requests.sessions.Session.request"))
        self.open_browser = stack.enter_context(patch(
            "catalogapp.watchlist_browser_helper.webbrowser.open_new_tab", return_value=True,
        ))
        # Exercise real Tk commands while leaving the user's clipboard intact.
        self.clipboard_clear = stack.enter_context(patch.object(self.root, "clipboard_clear"))
        self.clipboard_append = stack.enter_context(patch.object(self.root, "clipboard_append"))
        self.dialog = show_browser_helper(self.root, self.entries, import_snapshots=self.import_snapshots)
        self.dialog.withdraw()

    def descendants(self, widget):
        for child in widget.winfo_children():
            yield child
            yield from self.descendants(child)

    def button(self, text):
        return next(widget for widget in self.descendants(self.dialog)
                    if isinstance(widget, ttk.Button) and widget.cget("text") == text)

    def test_copy_helper_uses_exact_bundled_script_without_running_or_importing(self):
        self.button("Copy snapshot helper").invoke()

        self.clipboard_clear.assert_called_once_with()
        self.clipboard_append.assert_called_once_with(SNAPSHOT_HELPER.read_text(encoding="utf-8"))
        self.open_browser.assert_not_called()
        self.network.assert_not_called()
        self.import_snapshots.assert_not_called()

    def test_open_and_copy_artist_use_current_selection_without_reading_browser(self):
        choices = next(widget for widget in self.descendants(self.dialog) if isinstance(widget, ttk.Combobox))
        choices.current(1)

        self.button("Open artist search").invoke()
        self.button("Copy artist link").invoke()

        self.open_browser.assert_called_once_with(self.entries[1].url)
        self.clipboard_append.assert_called_once_with(self.entries[1].url)
        self.network.assert_not_called()
        self.import_snapshots.assert_not_called()

    def test_import_closes_dialog_before_delegating_existing_import(self):
        self.import_snapshots.side_effect = lambda: self.assertFalse(self.dialog.winfo_exists())

        self.button("Import snapshots and update Calendar").invoke()

        self.import_snapshots.assert_called_once_with()
        self.assertFalse(self.dialog.winfo_exists())
        self.network.assert_not_called()
        self.open_browser.assert_not_called()

    def test_missing_helper_reports_clean_error_and_preserves_import_option(self):
        with (
            TemporaryDirectory() as directory,
            patch("catalogapp.watchlist_browser_helper.SNAPSHOT_HELPER", Path(directory) / "missing.js"),
            patch("catalogapp.watchlist_browser_helper.messagebox.showerror") as error,
        ):
            self.button("Copy snapshot helper").invoke()

        error.assert_called_once()
        self.assertEqual(error.call_args.args[0], "Snapshot helper unavailable")
        self.assertIs(error.call_args.kwargs["parent"], self.dialog)
        self.assertTrue(self.dialog.winfo_exists())
        self.clipboard_clear.assert_not_called()
        self.clipboard_append.assert_not_called()
        self.network.assert_not_called()
        self.import_snapshots.assert_not_called()

    def test_close_leaves_browser_and_calendar_untouched(self):
        self.button("Close").invoke()

        self.assertFalse(self.dialog.winfo_exists())
        self.import_snapshots.assert_not_called()
        self.open_browser.assert_not_called()
        self.network.assert_not_called()
