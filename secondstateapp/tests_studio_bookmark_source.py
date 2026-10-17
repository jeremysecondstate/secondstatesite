"""Studio reads current browser bookmarks and keeps routine checks within seven days."""

import json
import os
from unittest import TestCase
from unittest.mock import patch

from catalogapp.watchlist_registry import save_watchlist
from secondstateapp import tests_studio_watchlist as studio_tests


def browser_bookmarks(artists, artprice_links=()):
    return json.dumps({
        "roots": {
            "bookmark_bar": {
                "type": "folder", "name": "Bookmarks bar", "children": [
                    {"type": "folder", "name": "ARTISTS INVALUABLE", "children": [
                        {"type": "url", "name": artist, "url": f"https://www.invaluable.com/search?artistName={artist}"}
                        for artist in artists
                    ]},
                    {"type": "folder", "name": "ARTPRICE", "children": [
                        {"type": "url", "name": artist, "url": url}
                        for artist, url in artprice_links
                    ]},
                ],
            },
        },
        "version": 1,
    })


class StudioBrowserBookmarkWorkflowTests(TestCase):
    setUp = studio_tests.StudioWatchlistControllerTests.setUp
    immediate_thread = staticmethod(studio_tests.StudioWatchlistControllerTests.immediate_thread)

    def named_profile(self):
        user_data = self.directory / "Google" / "Chrome" / "User Data"
        profile = user_data / "Profile 9"
        profile.mkdir(parents=True)
        source = profile / "Bookmarks"
        source.write_text(browser_bookmarks(["Calder"]), encoding="utf-8")
        other = user_data / "Profile 2"
        other.mkdir()
        (other / "Bookmarks").write_text(browser_bookmarks(["Other profile artist"]), encoding="utf-8")
        metadata = user_data / "Local State"
        metadata.write_text(json.dumps({"profile": {
            "last_used": "Profile 2", "info_cache": {
                "Profile 2": {"name": "secondstate.art"},
                "Profile 9": {"name": "secondstate.art"},
            },
        }}), encoding="utf-8")
        self.panel.bookmark_source_var = studio_tests.Value("")
        self.stack.enter_context(patch.dict(os.environ, {"LOCALAPPDATA": str(self.directory)}))
        return source, metadata

    def test_friendly_profile_header_keeps_only_selected_profile_connected(self):
        source, metadata = self.named_profile()
        original = {path: path.read_bytes() for path in (source, metadata)}
        with patch("catalogapp.watchlist_ui.discover_bookmark_sources") as discover:
            self.panel.load_bookmarks(source, source_label="Chrome — secondstate.art (Profile 9)")
            self.panel.sync_to_calendar()

        self.assertEqual(self.panel.bookmark_source_var.get(), "Chrome — secondstate.art")
        self.assertIn("One Chrome profile connected.", self.panel.bookmark_filename_var.get())
        self.assertEqual(self.service.return_value.refresh.call_args.kwargs["selected_artists"], {"Calder"})
        self.assertEqual(self.panel._read_settings()["last_bookmark_path"], str(source.resolve()))
        self.assertEqual(self.panel._read_settings()["bookmark_source_label"], "Chrome — secondstate.art (Profile 9)")
        self.assertEqual({path: path.read_bytes() for path in original}, original)
        discover.assert_not_called()

    def test_update_and_restart_refresh_renamed_profile_without_switching_source(self):
        source, metadata = self.named_profile()
        self.panel.load_bookmarks(source)
        for name, refresh in (("SECONDSTATE research", self.panel.sync_to_calendar), ("Art Studio", self.panel._load_initial_bookmarks)):
            with self.subTest(name=name):
                payload = json.loads(metadata.read_text(encoding="utf-8"))
                payload["profile"]["info_cache"]["Profile 9"]["name"] = name
                metadata.write_text(json.dumps(payload), encoding="utf-8")
                refresh()

                self.assertEqual(self.panel.bookmark_source_var.get(), f"Chrome — {name}")
                self.assertEqual(self.panel._read_settings()["bookmark_source_label"], f"Chrome — {name} (Profile 9)")
                self.assertEqual(self.panel.bookmark_path_var.get(), str(source.resolve()))
                self.assertEqual(self.panel.selected_artists, {"Calder"})

    def test_unavailable_profile_metadata_keeps_saved_friendly_label(self):
        source, metadata = self.named_profile()
        self.panel.load_bookmarks(source)
        for content in ('{"profile":', '{}'):
            with self.subTest(content=content):
                metadata.write_text(content, encoding="utf-8")
                self.panel.sync_to_calendar()

                self.assertEqual(self.panel.bookmark_source_var.get(), "Chrome — secondstate.art")
                self.assertEqual(self.panel._read_settings()["bookmark_source_label"], "Chrome — secondstate.art (Profile 9)")
                self.assertEqual(self.panel.bookmark_path_var.get(), str(source.resolve()))
                self.assertEqual(self.panel.selected_artists, {"Calder"})

    def test_update_reads_new_browser_artists_and_artprice_links_preserving_exclusions(self):
        source = self.directory / "Bookmarks"
        source.write_text(browser_bookmarks(["Calder", "Matisse"]), encoding="utf-8")
        self.panel.bookmark_source_var = studio_tests.Value("")
        self.panel.load_bookmarks(source, source_label="Chrome — Studio")
        self.panel.selected_artists.remove("Matisse")
        link = "https://www.artprice.com/artist/123/kathe-kollwitz/lots/pasts"
        source.write_text(browser_bookmarks(["Calder", "Matisse", "Käthe Kollwitz"], [("Käthe Kollwitz", link)]), encoding="utf-8")
        original_bytes = source.read_bytes()

        self.panel.sync_to_calendar()

        self.assertEqual(self.service.return_value.refresh.call_args.kwargs["selected_artists"], {"Calder", "Käthe Kollwitz"})
        self.assertEqual(self.service.return_value.refresh.call_args.kwargs["horizon_days"], 7)
        self.assertEqual(self.panel.calendar_syncer.call_args.kwargs["artist_artprice_links"], {"Käthe Kollwitz": link})
        self.assertEqual(self.panel.bookmark_source_var.get(), "Chrome — Studio")
        self.assertEqual(self.panel._read_settings()["bookmark_source_label"], "Chrome — Studio")
        self.assertIn("every Sync all", self.panel.bookmark_filename_var.get())
        # Reading and publishing must never rewrite the browser's bookmark file.
        self.assertEqual(source.read_bytes(), original_bytes)

    def test_browser_overlay_keeps_all_saved_artists_and_links_then_discovers_new_ones(self):
        artists = [f"Artist {number}" for number in range(54)]
        artists[50] = "Käthe Kollwitz"
        self.path.write_text(studio_tests.bookmarks(*artists), encoding="utf-8")
        self.panel._registry_path = self.directory / "watchlist.json"
        self.panel.load_bookmarks(self.path)
        old_link = "https://www.artprice.com/artist/150/kathe-kollwitz/lots/pasts"
        save_watchlist(self.panel._registry_path, self.panel.all_entries, {"Käthe Kollwitz": old_link})
        self.panel.selected_artists.remove("Artist 12")
        self.panel._save_settings_hint()
        source = self.directory / "Bookmarks"
        source.write_text(browser_bookmarks(artists[:43]), encoding="utf-8")
        settings = self.panel._read_settings()
        settings.update(last_bookmark_path=str(source), bookmark_source_kind="browser", bookmark_source_label="Chrome — Studio")
        self.panel._settings_path.write_text(json.dumps(settings), encoding="utf-8")
        self.panel.all_entries = []
        self.panel.active_entries = []
        self.panel.artist_artprice_links = {}

        self.panel._load_initial_bookmarks()

        self.assertEqual({entry.artist for entry in self.panel.active_entries}, set(artists))
        self.assertEqual(self.panel.selected_artists, set(artists) - {"Artist 12"})
        self.assertEqual(self.panel.artist_artprice_links["Käthe Kollwitz"], old_link)
        new_link = "https://www.artprice.com/artist/154/corinth/lots/pasts"
        refreshed_old_link = "https://www.artprice.com/artist/150/kathe-kollwitz"
        source.write_text(browser_bookmarks([*artists[:43], "Corinth"], [("Corinth", new_link), ("Käthe Kollwitz", refreshed_old_link)]), encoding="utf-8")

        self.panel.sync_to_calendar()

        self.assertEqual({entry.artist for entry in self.panel.active_entries}, {*artists, "Corinth"})
        self.assertEqual(self.panel.selected_artists, (set(artists) | {"Corinth"}) - {"Artist 12"})
        self.assertEqual(self.panel.artist_artprice_links, {"Käthe Kollwitz": refreshed_old_link, "Corinth": new_link})
        self.assertEqual(self.panel._read_settings()["bookmark_source_kind"], "browser")

    def test_remembered_browser_source_is_read_again_after_restart(self):
        source = self.directory / "Bookmarks"
        source.write_text(browser_bookmarks(["Calder", "Matisse"]), encoding="utf-8")
        self.panel.load_bookmarks(source, source_label="Edge — Personal")
        self.panel.selected_artists.remove("Matisse")
        self.panel._save_settings_hint()
        source.write_text(browser_bookmarks(["Calder", "Matisse", "Corinth"]), encoding="utf-8")
        self.panel.active_entries = []
        self.panel.selected_artists = set()

        self.panel._load_initial_bookmarks()

        self.assertEqual(self.panel.selected_artists, {"Calder", "Corinth"})
        self.assertEqual(self.panel._read_settings()["last_bookmark_path"], str(source.resolve()))
        self.assertEqual(self.panel._read_settings()["bookmark_source_label"], "Edge — Personal")
        self.service.assert_not_called()

    def test_legacy_horizons_are_migrated_and_saved_as_seven_days(self):
        for previous in (14, 30):
            with self.subTest(previous=previous):
                self.panel._settings_path.write_text(json.dumps({"last_bookmark_path": str(self.path), "horizon_days": previous}), encoding="utf-8")
                self.panel._load_initial_bookmarks()
                self.assertEqual(self.panel.horizon_var.get(), 7)
                self.assertEqual(self.panel._read_settings()["horizon_days"], 7)

    def test_three_day_preference_survives_restart(self):
        self.panel._settings_path.write_text(json.dumps({"last_bookmark_path": str(self.path), "horizon_days": 3}), encoding="utf-8")
        self.panel._load_initial_bookmarks()
        self.assertEqual(self.panel.horizon_var.get(), 3)
        self.panel.sync_to_calendar()
        self.assertEqual(self.service.return_value.refresh.call_args.kwargs["horizon_days"], 3)

    def test_browser_source_is_discovered_only_when_the_user_opens_picker(self):
        with patch("catalogapp.watchlist_ui.discover_bookmark_sources", return_value=[]) as discover:
            self.panel.choose_browser_bookmarks()
        discover.assert_called_once_with()
        self.assertEqual(self.info.call_args.args[0], "Browser Bookmarks")
        self.service.assert_not_called()
        self.panel.calendar_syncer.assert_not_called()

    def test_artprice_only_artists_explain_why_they_need_an_auction_bookmark(self):
        source = self.directory / "Bookmarks"
        source.write_text(browser_bookmarks(["Calder"], [("Corinth", "https://www.artprice.com/artist/150/corinth")]), encoding="utf-8")
        self.panel.artprice_summary_var = studio_tests.Value("")
        self.panel.load_bookmarks(source)

        self.assertEqual(self.panel.selected_artists, {"Calder"})
        self.assertIn("1 Artprice bookmarks need a matching auction artist bookmark", self.panel.artprice_summary_var.get())
        self.assertIn("Corinth", self.panel._source_refresh_details())
        self.assertIn("Add the artist's Invaluable", self.panel._source_refresh_details())

    def test_coverage_read_uses_current_time_and_seven_day_window(self):
        self.panel.load_bookmarks(self.path)
        self.panel.coverage_tree = object()
        with (
            patch("catalogapp.watchlist_ui.WatchlistCache") as cache,
            patch.object(self.panel, "_update_coverage_display"),
        ):
            self.panel._refresh_coverage_from_cache()
        call = cache.return_value.__enter__.return_value.coverage_for_entries.call_args
        self.assertEqual(call.kwargs["horizon_days"], 7)
        self.assertIsNotNone(call.kwargs["observed_at"].tzinfo)

    def test_unreadable_browser_change_preserves_current_artists_and_stops_upload(self):
        source = self.directory / "Bookmarks"
        source.write_text(browser_bookmarks(["Calder", "Matisse"]), encoding="utf-8")
        self.panel.load_bookmarks(source)
        source.write_text("{partially written", encoding="utf-8")

        self.panel.sync_to_calendar()

        self.assertEqual(self.panel.selected_artists, {"Calder", "Matisse"})
        self.service.assert_not_called()
        self.panel.calendar_syncer.assert_not_called()
        self.error.assert_called_once()

    def test_restart_with_temporarily_unreadable_browser_uses_registry_before_old_export(self):
        self.panel._registry_path = self.directory / "watchlist.json"
        source = self.directory / "Bookmarks"
        source.write_text(browser_bookmarks(["Calder", "Matisse", "Corinth"]), encoding="utf-8")
        self.panel.load_bookmarks(source, source_label="Chrome — Studio")
        self.panel.selected_artists.remove("Matisse")
        self.panel._save_settings_hint()
        source.write_text("{partially written", encoding="utf-8")
        self.path.write_text(studio_tests.bookmarks("Old Export Artist"), encoding="utf-8")
        self.panel.all_entries = []
        self.panel.active_entries = []
        with patch("catalogapp.watchlist_ui.PROJECT_BOOKMARK_PATH", self.path):
            self.panel._load_initial_bookmarks()
        self.assertEqual(self.panel.selected_artists, {"Calder", "Corinth"})
        self.assertEqual({entry.artist for entry in self.panel.all_entries}, {"Calder", "Matisse", "Corinth"})
        self.assertEqual(self.panel.bookmark_path_var.get(), str(source.resolve()))

    def test_browser_folder_reorganization_preserves_watch_membership_and_exclusions(self):
        source = self.directory / "Bookmarks"
        source.write_text(browser_bookmarks(["Calder", "Matisse"]), encoding="utf-8")
        self.panel.load_bookmarks(source)
        self.panel.selected_artists.remove("Matisse")
        moved = json.loads(browser_bookmarks(["Calder", "Matisse"]))
        moved["roots"]["bookmark_bar"]["children"][0]["name"] = "MOVED ARTISTS"
        source.write_text(json.dumps(moved), encoding="utf-8")

        self.panel.sync_to_calendar()

        self.assertEqual({entry.artist for entry in self.panel.active_entries}, {"Calder", "Matisse"})
        self.assertEqual(self.panel.selected_artists, {"Calder"})
        self.assertEqual(self.service.return_value.refresh.call_args.kwargs["selected_artists"], {"Calder"})

    def test_local_to_account_bookmark_migration_stays_live_for_update_and_restart(self):
        profile = self.directory / "Google" / "Chrome" / "User Data" / "Profile 9"
        profile.mkdir(parents=True)
        local_source = profile / "Bookmarks"
        account_source = profile / "AccountBookmarks"
        self.panel._registry_path = self.directory / "watchlist.json"
        local_source.write_text(browser_bookmarks(["Calder", "Matisse"]), encoding="utf-8")
        with patch.dict(os.environ, {"LOCALAPPDATA": str(self.directory)}):
            self.panel.load_bookmarks(local_source, source_label="Chrome — Studio (Profile 9)")
            self.panel.selected_artists.remove("Matisse")
            self.panel._save_settings_hint()
            account_source.write_text(browser_bookmarks(["Calder", "Matisse", "Corinth"]), encoding="utf-8")
            local_source.unlink()

            self.panel.sync_to_calendar()

            self.assertEqual(self.service.return_value.refresh.call_args.kwargs["selected_artists"], {"Calder", "Corinth"})
            self.assertEqual(self.panel._read_settings()["last_bookmark_path"], str(local_source.resolve()))
            account_source.write_text(browser_bookmarks(["Calder", "Matisse", "Corinth", "Käthe Kollwitz"]), encoding="utf-8")
            self.panel.all_entries = []
            self.panel.active_entries = []

            self.panel._load_initial_bookmarks()

        self.assertEqual(self.panel.selected_artists, {"Calder", "Corinth", "Käthe Kollwitz"})
        self.assertEqual(self.panel._read_settings()["bookmark_source_kind"], "browser")
        self.error.assert_not_called()

    def test_account_bookmarks_are_recognized_as_additive_browser_source(self):
        self.panel.load_bookmarks(self.path)
        account_source = self.directory / "AccountBookmarks"
        account_source.write_text(browser_bookmarks(["Corinth"]), encoding="utf-8")

        self.panel.load_bookmarks(account_source, preserve_selection=True)

        self.assertEqual(self.panel.selected_artists, {"Calder", "Matisse", "Corinth"})
        self.assertEqual(self.panel._read_settings()["bookmark_source_kind"], "browser")
