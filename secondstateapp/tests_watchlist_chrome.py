"""Regular Chrome launches only validated lot links, without browser control."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from catalogapp.watchlist_chrome import ChromeProfile, _find_chrome, chrome_profiles, open_invaluable_in_chrome


LOT_URL = "https://www.invaluable.com/auction-lot/alexander-calder-116-c-3e46f2f787"


class RegularChromeTests(TestCase):
    def test_launch_uses_only_new_tab_and_lot_url(self):
        executable = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")
        with (
            patch("catalogapp.watchlist_chrome._find_chrome", return_value=executable),
            patch("catalogapp.watchlist_chrome.subprocess.Popen") as launch,
        ):
            self.assertTrue(open_invaluable_in_chrome(LOT_URL))
        launch.assert_called_once_with([str(executable), "--new-tab", LOT_URL])

    def test_rejects_hostile_or_non_lot_urls_before_discovery(self):
        invalid_urls = (
            "http://www.invaluable.com/auction-lot/example",
            "https://invaluable.com.evil.test/auction-lot/example",
            "https://evil.test/auction-lot/example",
            "https://invaluable.com@evil.test/auction-lot/example",
            "https://user:password@www.invaluable.com/auction-lot/example",
            "https://www.invaluable.com:8443/auction-lot/example",
            "https://www.invaluable.com/search",
            "https://www.invaluable.com/auction-lot/",
            "https://www.invaluable.com/auction-lot///",
            "https://www.invaluable.com/auction-lot/%2e%2e/search",
            "https://www.invaluable.com/auction-lot/foo\\bar",
            "https://www.invaluable.com/auction-lot/foo%5cbar",
            "https://www.invaluable.com/auction-lot/foo\nbar",
            " https://www.invaluable.com/auction-lot/example",
            "--user-data-dir=somewhere",
            None,
        )
        with (
            patch("catalogapp.watchlist_chrome._find_chrome") as discovery,
            patch("catalogapp.watchlist_chrome.subprocess.Popen") as launch,
        ):
            for url in invalid_urls:
                with self.subTest(url=url), self.assertRaises(ValueError):
                    open_invaluable_in_chrome(url)
        discovery.assert_not_called()
        launch.assert_not_called()

    def test_accepts_apex_host_with_normal_lot_query(self):
        url = "https://invaluable.com:443/auction-lot/example?source=watchlist#details"
        with (
            patch("catalogapp.watchlist_chrome._find_chrome", return_value=Path("chrome.exe")),
            patch("catalogapp.watchlist_chrome.subprocess.Popen") as launch,
        ):
            self.assertTrue(open_invaluable_in_chrome(url))
        launch.assert_called_once_with(["chrome.exe", "--new-tab", url])

    def test_missing_chrome_gives_actionable_error_without_launching(self):
        with (
            patch("catalogapp.watchlist_chrome._find_chrome", return_value=None),
            patch("catalogapp.watchlist_chrome.subprocess.Popen") as launch,
            self.assertRaisesRegex(RuntimeError, "Chrome could not be found.*usual browser"),
        ):
            open_invaluable_in_chrome(LOT_URL)
        launch.assert_not_called()

    def test_failed_launch_gives_actionable_error(self):
        with (
            patch("catalogapp.watchlist_chrome._find_chrome", return_value=Path("chrome.exe")),
            patch("catalogapp.watchlist_chrome.subprocess.Popen", side_effect=OSError("unavailable")),
            self.assertRaisesRegex(RuntimeError, "Chrome could not be opened.*try again"),
        ):
            open_invaluable_in_chrome(LOT_URL)

    def test_discovers_existing_chrome_in_normal_install_directory(self):
        with TemporaryDirectory() as directory:
            executable = Path(directory) / "Google" / "Chrome" / "Application" / "chrome.exe"
            executable.parent.mkdir(parents=True)
            executable.touch()
            with (
                patch("catalogapp.watchlist_chrome._registry_chrome_paths", return_value=[]),
                patch.dict("catalogapp.watchlist_chrome.os.environ", {"LOCALAPPDATA": directory}, clear=True),
            ):
                self.assertEqual(_find_chrome(), executable)

    def test_registry_path_must_be_an_existing_absolute_chrome_executable(self):
        with TemporaryDirectory() as directory:
            executable = Path(directory) / "chrome.exe"
            other = Path(directory) / "other.exe"
            executable.touch()
            other.touch()
            with (
                patch("catalogapp.watchlist_chrome._registry_chrome_paths", return_value=[
                    Path("chrome.exe"), Path(directory) / "missing" / "chrome.exe", other, executable,
                ]),
                patch.dict("catalogapp.watchlist_chrome.os.environ", {}, clear=True),
            ):
                self.assertEqual(_find_chrome(), executable)

    def test_discovery_returns_none_if_no_install_exists(self):
        with (
            patch("catalogapp.watchlist_chrome._registry_chrome_paths", return_value=[]),
            patch.dict("catalogapp.watchlist_chrome.os.environ", {}, clear=True),
        ):
            self.assertIsNone(_find_chrome())

    def test_explicit_profile_is_passed_without_user_data_or_debug_flags(self):
        with (
            patch("catalogapp.watchlist_chrome._find_chrome", return_value=Path("chrome.exe")),
            patch("catalogapp.watchlist_chrome.chrome_profiles", return_value=[ChromeProfile("Profile 4", "Work")]),
            patch("catalogapp.watchlist_chrome.subprocess.Popen") as launch,
        ):
            self.assertTrue(open_invaluable_in_chrome(LOT_URL, profile_directory="Profile 4"))
        launch.assert_called_once_with(["chrome.exe", "--profile-directory=Profile 4", "--new-tab", LOT_URL])

    def test_stale_or_unsafe_profile_never_launches(self):
        with (
            patch("catalogapp.watchlist_chrome._find_chrome") as discovery,
            patch("catalogapp.watchlist_chrome.chrome_profiles", return_value=[ChromeProfile("Profile 4", "Work")]),
            patch("catalogapp.watchlist_chrome.subprocess.Popen") as launch,
        ):
            for directory in ("Profile 9", "Work", "../Profile 4", "Profile 4/child", "Profile 4\\child", "--remote-debugging-port=9222", ""):
                with self.subTest(directory=directory), self.assertRaisesRegex(ValueError, "profile.*available"):
                    open_invaluable_in_chrome(LOT_URL, profile_directory=directory)
        discovery.assert_not_called()
        launch.assert_not_called()

    def test_default_browser_choice_does_not_read_profile_metadata(self):
        with (
            patch("catalogapp.watchlist_chrome._find_chrome", return_value=Path("chrome.exe")),
            patch("catalogapp.watchlist_chrome.chrome_profiles") as profiles,
            patch("catalogapp.watchlist_chrome.subprocess.Popen"),
        ):
            open_invaluable_in_chrome(LOT_URL)
        profiles.assert_not_called()


class ChromeProfileMetadataTests(TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.user_data = self.directory / "Google" / "Chrome" / "User Data"
        self.user_data.mkdir(parents=True)
        environment = patch.dict("catalogapp.watchlist_chrome.os.environ", {"LOCALAPPDATA": str(self.directory)})
        environment.start()
        self.addCleanup(environment.stop)

    def write_profiles(self, information, last_used=""):
        (self.user_data / "Local State").write_text(json.dumps({"profile": {
            "info_cache": information, "last_used": last_used,
        }}), encoding="utf-8")

    def test_duplicate_names_remain_distinct_and_last_used_is_first(self):
        for directory in ("Default", "Profile 4", "Profile 9"):
            (self.user_data / directory).mkdir()
        self.write_profiles({
            "Profile 4": {"name": "Work", "user_name": "not-returned@example.test"},
            "Profile 9": {"name": "Work", "account_info": {"secret": "not-returned"}},
            "Default": {"name": "Personal"},
        }, last_used="Profile 9")
        self.assertEqual(chrome_profiles(), [
            ChromeProfile("Profile 9", "Work", is_last_used=True),
            ChromeProfile("Default", "Personal"),
            ChromeProfile("Profile 4", "Work"),
        ])

    def test_untrusted_paths_and_stale_entries_are_excluded(self):
        (self.user_data / "Profile 4").mkdir()
        self.write_profiles({
            "../Profile 4": {"name": "Outside"},
            "Profile 4/child": {"name": "Nested"},
            "Profile 4\\child": {"name": "Nested"},
            "Profile 4": {"name": "  Work\nProfile  "},
            "Profile 9": {"name": "Deleted"},
            "--remote-debugging-port=9222": {"name": "Invalid"},
        })
        self.assertEqual(chrome_profiles(), [ChromeProfile("Profile 4", "Work Profile")])

    def test_missing_or_invalid_metadata_returns_no_profiles(self):
        self.assertEqual(chrome_profiles(), [])
        for content in ("invalid json", "[]", '{"profile": []}', '{"profile":{"info_cache":[]}}'):
            with self.subTest(content=content):
                (self.user_data / "Local State").write_text(content, encoding="utf-8")
                self.assertEqual(chrome_profiles(), [])

    def test_missing_display_name_uses_directory(self):
        (self.user_data / "Default").mkdir()
        self.write_profiles({"Default": {"name": None}})
        self.assertEqual(chrome_profiles(), [ChromeProfile("Default", "Default")])

    def test_removed_profile_is_rechecked_at_launch(self):
        (self.user_data / "Profile 4").mkdir()
        self.write_profiles({"Profile 4": {"name": "Work"}})
        self.assertEqual(chrome_profiles(), [ChromeProfile("Profile 4", "Work")])
        self.write_profiles({})
        with (
            patch("catalogapp.watchlist_chrome.subprocess.Popen") as launch,
            self.assertRaisesRegex(ValueError, "profile.*available"),
        ):
            open_invaluable_in_chrome(LOT_URL, profile_directory="Profile 4")
        launch.assert_not_called()
