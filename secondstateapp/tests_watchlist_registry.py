import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from catalogapp.bookmark_watchlist import BookmarkEntry
from catalogapp.watchlist_registry import load_watchlist, save_watchlist


class SavedWatchlistTests(TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "watchlist.json"
        self.entry = BookmarkEntry(("ARTISTS INVALUABLE",), "Kollwitz",
            "https://www.invaluable.com/search?artistName=K%C3%A4the+Kollwitz",
            artist="Käthe Kollwitz", source="Invaluable")

    def test_saved_watchlist_restores_artist_filters_and_research_links_without_html(self):
        links = {"Käthe Kollwitz": "https://www.artprice.com/artist/15398/kathe-kollwitz"}
        save_watchlist(self.path, [self.entry], links)
        restored, restored_links = load_watchlist(self.path)
        self.assertEqual(restored, [self.entry])
        self.assertEqual(restored_links, links)
        self.assertEqual(restored[0].folder_path, ("ARTISTS INVALUABLE",))

    def test_unrelated_hosts_credentials_and_spoofed_source_are_rejected(self):
        payload = {"version": 1, "entries": [
            {"url": url, "title": "Unsafe", "artist": "Käthe Kollwitz", "source": "Invaluable"}
            for url in ("https://invaluable.com.evil.example/search", "file:///private",
                        "https://user:password@invaluable.com/search", "https://invaluable.com:123/search")
        ], "artist_artprice_links": {"Käthe Kollwitz": "https://private.example/profile"}}
        self.path.write_text(json.dumps(payload), encoding="utf-8")
        self.assertEqual(load_watchlist(self.path), ([], {}))

    def test_unknown_fields_are_not_persisted_and_duplicates_are_coalesced(self):
        save_watchlist(self.path, [self.entry, self.entry], {"Other artist": "https://www.artprice.com/artist/1/other"})
        restored, links = load_watchlist(self.path)
        self.assertEqual(restored, [self.entry])
        self.assertEqual(links, {})
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(set(payload), {"version", "entries", "artist_artprice_links"})

    def test_missing_or_corrupt_registry_does_not_block_setup(self):
        self.assertEqual(load_watchlist(self.path), ([], {}))
        for content in ("not json", "[]", '{"version": 9}', '{"version": 1, "entries": {}}'):
            self.path.write_text(content, encoding="utf-8")
            self.assertEqual(load_watchlist(self.path), ([], {}))

    def test_failed_replacement_preserves_previous_watchlist(self):
        save_watchlist(self.path, [self.entry], {})
        original = self.path.read_bytes()
        with patch("catalogapp.watchlist_registry.os.replace", side_effect=PermissionError("Busy")):
            with self.assertRaises(PermissionError):
                save_watchlist(self.path, [], {})
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])
