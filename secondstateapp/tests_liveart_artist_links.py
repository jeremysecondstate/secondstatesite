"""Saved artist bookmarks add LiveArt research links without changing lot state."""

from html import escape
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from catalogapp.bookmark_watchlist import parse_netscape_bookmarks

from .artist_research_registry import artist_liveart_url, artist_research_urls
from .calendar_views import _lot_json
from .models import AuctionWatchLot


PICASSO = "https://www.liveart.ai/artists/aMCprL/pablo-picasso"


def bookmarks(*entries, folder="LIVEART"):
    links = "".join(
        f'<DT><A HREF="{escape(url, quote=True)}">{escape(name)} — LiveArt</A>'
        for name, url in entries
    )
    return f"<DL><DT><H3>{folder}</H3><DL>{links}</DL></DL>"


class LiveArtArtistBookmarkTests(SimpleTestCase):
    def test_project_bookmarks_resolve_names_diacritics_and_verified_aliases(self):
        cases = {
            "Pablo Picasso": PICASSO,
            "Picasso, Pablo (1881–1973)": PICASSO,
            "Joan Miro": "https://www.liveart.ai/artists/oVb6My/joan-miro",
            "Miró, Joan": "https://www.liveart.ai/artists/oVb6My/joan-miro",
            "John W Nieto": "https://www.liveart.ai/artists/kiEVVM/john-nieto",
            "Leroy Neimann": "https://www.liveart.ai/artists/c9GBTz/leroy-neiman",
            "Friedensreich Hundertwasser": "https://www.liveart.ai/artists/hAEazR/friedrich-hundertwasser",
            "Romare Howard Bearden": "https://www.liveart.ai/artists/8Bwp9T/romare-bearden",
        }
        with patch("requests.sessions.Session.request", side_effect=AssertionError("Offline lookup")):
            for name, expected in cases.items():
                with self.subTest(name=name):
                    self.assertEqual(artist_liveart_url(name), expected)
        self.assertEqual(artist_liveart_url("An unknown artist"), "")
        self.assertEqual(artist_liveart_url("John B Nieto"), "")
        self.assertEqual(artist_liveart_url(""), "")
        self.assertEqual(artist_liveart_url(None), "")

    def test_every_current_liveart_bookmark_resolves_from_its_saved_label(self):
        path = Path(__file__).resolve().parents[1] / "docs" / "artist-links.html"
        entries = [entry for entry in parse_netscape_bookmarks(path.read_text(encoding="utf-8-sig"))
                   if "LIVEART" in entry.folder_path]
        self.assertEqual(len(entries), 153)
        for entry in entries:
            with self.subTest(title=entry.title):
                self.assertEqual(artist_liveart_url(entry.title.removesuffix(" — LiveArt")), entry.url)

    def test_unsafe_urls_and_other_folders_cannot_supply_research_links(self):
        unsafe = (
            "http://www.liveart.ai/artists/abc123/jane-example",
            "javascript:alert(1)",
            "https://www.liveart.ai.evil.test/artists/abc123/jane-example",
            "https://www.liveart.ai@evil.test/artists/abc123/jane-example",
            "https://user:password@www.liveart.ai/artists/abc123/jane-example",
            "https://@www.liveart.ai/artists/abc123/jane-example",
            "https://www.liveart.ai:444/artists/abc123/jane-example",
            "https://www.liveart.ai:bad/artists/abc123/jane-example",
            "https://www.liveart.ai/price-database/artwork/jane-example",
            "https://www.liveart.ai/artists/abc123/jane-example?redirect=https://evil.test",
            "https://www.liveart.ai/artists/abc123/jane-example#other",
            "https://www.liveart.ai/artists/abc123/jane%2Fexample",
        )
        with TemporaryDirectory() as directory, self.settings(BASE_DIR=Path(directory)):
            docs = Path(directory) / "docs"
            docs.mkdir()
            path = docs / "artist-links.html"
            for url in unsafe:
                with self.subTest(url=url):
                    path.write_text(bookmarks(("Jane Example", url)), encoding="utf-8")
                    self.assertEqual(artist_liveart_url("Jane Example"), "")
            path.write_text(bookmarks(("Pablo Picasso", PICASSO), folder="LIVEARTS"), encoding="utf-8")
            self.assertEqual(artist_liveart_url("Pablo Picasso"), "")

    def test_cache_refreshes_and_ambiguous_names_do_not_select_an_artist(self):
        jane = "https://www.liveart.ai/artists/abc123/jane-example"
        john = "https://www.liveart.ai/artists/def456/john-example"
        with TemporaryDirectory() as directory, self.settings(BASE_DIR=Path(directory)):
            docs = Path(directory) / "docs"
            docs.mkdir()
            path = docs / "artist-links.html"
            self.assertEqual(artist_liveart_url("Jane Example"), "")
            path.write_text(bookmarks(("Example, Jane", jane)), encoding="utf-8")
            self.assertEqual(artist_liveart_url("Jane Example"), jane)
            self.assertEqual(artist_liveart_url("Example"), jane)
            path.write_text(bookmarks(("Example, Jane", jane), ("Example, John", john)), encoding="utf-8")
            self.assertEqual(artist_liveart_url("Jane Example"), jane)
            self.assertEqual(artist_liveart_url("Example"), "")
            path.write_text(bookmarks(("Jane Example", jane), ("Jane Example", john)), encoding="utf-8")
            self.assertEqual(artist_liveart_url("Jane Example"), "")
            path.unlink()
            self.assertEqual(artist_liveart_url("Jane Example"), "")


class CalendarLiveArtArtistLinkTests(SimpleTestCase):
    def test_lot_payload_has_saved_liveart_url_and_preserves_artprice_and_qualified_lot(self):
        saved_work = "https://www.artprice.com/lots/7777/saved-work"
        lot = AuctionWatchLot(
            pk=9001, source="Heritage", source_lot_id="qualified-picasso",
            artist="After Pablo Picasso", artist_watchlist_name="Pablo Picasso",
            title="Nestor's Tales of the Trojan War", medium="Etching", lot_number="127",
            artprice_url=saved_work, won_by_us=True,
        )
        lot._state.fields_cache["bid_board_analysis"] = None
        before = dict(lot.__dict__)
        expected_artprice, expected_invaluable = artist_research_urls("Pablo Picasso")
        with patch("requests.sessions.Session.request", side_effect=AssertionError("Offline lookup")):
            detail = _lot_json(lot, ZoneInfo("America/New_York"), {lot.pk}, {lot.pk: {"status": "pending"}})
        self.assertEqual(detail["artist_liveart_url"], PICASSO)
        self.assertEqual(detail["artist_artprice_url"], expected_artprice)
        self.assertEqual(detail["artist_invaluable_url"], expected_invaluable)
        self.assertEqual(detail["artist_source"], "Pablo Picasso")
        self.assertEqual(detail["attribution_label"], "After")
        self.assertEqual(detail["artprice_url"], saved_work)
        self.assertTrue(detail["email_tray_selected"])
        self.assertTrue(detail["research_queue_selected"])
        self.assertTrue(detail["won_by_us"])
        self.assertEqual(lot.__dict__, before)
        self.assertTrue(lot._state.adding)

    def test_unknown_artist_payload_omits_a_link_without_affecting_research_actions(self):
        lot = AuctionWatchLot(pk=9002, source="Doyle", source_lot_id="unknown",
                              artist="An unknown artist", title="Untitled")
        lot._state.fields_cache["bid_board_analysis"] = None
        detail = _lot_json(lot, ZoneInfo("America/New_York"))
        self.assertEqual(detail["artist_liveart_url"], "")
        self.assertTrue(detail["liveart_research_url"])
        self.assertTrue(detail["liveart_analysis_url"])
