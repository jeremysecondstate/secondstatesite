"""Desktop connection lifecycle, opt-in persistence, and refresh wiring."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from catalogapp.bookmark_watchlist import BookmarkEntry
from catalogapp.watchlist_service import WatchlistMetrics, WatchlistResult
from catalogapp.watchlist_ui import ArtistWatchlistPanel


class InvaluableConnectionUiTests(TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.panel = ArtistWatchlistPanel.__new__(ArtistWatchlistPanel)
        self.panel._settings_path = self.directory / "settings.json"
        self.panel._cache_path = self.directory / "watchlist.sqlite3"
        self.panel._invaluable_profile_directory = self.directory / "invaluable-browser"
        self.panel.worker = None
        self.panel.service_factory = None
        self.panel.after = lambda _delay, callback: callback()
        self.panel._set_status = Mock()
        self.panel._finish_refresh_error = Mock()
        self.panel._sync_and_finish_result = Mock()
        self.panel.bookmark_path_var = Mock(get=Mock(return_value="bookmarks.html"))
        self.panel.invaluable_session_var = Mock(get=Mock(return_value=True))
        self.panel.invaluable_connection_status_var = Mock()
        self.panel.horizon_var = Mock(get=Mock(return_value=7))
        self.panel.zero_ai_var = Mock(get=Mock(return_value=True))
        self.panel.new_changed_var = Mock(get=Mock(return_value=False))
        for name in ("refresh_button", "stop_button", "import_saved_button", "import_sold_button",
                     "connect_invaluable_button", "invaluable_session_check"):
            setattr(self.panel, name, Mock())
        self.entry = BookmarkEntry(
            folder_path=("ARTISTS INVALUABLE",), title="Alexander Calder", artist="Alexander Calder",
            source="Invaluable", url="https://www.invaluable.com/search?artistName=Alexander+Calder",
        )
        self.panel.active_entries = [self.entry]
        self.panel.selected_artists = {self.entry.watch_label}

    @staticmethod
    def immediate_thread(*, target, **_kwargs):
        worker = Mock()
        worker.is_alive.return_value = False
        worker.start.side_effect = target
        return worker

    def test_settings_preserve_other_preferences_and_remember_opt_in(self):
        self.panel._settings_path.write_text(json.dumps({"other_preference": 3}), encoding="utf-8")
        project = self.directory / "project"
        project.mkdir()
        path = project / "bookmarks.html"
        path.write_text("<DL></DL>", encoding="utf-8")
        self.panel.bookmark_path_var.get.return_value = str(path)
        with patch("catalogapp.watchlist_ui.PROJECT_BOOKMARK_PATH", project / "docs" / "artists.html"):
            self.panel._save_settings_hint()
        self.assertEqual(self.panel._read_settings(), {
            "other_preference": 3, "last_bookmark_path": str(path.resolve()),
            "last_bookmark_path_relative": "bookmarks.html", "invaluable_session_enabled": True,
            "selected_artists": ["Alexander Calder"], "known_artists": ["Alexander Calder"], "horizon_days": 7,
        })
        self.assertEqual(self.panel._remembered_bookmark_path(), path.resolve())

    def test_successful_connection_enables_session_and_starts_refresh(self):
        self.panel.refresh_watchlist = Mock()
        with (
            patch("catalogapp.watchlist_ui.threading.Thread", side_effect=self.immediate_thread),
            patch("catalogapp.watchlist_ui.connect_invaluable", return_value=True) as connect,
        ):
            self.panel.connect_invaluable()
        self.assertEqual(connect.call_args.args[0], self.panel._invaluable_profile_directory)
        self.panel.invaluable_session_var.set.assert_called_once_with(True)
        self.assertTrue(self.panel._read_settings()["invaluable_session_enabled"])
        self.panel.refresh_watchlist.assert_called_once_with()

    def test_cancelled_first_connection_does_not_enable_or_refresh(self):
        self.panel.refresh_watchlist = Mock()
        with (
            patch("catalogapp.watchlist_ui.threading.Thread", side_effect=self.immediate_thread),
            patch("catalogapp.watchlist_ui.connect_invaluable", return_value=False),
        ):
            self.panel.connect_invaluable()
        self.panel.invaluable_session_var.set.assert_not_called()
        self.panel.refresh_watchlist.assert_not_called()
        self.assertFalse(self.panel._settings_path.exists())

    def test_connection_progress_is_visible_next_to_connect_button(self):
        message = "Chrome is open. Complete Invaluable sign-in in that window."
        self.panel._set_invaluable_connection_status(message)
        self.panel.invaluable_connection_status_var.set.assert_called_once_with(message)
        self.panel._set_status.assert_called_once_with(message)

    def test_regular_chrome_uses_selected_profile_without_connecting_or_refreshing(self):
        url = "https://www.invaluable.com/auction-lot/calder-106-c-d8e264e7ed"
        self.panel.agenda_tree = Mock(selection=Mock(return_value=("lot-1",)))
        self.panel._lot_urls = {"lot-1": url}
        self.panel.chrome_profile_choices = {"Work (Profile 4)": "Profile 4"}
        self.panel.chrome_profile_var = Mock(get=Mock(return_value="Work (Profile 4)"))
        self.panel.chrome_open_status_var = Mock()
        self.panel.refresh_watchlist = Mock()
        with patch("catalogapp.watchlist_ui.open_invaluable_in_chrome") as launch:
            self.panel.open_regular_chrome()
        launch.assert_called_once_with(url, profile_directory="Profile 4")
        self.assertEqual(self.panel._read_settings()["invaluable_chrome_profile"], "Profile 4")
        self.panel.invaluable_session_var.set.assert_not_called()
        self.panel.refresh_watchlist.assert_not_called()
        self.assertIn("does not connect", self.panel.chrome_open_status_var.set.call_args.args[0])

    def test_unavailable_regular_profile_does_not_claim_opened_or_change_preference(self):
        self.panel.agenda_tree = Mock(selection=Mock(return_value=()))
        self.panel._lot_urls = {}
        self.panel.chrome_profile_choices = {"Saved profile unavailable": "Profile 4"}
        self.panel.chrome_profile_var = Mock(get=Mock(return_value="Saved profile unavailable"))
        self.panel.chrome_open_status_var = Mock()
        with (
            patch("catalogapp.watchlist_ui.open_invaluable_in_chrome", side_effect=ValueError("Choose an available profile.")),
            patch("catalogapp.watchlist_ui.messagebox.showwarning") as warning,
        ):
            self.panel.open_regular_chrome()
        warning.assert_called_once()
        self.panel.chrome_open_status_var.set.assert_called_once_with("Choose an available profile.")
        self.assertFalse(self.panel._settings_path.exists())

    def test_refresh_reuses_one_browser_and_closes_it_before_sync(self):
        result = WatchlistResult([], WatchlistMetrics())
        with (
            patch("catalogapp.watchlist_ui.threading.Thread", side_effect=self.immediate_thread),
            patch("catalogapp.watchlist_ui.local_watchlist_directory", return_value=self.directory),
            patch("catalogapp.watchlist_ui.InvaluableBrowserFetcher") as browser,
            patch("catalogapp.watchlist_ui.WatchlistService") as service,
        ):
            service.return_value.refresh.return_value = result
            self.panel._sync_and_finish_result.side_effect = lambda _result: browser.return_value.close.assert_called_once()
            self.panel.refresh_watchlist()
        browser.assert_called_once_with(self.panel._invaluable_profile_directory, stop_event=self.panel.stop_event)
        self.assertIs(service.call_args.kwargs["invaluable_fetcher"], browser.return_value)
        self.panel._sync_and_finish_result.assert_called_once_with(result)
        self.panel._finish_refresh_error.assert_not_called()

    def test_browser_cleanup_runs_on_refresh_failure(self):
        with (
            patch("catalogapp.watchlist_ui.threading.Thread", side_effect=self.immediate_thread),
            patch("catalogapp.watchlist_ui.local_watchlist_directory", return_value=self.directory),
            patch("catalogapp.watchlist_ui.InvaluableBrowserFetcher") as browser,
            patch("catalogapp.watchlist_ui.WatchlistService") as service,
        ):
            service.return_value.refresh.side_effect = RuntimeError("refresh failed")
            self.panel.refresh_watchlist()
        browser.return_value.close.assert_called_once()
        self.panel._finish_refresh_error.assert_called_once_with("refresh failed")
        self.panel._sync_and_finish_result.assert_not_called()

    def test_disabled_session_does_not_launch_browser(self):
        self.panel.invaluable_session_var.get.return_value = False
        with (
            patch("catalogapp.watchlist_ui.threading.Thread", side_effect=self.immediate_thread),
            patch("catalogapp.watchlist_ui.local_watchlist_directory", return_value=self.directory),
            patch("catalogapp.watchlist_ui.InvaluableBrowserFetcher") as browser,
            patch("catalogapp.watchlist_ui.WatchlistService") as service,
        ):
            self.panel.refresh_watchlist()
        browser.assert_not_called()
        self.assertIsNone(service.call_args.kwargs["invaluable_fetcher"])
