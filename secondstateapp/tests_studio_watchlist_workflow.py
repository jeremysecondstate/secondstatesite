"""Offline regressions for saved watchlists and targeted calendar recovery."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest import TestCase
from unittest.mock import Mock

import tkinter as tk

from catalogapp.watchlist_service import WatchCoverage, WatchlistMetrics, WatchlistResult
from catalogapp.watchlist_cache import WatchlistCache
from catalogapp.watchlist_sync import CalendarSyncResult
from secondstateapp import tests_studio_watchlist as studio_tests
from secondstateapp import tests_watchlist_sync_details as details_tests


class SavedWatchlistWorkflowTests(TestCase):
    setUp = studio_tests.StudioWatchlistControllerTests.setUp
    immediate_thread = staticmethod(studio_tests.StudioWatchlistControllerTests.immediate_thread)

    def test_recover_pending_retains_watch_selection_and_requests_targeted_refresh(self):
        self.panel.load_bookmarks(self.path)
        self.panel.recover_pending()

        self.assertTrue(self.service.return_value.refresh.call_args.kwargs['pending_only'])
        self.assertEqual(self.service.return_value.refresh.call_args.kwargs['selected_artists'], {'Calder', 'Matisse'})
        self.panel.calendar_syncer.assert_called_once()
        self.public_browser.assert_not_called()

    def test_browser_recovery_uses_pending_catalogs_after_a_coverage_check(self):
        self.panel.load_bookmarks(self.path)
        self.panel.artist_coverage = [WatchCoverage('Calder', 'Invaluable', self.panel.active_entries[0].url)]
        self.panel.retry_with_browser()

        self.assertTrue(self.service.return_value.refresh.call_args.kwargs['pending_only'])
        self.public_browser.assert_called_once()

    def test_update_works_after_original_bookmark_export_moves(self):
        self.panel._registry_path = self.directory / 'watchlist.json'
        self.panel.load_bookmarks(self.path)
        self.panel.selected_artists.remove('Matisse')
        self.panel._save_settings_hint()
        self.path.unlink()

        self.panel.sync_to_calendar()

        self.error.assert_not_called()
        self.assertEqual(self.service.return_value.refresh.call_args.kwargs['selected_artists'], {'Calder'})
        self.assertEqual(self.panel.bookmark_path_var.get(), str(self.path.resolve()))
        self.panel.calendar_syncer.assert_called_once()

    def test_restart_restores_exclusions_horizon_and_includes_new_artists(self):
        self.panel.load_bookmarks(self.path)
        self.panel.selected_artists.remove('Matisse')
        self.panel.horizon_var.set(14)
        self.panel._save_settings_hint()
        self.path.write_text(studio_tests.bookmarks('Calder', 'Matisse', 'Corinth'), encoding='utf-8')
        self.panel.active_entries = []
        self.panel.selected_artists = set()
        self.panel.horizon_var.set(30)

        self.panel._load_initial_bookmarks()

        self.assertEqual(self.panel.selected_artists, {'Calder', 'Corinth'})
        self.assertEqual(self.panel.horizon_var.get(), 7)
        self.service.assert_not_called()

    def test_restart_uses_saved_watchlist_before_project_fallback(self):
        self.panel._registry_path = self.directory / 'watchlist.json'
        self.panel.load_bookmarks(self.path)
        self.panel.selected_artists.clear()
        self.panel._save_settings_hint()
        self.path.unlink()
        self.panel.active_entries = []

        self.panel._load_initial_bookmarks()

        self.assertEqual({entry.watch_label for entry in self.panel.active_entries}, {'Calder', 'Matisse'})
        self.assertEqual(self.panel.selected_artists, set())
        self.assertEqual(self.panel._read_settings()['last_bookmark_path'], str(self.path.resolve()))
        self.service.assert_not_called()

    def test_restart_restores_selected_cached_agenda_and_keeps_old_observations(self):
        self.panel.load_bookmarks(self.path)
        self.panel.selected_artists = {'Calder'}
        self.panel._save_settings_hint()
        entries = {entry.watch_label: entry for entry in self.panel.active_entries}
        now = datetime.now(timezone.utc)
        current = replace(self.lot, artist='Calder', artist_watchlist_name='Calder', start_at=(now + timedelta(days=5)).isoformat())
        distant = replace(current, source_lot_id='distant', start_at=(now + timedelta(days=90)).isoformat())
        excluded = replace(current, source_lot_id='excluded', artist='Matisse', artist_watchlist_name='Matisse')
        ended = replace(current, source_lot_id='ended', start_at=(now - timedelta(days=90)).isoformat())
        with WatchlistCache(self.panel._cache_path) as cache:
            for lot, watch, active in ((current, 'Calder', True), (distant, 'Calder', True), (excluded, 'Matisse', True), (ended, 'Calder', False)):
                cache.upsert(lot, watch_url=entries[watch].url, search_hash='', observed_at=now - timedelta(days=2), active=active)

        self.panel._load_initial_bookmarks()

        self.assertEqual({lot.cache_key for lot in self.panel.current_lots}, {current.cache_key, ended.cache_key})
        self.assertEqual(self.panel.fallback_lot_keys, {current.cache_key, ended.cache_key})
        self.assertTrue(all(lot.last_seen_at == (now - timedelta(days=2)).isoformat() for lot in self.panel.current_lots))
        self.assertIn('2 saved lots loaded', self.panel.sync_status_var.get())
        self.service.assert_not_called()
        self.panel.calendar_syncer.assert_not_called()

    def test_coverage_does_not_count_blocked_zero_as_verified_empty(self):
        self.panel.selected_artists = {'Megargee', 'Kollwitz', 'Corinth', 'Garcia'}
        self.panel.artist_coverage = [
            WatchCoverage('Megargee', 'Invaluable', 'megargee', state='empty'),
            WatchCoverage('Kollwitz', 'Invaluable', 'kollwitz', state='verified', lot_count=7),
            WatchCoverage('Corinth', 'Invaluable', 'corinth', state='partial', lot_count=2),
            WatchCoverage('Garcia', 'Invaluable', 'garcia', state='blocked', lot_count=0),
        ]
        self.panel.coverage_summary_var = studio_tests.Value()
        self.panel.recover_pending_button = Mock()
        self.panel._update_coverage_display()

        self.assertEqual(self.panel.coverage_summary_var.get(), '4 artists · 1 verified · 1 no upcoming lots · 2 pending')
        self.panel.recover_pending_button.configure.assert_called_with(state=tk.NORMAL)
        self.panel._busy = True
        self.panel._update_coverage_display()
        self.panel.recover_pending_button.configure.assert_called_with(state=tk.DISABLED)

    def test_completed_coverage_disables_recovery(self):
        self.panel.selected_artists = {'Megargee'}
        self.panel.artist_coverage = [WatchCoverage('Megargee', 'Invaluable', 'megargee', state='empty')]
        self.panel.recover_pending_button = Mock()
        self.panel._update_coverage_display()

        self.panel.recover_pending_button.configure.assert_called_with(state=tk.DISABLED)

    def test_partial_coverage_keeps_persistent_report_without_repeating_modal(self):
        self.panel.load_bookmarks(self.path)
        result = WatchlistResult(
            [self.lot], WatchlistMetrics(), errors=['Invaluable catalog access is unavailable.'],
            coverage=[WatchCoverage('Calder', 'Invaluable', 'calder', state='partial', lot_count=1)],
        )
        self.panel._finish_refresh(result, sync_result=CalendarSyncResult(1, 1, 0, 0))

        self.assertIn('Calder (Invaluable): partial', self.panel._sync_details_text)
        self.assertIn('Recover pending', self.panel._sync_details_text)
        self.assertIn('incomplete', self.panel.sync_status_var.get())
        self.warning.assert_not_called()


class SavedWatchlistEmptyStateTests(TestCase):
    setUp = details_tests.WatchlistSyncDetailsTests.setUp

    def test_pending_artist_without_cache_does_not_claim_verified_zero(self):
        self.panel.selected_artists = {'Megargee'}
        self.panel.artist_coverage = [WatchCoverage('Megargee', 'Invaluable', 'megargee')]
        self.panel._fill_agenda()

        self.assertIn('Recover pending', self.panel.empty_state.cget('text'))
        self.assertNotIn('No upcoming lots found', self.panel.empty_state.cget('text'))

        self.panel.artist_coverage = [WatchCoverage('Megargee', 'Invaluable', 'megargee', state='empty')]
        self.panel._fill_agenda()
        self.assertEqual(self.panel.empty_state.cget('text'), 'No upcoming lots found for the selected artists.')

