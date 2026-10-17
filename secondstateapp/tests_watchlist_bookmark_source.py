import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from catalogapp.artprice_artist_links import parse_artprice_artist_links
from catalogapp.bookmark_watchlist import parse_bookmarks_html
from catalogapp.watchlist_bookmark_source import bookmark_source_paths, discover_bookmark_sources, load_bookmark_source


def folder(name, children):
    return {"type": "folder", "name": name, "children": children}


def bookmark(name, url):
    return {"type": "url", "name": name, "url": url}


class BookmarkSourceTests(TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "Bookmarks"
        self.artist_url = "https://www.invaluable.com/search?artistName=K%C3%A4the+Kollwitz&utm_source=browser"
        self.artprice_url = "https://www.artprice.com/artist/15398/kathe-kollwitz/lots/pasts"

    def write(self, children, path=None):
        (path or self.path).write_text(json.dumps({"roots": {"bookmark_bar": folder("Bookmarks bar", children)}}), encoding="utf-8")

    def browser_profile(self):
        profile = self.root / "Google" / "Chrome" / "User Data" / "Profile 15"
        profile.mkdir(parents=True)
        return profile

    def test_json_preserves_html_artist_folder_filter_and_artprice_matching_semantics(self):
        self.write([
            folder("ARTISTS INVALUABLE", [bookmark("Käthe Kollwitz", self.artist_url)]),
            folder("ARTPRICE", [folder("German artists", [bookmark("KOLLWITZ Käthe", self.artprice_url)])]),
        ])
        html = f"""<!DOCTYPE NETSCAPE-Bookmark-file-1><DL><DT><H3>Bookmarks bar</H3><DL>
        <DT><H3>ARTISTS INVALUABLE</H3><DL><DT><A HREF="{self.artist_url}">Käthe Kollwitz</A></DL>
        <DT><H3>ARTPRICE</H3><DL><DT><H3>German artists</H3><DL><DT><A HREF="{self.artprice_url}">KOLLWITZ Käthe</A></DL></DL>
        </DL></DL>"""
        entries, matches = load_bookmark_source(self.path)
        self.assertEqual(entries, parse_bookmarks_html(html))
        self.assertEqual(matches, parse_artprice_artist_links(html, ["Käthe Kollwitz"]))
        self.assertEqual(matches.links_by_artist, {"Käthe Kollwitz": self.artprice_url})

    def test_each_read_sees_added_artists_and_new_research_bookmarks_without_writing_source(self):
        self.write([folder("Invaluable", [bookmark("Kollwitz", self.artist_url)])])
        first, matches = load_bookmark_source(self.path)
        self.assertEqual(len(first), 1)
        self.assertEqual(matches.extracted_count, 0)
        self.write([
            folder("Invaluable", [bookmark("Kollwitz", self.artist_url), bookmark("Corinth", "https://www.invaluable.com/search?artistName=Lovis+Corinth")]),
            folder("ARTPRICE", [bookmark("Kollwitz", self.artprice_url)]),
        ])
        before = self.path.read_bytes()
        entries, matches = load_bookmark_source(self.path)
        self.assertEqual({entry.artist for entry in entries}, {"Käthe Kollwitz", "Lovis Corinth"})
        self.assertEqual(matches.matched_artist_count, 1)
        self.assertEqual(self.path.read_bytes(), before)

    def test_private_or_unrelated_urls_are_never_returned_and_duplicates_are_canonicalized(self):
        self.write([folder("Invaluable", [bookmark("Unsafe", url) for url in (
            "https://user:password@www.invaluable.com/search?artistName=Private",
            "https://www.invaluable.com:123/search?artistName=Private",
            "https://invaluable.com.evil.example/search", "file:///private", "chrome://settings",
            "https://example.org/private", self.artist_url,
            self.artist_url.replace("utm_source=browser", "utm_campaign=duplicate"),
        )])])
        entries, _matches = load_bookmark_source(self.path)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].artist, "Käthe Kollwitz")
        self.assertNotIn("utm_", entries[0].url)

    def test_html_export_remains_supported_and_artprice_folder_scope_is_preserved(self):
        self.path.write_text(f'<DL><H3>Invaluable</H3><DL><A HREF="{self.artist_url}">Kollwitz</A></DL><H3>Other</H3><DL><A HREF="{self.artprice_url}">Kollwitz</A></DL></DL>', encoding="utf-8")
        entries, matches = load_bookmark_source(self.path)
        self.assertEqual(len(entries), 1)
        self.assertEqual(matches.extracted_count, 0)

    def test_separate_artprice_source_can_match_established_artist_names(self):
        self.write([folder("ARTPRICE", [bookmark("Kollwitz", self.artprice_url)])])
        entries, matches = load_bookmark_source(self.path, artist_names=["Käthe Kollwitz"])
        self.assertEqual(entries, [])
        self.assertEqual(matches.links_by_artist, {"Käthe Kollwitz": self.artprice_url})

    def test_saved_artist_names_extend_new_browser_artists_for_research_matching(self):
        corinth_artprice = "https://www.artprice.com/artist/6712/lovis-corinth/lots/pasts"
        self.write([
            folder("Invaluable", [bookmark("Corinth", "https://www.invaluable.com/search?artistName=Lovis+Corinth")]),
            folder("ARTPRICE", [bookmark("Kollwitz", self.artprice_url), bookmark("Corinth", corinth_artprice)]),
        ])
        entries, matches = load_bookmark_source(self.path, artist_names=["Käthe Kollwitz"])
        self.assertEqual([entry.artist for entry in entries], ["Lovis Corinth"])
        self.assertEqual(matches.links_by_artist, {
            "Käthe Kollwitz": self.artprice_url,
            "Lovis Corinth": corinth_artprice,
        })
        self.assertEqual(matches.unmatched_titles, ())

    def test_malformed_or_non_bookmark_files_raise_so_saved_watchlist_can_be_preserved(self):
        for content in ('{"roots":', '[]', '{"roots": {}}', '{"secret": "unrelated"}', "plain text"):
            with self.subTest(content=content):
                self.path.write_text(content, encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_bookmark_source(self.path)
        self.path.unlink()
        with self.assertRaises(OSError):
            load_bookmark_source(self.path)

    def test_deep_or_oversized_file_is_rejected(self):
        child = bookmark("Kollwitz", self.artist_url)
        for _ in range(70):
            child = folder("Nested", [child])
        self.write([child])
        with self.assertRaises(ValueError):
            load_bookmark_source(self.path)
        with patch("catalogapp.watchlist_bookmark_source._MAX_BYTES", 10):
            with self.assertRaises(ValueError):
                load_bookmark_source(self.path)

    def test_escaped_folder_and_title_markup_is_text(self):
        self.write([folder("ARTISTS <DL> & Friends", [bookmark('Kollwitz <A HREF="https://evil.example">', self.artist_url)])])
        entries, _matches = load_bookmark_source(self.path)
        self.assertEqual(entries[0].folder_path, ("Bookmarks bar", "ARTISTS <DL> & Friends"))
        self.assertIn("<A HREF=", entries[0].title)

    def test_discovery_lists_only_safe_existing_chrome_edge_bookmark_files(self):
        for browser_path in (("Google", "Chrome"), ("Microsoft", "Edge")):
            root = self.root.joinpath(*browser_path, "User Data")
            root.mkdir(parents=True)
            (root / "Local State").write_text(json.dumps({"profile": {
                "last_used": "Profile 2", "info_cache": {
                    "Default": {"name": "Main"}, "Profile 2": {"name": "Auction research"},
                    "../outside": {"name": "Wrong"}, "Profile 8": {"name": "Missing"},
                },
            }, "account_info": [{"email": "not-returned@example.org"}]}), encoding="utf-8")
            for directory in ("Default", "Profile 2", "Profile nonsense"):
                profile = root / directory
                profile.mkdir()
                (profile / "Bookmarks").write_text("not read during discovery", encoding="utf-8")
        with patch.dict("os.environ", {"LOCALAPPDATA": str(self.root)}):
            sources = discover_bookmark_sources()
        self.assertEqual(len(sources), 4)
        self.assertEqual([source.browser for source in sources[:2]], ["Chrome", "Edge"])
        self.assertTrue(all(source.is_last_used for source in sources[:2]))
        self.assertEqual({source.profile_directory for source in sources}, {"Default", "Profile 2"})
        self.assertEqual(sources[0].label, "Chrome — Auction research (Profile 2)")
        self.assertNotIn("not-returned", repr(sources))

    def test_profile_directory_keeps_duplicate_browser_profile_labels_distinct(self):
        root = self.root / "Google" / "Chrome" / "User Data"
        root.mkdir(parents=True)
        (root / "Local State").write_text(json.dumps({"profile": {"info_cache": {
            "Profile 2": {"name": "secondstate.art"},
            "Profile 9": {"name": "secondstate.art"},
        }}}), encoding="utf-8")
        for directory in ("Profile 2", "Profile 9"):
            profile = root / directory
            profile.mkdir()
            (profile / "Bookmarks").write_text("{}", encoding="utf-8")
        with patch.dict("os.environ", {"LOCALAPPDATA": str(self.root)}):
            sources = discover_bookmark_sources()
        self.assertEqual({source.label for source in sources}, {
            "Chrome — secondstate.art (Profile 2)", "Chrome — secondstate.art (Profile 9)",
        })
        self.assertEqual({source.display_label for source in sources}, {"Chrome — secondstate.art"})

    def test_discovery_works_without_local_state_and_with_missing_browser_directory(self):
        profile = self.root / "Google" / "Chrome" / "User Data" / "Default"
        profile.mkdir(parents=True)
        (profile / "Bookmarks").write_text("{}", encoding="utf-8")
        with patch.dict("os.environ", {"LOCALAPPDATA": str(self.root)}):
            sources = discover_bookmark_sources()
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0].profile_name, "Default")

    def test_busy_profile_metadata_does_not_hide_a_readable_bookmark_source(self):
        profile = self.root / "Google" / "Chrome" / "User Data" / "Default"
        profile.mkdir(parents=True)
        (profile / "Bookmarks").write_text("{}", encoding="utf-8")
        (profile.parent / "Local State").write_text('{"profile":', encoding="utf-8")
        with patch.dict("os.environ", {"LOCALAPPDATA": str(self.root)}):
            sources = discover_bookmark_sources()
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0].profile_name, "Default")

    def test_account_only_profile_is_discovered_and_remains_available_after_store_migration(self):
        profile = self.browser_profile()
        account = profile / "AccountBookmarks"
        self.write([folder("Invaluable", [bookmark("Kollwitz", self.artist_url)])], account)
        with patch.dict("os.environ", {"LOCALAPPDATA": str(self.root)}):
            sources = discover_bookmark_sources()
            self.assertEqual(len(sources), 1)
            self.assertEqual(sources[0].path, account)
            self.assertEqual(bookmark_source_paths(profile / "Bookmarks"), (account,))
            entries, _matches = load_bookmark_source(profile / "Bookmarks")
        self.assertEqual([entry.artist for entry in entries], ["Käthe Kollwitz"])

    def test_profile_merges_both_plain_stores_and_matches_account_research_to_local_artist(self):
        profile = self.browser_profile()
        local, account = profile / "Bookmarks", profile / "AccountBookmarks"
        self.write([folder("Invaluable", [bookmark("Kollwitz", self.artist_url)])], local)
        self.write([
            folder("Invaluable", [bookmark("Duplicate", self.artist_url), bookmark("Corinth", "https://www.invaluable.com/search?artistName=Lovis+Corinth")]),
            folder("ARTPRICE", [bookmark("Kollwitz", self.artprice_url)]),
        ], account)
        before = {path: path.read_bytes() for path in (local, account)}
        with patch.dict("os.environ", {"LOCALAPPDATA": str(self.root)}):
            sources = discover_bookmark_sources()
            self.assertEqual(len(sources), 1)
            self.assertEqual(bookmark_source_paths(account), (local, account))
            entries, matches = load_bookmark_source(account)
        self.assertEqual({entry.artist for entry in entries}, {"Käthe Kollwitz", "Lovis Corinth"})
        self.assertEqual(len(entries), 2)
        self.assertEqual(matches.links_by_artist, {"Käthe Kollwitz": self.artprice_url})
        self.assertEqual({path: path.read_bytes() for path in (local, account)}, before)

    def test_empty_chromium_account_store_is_compatible_with_local_bookmarks(self):
        profile = self.browser_profile()
        self.write([folder("Invaluable", [bookmark("Kollwitz", self.artist_url)])], profile / "Bookmarks")
        (profile / "AccountBookmarks").write_text('{"roots": {}, "version": 1}', encoding="utf-8")
        with patch.dict("os.environ", {"LOCALAPPDATA": str(self.root)}):
            entries, _matches = load_bookmark_source(profile / "Bookmarks")
        self.assertEqual(len(entries), 1)

    def test_corrupt_account_store_does_not_silently_publish_only_local_artists(self):
        profile = self.browser_profile()
        self.write([folder("Invaluable", [bookmark("Kollwitz", self.artist_url)])], profile / "Bookmarks")
        (profile / "AccountBookmarks").write_text('{"roots":', encoding="utf-8")
        with patch.dict("os.environ", {"LOCALAPPDATA": str(self.root)}):
            with self.assertRaises(ValueError):
                load_bookmark_source(profile / "Bookmarks")

    def test_arbitrary_export_named_bookmarks_never_reads_a_sibling_account_file(self):
        self.write([folder("Invaluable", [bookmark("Kollwitz", self.artist_url)])])
        (self.root / "AccountBookmarks").write_text("not a readable file", encoding="utf-8")
        with patch.dict("os.environ", {"LOCALAPPDATA": str(self.root)}):
            self.assertEqual(bookmark_source_paths(self.path), (self.path,))
            entries, _matches = load_bookmark_source(self.path)
        self.assertEqual(len(entries), 1)

    def test_encrypted_and_backup_stores_are_never_discovered_or_read(self):
        profile = self.browser_profile()
        for name in ("EncryptedBookmarks2", "EncryptedAccountBookmarks2", "Bookmarks.bak", "AccountBookmarks.bak"):
            (profile / name).write_text("must not read this store", encoding="utf-8")
        with patch.dict("os.environ", {"LOCALAPPDATA": str(self.root)}):
            self.assertEqual(discover_bookmark_sources(), [])
            self.assertEqual(bookmark_source_paths(profile / "Bookmarks"), ())
