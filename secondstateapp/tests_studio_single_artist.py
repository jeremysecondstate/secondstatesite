"""Exercise per-artist Calendar actions without refreshing the whole watchlist."""

from dataclasses import replace
from unittest import TestCase
from unittest.mock import Mock, patch

from catalogapp.watchlist_service import WatchCoverage, WatchlistMetrics, WatchlistResult
from catalogapp.watchlist_sync import CalendarSyncResult
from secondstateapp import tests_studio_watchlist as studio_tests
from secondstateapp import tests_watchlist_sync_details as details_tests


class SingleArtistControllerTests(TestCase):
    immediate_thread = staticmethod(studio_tests.StudioWatchlistControllerTests.immediate_thread)

    def setUp(self):
        studio_tests.StudioWatchlistControllerTests.setUp(self)
        self.path.write_text(studio_tests.bookmarks('Calder', 'Matisse', 'Will Barnet'), encoding='utf-8')
        self.panel.load_bookmarks(self.path)
        self.target = 'Will Barnet'
        self.entries = {entry.watch_label: entry for entry in self.panel.active_entries}
        # A row action is an explicit choice, independent of the bulk selection.
        self.panel.selected_artists = {'Calder'}
        self.target_lot = replace(self.lot, source_lot_id='will-one', artist=self.target,
                                  artist_watchlist_name=self.target, title='Fresh Will Barnet print')
        self.other_lot = replace(self.lot, source_lot_id='calder-one', artist='Calder',
                                 artist_watchlist_name='Calder', title='Retained Calder print')
        self.other_coverage = WatchCoverage(
            'Calder', 'Invaluable', self.entries['Calder'].url, state='blocked', lot_count=1,
            checked_at='2026-10-16T12:00:00+00:00', detail='Previous source block',
        )
        self.target_coverage = WatchCoverage(
            self.target, 'Invaluable', self.entries[self.target].url, state='verified', lot_count=1,
            checked_at='2026-10-17T12:00:00+00:00',
        )
        self.panel.current_lots = [self.other_lot]
        self.panel.fallback_lot_keys = {self.other_lot.cache_key}
        self.panel.artist_coverage = [self.other_coverage]
        self.panel.artist_artprice_links = {
            self.target: 'https://www.artprice.com/artist/1474/will-r-barnet',
            'Calder': 'https://www.artprice.com/artist/3089/alexander-calder',
        }
        self.service.return_value.refresh.return_value = self.fresh_result()

    def fresh_result(self):
        return WatchlistResult(
            [self.target_lot], WatchlistMetrics(artists=1, bookmark_urls=1, new_lots=1),
            coverage=[self.target_coverage],
        )

    def assert_only_target_requested(self):
        entries = self.service.return_value.refresh.call_args.args[0]
        options = self.service.return_value.refresh.call_args.kwargs
        self.assertEqual(entries, [self.entries[self.target]])
        self.assertEqual(options['selected_artists'], {self.target})
        self.assertTrue(options['zero_ai'])
        self.assertFalse(options['new_changed_only'])

    def assert_other_display_retained(self):
        self.assertIn(self.other_lot, self.panel.current_lots)
        self.assertIn(self.other_lot.cache_key, self.panel.fallback_lot_keys)
        self.assertIn(self.other_coverage, self.panel.artist_coverage)

    def test_sync_row_fetches_and_uploads_only_artist_without_changing_bulk_selection(self):
        self.panel.sync_artist(self.target)

        self.assert_only_target_requested()
        self.panel.calendar_syncer.assert_called_once()
        self.assertEqual(self.panel.calendar_syncer.call_args.args[0], [self.target_lot])
        self.assertEqual(self.panel.calendar_syncer.call_args.kwargs['artist_artprice_links'], {
            self.target: self.panel.artist_artprice_links[self.target],
        })
        self.assertEqual(self.panel.selected_artists, {'Calder'})
        self.assertEqual(self.panel._last_artist_scope, {self.target})
        self.assertEqual({lot.cache_key for lot in self.panel.current_lots},
                         {self.target_lot.cache_key, self.other_lot.cache_key})
        self.assert_other_display_retained()
        self.assertIn(self.target_coverage, self.panel.artist_coverage)
        self.assertNotIn(self.target_lot.cache_key, self.panel.fallback_lot_keys)
        self.assertIn('Will Barnet only.', self.panel.sync_status_var.get())
        self.assertFalse(self.panel._busy)
        self.error.assert_not_called()

    def test_blocked_new_artist_does_not_upload_unrelated_agenda(self):
        blocked = replace(self.target_coverage, state='blocked', lot_count=0)
        self.service.return_value.refresh.return_value = WatchlistResult(
            [], WatchlistMetrics(artists=1), errors=['Will Barnet (Invaluable): HTTP 202'],
            coverage=[blocked],
        )

        self.panel.sync_artist(self.target)

        self.assert_only_target_requested()
        self.panel.calendar_syncer.assert_not_called()
        self.assertEqual(self.panel.current_lots, [self.other_lot])
        self.assert_other_display_retained()
        self.assertIn(blocked, self.panel.artist_coverage)
        self.assertIn('Will Barnet only.', self.panel.sync_status_var.get())
        self.assertIn('No lots were available to upload', self.panel.sync_status_var.get())
        self.assertEqual(self.panel.selected_artists, {'Calder'})
        self.error.assert_not_called()

    def test_browser_retry_reuses_only_failed_artist_scope(self):
        self.panel._last_artist_scope = {self.target}
        self.panel.source_refresh_errors = ['Will Barnet (Invaluable): HTTP 202']

        self.panel.retry_with_browser()

        self.assert_only_target_requested()
        self.public_browser.assert_called_once()
        self.public_browser.return_value.close.assert_called_once()
        self.assertEqual(self.panel.calendar_syncer.call_args.args[0], [self.target_lot])
        self.assertEqual(self.panel.selected_artists, {'Calder'})
        self.assert_other_display_retained()

    def test_usual_browser_helper_and_delayed_callback_preserve_artist_scope(self):
        self.panel._last_artist_scope = {self.target}
        self.panel.import_saved_invaluable_pages = Mock()

        with patch('catalogapp.watchlist_ui.show_browser_helper') as helper:
            self.panel.use_regular_browser()

        helper.assert_called_once()
        self.assertEqual(helper.call_args.args[1], [self.entries[self.target]])
        self.panel.import_saved_invaluable_pages.assert_not_called()
        # Opening another row later cannot retarget this helper's import.
        self.panel._last_artist_scope = {'Matisse'}
        helper.call_args.kwargs['import_snapshots']()
        self.panel.import_saved_invaluable_pages.assert_called_once_with(artist_scope={self.target})
        self.assertEqual(self.panel.selected_artists, {'Calder'})
        self.panel.calendar_syncer.assert_not_called()
        self.service.assert_not_called()

    def test_explicit_usual_browser_artist_overrides_previous_failed_artist(self):
        self.panel._last_artist_scope = {'Matisse'}
        self.panel.import_saved_invaluable_pages = Mock()

        with patch('catalogapp.watchlist_ui.show_browser_helper') as helper:
            self.panel.use_regular_browser(artist_scope={self.target})

        self.assertEqual(helper.call_args.args[1], [self.entries[self.target]])
        helper.call_args.kwargs['import_snapshots']()
        self.panel.import_saved_invaluable_pages.assert_called_once_with(artist_scope={self.target})
        self.assertEqual(self.panel._last_artist_scope, {self.target})

    def test_snapshot_import_uploads_only_target_and_preserves_unrelated_display(self):
        retained_target = replace(self.target_lot, source_lot_id='will-retained', title='Unobserved older print')
        self.panel.current_lots.append(retained_target)
        self.panel.fallback_lot_keys.add(retained_target.cache_key)
        self.panel.source_refresh_errors = [
            'Will Barnet (Invaluable): HTTP 202', 'Calder (Invaluable): HTTP 202',
        ]
        paths = ('will-barnet.json',)
        self.panel.calendar_syncer.return_value = CalendarSyncResult(2, 1, 1, 0)

        with (
            patch('catalogapp.watchlist_ui.filedialog.askopenfilenames', return_value=paths),
            patch('catalogapp.watchlist_ui.import_saved_invaluable_pages', return_value=self.fresh_result()) as importer,
        ):
            self.panel.import_saved_invaluable_pages(artist_scope={self.target})

        self.assertEqual(importer.call_args.args[0], paths)
        self.assertEqual(importer.call_args.kwargs['entries'], [self.entries[self.target]])
        self.assertEqual({lot.cache_key for lot in self.panel.calendar_syncer.call_args.args[0]},
                         {self.target_lot.cache_key, retained_target.cache_key})
        self.assert_other_display_retained()
        self.assertIn(retained_target.cache_key, self.panel.fallback_lot_keys)
        self.assertNotIn(self.target_lot.cache_key, self.panel.fallback_lot_keys)
        self.assertIn(self.target_lot, self.panel.current_lots)
        self.assertEqual(self.panel.selected_artists, {'Calder'})
        self.assertEqual(self.panel._last_artist_scope, {self.target})
        self.assertEqual(self.panel.source_refresh_errors, ['Will Barnet (Invaluable): HTTP 202'])
        self.service.assert_not_called()
        self.error.assert_not_called()

    def test_snapshot_import_without_argument_reuses_failed_artist_scope(self):
        self.panel._last_artist_scope = {self.target}
        with (
            patch('catalogapp.watchlist_ui.filedialog.askopenfilenames', return_value=('will.json',)),
            patch('catalogapp.watchlist_ui.import_saved_invaluable_pages', return_value=self.fresh_result()) as importer,
        ):
            self.panel.import_saved_invaluable_pages()

        self.assertEqual(importer.call_args.kwargs['entries'], [self.entries[self.target]])
        self.assertEqual(self.panel.calendar_syncer.call_args.args[0], [self.target_lot])
        self.assert_other_display_retained()

    def test_bulk_update_clears_previous_artist_scope(self):
        self.panel._last_artist_scope = {self.target}

        self.panel.sync_to_calendar()

        self.assertIsNone(self.panel._last_artist_scope)
        self.assertEqual(self.service.return_value.refresh.call_args.kwargs['selected_artists'], {'Calder'})
        self.assertEqual({entry.watch_label for entry in self.service.return_value.refresh.call_args.args[0]},
                         {'Calder', 'Matisse', self.target})

    def test_busy_actions_do_not_read_import_fetch_or_upload(self):
        self.panel._last_artist_scope = {self.target}
        for worker_alive in (False, True):
            with self.subTest(worker_alive=worker_alive):
                self.panel._busy = not worker_alive
                self.panel.worker = Mock(is_alive=Mock(return_value=worker_alive))
                with (
                    patch.object(self.panel, '_load_watchlist_for_update') as load,
                    patch('catalogapp.watchlist_ui.show_browser_helper') as helper,
                    patch('catalogapp.watchlist_ui.filedialog.askopenfilenames') as picker,
                ):
                    self.panel.sync_artist(self.target)
                    self.panel.retry_with_browser()
                    self.panel.use_regular_browser(artist_scope={self.target})
                    self.panel.import_saved_invaluable_pages(artist_scope={self.target})
                load.assert_not_called()
                helper.assert_not_called()
                picker.assert_not_called()
        self.service.assert_not_called()
        self.panel.calendar_syncer.assert_not_called()
        self.assertEqual(self.panel.selected_artists, {'Calder'})
        self.assertEqual(self.panel._last_artist_scope, {self.target})
        self.assert_other_display_retained()

    def test_unknown_artist_cannot_fall_back_to_bulk_selection(self):
        self.panel.sync_artist('No saved bookmark')

        self.service.assert_not_called()
        self.panel.calendar_syncer.assert_not_called()
        self.assertIn('Scan the artist’s bookmark HTML first', self.panel.sync_status_var.get())
        self.assert_other_display_retained()


class SingleArtistStatusWidgetTests(TestCase):
    """The second status update after merging the agenda must retain upload scope."""

    def setUp(self):
        details_tests.WatchlistSyncDetailsTests.setUp(self)
        self.target = replace(
            self.lot, source_lot_id='will-one', artist='Will Barnet', artist_watchlist_name='Will Barnet',
            last_seen_at='2026-10-17T12:00:00+00:00',
        )
        self.panel.current_lots = [self.lot]
        self.panel.fallback_lot_keys = {self.lot.cache_key}
        self.panel.selected_artists = {'Alexander Calder', 'Will Barnet'}
        self.coverage = WatchCoverage(
            'Will Barnet', 'Invaluable', 'https://www.invaluable.com/search?artistName=Will+Barnet',
            state='verified', lot_count=1,
        )

    def test_fresh_artist_upload_stays_successful_when_unrelated_cached_lots_are_displayed(self):
        result = WatchlistResult([self.target], WatchlistMetrics(), coverage=[self.coverage])

        self.panel._finish_scoped_refresh(result, artist_scope={'Will Barnet'}, sync_result=self.upload)

        self.assertEqual(self.panel.status_title_var.get(), 'Calendar updated')
        self.assertEqual(self.panel.fallback_lot_keys, {self.lot.cache_key})
        self.assertEqual({lot.cache_key for lot in self.panel.current_lots},
                         {self.target.cache_key, self.lot.cache_key})
        self.assertIn('Will Barnet only.', self.panel.sync_status_var.get())
        self.assertNotIn('cached lots', self.panel.sync_status_var.get())
        self.status_callback.assert_called_with(self.panel.sync_status_var.get())

    def test_cached_artist_upload_keeps_cached_heading_and_counts_only_uploaded_cache(self):
        result = WatchlistResult(
            [self.target], WatchlistMetrics(), coverage=[self.coverage],
            fallback_lot_keys={self.target.cache_key},
        )

        self.panel._finish_scoped_refresh(result, artist_scope={'Will Barnet'}, sync_result=self.upload)

        self.assertEqual(self.panel.status_title_var.get(), 'Calendar updated with cached lots')
        self.assertEqual(self.panel.fallback_lot_keys, {self.target.cache_key, self.lot.cache_key})
        self.assertIn('Includes 1 cached lots', self.panel.sync_status_var.get())
        self.assertNotIn('Includes 2 cached lots', self.panel.sync_status_var.get())
        self.status_callback.assert_called_with(self.panel.sync_status_var.get())
