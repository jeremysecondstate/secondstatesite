"""Offline regressions for the Studio import → calendar workflow."""

from contextlib import ExitStack
from dataclasses import replace
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

import tkinter as tk

from catalogapp.artprice_artist_links import ArtpriceMatchResult
from catalogapp.watchlist_fetch import HttpPageFetcher
from catalogapp.watchlist_models import NormalizedLot
from catalogapp.watchlist_service import WatchlistMetrics, WatchlistResult
from catalogapp.watchlist_sync import CalendarSyncResult
from catalogapp.watchlist_ui import ArtistWatchlistPanel


class Value:
    def __init__(self, value=None):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


def bookmarks(*artists):
    return (
        '<DL><DT><H3>ARTISTS INVALUABLE</H3><DL>'
        + ''.join(
            f'<DT><A HREF="https://www.invaluable.com/search?artistName={artist}">{artist}</A>'
            for artist in artists
        )
        + '</DL><DT><H3>OTHER</H3><DL>'
        '<DT><A HREF="https://www.liveauctioneers.com/search?keyword=Other">Other</A></DL></DL>'
    )


class StudioWatchlistControllerTests(TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.path = self.directory / 'artists.html'
        self.path.write_text(bookmarks('Calder', 'Matisse'), encoding='utf-8')
        self.panel = ArtistWatchlistPanel.__new__(ArtistWatchlistPanel)
        panel = self.panel
        panel.worker = None
        panel._busy = False
        panel._settings_path = self.directory / 'settings.json'
        panel._cache_path = self.directory / 'cache.sqlite3'
        panel._invaluable_profile_directory = self.directory / 'browser'
        panel.all_entries = []
        panel.active_entries = []
        panel.selected_artists = set()
        panel.folder_vars = {}
        panel.artist_artprice_links = {}
        panel.artprice_match_result = ArtpriceMatchResult({}, (), (), 0)
        panel.folder_controls = Mock(winfo_children=Mock(return_value=[]))
        panel.artist_tree = Mock(get_children=Mock(return_value=[]))
        panel.artist_filter_var = Value('')
        panel.bookmark_path_var = Value('')
        panel.bookmark_filename_var = Value('')
        panel.import_summary_var = Value('')
        panel.sync_status_var = Value('')
        panel.horizon_var = Value(30)
        panel.zero_ai_var = Value(False)  # Studio always uses deterministic parsing.
        panel.new_changed_var = Value(True)  # Studio sync always sends the full selected agenda.
        panel.invaluable_session_var = Value(True)  # Old saved opt-in must be ignored.
        panel.current_lots = []
        panel.fallback_lot_keys = set()
        panel.source_refresh_errors = []
        panel.service_factory = None
        panel.calendar_base_url = 'https://calendar.example'
        panel.calendar_api_key = 'offline-test-key'
        panel.calendar_syncer = Mock(return_value=CalendarSyncResult(1, 1, 0, 0))
        panel._calendar_sync_configured = Mock(return_value=True)
        panel.status_callback = Mock()
        panel.after = lambda _delay, callback: callback()
        panel._fill_agenda = Mock()
        for name in ('sync_to_calendar_button', 'stop_button', 'import_bookmarks_button', 'review_button',
                     'more_button', 'metrics_var', 'retry_browser_button', 'import_invaluable_button'):
            setattr(panel, name, Mock())
        panel.refresh_button = panel.calendar_sync_button = panel.sync_to_calendar_button
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch('catalogapp.watchlist_ui.tk.BooleanVar', side_effect=Value))
        self.stack.enter_context(patch('catalogapp.watchlist_ui.ttk.Checkbutton'))
        self.stack.enter_context(patch('catalogapp.watchlist_ui.ttk.Label'))
        self.stack.enter_context(patch('catalogapp.watchlist_ui.local_watchlist_directory', return_value=self.directory))
        self.stack.enter_context(patch('catalogapp.watchlist_ui.threading.Thread', side_effect=self.immediate_thread))
        self.warning = self.stack.enter_context(patch('catalogapp.watchlist_ui.messagebox.showwarning'))
        self.error = self.stack.enter_context(patch('catalogapp.watchlist_ui.messagebox.showerror'))
        self.info = self.stack.enter_context(patch('catalogapp.watchlist_ui.messagebox.showinfo'))
        self.browser = self.stack.enter_context(patch('catalogapp.watchlist_ui.InvaluableBrowserFetcher'))
        self.public_browser = self.stack.enter_context(patch('catalogapp.watchlist_ui.InvaluablePublicBrowserFetcher'))
        self.profiles = self.stack.enter_context(patch('catalogapp.watchlist_ui.chrome_profiles'))
        self.service = self.stack.enter_context(patch('catalogapp.watchlist_ui.WatchlistService'))
        self.lot = NormalizedLot(
            source='Invaluable', source_lot_id='test-1', artist='Zúñiga', artist_watchlist_name='Zúñiga',
            title='Print', start_at='2026-10-22',
        )
        self.service.return_value.refresh.return_value = WatchlistResult([self.lot], WatchlistMetrics(new_lots=1))

    @staticmethod
    def immediate_thread(*, target, **_kwargs):
        worker = Mock()
        worker.is_alive.return_value = False
        worker.start.side_effect = target
        return worker

    def test_import_is_local_and_remembers_the_selected_file(self):
        with patch('catalogapp.watchlist_ui.filedialog.askopenfilename', return_value=str(self.path)):
            self.panel.import_bookmarks()
        self.assertEqual(self.panel.selected_artists, {'Calder', 'Matisse'})
        self.assertEqual(self.panel.bookmark_filename_var.get(), 'artists.html')
        self.assertEqual(self.panel._read_settings()['last_bookmark_path'], str(self.path.resolve()))
        self.assertIn('Bookmarks imported', self.panel.sync_status_var.get())
        self.service.assert_not_called()
        self.panel.calendar_syncer.assert_not_called()
        self.browser.assert_not_called()
        self.public_browser.assert_not_called()

    def test_sync_reloads_edited_file_preserves_choices_and_fetches_before_upload(self):
        self.panel.load_bookmarks(self.path)
        self.panel.selected_artists.remove('Matisse')
        self.path.write_text(bookmarks('Calder', 'Matisse', 'Zúñiga'), encoding='utf-8')
        order = []

        def refresh(entries, **kwargs):
            order.append('fetch')
            self.assertEqual(kwargs['selected_artists'], {'Calder', 'Zúñiga'})
            self.assertEqual({entry.watch_label for entry in entries}, {'Calder', 'Matisse', 'Zúñiga'})
            self.assertTrue(kwargs['zero_ai'])
            self.assertFalse(kwargs['new_changed_only'])
            self.assertEqual(kwargs['horizon_days'], 30)
            self.assertFalse(self.panel.folder_vars['OTHER'].get())
            return WatchlistResult([self.lot], WatchlistMetrics(new_lots=1))

        def upload(lots, **kwargs):
            order.append('upload')
            self.assertEqual(lots, [self.lot])
            self.assertEqual(kwargs['base_url'], 'https://calendar.example')
            return CalendarSyncResult(1, 1, 0, 0)

        self.service.return_value.refresh.side_effect = refresh
        self.panel.calendar_syncer.side_effect = upload
        self.panel.sync_to_calendar()
        self.assertEqual(order, ['fetch', 'upload'])
        self.assertIsNone(self.service.call_args.kwargs['invaluable_fetcher'])
        self.browser.assert_not_called()
        self.public_browser.assert_not_called()
        self.profiles.assert_not_called()
        self.assertEqual(self.panel.current_lots, [self.lot])
        self.assertIn('Website calendar synced', self.panel.sync_status_var.get())
        self.assertFalse(self.panel._busy)
        self.panel.stop_button.grid_remove.assert_called()

    def test_all_deselected_artists_stay_deselected_on_reload(self):
        self.panel.load_bookmarks(self.path)
        self.panel.selected_artists.clear()
        self.panel.sync_to_calendar()
        self.assertEqual(self.panel.selected_artists, set())
        self.service.assert_not_called()
        self.panel.calendar_syncer.assert_not_called()
        self.assertEqual(self.warning.call_args.args[0], 'No Selection')

    def test_old_playwright_environment_opt_in_cannot_select_a_browser_fetcher(self):
        self.panel.load_bookmarks(self.path)
        with (
            patch.dict(os.environ, {'WATCHLIST_USE_PLAYWRIGHT': '1', 'WATCHLIST_PLAYWRIGHT_PROFILE': 'unused'}),
            patch('catalogapp.watchlist_fetch.ControlledPlaywrightFetcher') as browser_factory,
        ):
            self.panel.sync_to_calendar()
        fetcher = self.service.call_args.kwargs['fetcher']
        self.assertIsInstance(fetcher, HttpPageFetcher)
        self.assertIs(fetcher.stop_event, self.panel.stop_event)
        self.assertIsNone(self.service.call_args.kwargs['invaluable_fetcher'])
        browser_factory.assert_not_called()
        self.browser.assert_not_called()
        self.public_browser.assert_not_called()

    def test_browser_retry_reloads_selection_and_closes_both_fetchers_before_upload(self):
        self.panel.load_bookmarks(self.path)
        self.panel.selected_artists.remove('Matisse')
        self.path.write_text(bookmarks('Calder', 'Matisse', 'Zúñiga'), encoding='utf-8')
        self.panel.source_refresh_errors = ['Invaluable returned HTTP 202.']
        http = Mock()
        order = []

        def refresh(entries, **kwargs):
            order.append('fetch')
            self.assertEqual(kwargs['selected_artists'], {'Calder', 'Zúñiga'})
            self.assertEqual({entry.watch_label for entry in entries}, {'Calder', 'Matisse', 'Zúñiga'})
            self.assertTrue(kwargs['zero_ai'])
            self.assertFalse(kwargs['new_changed_only'])
            self.assertTrue(self.panel._busy)
            self.panel.retry_browser_button.configure.assert_called_with(state=tk.DISABLED)
            self.assertEqual(self.panel.sync_status_var.get(), 'Opening browser to retrieve Invaluable lots…')
            return WatchlistResult([self.lot], WatchlistMetrics(new_lots=1))

        def upload(lots, **_kwargs):
            order.append('upload')
            self.public_browser.return_value.close.assert_called_once()
            http.session.close.assert_called_once()
            self.assertEqual(lots, [self.lot])
            return CalendarSyncResult(1, 1, 0, 0)

        self.service.return_value.refresh.side_effect = refresh
        self.panel.calendar_syncer.side_effect = upload
        with (
            patch.dict(os.environ, {'WATCHLIST_USE_PLAYWRIGHT': '1', 'WATCHLIST_PLAYWRIGHT_PROFILE': 'unused'}),
            patch('catalogapp.watchlist_ui.HttpPageFetcher', return_value=http) as http_factory,
        ):
            self.panel.retry_with_browser()
        self.assertEqual(order, ['fetch', 'upload'])
        self.assertEqual(self.public_browser.call_args.args, (self.directory / 'invaluable-public-browser',))
        self.assertIs(self.public_browser.call_args.kwargs['stop_event'], self.panel.stop_event)
        self.assertIs(self.public_browser.call_args.kwargs['headless'], False)
        self.assertTrue(callable(self.public_browser.call_args.kwargs['progress']))
        http_factory.assert_called_once_with(stop_event=self.panel.stop_event)
        self.assertIs(self.service.call_args.kwargs['fetcher'], http)
        self.assertIs(self.service.call_args.kwargs['invaluable_fetcher'], self.public_browser.return_value)
        self.browser.assert_not_called()
        self.profiles.assert_not_called()
        self.assertFalse(self.panel._busy)
        self.assertEqual(self.panel.source_refresh_errors, [])
        self.panel.retry_browser_button.grid_remove.assert_called()
        self.assertTrue(self.panel._read_settings()['invaluable_session_enabled'])

        # The explicit retry does not change subsequent ordinary syncs.
        self.service.return_value.refresh.side_effect = None
        self.panel.calendar_syncer.side_effect = None
        self.panel.sync_to_calendar()
        self.assertEqual(self.public_browser.call_count, 1)
        self.assertIsInstance(self.service.call_args.kwargs['fetcher'], HttpPageFetcher)
        self.assertIsNone(self.service.call_args.kwargs['invaluable_fetcher'])

    def test_cancelled_browser_retry_closes_browser_and_does_not_upload(self):
        self.panel.load_bookmarks(self.path)
        self.panel.source_refresh_errors = ['Invaluable returned HTTP 202.']

        def stopped_refresh(*_args, **_kwargs):
            self.panel.stop_refresh()
            return WatchlistResult([self.lot], WatchlistMetrics())

        self.service.return_value.refresh.side_effect = stopped_refresh
        self.panel.retry_with_browser()
        self.public_browser.return_value.close.assert_called_once()
        self.panel.calendar_syncer.assert_not_called()
        self.assertFalse(self.panel._busy)
        self.assertIn('stopped', self.panel.sync_status_var.get())

    def test_browser_retry_failure_preserves_retry_and_cached_result(self):
        self.panel.load_bookmarks(self.path)
        self.panel.current_lots = [self.lot]
        self.panel.source_refresh_errors = ['Invaluable returned HTTP 202.']
        self.public_browser.side_effect = RuntimeError('Invaluable browser could not open.')
        self.panel.retry_with_browser()
        self.panel.calendar_syncer.assert_not_called()
        self.assertEqual(self.panel.current_lots, [self.lot])
        self.assertFalse(self.panel._busy)
        self.panel.retry_browser_button.grid.assert_called()
        self.panel.retry_browser_button.configure.assert_called_with(state=tk.NORMAL)
        self.assertIn('Invaluable browser could not open', self.panel._sync_details_text)

    def test_browser_retry_missing_bookmark_file_does_not_open_browser(self):
        self.panel.load_bookmarks(self.path)
        self.path.unlink()
        self.panel.retry_with_browser()
        self.public_browser.assert_not_called()
        self.service.assert_not_called()
        self.panel.calendar_syncer.assert_not_called()
        self.assertEqual(self.error.call_args.args[0], 'Bookmark Import Failed')

    def test_invaluable_import_reloads_selection_merges_observations_and_syncs(self):
        self.panel.load_bookmarks(self.path)
        self.panel.selected_artists.remove('Matisse')
        self.path.write_text(bookmarks('Calder', 'Matisse', 'Zúñiga'), encoding='utf-8')
        observed = replace(self.lot, title='Fresh print')
        absent = replace(self.lot, source_lot_id='unobserved', title='Older print')
        other = replace(self.lot, source='Heritage', source_lot_id='other', title='Other source')
        self.panel.current_lots = [self.lot, absent, other]
        self.panel.fallback_lot_keys = {lot.cache_key for lot in self.panel.current_lots}
        failure = 'Invaluable returned HTTP 202; live refresh remains unavailable.'
        self.panel.source_refresh_errors = [failure]
        paths = ('calder.html', 'zuniga.json')
        order = []

        def imported(selected_paths, *, entries, cache, horizon_days, new_changed_only):
            order.append('import')
            self.assertEqual(selected_paths, paths)
            self.assertEqual({entry.watch_label for entry in entries}, {'Calder', 'Zúñiga'})
            self.assertTrue(all(entry.source == 'Invaluable' for entry in entries))
            self.assertEqual(horizon_days, 30)
            self.assertFalse(new_changed_only)
            self.assertTrue(self.panel._busy)
            self.panel.import_invaluable_button.configure.assert_called_with(state=tk.DISABLED)
            return WatchlistResult(
                [observed, absent], WatchlistMetrics(new_lots=1),
                fallback_lot_keys={absent.cache_key}, notices=['Imported one saved snapshot.'],
            )

        def uploaded(lots, **_kwargs):
            order.append('upload')
            self.assertEqual({lot.cache_key for lot in lots}, {observed.cache_key, absent.cache_key, other.cache_key})
            return CalendarSyncResult(3, 1, 2, 0)

        self.panel.calendar_syncer.side_effect = uploaded
        with (
            patch('catalogapp.watchlist_ui.filedialog.askopenfilenames', return_value=paths),
            patch('catalogapp.watchlist_ui.import_saved_invaluable_pages', side_effect=imported),
        ):
            self.panel.import_saved_invaluable_pages()
        self.assertEqual(order, ['import', 'upload'])
        self.assertEqual(self.panel.fallback_lot_keys, {absent.cache_key, other.cache_key})
        self.assertEqual(self.panel.source_refresh_errors, [failure])
        self.assertEqual(next(lot.title for lot in self.panel.current_lots if lot.cache_key == observed.cache_key), 'Fresh print')
        self.assertIn('Imported one saved snapshot.', self.panel._sync_details_text)
        self.assertFalse(self.panel._busy)
        self.panel.import_invaluable_button.configure.assert_called_with(state=tk.NORMAL)
        self.service.assert_not_called()
        self.public_browser.assert_not_called()

    def test_invaluable_import_missing_bookmarks_preserves_results_and_skips_picker(self):
        self.panel.load_bookmarks(self.path)
        self.panel.current_lots = [self.lot]
        self.path.unlink()
        with patch('catalogapp.watchlist_ui.filedialog.askopenfilenames') as picker:
            self.panel.import_saved_invaluable_pages()
        picker.assert_not_called()
        self.panel.calendar_syncer.assert_not_called()
        self.assertEqual(self.panel.current_lots, [self.lot])
        self.assertEqual(self.error.call_args.args[0], 'Bookmark Import Failed')

    def test_invaluable_import_cancelled_or_without_selected_artists_does_not_upload(self):
        self.panel.load_bookmarks(self.path)
        with (
            patch('catalogapp.watchlist_ui.filedialog.askopenfilenames', return_value=()) as picker,
            patch('catalogapp.watchlist_ui.import_saved_invaluable_pages') as importer,
        ):
            self.panel.import_saved_invaluable_pages()
            picker.assert_called_once()
            self.panel.selected_artists.clear()
            self.panel.import_saved_invaluable_pages()
            picker.assert_called_once()
        importer.assert_not_called()
        self.panel.calendar_syncer.assert_not_called()
        self.assertFalse(self.panel._busy)
        self.assertEqual(self.warning.call_args.args[0], 'Select Invaluable Artists')

    def test_invaluable_import_failure_retains_previous_results_and_reenables_controls(self):
        self.panel.load_bookmarks(self.path)
        self.panel.current_lots = [self.lot]
        self.panel.source_refresh_errors = ['Invaluable HTTP 202.']
        with (
            patch('catalogapp.watchlist_ui.filedialog.askopenfilenames', return_value=('bad.html',)),
            patch('catalogapp.watchlist_ui.import_saved_invaluable_pages', side_effect=ValueError('Unreadable snapshot')),
        ):
            self.panel.import_saved_invaluable_pages()
        self.panel.calendar_syncer.assert_not_called()
        self.assertEqual(self.panel.current_lots, [self.lot])
        self.assertFalse(self.panel._busy)
        self.panel.import_invaluable_button.configure.assert_called_with(state=tk.NORMAL)
        self.assertIn('Unreadable snapshot', self.panel._sync_details_text)

    def test_missing_file_keeps_existing_lots_and_does_not_upload_stale_results(self):
        self.panel.load_bookmarks(self.path)
        self.panel.current_lots = [self.lot]
        self.path.unlink()
        self.panel.sync_to_calendar()
        self.service.assert_not_called()
        self.panel.calendar_syncer.assert_not_called()
        self.assertEqual(self.panel.current_lots, [self.lot])
        self.assertEqual(self.error.call_args.args[0], 'Bookmark Import Failed')

    def test_cached_upload_keeps_source_failure_and_missing_artist_visible(self):
        self.panel.load_bookmarks(self.path)
        self.service.return_value.refresh.return_value = WatchlistResult(
            [self.lot], WatchlistMetrics(cache_hits=1),
            errors=['Invaluable HTTP 202; no cached lots for Francisco Zúñiga.'],
            fallback_lot_keys={self.lot.cache_key},
        )
        self.panel.sync_to_calendar()
        self.panel.calendar_syncer.assert_called_once()
        self.assertEqual(self.panel.fallback_lot_keys, {self.lot.cache_key})
        self.assertIn('Francisco Zúñiga', self.warning.call_args.args[1])
        self.assertIn('live data was not verified', self.panel.sync_status_var.get())
        self.assertIn('Live source refresh remains incomplete', self.panel.sync_status_var.get())

    def test_long_access_warning_is_compact_and_full_errors_remain_in_details(self):
        failure = 'Invaluable HTTP 202. ' + 'Repeated diagnostic detail. ' * 80 + 'Missing artist at end.'
        self.panel._finish_refresh(
            WatchlistResult([self.lot], WatchlistMetrics(), errors=[failure]),
            sync_result=CalendarSyncResult(1, 0, 1, 0),
        )
        warning = self.warning.call_args.args[1]
        self.assertIn('Import saved Invaluable pages', warning)
        self.assertLess(len(warning), 900)
        self.assertIn(failure, self.panel._sync_details_text)

    def test_compact_access_warning_keeps_separate_missing_artist_error(self):
        failure = 'Invaluable HTTP 202. ' + 'Repeated diagnostic detail. ' * 80
        missing = 'No cached lots are available for calendar sync for: Francisco Zúñiga, Alonzo Megargee.'
        self.panel._finish_refresh(
            WatchlistResult([self.lot], WatchlistMetrics(), errors=[failure, missing]),
            sync_result=CalendarSyncResult(1, 0, 1, 0),
        )
        warning = self.warning.call_args.args[1]
        self.assertIn('Francisco Zúñiga', warning)
        self.assertIn('Alonzo Megargee', warning)
        self.assertIn('Artists without retrieved or cached lots cannot appear on the calendar yet', warning)
        self.assertIn('Sync to Calendar', warning)
        self.assertLess(len(warning), 1100)
        self.assertIn(failure, self.panel._sync_details_text)
        self.assertIn(missing, self.panel._sync_details_text)

    def test_unavailable_source_without_cached_lots_does_not_claim_a_sync(self):
        self.panel.load_bookmarks(self.path)
        self.service.return_value.refresh.return_value = WatchlistResult(
            [], WatchlistMetrics(), errors=['Invaluable HTTP 202; no cached lots for Francisco Zúñiga.'],
        )
        self.panel.sync_to_calendar()
        self.panel.calendar_syncer.assert_not_called()
        self.assertIn('Francisco Zúñiga', self.warning.call_args.args[1])
        self.assertIn('website calendar was not synced', self.panel.sync_status_var.get())

    def test_upload_failure_keeps_lots_and_reenables_the_single_sync_button(self):
        self.panel.load_bookmarks(self.path)
        self.panel.calendar_syncer.side_effect = RuntimeError('Calendar is temporarily unavailable')
        self.panel.sync_to_calendar()
        self.assertEqual(self.panel.current_lots, [self.lot])
        self.assertFalse(self.panel._busy)
        self.panel.sync_to_calendar_button.configure.assert_called_with(state=tk.NORMAL)
        self.assertIn('sync incomplete', self.panel.sync_status_var.get())
        self.panel.calendar_syncer.side_effect = None
        self.panel.sync_to_calendar()
        self.assertEqual(self.panel.calendar_syncer.call_count, 2)
        self.assertIn('Website calendar synced', self.panel.sync_status_var.get())

    def test_stop_after_fetch_prevents_upload_and_allows_retry(self):
        self.panel.load_bookmarks(self.path)

        def stopped_refresh(*_args, **_kwargs):
            self.panel.stop_refresh()
            return WatchlistResult([self.lot], WatchlistMetrics())

        self.service.return_value.refresh.side_effect = stopped_refresh
        self.panel.sync_to_calendar()
        self.panel.calendar_syncer.assert_not_called()
        self.assertFalse(self.panel._busy)
        self.assertIn('stopped', self.panel.sync_status_var.get())
        self.service.return_value.refresh.side_effect = None
        self.panel.sync_to_calendar()
        self.panel.calendar_syncer.assert_called_once()

    def test_busy_import_and_sync_cannot_start_conflicting_work(self):
        self.panel._busy = True
        with (
            patch('catalogapp.watchlist_ui.filedialog.askopenfilename') as picker,
            patch('catalogapp.watchlist_ui.filedialog.askopenfilenames') as pages_picker,
        ):
            self.panel.import_bookmarks()
            self.panel.sync_to_calendar()
            self.panel.retry_with_browser()
            self.panel.import_saved_invaluable_pages()
        picker.assert_not_called()
        pages_picker.assert_not_called()
        self.service.assert_not_called()
        self.public_browser.assert_not_called()

    def test_startup_prefers_remembered_file_then_project_then_legacy(self):
        project = self.directory / 'project.html'
        legacy = self.directory / 'legacy.html'
        project.write_text(bookmarks('Project'), encoding='utf-8')
        legacy.write_text(bookmarks('Legacy'), encoding='utf-8')
        self.panel._settings_path.write_text(json.dumps({'last_bookmark_path': str(self.path)}), encoding='utf-8')
        with (
            patch('catalogapp.watchlist_ui.PROJECT_BOOKMARK_PATH', project),
            patch('catalogapp.watchlist_ui.DEFAULT_BOOKMARK_PATH', legacy),
        ):
            self.panel._load_initial_bookmarks()
            self.assertEqual(self.panel.selected_artists, {'Calder', 'Matisse'})
            self.path.unlink()
            self.panel._load_initial_bookmarks()
            self.assertEqual(self.panel.selected_artists, {'Project'})
            project.unlink()
            self.panel._load_initial_bookmarks()
            self.assertEqual(self.panel.selected_artists, {'Legacy'})


class StudioWatchlistWidgetTests(TestCase):
    def test_compact_estimate_tolerates_legacy_missing_currency(self):
        lot = NormalizedLot(
            source="Invaluable", source_lot_id="legacy-null-currency", artist="Calder",
            artist_watchlist_name="Calder", title="Print", estimate_low=100,
            estimate_high=200, currency=None,
        )
        self.assertEqual(ArtistWatchlistPanel._compact_estimate(lot), "100–200")

    def test_default_panel_hides_legacy_controls_and_does_not_inspect_chrome(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f'Tk display unavailable: {exc}')
        root.withdraw()
        self.addCleanup(root.destroy)
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        with (
            patch('catalogapp.watchlist_ui.local_watchlist_directory', return_value=Path(temporary.name)),
            patch.object(ArtistWatchlistPanel, '_load_initial_bookmarks'),
            patch('catalogapp.watchlist_ui.chrome_profiles') as profiles,
        ):
            panel = ArtistWatchlistPanel(root)
            self.assertEqual(panel.horizon_var.get(), 30)
            self.assertTrue(panel.zero_ai_var.get())
            self.assertFalse(panel.review_frame.winfo_manager())
            self.assertFalse(panel.stop_button.winfo_manager())
            self.assertFalse(panel.retry_browser_button.winfo_manager())
            self.assertFalse(panel.import_invaluable_button.winfo_manager())
            labels = [panel.more_menu.entrycget(index, 'label') for index in range(panel.more_menu.index('end') + 1)
                      if panel.more_menu.type(index) == 'command']
            self.assertIn('Import saved Invaluable pages…', labels)
            self.assertEqual(panel.sync_to_calendar_button.cget('text'), 'Sync to Calendar')
            self.assertNotIn('connect_invaluable_button', panel.__dict__)
            self.assertNotIn('chrome_profile_picker', panel.__dict__)
            profiles.assert_not_called()
            panel.source_refresh_errors = ['Invaluable returned HTTP 202.']
            panel._set_sync_details('Invaluable is blocked.')
            self.assertEqual(panel.import_invaluable_button.winfo_manager(), 'grid')
            panel._set_import_buttons_state(tk.DISABLED)
            self.assertEqual(str(panel.import_invaluable_button.cget('state')), tk.DISABLED)
            panel._set_import_buttons_state(tk.NORMAL)
            self.assertEqual(str(panel.import_invaluable_button.cget('state')), tk.NORMAL)
            panel.source_refresh_errors = ['Heritage returned HTTP 403.']
            panel._set_sync_details('Only Heritage is blocked.')
            self.assertFalse(panel.import_invaluable_button.winfo_manager())
            panel._toggle_review()
            self.assertEqual(panel.review_frame.winfo_manager(), 'grid')
