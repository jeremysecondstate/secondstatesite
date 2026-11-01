"""Portable setup counts follow the packaged export without building an archive."""

from html import escape
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from urllib.parse import urlencode

from scripts.build_invaluable_collector import portable_instructions


def bookmark(title, artists, categories=()):
    params = [("artistName", artist) for artist in artists]
    params.extend(("Fine Art", category) for category in categories)
    url = "https://www.invaluable.com/search?" + urlencode(params)
    return f'<DT><A HREF="{escape(url, quote=True)}">{escape(title)}</A>'


class PortableGuideTests(TestCase):
    def instructions(self, entries):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "intake.html"
            path.write_text("<DL>" + "".join(entries) + "</DL>", encoding="utf-8")
            return portable_instructions("test", path)

    def test_named_split_excludes_legacy_counts_and_preserves_multiple_categories(self):
        categories = ("Prints", "Drawings", "Mixed Media")
        entries = [bookmark("Old bulk", ["Old A", "Old B"]), bookmark("Single", ["Other"])]
        entries.extend(bookmark(title, ["Shared", title], categories) for title in
                       ("BULK-1A", "BULK-1B", "BULK-2A", "BULK-2B"))
        guide = self.instructions(entries)
        self.assertIn("4 bulk searches covering 5 distinct artists (2 + 2 + 2 + 2)", guide)
        self.assertIn("Selected category filters: Drawings, Mixed Media, Prints.", guide)
        self.assertIn("5 selected artists individually", guide)
        self.assertNotIn("82 artists", guide)

    def test_legacy_and_single_artist_exports_derive_their_own_counts(self):
        guide = self.instructions([
            bookmark("Old 1", ["A", "B"], ["Prints"]),
            bookmark("Old 2", ["B", "C", "D"], ["Prints"]),
            bookmark("Single", ["Skipped"]),
        ])
        self.assertIn("2 bulk searches covering 4 distinct artists (2 + 3)", guide)
        self.assertIn("Selected category filters: Prints.", guide)
        guide = self.instructions([bookmark("A", ["A"]), bookmark("B", ["B"])])
        self.assertIn("2 artist searches covering 2 distinct artists (1 + 1)", guide)
        self.assertIn("no category restriction", guide)

    def test_incomplete_named_split_cannot_be_packaged_as_a_legacy_fallback(self):
        with self.assertRaisesRegex(ValueError, "incomplete"):
            self.instructions([bookmark("BULK-1A", ["A", "B"]), bookmark("Old", ["C", "D"])])
