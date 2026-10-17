"""A selected-artist import adds only lots absent from the live Calendar."""

from dataclasses import replace
import threading
from unittest import TestCase

from catalogapp.watchlist_service import WatchCoverage, WatchlistMetrics, WatchlistResult
from catalogapp.watchlist_shared import SharedWatchlistSnapshot
from catalogapp.watchlist_sync import CalendarSyncResult
from secondstateapp import tests_studio_watchlist as studio_tests


class MissingLotImportControllerTests(TestCase):
    immediate_thread = staticmethod(studio_tests.StudioWatchlistControllerTests.immediate_thread)

    def setUp(self):
        studio_tests.StudioWatchlistControllerTests.setUp(self)
        self.path.write_text(studio_tests.bookmarks("Calder", "Will Barnet"), encoding="utf-8")
        self.panel.load_bookmarks(self.path)
        self.scope = {"Will Barnet"}
        self.new_lot = replace(self.lot, source_lot_id="new-one", artist="Will Barnet",
                               artist_watchlist_name="Will Barnet", title="New print",
                               lot_url="https://www.invaluable.com/auction-lot/new-one")
        self.existing_lot = replace(self.new_lot, source_lot_id="existing-one", title="Existing print",
                                    lot_url="https://www.invaluable.com/auction-lot/existing-one")
        self.unrelated_lot = replace(self.new_lot, source_lot_id="calder-one", artist="Calder",
                                     artist_watchlist_name="Calder", lot_url="")
        self.panel.current_lots = [self.unrelated_lot]
        self.panel.fallback_lot_keys = {self.unrelated_lot.cache_key}
        watched = next(entry for entry in self.panel.active_entries if entry.watch_label == "Will Barnet")
        self.check = WatchCoverage("Will Barnet", "Invaluable", watched.url, "verified", lot_count=2,
                                   checked_at="2026-10-17T18:00:00+00:00")
        self.shared_fetch.reset_mock()
        self.shared_publish.reset_mock()

    def result(self, lots=None, **overrides):
        values = dict(lots=[self.existing_lot, self.new_lot] if lots is None else lots,
                      metrics=WatchlistMetrics(), coverage=[self.check])
        values.update(overrides)
        return WatchlistResult(**values)

    def test_fresh_inventory_filters_existing_and_uploads_only_selected_new_lots(self):
        self.panel._calendar_lot_keys = set()  # A stale Scan result must not authorize updates.
        self.shared_fetch.return_value = SharedWatchlistSnapshot(calendar_lot_keys=frozenset({self.existing_lot.cache_key}))
        result = self.result()
        self.panel._sync_and_finish_result(result, artist_scope=self.scope)
        self.shared_fetch.assert_called_once_with(base_url=self.panel.calendar_base_url, api_key=self.panel.calendar_api_key)
        self.assertEqual(self.panel.calendar_syncer.call_args.args[0], [self.new_lot])
        self.assertEqual(result.lots, [self.existing_lot, self.new_lot])
        self.assertEqual({lot.cache_key for lot in self.panel.current_lots},
                         {self.unrelated_lot.cache_key, self.existing_lot.cache_key, self.new_lot.cache_key})
        self.assertIn("1 lots were already on the Calendar", self.panel.sync_status_var.get())
        self.assertIn(self.new_lot.cache_key, self.panel._calendar_lot_keys)
        self.assertIn("invaluable:" + self.new_lot.lot_url, self.panel._calendar_lot_keys)

    def test_same_url_with_different_source_id_is_already_imported(self):
        self.shared_fetch.return_value = SharedWatchlistSnapshot(calendar_lot_keys=frozenset({
            "invaluable:legacy-hash", "invaluable:" + self.new_lot.lot_url,
        }))
        self.panel._sync_and_finish_result(self.result([self.new_lot]), artist_scope=self.scope)
        self.panel.calendar_syncer.assert_not_called()
        self.assertIn("already on the Calendar", self.panel.sync_status_var.get())
        self.assertNotIn("No upcoming lots", self.panel.sync_status_var.get())
        self.assertNotIn("No upcoming lots", self.panel._sync_details_text)

    def test_lookup_failure_prevents_all_uploads_and_preserves_local_results(self):
        self.panel._calendar_lot_keys = {self.existing_lot.cache_key}
        self.shared_fetch.side_effect = RuntimeError("Calendar returned HTTP 503")
        self.panel._sync_and_finish_result(self.result(), artist_scope=self.scope)
        self.panel.calendar_syncer.assert_not_called()
        self.shared_publish.assert_not_called()
        self.assertIsNone(self.panel._calendar_lot_keys)
        self.assertIn("no lots were imported", self.panel.sync_status_var.get())
        self.assertIn("HTTP 503", self.panel._sync_details_text)
        self.assertNotIn("No upcoming lots", self.panel._sync_details_text)
        self.assertEqual(len(self.panel.current_lots), 3)
        self.assertFalse(self.panel._busy)

    def test_existing_cache_is_not_counted_as_uploaded_cache(self):
        self.shared_fetch.return_value = SharedWatchlistSnapshot(calendar_lot_keys=frozenset({self.existing_lot.cache_key}))
        self.panel._sync_and_finish_result(self.result(fallback_lot_keys={self.existing_lot.cache_key}), artist_scope=self.scope)
        self.assertNotIn("Includes 1 cached lots", self.panel.sync_status_var.get())
        self.assertEqual(self.panel.fallback_lot_keys, {self.existing_lot.cache_key, self.unrelated_lot.cache_key})

    def test_source_failure_remains_visible_when_all_available_lots_already_exist(self):
        self.shared_fetch.return_value = SharedWatchlistSnapshot(calendar_lot_keys=frozenset({self.existing_lot.cache_key}))
        self.panel._sync_and_finish_result(self.result([self.existing_lot], errors=["Will Barnet: HTTP 202"],
                                          coverage=[replace(self.check, state="blocked")]), artist_scope=self.scope)
        self.panel.calendar_syncer.assert_not_called()
        self.assertIn("already on the Calendar", self.panel.sync_status_var.get())
        self.assertIn("Source refresh remains incomplete", self.panel.sync_status_var.get())
        self.assertIn("HTTP 202", self.panel._sync_details_text)

    def test_global_update_still_uploads_existing_and_new_records(self):
        self.panel._calendar_lot_keys = {self.existing_lot.cache_key}
        self.panel.calendar_syncer.return_value = CalendarSyncResult(2, 1, 1, 0)
        self.panel._sync_and_finish_result(self.result())
        self.assertEqual(self.panel.calendar_syncer.call_args.args[0], [self.existing_lot, self.new_lot])
        self.shared_fetch.assert_not_called()
        self.shared_publish.assert_called_once()

    def test_selected_scope_cannot_upload_an_unrelated_lot_returned_by_import(self):
        self.panel._sync_and_finish_result(self.result([self.new_lot, self.unrelated_lot]), artist_scope=self.scope)
        self.assertEqual(self.panel.calendar_syncer.call_args.args[0], [self.new_lot])

    def test_stop_before_or_during_inventory_prevents_upload_and_publication(self):
        self.panel.stop_event = threading.Event()
        self.panel.stop_event.set()
        self.panel._sync_and_finish_result(self.result(), artist_scope=self.scope)
        self.shared_fetch.assert_not_called()
        self.panel.calendar_syncer.assert_not_called()
        self.shared_publish.assert_not_called()
        self.panel.stop_event.clear()

        def stop_in_lookup(**_kwargs):
            self.panel.stop_event.set()
            return SharedWatchlistSnapshot()

        self.shared_fetch.side_effect = stop_in_lookup
        self.panel._sync_and_finish_result(self.result(), artist_scope=self.scope)
        self.panel.calendar_syncer.assert_not_called()
        self.shared_publish.assert_not_called()
        self.assertIn("stopped", self.panel.sync_status_var.get())

    def test_real_coverage_and_selection_are_published_after_import(self):
        self.panel.selected_artists = {"Calder"}
        self.panel._sync_and_finish_result(self.result(), artist_scope=self.scope)
        call = self.shared_publish.call_args
        self.assertEqual(call.args, (self.panel.all_entries,))
        self.assertEqual(call.kwargs["coverage"], [self.check])
        self.assertEqual(call.kwargs["enabled_watch_urls"], {
            entry.url for entry in self.panel.active_entries if entry.watch_label == "Calder"
        })
        self.assertNotIn("bookmark_path", call.kwargs)
        self.assertNotIn("browser_profile", call.kwargs)

    def test_publication_failure_does_not_hide_successful_lot_import(self):
        self.shared_publish.side_effect = RuntimeError("metadata unavailable")
        self.panel._sync_and_finish_result(self.result([self.new_lot]), artist_scope=self.scope)
        self.panel.calendar_syncer.assert_called_once()
        self.assertIn("Website calendar synced: 1 lots", self.panel.sync_status_var.get())
        self.assertIn("Shared artist list could not be saved", self.panel.sync_status_var.get())
        self.assertIn(self.new_lot.cache_key, self.panel._calendar_lot_keys)
        self.assertIn("metadata unavailable", self.panel._sync_details_text)

    def test_genuinely_empty_source_remains_no_upcoming_not_already_imported(self):
        self.panel._sync_and_finish_result(self.result([], coverage=[replace(self.check, state="empty", lot_count=0)]),
                                          artist_scope=self.scope)
        self.shared_fetch.assert_not_called()
        self.panel.calendar_syncer.assert_not_called()
        self.assertIn("No upcoming lots", self.panel.sync_status_var.get())
        self.assertNotIn("already on the Calendar", self.panel.sync_status_var.get())
