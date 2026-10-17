"""A second Studio PC restores shared artists and scans only unsynced lots."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest import TestCase
from unittest.mock import Mock, patch

from catalogapp.artprice_artist_links import artist_identity_key
from catalogapp.bookmark_watchlist import parse_bookmarks_html
from catalogapp.watchlist_cache import WatchlistCache
from catalogapp.watchlist_shared import SharedWatchlistSnapshot
from catalogapp.watchlist_sync import CalendarArtistInventory
from secondstateapp import tests_studio_watchlist as studio_tests
from secondstateapp import tests_watchlist_sync_details as details_tests


class SharedWatchlistStartupControllerTests(TestCase):
    immediate_thread = staticmethod(studio_tests.StudioWatchlistControllerTests.immediate_thread)

    def setUp(self):
        studio_tests.StudioWatchlistControllerTests.setUp(self)
        self.panel._registry_path = self.directory / 'watchlist.json'
        self.panel._calendar_lot_keys = None
        self.panel._calendar_inventory = None
        self.panel._selected_sync_artist = ''
        self.panel.sync_selected_button = Mock()
        self.panel.load_bookmarks(self.path)
        now = datetime.now(timezone.utc)
        self.observed = (now - timedelta(days=1)).isoformat()
        self.calder = replace(self.lot, artist='Calder', artist_watchlist_name='Calder',
                              source_lot_id='shared-calder', start_at=(now + timedelta(days=2)).isoformat(),
                              first_seen_at=self.observed, last_seen_at=self.observed)
        self.will = replace(self.calder, artist='Will Barnet', artist_watchlist_name='Will Barnet',
                            source_lot_id='shared-will')
        entries = parse_bookmarks_html(studio_tests.bookmarks('Calder', 'Matisse', 'Will Barnet'))
        self.snapshot = SharedWatchlistSnapshot(
            entries=entries, lots=[self.calder, self.will],
            enabled_watch_urls=frozenset(entry.url for entry in entries),
            calendar_lot_keys=frozenset({self.calder.cache_key, self.will.cache_key}),
        )
        self.inventory = [CalendarArtistInventory(
            name, artist_identity_key(name), 'Invaluable', 1, 1, self.observed,
        ) for name in ('Calder', 'Will Barnet')]

    def finish(self, *, automatic=True):
        self.panel._finish_shared_calendar(self.snapshot, self.inventory, '', automatic=automatic)

    def test_other_pc_restores_shared_artists_and_lots_without_source_fetch_or_upload(self):
        self.finish()

        self.assertEqual({entry.watch_label for entry in self.panel.active_entries},
                         {'Calder', 'Matisse', 'Will Barnet'})
        self.assertEqual({lot.cache_key for lot in self.panel.current_lots},
                         {self.calder.cache_key, self.will.cache_key})
        self.assertTrue(all(lot.last_seen_at == self.observed for lot in self.panel.current_lots))
        self.assertEqual(self.panel.fallback_lot_keys, {self.calder.cache_key, self.will.cache_key})
        self.assertEqual(self.panel._calendar_lot_keys, self.snapshot.calendar_lot_keys)
        self.service.assert_not_called()
        self.public_browser.assert_not_called()
        self.browser.assert_not_called()
        self.panel.calendar_syncer.assert_not_called()
        self.shared_publish.assert_not_called()

    def test_shared_restore_preserves_browser_connection_and_local_exclusion(self):
        self.panel.load_bookmarks(self.path, source_kind='browser', source_label='Chrome — secondstate.art')
        self.panel.selected_artists.remove('Matisse')
        self.panel._save_settings_hint()
        source = self.panel.bookmark_path_var.get()

        self.finish()

        self.assertEqual(self.panel.bookmark_path_var.get(), source)
        self.assertEqual(self.panel._bookmark_source_kind, 'browser')
        self.assertEqual(self.panel._bookmark_source_label, 'Chrome — secondstate.art')
        self.assertEqual(self.panel.selected_artists, {'Calder', 'Will Barnet'})

    def test_old_html_reload_cannot_remove_shared_artist_additions(self):
        self.finish()

        self.assertTrue(self.panel._load_watchlist_for_update(str(self.path)))

        self.assertEqual({entry.watch_label for entry in self.panel.active_entries},
                         {'Calder', 'Matisse', 'Will Barnet'})

    def test_calendar_failure_preserves_local_results_and_selection(self):
        self.panel.current_lots = [self.calder]
        self.panel.selected_artists = {'Calder'}
        entries = list(self.panel.all_entries)

        self.panel._finish_shared_calendar(None, None, 'Website unavailable', automatic=True)

        self.assertEqual(self.panel.current_lots, [self.calder])
        self.assertEqual(self.panel.all_entries, entries)
        self.assertEqual(self.panel.selected_artists, {'Calder'})
        self.panel.calendar_syncer.assert_not_called()
        self.service.assert_not_called()

    def test_load_shared_calendar_reads_only_calendar_endpoints(self):
        self.shared_fetch.return_value = self.snapshot
        self.inventory_fetch.return_value = self.inventory

        self.panel.load_shared_calendar(automatic=True)

        self.shared_fetch.assert_called_once()
        self.inventory_fetch.assert_called_once()
        self.panel.calendar_syncer.assert_not_called()
        self.shared_publish.assert_not_called()
        self.service.assert_not_called()
        self.public_browser.assert_not_called()
        self.assertEqual({lot.cache_key for lot in self.panel.current_lots}, self.snapshot.calendar_lot_keys)


class MissingArtistSelectionWidgetTests(TestCase):
    def setUp(self):
        details_tests.WatchlistSyncDetailsTests.setUp(self)
        self.path = self.panel._settings_path.parent / 'artists.html'
        self.path.write_text(studio_tests.bookmarks('Calder', 'Matisse', 'Will Barnet'), encoding='utf-8')
        self.panel.load_bookmarks(self.path)
        self.calder = replace(self.lot, artist='Calder', artist_watchlist_name='Calder', source_lot_id='calder-existing')
        self.new_calder = replace(self.calder, source_lot_id='calder-new')
        self.panel.current_lots = [self.calder]
        self.panel._calendar_lot_keys = {self.calder.cache_key}
        self.panel._calendar_inventory = [CalendarArtistInventory(
            'Calder', artist_identity_key('Calder'), 'Invaluable', 1, 1, '2026-10-17T15:00:00Z',
        )]
        self.panel._fill_agenda()

    def test_artist_already_on_calendar_is_ineligible_but_new_artist_can_be_checked(self):
        self.assertFalse(self.panel._artist_has_missing_lots('Calder'))
        self.assertTrue(self.panel._artist_has_missing_lots('Will Barnet'))
        self.panel._selected_sync_artist = 'Calder'
        with patch.object(self.panel, '_start_refresh') as refresh:
            self.panel.sync_selected()
        refresh.assert_not_called()

    def test_existing_artist_becomes_eligible_only_when_a_lot_is_missing(self):
        self.panel.current_lots.append(self.new_calder)
        self.panel._fill_agenda()

        self.assertTrue(self.panel._artist_has_missing_lots('Calder'))
        self.panel._selected_sync_artist = 'Calder'
        with patch.object(self.panel, '_start_refresh') as refresh:
            self.panel.sync_selected()
        refresh.assert_called_once()
        self.assertEqual(refresh.call_args.kwargs['artist_scope'], {'Calder'})

    def test_unknown_calendar_state_cannot_enable_selected_sync(self):
        self.panel._calendar_lot_keys = None
        self.panel._selected_sync_artist = 'Will Barnet'

        self.assertFalse(self.panel._artist_has_missing_lots('Will Barnet'))
        with patch.object(self.panel, '_start_refresh') as refresh:
            self.panel.sync_selected()
        refresh.assert_not_called()

    def test_same_calendar_url_with_changed_source_id_is_not_a_missing_lot(self):
        lot = replace(self.calder, source_lot_id='different-local-id',
                      lot_url='https://www.invaluable.com/auction-lot/calder-print-1-c-abcd')
        self.panel.current_lots = [lot]
        self.panel._calendar_lot_keys = {f'invaluable:{lot.lot_url}'}

        self.assertEqual(self.panel._missing_lots(), [])
        self.assertFalse(self.panel._artist_has_missing_lots('Calder'))

    def test_scan_hides_calendar_lots_and_artists_then_selected_button_targets_missing_artist(self):
        now = datetime.now(timezone.utc)
        calder = replace(self.calder, start_at=(now + timedelta(days=2)).isoformat())
        new_calder = replace(calder, source_lot_id='new-calder')
        matisse = replace(calder, source_lot_id='existing-matisse', artist='Matisse', artist_watchlist_name='Matisse')
        watches = {entry.watch_label: entry for entry in self.panel.active_entries}
        with WatchlistCache(self.panel._cache_path) as cache:
            for lot in (calder, new_calder, matisse):
                cache.upsert(lot, watch_url=watches[lot.artist_watchlist_name].url, search_hash='', observed_at=now)
        self.shared_fetch.return_value = SharedWatchlistSnapshot(
            entries=list(self.panel.all_entries), lots=[calder, matisse],
            enabled_watch_urls=frozenset(entry.url for entry in self.panel.active_entries),
            calendar_lot_keys=frozenset({calder.cache_key, matisse.cache_key}),
        )
        self.inventory_fetch.return_value = [CalendarArtistInventory(
            name, artist_identity_key(name), 'Invaluable', 1, 1, now.isoformat(),
        ) for name in ('Calder', 'Matisse')]
        self.panel._calendar_sync_configured = Mock(return_value=True)
        self.panel.after = lambda _delay, callback: callback()
        with (
            patch('catalogapp.watchlist_ui.threading.Thread', side_effect=studio_tests.StudioWatchlistControllerTests.immediate_thread),
            patch('catalogapp.watchlist_ui.WatchlistService') as service,
            patch('catalogapp.watchlist_ui.InvaluablePublicBrowserFetcher') as browser,
            patch.object(self.panel, 'calendar_syncer') as upload,
        ):
            self.panel.scan_artists()

        self.assertTrue(self.panel._scan_missing_only)
        self.assertEqual({lot.cache_key for lot in self.panel._lots_by_iid.values()}, {new_calder.cache_key})
        self.assertEqual({row.artist for row in self.panel._inventory_rows.values()}, {'Calder', 'Will Barnet'})
        self.assertIn('1 lots', self.panel.lot_summary_var.get())
        self.assertEqual({lot.cache_key for lot in self.panel.current_lots},
                         {calder.cache_key, new_calder.cache_key, matisse.cache_key})
        service.assert_not_called()
        browser.assert_not_called()
        upload.assert_not_called()
        self.shared_fetch.assert_called_once()
        calder_row = next(iid for iid, row in self.panel._inventory_rows.items() if row.artist == 'Calder')
        self.panel.artist_inventory_tree.selection_set(calder_row)
        self.panel._inventory_selection_changed()
        with patch.object(self.panel, '_start_refresh') as refresh:
            self.panel.sync_selected_button.invoke()
        refresh.assert_called_once()
        self.assertEqual(refresh.call_args.kwargs['artist_scope'], {'Calder'})

    def test_filtered_empty_agenda_reports_no_missing_lots_without_hiding_saved_data(self):
        self.panel._scan_missing_only = True
        self.panel._fill_agenda()

        self.assertEqual(self.panel.upcoming_tree.get_children(''), ())
        self.assertEqual(self.panel.current_lots, [self.calder])
        self.assertIn('No known lots are missing', self.panel.empty_state.cget('text'))
        self.assertNotIn('Calder', {row.artist for row in self.panel._inventory_rows.values()})
