"""A browser capture refreshes only the records actually observed in that file."""

from dataclasses import replace
from unittest import TestCase
from unittest.mock import patch

from catalogapp.watchlist_service import WatchlistMetrics, WatchlistResult
from secondstateapp import tests_studio_watchlist as studio_tests


class BrowserCaptureControllerTests(TestCase):
    setUp = studio_tests.StudioWatchlistControllerTests.setUp
    immediate_thread = staticmethod(studio_tests.StudioWatchlistControllerTests.immediate_thread)

    def test_capture_updates_existing_artist_without_uploading_unobserved_lots(self):
        self.panel.load_bookmarks(self.path)
        self.panel.selected_artists = {"Calder"}
        self.panel._last_artist_scope = {"Calder"}
        self.panel._scan_missing_only = True
        captured = replace(self.lot, artist="Matisse", artist_watchlist_name="Matisse", status="changed")
        cached = replace(self.lot, source_lot_id="cached", artist="Calder", artist_watchlist_name="Calder")
        previous = replace(cached, source_lot_id="previous")
        self.panel.current_lots = [previous]
        self.panel.fallback_lot_keys = {previous.cache_key}
        self.panel._calendar_lot_keys = {captured.cache_key, cached.cache_key, previous.cache_key}
        result = WatchlistResult([captured, cached], WatchlistMetrics(changed_lots=1),
                                 fallback_lot_keys={cached.cache_key})
        with (patch("catalogapp.watchlist_ui.filedialog.askopenfilenames", return_value=["capture.json"]),
              patch("catalogapp.watchlist_ui.import_saved_invaluable_pages", return_value=result) as importer):
            self.panel.import_browser_capture()
        self.error.assert_not_called()
        self.assertEqual({entry.artist for entry in importer.call_args.kwargs["entries"]}, {"Calder", "Matisse"})
        self.assertIsNone(self.panel._last_artist_scope)
        self.assertFalse(self.panel._scan_missing_only)
        self.panel.calendar_syncer.assert_called_once()
        self.assertEqual(self.panel.calendar_syncer.call_args.args[0], [captured])
        self.assertEqual({lot.cache_key for lot in self.panel.current_lots},
                         {captured.cache_key, cached.cache_key, previous.cache_key})
        self.service.assert_not_called()
        self.public_browser.assert_not_called()

    def test_empty_or_invalid_capture_does_not_upload_the_existing_agenda(self):
        self.panel.load_bookmarks(self.path)
        self.panel.current_lots = [self.lot]
        self.panel.fallback_lot_keys = {self.lot.cache_key}
        with (patch("catalogapp.watchlist_ui.filedialog.askopenfilenames", return_value=["capture.json"]),
              patch("catalogapp.watchlist_ui.import_saved_invaluable_pages",
                    return_value=WatchlistResult([], WatchlistMetrics(), errors=["Unreadable capture"]))):
            self.panel.import_browser_capture()
        self.panel.calendar_syncer.assert_not_called()
        self.assertEqual(self.panel.current_lots, [self.lot])
        self.assertIn("Unreadable capture", " ".join(self.panel.source_refresh_errors))

    def test_cancel_capture_leaves_calendar_untouched(self):
        self.panel.load_bookmarks(self.path)
        self.panel._last_artist_scope = {"Calder"}
        with (patch("catalogapp.watchlist_ui.filedialog.askopenfilenames", return_value=[]),
              patch("catalogapp.watchlist_ui.import_saved_invaluable_pages") as importer):
            self.panel.import_browser_capture()
        importer.assert_not_called()
        self.panel.calendar_syncer.assert_not_called()
        self.assertEqual(self.panel._last_artist_scope, {"Calder"})
