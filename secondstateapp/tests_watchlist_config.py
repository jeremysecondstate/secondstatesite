"""Desktop calendar sync reports missing configuration and reloads local setup."""

import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

import tkinter as tk

from catalogapp.bookmark_watchlist import BookmarkEntry
from catalogapp.watchlist_models import NormalizedLot
from catalogapp.watchlist_service import WatchlistMetrics, WatchlistResult
from catalogapp.watchlist_shared import SharedWatchlistSnapshot
from catalogapp.watchlist_sync import CalendarSyncError, CalendarSyncResult
from catalogapp.watchlist_ui import ArtistWatchlistPanel


class CalendarSyncConfigurationTests(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.env_patch = patch.dict(os.environ, {}, clear=True)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.root_patch = patch("secondstate.environment.PROJECT_ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.warning_patch = patch("catalogapp.watchlist_ui.messagebox.showwarning")
        self.warning = self.warning_patch.start()
        self.addCleanup(self.warning_patch.stop)
        self.shared_fetch = patch('catalogapp.watchlist_ui.fetch_shared_watchlist', return_value=SharedWatchlistSnapshot())
        self.shared_fetch.start()
        self.addCleanup(self.shared_fetch.stop)
        self.shared_publish = patch('catalogapp.watchlist_ui.publish_shared_watchlist', return_value=0)
        self.shared_publish.start()
        self.addCleanup(self.shared_publish.stop)
        # Exercise the real controller methods without creating a Tk window.
        self.panel = ArtistWatchlistPanel.__new__(ArtistWatchlistPanel)
        self.panel.calendar_base_url = "https://secondstate.art"
        self.panel.calendar_api_key = ""
        self.panel.artist_artprice_links = {}
        self.panel.all_entries = []
        self.panel.active_entries = []
        self.panel.selected_artists = set()
        self.panel.worker = None
        self.panel.calendar_syncer = Mock(return_value=CalendarSyncResult(1, 1, 0, 0))
        self.panel.status_callback = Mock()
        self.panel.after = lambda _delay, callback: callback()
        self.panel._fill_agenda = Mock()
        for name in ("refresh_button", "import_saved_button", "stop_button", "calendar_sync_button", "metrics_var"):
            setattr(self.panel, name, Mock())
        self.lot = NormalizedLot(
            source="Heritage", source_lot_id="8280-65001", artist="Pablo Picasso",
            artist_watchlist_name="Pablo Picasso", title="Portrait", start_at="2026-10-22",
        )
        self.panel.current_lots = [self.lot]
        self.panel.fallback_lot_keys = set()
        self.panel.source_refresh_errors = []
        self.result = WatchlistResult([self.lot], WatchlistMetrics(new_lots=1))

    @staticmethod
    def immediate_thread(*, target, **_kwargs):
        worker = Mock()
        worker.is_alive.return_value = False
        worker.start.side_effect = target
        return worker

    def test_sync_button_keeps_setup_guidance_accessible_when_key_is_missing(self):
        self.panel._set_calendar_sync_button_state()
        self.panel.calendar_sync_button.configure.assert_called_once_with(state=tk.NORMAL)
        self.panel.sync_website_calendar()
        self.panel.calendar_syncer.assert_not_called()
        title, message = self.warning.call_args.args
        self.assertEqual(title, "Calendar Sync Not Configured")
        self.assertIn("CATALOG_API_KEY", message)
        self.assertIn(str(self.root / ".env"), message)
        self.assertIn("reloads this file automatically", message)
        self.assertIn("not synced", self.panel.status_callback.call_args.args[0])

    def test_automatic_sync_reports_missing_configuration_and_keeps_local_lots(self):
        self.panel._sync_and_finish_result(self.result)
        self.panel.calendar_syncer.assert_not_called()
        self.assertEqual(self.panel.current_lots, [self.lot])
        self.panel.calendar_sync_button.configure.assert_called_with(state=tk.NORMAL)
        self.assertEqual(self.warning.call_args.args[0], "Calendar Sync Not Configured")
        self.assertIn("website calendar not synced", self.panel.status_callback.call_args.args[0])

    def test_manual_retry_reads_new_project_env_without_restart(self):
        self.panel.sync_website_calendar()
        (self.root / ".env").write_text("CATALOG_API_KEY=offline-test-key\n", encoding="utf-8")
        with patch("catalogapp.watchlist_ui.threading.Thread", side_effect=self.immediate_thread):
            self.panel.sync_website_calendar()
        self.panel.calendar_syncer.assert_called_once_with(
            [self.lot], base_url="https://secondstate.art", api_key="offline-test-key", artist_artprice_links={}
        )
        self.assertIn("Website calendar synced: 1 lots", self.panel.status_callback.call_args.args[0])

    def test_environment_and_explicit_settings_keep_precedence_over_project_env(self):
        (self.root / ".env").write_text(
            "CATALOG_API_KEY=file-test-key\nSECONDSTATE_BASE_URL=https://file.example\n", encoding="utf-8"
        )
        os.environ["CATALOG_API_KEY"] = "process-test-key"
        self.assertTrue(self.panel._calendar_sync_configured())
        self.assertEqual(self.panel.calendar_api_key, "process-test-key")
        self.assertEqual(self.panel.calendar_base_url, "https://secondstate.art")
        self.panel.calendar_api_key = "explicit-test-key"
        self.assertTrue(self.panel._calendar_sync_configured())
        self.assertEqual(self.panel.calendar_api_key, "explicit-test-key")

    def test_saved_page_import_automatically_syncs_with_newly_added_configuration(self):
        (self.root / ".env").write_text("CATALOG_API_KEY=offline-test-key\n", encoding="utf-8")
        self.panel.source_refresh_errors = ["Francisco Zúñiga (Invaluable): HTTP 202; no cached lots."]
        entry = BookmarkEntry(
            folder_path=("HERITAGE",), title="10-22 SALE", source="Heritage",
            url="https://fineart.ha.com/c/search/results.zx?auction_name=8280&dept=1544&mode=live",
        )
        self.panel.active_entries = [entry]
        self.panel.selected_artists = {entry.watch_label}
        self.panel.horizon_var = Mock(get=Mock(return_value="30"))
        self.panel.new_changed_var = Mock(get=Mock(return_value=False))
        self.panel._cache_path = self.root / "unused.sqlite3"
        with (
            patch("catalogapp.watchlist_ui.filedialog.askopenfilenames", return_value=["saved.html"]),
            patch("catalogapp.watchlist_ui.WatchlistCache"),
            patch("catalogapp.watchlist_ui.local_watchlist_directory", return_value=self.root),
            patch("catalogapp.watchlist_ui.import_saved_heritage_pages", return_value=self.result) as importer,
            patch("catalogapp.watchlist_ui.threading.Thread", side_effect=self.immediate_thread),
        ):
            self.panel.import_saved_heritage_pages()
        importer.assert_called_once()
        self.panel.calendar_syncer.assert_called_once_with(
            [self.lot], base_url="https://secondstate.art", api_key="offline-test-key", artist_artprice_links={}
        )
        self.assertIn("Francisco Zúñiga", self.warning.call_args.args[1])
        self.assertIn("Website calendar synced", self.panel.status_callback.call_args.args[0])
        self.warning.reset_mock()
        with patch("catalogapp.watchlist_ui.threading.Thread", side_effect=self.immediate_thread):
            self.panel.sync_website_calendar()
        self.assertIn("Francisco Zúñiga", self.warning.call_args.args[1])

    def test_sync_error_is_not_reported_as_success_or_missing_configuration(self):
        self.panel.calendar_api_key = "offline-test-key"
        self.panel.calendar_syncer.side_effect = RuntimeError("Server rejected the upload")
        self.panel._sync_and_finish_result(self.result)
        self.assertEqual(self.warning.call_args.args[0], "Website Calendar Sync Incomplete")
        self.assertIn("Server rejected the upload", self.warning.call_args.args[1])
        self.assertIn("sync incomplete", self.panel.status_callback.call_args.args[0])

    def test_saved_sold_result_import_merges_agenda_and_automatically_syncs(self):
        self.panel.calendar_api_key = "offline-test-key"
        self.panel.source_refresh_errors = ["Francisco Zúñiga (Invaluable): HTTP 202; no cached lots."]
        entry = BookmarkEntry(
            folder_path=("ARTISTS INVALUABLE",), title="Alexander Calder", source="Invaluable",
            artist="Alexander Calder", url="https://www.invaluable.com/search?artistName=Alexander+Calder",
        )
        self.panel.active_entries = [entry]
        self.panel.selected_artists = {entry.watch_label}
        self.panel._cache_path = self.root / "unused.sqlite3"
        self.panel.import_sold_button = Mock()
        sold = NormalizedLot(
            source="Invaluable", source_lot_id="116", artist="Alexander Calder",
            artist_watchlist_name="Alexander Calder", title="Nid d'araignee", sold_price=11000,
            sold_currency="USD", status="changed",
        )
        result = WatchlistResult([sold], WatchlistMetrics(changed_lots=1))
        with (
            patch("catalogapp.watchlist_ui.filedialog.askopenfilenames", return_value=["sold.html"]),
            patch("catalogapp.watchlist_ui.WatchlistCache") as cache,
            patch("catalogapp.watchlist_ui.local_watchlist_directory", return_value=self.root),
            patch("catalogapp.watchlist_ui.import_saved_sold_pages", return_value=result) as importer,
            patch("catalogapp.watchlist_ui.threading.Thread", side_effect=self.immediate_thread),
        ):
            self.panel.import_saved_sold_results()
        importer.assert_called_once_with(["sold.html"], entries=[entry], cache=cache.return_value.__enter__.return_value)
        self.assertEqual({lot.cache_key for lot in self.panel.current_lots}, {self.lot.cache_key, sold.cache_key})
        self.panel.calendar_syncer.assert_called_once()
        self.assertIn(sold, self.panel.calendar_syncer.call_args.args[0])
        self.assertIn("Francisco Zúñiga", self.warning.call_args.args[1])
        self.panel.import_sold_button.configure.assert_called_with(state=tk.NORMAL)
        self.warning.assert_called_once()

    def test_unconfirmed_images_keep_deployment_guidance_visible_after_partial_sync(self):
        self.panel.calendar_api_key = "offline-test-key"
        self.result.errors = ["Heritage live refresh failed; retained cached lots."]
        self.panel.calendar_syncer.side_effect = CalendarSyncError(
            "Lot details reached the website, but saved artwork images were not confirmed. "
            "Deploy the website's saved-image update, then click Sync to Calendar again."
        )

        def warning_is_open(_title, message, **_kwargs):
            self.assertIn("sync incomplete", self.panel.status_callback.call_args.args[0])
            self.assertIn("Deploy the website's saved-image update", message)
            self.assertNotIn("was not synced", message)
            self.assertNotIn("did not sync", message)

        self.warning.side_effect = warning_is_open
        self.panel._sync_and_finish_result(self.result)
        self.assertEqual(self.warning.call_count, 2)
        self.assertEqual(self.panel.current_lots, [self.lot])
        self.panel.calendar_sync_button.configure.assert_called_with(state=tk.NORMAL)

    def test_manual_sync_failure_preserves_partial_batch_retry_instructions(self):
        self.panel.calendar_api_key = "offline-test-key"
        self.panel.calendar_syncer.side_effect = CalendarSyncError(
            "Could not reach the website calendar. Retry Sync to Calendar; "
            "any completed batches will be updated without duplicates."
        )
        with (
            patch("catalogapp.watchlist_ui.threading.Thread", side_effect=self.immediate_thread),
            patch("catalogapp.watchlist_ui.messagebox.showerror") as error,
        ):
            self.panel.sync_website_calendar()
        title, message = error.call_args.args
        self.assertEqual(title, "Website Calendar Sync Incomplete")
        self.assertIn("earlier batches may already be saved", message)
        self.assertIn("completed batches will be updated without duplicates", message)
        self.assertIn("sync incomplete", self.panel.status_callback.call_args.args[0])
        self.panel.calendar_sync_button.configure.assert_called_with(state=tk.NORMAL)

    def test_partial_import_notice_is_visible_alongside_successful_sync(self):
        self.panel.calendar_api_key = "offline-test-key"
        self.result.notices = ["This saved page contains 72 of 151 lots. Import the remaining results pages."]
        with patch("catalogapp.watchlist_ui.messagebox.showinfo") as info:
            self.panel._sync_and_finish_result(self.result)
        self.assertEqual(info.call_args.args, ("Watchlist Import Notes", self.result.notices[0]))
        self.warning.assert_not_called()
        self.assertIn("Website calendar synced", self.panel.status_callback.call_args.args[0])

    def test_source_warning_shows_completed_sync_before_opening_modal(self):
        self.panel.calendar_api_key = "offline-test-key"
        self.result.errors = ["Heritage could not be reached; retained cached lots."]
        self.result.fallback_lot_keys = {self.lot.cache_key}

        def warning_is_open(title, message, **_kwargs):
            status = self.panel.status_callback.call_args.args[0]
            self.assertIn("Website calendar synced", status)
            self.assertNotIn("Syncing", status)
            self.assertIn("cached lots", status)
            self.assertEqual(title, "Live Source Refresh Incomplete")
            self.assertIn("Website calendar synced", message)
            self.assertIn("live data was not verified", message)

        self.warning.side_effect = warning_is_open
        self.panel._sync_and_finish_result(self.result)
        self.warning.assert_called_once()

    def test_manual_sync_preserves_missing_artist_warning_after_source_failure(self):
        self.panel.calendar_api_key = "offline-test-key"
        self.result.errors = [
            "Invaluable returned an access page (HTTP 202).",
            "No cached lots for Francisco Zúñiga; no lots available for calendar sync.",
        ]
        self.result.fallback_lot_keys = {self.lot.cache_key}
        self.panel._sync_and_finish_result(self.result)
        self.warning.reset_mock()
        self.panel.calendar_syncer.reset_mock()

        with patch("catalogapp.watchlist_ui.threading.Thread", side_effect=self.immediate_thread):
            self.panel.sync_website_calendar()

        self.panel.calendar_syncer.assert_called_once_with(
            [self.lot], base_url="https://secondstate.art", api_key="offline-test-key", artist_artprice_links={}
        )
        title, message = self.warning.call_args.args
        self.assertEqual(title, "Live Source Refresh Incomplete")
        self.assertIn("Francisco Zúñiga", message)
        self.assertIn("Artists without retrieved or cached lots cannot appear on the calendar yet", message)
        self.assertIn("Sync all", message)
        status = self.panel.status_callback.call_args.args[0]
        self.assertIn("Website calendar synced", status)
        self.assertIn("cached lots", status)
        self.assertIn("Live source refresh remains incomplete", status)

    def test_manual_sync_preserves_source_warning_without_fallback_lots(self):
        self.panel.calendar_api_key = "offline-test-key"
        self.result.errors = ["Francisco Zúñiga (Invaluable): HTTP 202; no cached lots."]
        self.panel._sync_and_finish_result(self.result)
        self.warning.reset_mock()

        with patch("catalogapp.watchlist_ui.threading.Thread", side_effect=self.immediate_thread):
            self.panel.sync_website_calendar()

        self.warning.assert_called_once()
        self.assertIn("Francisco Zúñiga", self.warning.call_args.args[1])
        self.assertIn("Live source refresh remains incomplete", self.panel.status_callback.call_args.args[0])

    def test_successful_refresh_clears_source_warning_for_later_sync(self):
        self.panel.calendar_api_key = "offline-test-key"
        self.result.errors = ["Invaluable: HTTP 202"]
        self.result.fallback_lot_keys = {self.lot.cache_key}
        self.panel._sync_and_finish_result(self.result)
        self.panel._sync_and_finish_result(WatchlistResult([self.lot], WatchlistMetrics()))
        self.warning.reset_mock()

        with patch("catalogapp.watchlist_ui.threading.Thread", side_effect=self.immediate_thread):
            self.panel.sync_website_calendar()

        self.warning.assert_not_called()
        self.assertEqual(self.panel.source_refresh_errors, [])
        self.assertNotIn("cached", self.panel.status_callback.call_args.args[0])
        self.assertNotIn("incomplete", self.panel.status_callback.call_args.args[0])

    def test_agenda_displays_fallback_as_cached_without_overwriting_lot_status(self):
        self.lot.status = "changed"
        self.lot.last_seen_at = "2026-10-09T12:00:00+00:00"
        self.panel.fallback_lot_keys = {self.lot.cache_key}
        self.panel.agenda_tree = Mock(get_children=Mock(return_value=[]))
        self.panel.calendar_text = Mock()
        self.panel._lot_urls = {}
        ArtistWatchlistPanel._fill_agenda(self.panel)
        row = next(
            call.kwargs for call in self.panel.agenda_tree.insert.call_args_list
            if call.kwargs.get("iid") == "lot-0"
        )
        self.assertEqual(row["values"][-1], "Cached")
        self.assertEqual(row["tags"], ("cached",))
        self.assertEqual(self.lot.status, "changed")
        self.assertEqual(self.lot.last_seen_at, "2026-10-09T12:00:00+00:00")

    def test_empty_or_stopped_refresh_does_not_prompt_for_sync_configuration(self):
        for result in (WatchlistResult([], WatchlistMetrics()), WatchlistResult([self.lot], WatchlistMetrics(), stopped=True)):
            with self.subTest(stopped=result.stopped):
                self.panel._sync_and_finish_result(result)
        self.panel.calendar_syncer.assert_not_called()
        self.warning.assert_not_called()
