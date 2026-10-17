"""Bookmark HTML moves between clones; browser connections stay on one PC."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from catalogapp.watchlist_paths import remember_bookmark_path, resolve_saved_bookmark_path


class PortableBookmarkPathTests(TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name).resolve()
        self.project = self.directory / "second-pc" / "secondstate"
        self.project.mkdir(parents=True)
        self.html = self.project / "docs" / "ARTIST-LINKZZZZZZ.html"
        self.html.parent.mkdir()
        self.html.write_text("<DL></DL>", encoding="utf-8")
        self.old_path = self.directory / "first-pc" / "docs" / self.html.name

    def test_missing_first_pc_html_resolves_under_current_clone(self):
        saved = {"scan_html_path": str(self.old_path),
                 "scan_html_path_relative": "docs/ARTIST-LINKZZZZZZ.html"}
        self.assertEqual(resolve_saved_bookmark_path(saved, "scan_html_path", self.project), self.html)

    def test_existing_local_source_takes_precedence_over_shared_relative_hint(self):
        self.old_path.parent.mkdir(parents=True)
        self.old_path.write_text("<DL></DL>", encoding="utf-8")
        saved = {"last_bookmark_path": str(self.old_path),
                 "last_bookmark_path_relative": "docs/ARTIST-LINKZZZZZZ.html"}
        self.assertEqual(resolve_saved_bookmark_path(saved, "last_bookmark_path", self.project), self.old_path)

    def test_missing_browser_source_never_resolves_to_portable_html(self):
        for name in ("Bookmarks", "AccountBookmarks", "bookmarks.json"):
            with self.subTest(name=name):
                browser = self.directory / "old-pc" / name
                saved = {"last_bookmark_path": str(browser),
                         "last_bookmark_path_relative": "docs/ARTIST-LINKZZZZZZ.html"}
                self.assertEqual(resolve_saved_bookmark_path(saved, "last_bookmark_path", self.project), browser)

    def test_relative_only_html_hint_is_supported(self):
        self.assertEqual(resolve_saved_bookmark_path(
            {"scan_html_path_relative": "docs/ARTIST-LINKZZZZZZ.html"}, "scan_html_path", self.project,
        ), self.html)

    def test_unavailable_fallback_retains_original_source(self):
        saved = {"scan_html_path": str(self.old_path), "scan_html_path_relative": "docs/missing.html"}
        self.assertEqual(resolve_saved_bookmark_path(saved, "scan_html_path", self.project), self.old_path)
        self.assertIsNone(resolve_saved_bookmark_path({}, "scan_html_path", self.project))

    def test_relative_fallback_rejects_outside_clone_and_non_html_files(self):
        outside = self.directory / "outside.html"
        outside.write_text("<DL></DL>", encoding="utf-8")
        json_path = self.project / "bookmarks.json"
        json_path.write_text("{}", encoding="utf-8")
        for relative in (str(outside), "../../outside.html", "..\\..\\outside.html",
                         "C:/other/source.html", "C:source.html", "/outside.html", "bookmarks.json"):
            with self.subTest(relative=relative):
                saved = {"scan_html_path": str(self.old_path), "scan_html_path_relative": relative}
                self.assertEqual(resolve_saved_bookmark_path(saved, "scan_html_path", self.project), self.old_path)

    def test_remember_html_writes_legacy_absolute_and_portable_relative(self):
        saved = {}
        remember_bookmark_path(saved, "scan_html_path", self.html, self.project)
        self.assertEqual(saved, {"scan_html_path": str(self.html),
                                 "scan_html_path_relative": "docs/ARTIST-LINKZZZZZZ.html"})

    def test_browser_or_external_sources_clear_old_relative_hint(self):
        for path in (self.project / "bookmarks.json", self.project / "Bookmarks", self.old_path):
            with self.subTest(path=path):
                saved = {"last_bookmark_path_relative": "docs/ARTIST-LINKZZZZZZ.html"}
                remember_bookmark_path(saved, "last_bookmark_path", path, self.project)
                self.assertEqual(saved, {"last_bookmark_path": str(path)})

    def test_empty_source_clears_both_hints(self):
        saved = {"scan_html_path_relative": "docs/ARTIST-LINKZZZZZZ.html"}
        remember_bookmark_path(saved, "scan_html_path", "", self.project)
        self.assertEqual(saved, {"scan_html_path": ""})
