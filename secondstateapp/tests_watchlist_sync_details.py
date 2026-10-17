"""Keep calendar upload outcomes and incomplete source refreshes inspectable."""

from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

import tkinter as tk

from catalogapp.studio_theme import apply_studio_theme
from catalogapp.watchlist_models import NormalizedLot
from catalogapp.watchlist_service import WatchlistMetrics, WatchlistResult
from catalogapp.watchlist_shared import SharedWatchlistSnapshot
from catalogapp.watchlist_sync import CalendarSyncResult
from catalogapp.watchlist_ui import ArtistWatchlistPanel


class WatchlistSyncDetailsTests(TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display is unavailable: {exc}")
        self.addCleanup(self.root.destroy)
        self.root.withdraw()
        apply_studio_theme(self.root)
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch(
            "catalogapp.watchlist_ui.local_watchlist_directory", return_value=Path(directory.name),
        ))
        stack.enter_context(patch.object(ArtistWatchlistPanel, "_load_initial_bookmarks"))
        self.warning = stack.enter_context(patch("catalogapp.watchlist_ui.messagebox.showwarning"))
        self.error = stack.enter_context(patch("catalogapp.watchlist_ui.messagebox.showerror"))
        self.info = stack.enter_context(patch("catalogapp.watchlist_ui.messagebox.showinfo"))
        self.shared_fetch = stack.enter_context(patch(
            "catalogapp.watchlist_ui.fetch_shared_watchlist", return_value=SharedWatchlistSnapshot(),
        ))
        self.shared_publish = stack.enter_context(patch("catalogapp.watchlist_ui.publish_shared_watchlist", return_value=0))
        self.inventory_fetch = stack.enter_context(patch("catalogapp.watchlist_ui.fetch_calendar_inventory", return_value=[]))
        self.status_callback = Mock()
        self.panel = ArtistWatchlistPanel(self.root, status_callback=self.status_callback)
        self.panel.pack(fill=tk.BOTH, expand=True)
        self.lot = NormalizedLot(
            source="Invaluable", source_lot_id="cached-1", artist="Alexander Calder",
            artist_watchlist_name="Alexander Calder", title="Print", start_at="2026-10-22",
            first_seen_at="2026-01-01T12:00:00+00:00", last_seen_at="2026-10-08T12:00:00+00:00",
        )
        self.upload = CalendarSyncResult(1, 0, 1, 0)

    def result(self, *, cached=False, errors=(), notices=(), stopped=False):
        return WatchlistResult(
            [self.lot], WatchlistMetrics(), errors=list(errors), notices=list(notices), stopped=stopped,
            fallback_lot_keys={self.lot.cache_key} if cached else set(),
        )

    @staticmethod
    def descendants(widget):
        for child in widget.winfo_children():
            yield child
            yield from WatchlistSyncDetailsTests.descendants(child)

    def test_details_start_hidden_and_can_be_cleared(self):
        self.assertEqual(self.panel._sync_details_text, "")
        self.assertFalse(self.panel.sync_details_button.winfo_manager())
        self.panel._set_sync_details("Last sync details")
        self.assertEqual(self.panel._sync_details_text, "Last sync details")
        self.assertEqual(self.panel.sync_details_button.winfo_manager(), "grid")
        self.panel._set_sync_details("")
        self.assertEqual(self.panel._sync_details_text, "")
        self.assertFalse(self.panel.sync_details_button.winfo_manager())

    def test_details_button_opens_read_only_scrollable_report(self):
        report = "Calendar upload completed.\n" + "Source details\n" * 100
        self.panel._set_sync_details(report)
        self.panel.sync_details_button.invoke()
        windows = [widget for widget in self.descendants(self.root) if isinstance(widget, tk.Toplevel)]
        self.assertEqual(len(windows), 1)
        texts = [widget for widget in self.descendants(windows[0]) if isinstance(widget, tk.Text)]
        self.assertEqual(len(texts), 1)
        self.assertEqual(texts[0].get("1.0", "end-1c"), report.strip())
        self.assertEqual(str(texts[0].cget("state")), tk.DISABLED)
        self.assertTrue(texts[0].cget("yscrollcommand"))

    def test_fresh_upload_reports_success_and_updates_status_callback(self):
        self.panel._finish_refresh(self.result(), sync_result=self.upload)
        self.assertEqual(self.panel.status_title_var.get(), "Calendar updated")
        self.assertIn(self.upload.summary(), self.panel._sync_details_text)
        self.assertEqual(self.panel.sync_details_button.winfo_manager(), "grid")
        self.status_callback.assert_called_with(self.panel.sync_status_var.get())
        self.warning.assert_not_called()

    def test_cached_upload_keeps_missing_artist_and_source_failure_visible(self):
        failure = "Invaluable HTTP 202; no cached lots for Francisco Zúñiga."
        self.panel._finish_refresh(self.result(cached=True, errors=[failure]), sync_result=self.upload)
        self.assertEqual(self.panel.status_title_var.get(), "Calendar updated; source refresh incomplete")
        self.assertIn("live data was not verified", self.panel.sync_status_var.get())
        self.assertIn(failure, self.panel.sync_status_var.get())
        self.assertIn(self.upload.summary(), self.panel._sync_details_text)
        self.assertIn(failure, self.panel._sync_details_text)
        self.assertIn("2026-10-08", self.panel._sync_details_text)
        self.assertIn("Retry with browser", self.panel._sync_details_text)
        self.assertIn("Use my browser", self.warning.call_args.args[1])
        self.assertEqual(self.panel.import_invaluable_button.winfo_manager(), "grid")
        self.status_callback.assert_called_with(self.panel.sync_status_var.get())

    def test_new_artist_with_blocked_source_has_actionable_empty_state_and_no_upload(self):
        failure = "www.invaluable.com returned a web page instead of auction data (HTTP 202)."
        self.panel.calendar_syncer = Mock()
        result = WatchlistResult([], WatchlistMetrics(), errors=[
            failure, "No cached lots are available for calendar sync for: John W Nieto.",
        ])
        self.panel.after = lambda _delay, callback: callback()

        self.panel._sync_and_finish_result(result)

        self.panel.calendar_syncer.assert_not_called()
        self.assertEqual(self.panel.status_title_var.get(), "Sync needs attention")
        status = self.panel.sync_status_var.get()
        self.assertIn("No lots were available to upload", status)
        self.assertIn("HTTP 202", status)
        self.assertIn("Retry with browser", status)
        self.assertIn("Import saved Invaluable pages", status)
        self.assertNotIn("Calendar updated", status)
        self.assertNotIn("No upcoming lots found", status)
        self.assertIn("Retry with browser", self.panel.empty_state.cget("text"))
        self.assertEqual(self.panel.import_invaluable_button.winfo_manager(), "grid")
        self.assertEqual(self.panel.import_invaluable_button.winfo_manager(), "grid")
        self.assertIn("John W Nieto", self.panel._sync_details_text)
        self.assertIn("John W Nieto", self.warning.call_args.args[1])

    def test_verified_empty_search_keeps_zero_results_distinct_from_source_failure(self):
        self.panel.calendar_syncer = Mock()
        self.panel.after = lambda _delay, callback: callback()

        self.panel._sync_and_finish_result(WatchlistResult([], WatchlistMetrics()))

        self.panel.calendar_syncer.assert_not_called()
        self.assertEqual(self.panel.status_title_var.get(), "No upcoming lots")
        self.assertEqual(self.panel.empty_state.cget("text"), "No upcoming lots found for the selected artists.")
        self.assertFalse(self.panel.import_invaluable_button.winfo_manager())
        self.warning.assert_not_called()

    def test_usual_browser_action_is_only_shown_for_invaluable_and_disabled_during_work(self):
        self.assertFalse(self.panel.import_invaluable_button.winfo_manager())
        self.panel._finish_refresh(self.result(errors=["Heritage returned HTTP 403."]))
        self.assertFalse(self.panel.import_invaluable_button.winfo_manager())
        self.panel._finish_refresh(self.result(errors=["www.INVALUABLE.com returned HTTP 202."]))
        self.assertEqual(self.panel.import_invaluable_button.winfo_manager(), "grid")
        self.assertEqual(str(self.panel.import_invaluable_button.cget("state")), tk.NORMAL)
        self.panel._set_import_buttons_state(tk.DISABLED)
        self.assertEqual(str(self.panel.import_invaluable_button.cget("state")), tk.DISABLED)
        self.panel._set_import_buttons_state(tk.NORMAL)
        with patch.object(self.panel, "_load_watchlist_for_update", return_value=False) as recovery:
            self.panel.import_invaluable_button.invoke()
        recovery.assert_called_once()
        self.panel._finish_refresh(self.result(), sync_result=self.upload)
        self.assertFalse(self.panel.import_invaluable_button.winfo_manager())

    def test_cached_upload_without_source_error_has_distinct_heading(self):
        self.panel._finish_refresh(self.result(cached=True), sync_result=self.upload)
        self.assertEqual(self.panel.status_title_var.get(), "Calendar updated with cached lots")
        self.assertIn("cached", self.panel._sync_details_text.casefold())

    def test_successful_fresh_retry_replaces_prior_failure_details(self):
        failure = "Invaluable HTTP 202; no cached lots for Francisco Zúñiga."
        self.panel._finish_refresh(self.result(cached=True, errors=[failure]), sync_error="Upload timed out")
        self.panel._finish_refresh(self.result(), sync_result=self.upload)
        self.assertEqual(self.panel.source_refresh_errors, [])
        self.assertEqual(self.panel.fallback_lot_keys, set())
        self.assertEqual(self.panel.status_title_var.get(), "Calendar updated")
        self.assertIn(self.upload.summary(), self.panel._sync_details_text)
        self.assertNotIn(failure, self.panel._sync_details_text)
        self.assertNotIn("Upload timed out", self.panel._sync_details_text)
        self.assertNotIn("2026-10-08", self.panel._sync_details_text)
        self.assertFalse(self.panel.import_invaluable_button.winfo_manager())

    def test_report_retains_every_source_error_and_import_notice(self):
        errors = [f"Source issue {number}: missing artist {number}" for number in range(12)]
        notices = [f"Import note {number}" for number in range(12)]
        self.panel._finish_refresh(self.result(errors=errors, notices=notices), sync_result=self.upload)
        for message in [*errors, *notices]:
            with self.subTest(message=message):
                self.assertIn(message, self.panel._sync_details_text)

    def test_cached_observation_range_uses_only_fallback_lots(self):
        latest = replace(self.lot, source_lot_id="cached-2", last_seen_at="2026-10-12T12:00:00+00:00")
        fresh = replace(self.lot, source_lot_id="fresh", last_seen_at="2026-10-16T12:00:00+00:00")
        invalid = replace(self.lot, source_lot_id="invalid", last_seen_at="not-a-timestamp")
        missing = replace(self.lot, source_lot_id="missing", last_seen_at="")
        self.panel.current_lots = [fresh, invalid, latest, missing, self.lot]
        self.panel.fallback_lot_keys = {lot.cache_key for lot in (self.lot, latest, invalid, missing)}
        report = self.panel._source_refresh_details()
        self.assertIn("2026-10-08", report)
        self.assertIn("2026-10-12", report)
        self.assertNotIn("2026-10-16", report)
        self.assertNotIn("2026-01-01", report)
        self.assertNotIn("not-a-timestamp", report)
        self.assertRegex(report.casefold(), r"unavailable.*2|2.*unavailable")

    def test_all_missing_cached_timestamps_are_explicitly_unavailable(self):
        self.panel.current_lots = [replace(self.lot, last_seen_at="")]
        self.panel.fallback_lot_keys = {self.lot.cache_key}
        self.assertIn("unavailable", self.panel._source_refresh_details().casefold())

    def test_summary_limits_first_source_error_but_report_retains_it(self):
        failure = "Invaluable HTTP 202 " + "detail " * 60 + "unique final detail"
        self.panel.source_refresh_errors = [failure, "Second source problem"]
        summary = self.panel._calendar_sync_summary(self.upload)
        baseline = self.upload.summary()
        self.assertIn("Invaluable HTTP 202", summary)
        self.assertIn("Live source refresh remains incomplete", summary)
        self.assertNotIn("unique final detail", summary)
        self.assertNotIn("Second source problem", summary)
        self.assertLess(len(summary) - len(baseline), 350)
        self.assertIn(failure, self.panel._source_refresh_details())

    def test_incomplete_upload_preserves_error_in_persistent_details(self):
        failure = "Calendar request failed after the first batch"
        self.panel._finish_refresh(self.result(), sync_error=failure)
        self.assertIn(failure, self.panel._sync_details_text)
        self.assertIn("incomplete", self.panel.sync_status_var.get())
        self.assertEqual(self.panel.sync_details_button.winfo_manager(), "grid")
        self.assertEqual(self.panel.current_lots, [self.lot])

    def test_setup_and_stopped_outcomes_remain_inspectable(self):
        setup = "Set SECONDSTATE_BASE_URL and CATALOG_API_KEY in .env"
        self.panel._finish_refresh(self.result(), sync_setup_message=setup)
        self.assertIn(setup, self.panel._sync_details_text)
        self.panel._finish_refresh(self.result(stopped=True))
        self.assertIn("stopped", self.panel._sync_details_text.casefold())
        self.assertNotIn(setup, self.panel._sync_details_text)

    def test_upload_only_completion_and_failure_replace_report(self):
        failure = "Invaluable HTTP 202; no cached lots for Francisco Zúñiga."
        self.panel.current_lots = [self.lot]
        self.panel.fallback_lot_keys = {self.lot.cache_key}
        self.panel.source_refresh_errors = [failure]
        self.panel._finish_calendar_sync(self.upload)
        self.assertIn(self.upload.summary(), self.panel._sync_details_text)
        self.assertIn(failure, self.panel._sync_details_text)
        self.assertEqual(self.panel.status_title_var.get(), "Calendar updated; source refresh incomplete")
        self.panel._finish_calendar_sync_error("Website unavailable")
        self.assertIn("Website unavailable", self.panel._sync_details_text)
        self.assertIn(failure, self.panel._sync_details_text)
        self.assertNotIn(self.upload.summary(), self.panel._sync_details_text)

    def test_refresh_exception_preserves_actionable_details(self):
        self.panel._finish_refresh_error("Bookmark source failed unexpectedly")
        self.assertIn("Bookmark source failed unexpectedly", self.panel._sync_details_text)
        self.assertEqual(self.panel.sync_details_button.winfo_manager(), "grid")
        self.status_callback.assert_called_with(self.panel.sync_status_var.get())
