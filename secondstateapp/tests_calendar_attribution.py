"""Attribution warnings stay visible without changing source or saved lot state."""

from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from .calendar_views import _lot_json
from .lot_presentation import artist_attribution_label, artist_display_name
from .models import AuctionWatchArtist, AuctionWatchLot


class ArtistAttributionLabelTests(SimpleTestCase):
    def test_explicit_artist_prefixes_suffixes_and_biography_are_flagged(self):
        cases = {
            "After Pablo Picasso": "After",
            "AFTER Picasso, Pablo": "After",
            "Attributed To Joan Miró": "Attributed to",
            "Pablo Picasso, after": "After",
            "Picasso, Pablo (AFTER)": "After",
            "Joan Miró (attributed to)": "Attributed to",
            "Pablo Picasso (1881–1973) (after)": "After",
            "Pablo Picasso (after) (Spanish, 1881–1973)": "After",
            "Attributed to: Joan Miró (1893–1983)": "Attributed to",
            "(After) Pablo Picasso": "After",
            "(After Pablo Picasso)": "After",
            "Circle of After Pablo Picasso": "After",
        }
        for credit, expected in cases.items():
            with self.subTest(credit=credit):
                self.assertEqual(artist_attribution_label(credit), expected)

    def test_raw_auction_credit_precedes_the_canonical_watchlist_name(self):
        self.assertEqual(artist_attribution_label("After Pablo Picasso", "Pablo Picasso"), "After")
        self.assertEqual(artist_attribution_label("Attributed to Joan Miró", "Miró, Joan"), "Attributed to")
        self.assertEqual(artist_attribution_label("", "Pablo Picasso (after)"), "After")

    def test_direct_french_equivalents_get_english_warning_labels(self):
        cases = {
            "D’après Pablo Picasso": "After",
            "D'APRES Picasso, Pablo": "After",
            "D’apres Pablo Picasso": "After",
            "Dapres Pablo Picasso": "After",
            "Picasso, Pablo (d'après)": "After",
            "Pablo Picasso, d’apres": "After",
            "Attribué à Joan Miró": "Attributed to",
            "ATTRIBUE A Miró, Joan": "Attributed to",
            "Attribuée à Joan Miró (1893–1983)": "Attributed to",
            "Joan Miró (attribuée à)": "Attributed to",
            "Joan Miró, attribuee a": "Attributed to",
        }
        for credit, expected in cases.items():
            with self.subTest(credit=credit):
                self.assertEqual(artist_attribution_label(credit), expected)

    def test_only_requested_credit_types_are_flagged(self):
        for credit in ("Pablo Picasso", "Circle of Pablo Picasso", "School of Pablo Picasso",
                       "Workshop of Pablo Picasso", "In the style of Pablo Picasso", "", None):
            with self.subTest(credit=credit):
                self.assertEqual(artist_attribution_label(credit), "")

    def test_title_credit_must_bind_to_the_current_complete_artist_name(self):
        cases = (
            ("Alexander (1898) Calder", "After Alexander Calder (1898–1976)", "After"),
            ("Joan Miró", "Â§ Attributed to Joan MirÃ³ — Composition", "Attributed to"),
            ("Pablo Picasso", "After Picasso, Pablo, Bouquet de Fleurs", "After"),
            ("Pablo Picasso", "Picasso, Pablo (attributed to) — Composition", "Attributed to"),
            ("Pablo Picasso", "Bouquet de Fleurs (after Pablo Picasso)", "After"),
            ("Pablo Picasso", "After Pablo Picasso\nComposition", "After"),
            ("Pablo Picasso", "D’après Pablo Picasso — Bouquet", "After"),
            ("Joan Miró", "Composition (attribuée à Joan Miró)", "Attributed to"),
            ("Pablo Picasso", "Picasso, Pablo (d’apres) — Bouquet", "After"),
            ("Andy Warhol", "After Pablo Picasso — Composition", ""),
            ("Pablo Picasso", "After Pablo Picasso Jr. — Composition", ""),
            ("Pablo Picasso", "D'après Andy Warhol — Composition", ""),
        )
        for artist, title, expected in cases:
            with self.subTest(artist=artist, title=title):
                self.assertEqual(artist_attribution_label(artist, title=title), expected)

    def test_ordinary_work_titles_and_later_mentions_are_not_credits(self):
        titles = ("After the Party", "He Enquired After the Quality", "Life After Picasso",
                  "The day after", "Composition by Pablo Picasso, after Andy Warhol",
                  "After Picasso's studio", "Aftercare", "Attributed To", "D’après la pluie",
                  "La vie d'après Picasso", "Composition d’après les archives de Pablo Picasso", "")
        for title in titles:
            with self.subTest(title=title):
                self.assertEqual(artist_attribution_label("Pablo Picasso", title=title), "")
        self.assertEqual(artist_attribution_label(title="After Pablo Picasso"), "")


class CalendarAttributionPayloadTests(SimpleTestCase):
    def test_warning_uses_raw_credit_and_preserves_lot_data_links_and_selections(self):
        artist_url = "https://www.artprice.com/artist/22796/pablo-picasso/lots/pasts?idcategory=2"
        saved_work_url = "https://www.artprice.com/lots/7777/saved-work"
        cases = (
            ("After Pablo Picasso", "Pablo Picasso", "Bouquet de Fleurs", "After"),
            ("Pablo Picasso", "Pablo Picasso", "Attributed to Pablo Picasso — Bouquet", "Attributed to"),
            ("D’après Pablo Picasso", "Pablo Picasso", "Bouquet", "After"),
            ("Pablo Picasso", "Pablo Picasso", "Attribuée à Pablo Picasso — Bouquet", "Attributed to"),
            ("Pablo Picasso", "Pablo Picasso", "After the Party", ""),
        )
        with patch("django.db.backends.utils.CursorWrapper.execute", side_effect=AssertionError("Unexpected database query")), \
                patch("secondstateapp.calendar_views.artist_research_urls", return_value=(artist_url, "")):
            for index, (raw_artist, watchlist_name, title, expected) in enumerate(cases, 100):
                with self.subTest(artist=raw_artist, title=title):
                    lot = AuctionWatchLot(pk=index, source="Heritage", source_lot_id=str(index),
                                          artist=raw_artist, artist_watchlist_name=watchlist_name,
                                          title=title, medium="Lithograph", lot_number=str(index),
                                          artprice_url=saved_work_url, won_by_us=True)
                    lot._state.fields_cache["bid_board_analysis"] = None
                    before = dict(lot.__dict__)
                    payload = _lot_json(lot, ZoneInfo("America/Los_Angeles"), {lot.pk},
                                        {lot.pk: {"status": "pending"}})
                    self.assertEqual(payload["attribution_label"], expected)
                    self.assertEqual(payload["artist_source"], watchlist_name)
                    self.assertEqual(payload["artist"], artist_display_name(watchlist_name))
                    self.assertEqual(payload["artist_artprice_url"], artist_url)
                    self.assertEqual(payload["artprice_url"], saved_work_url)
                    self.assertEqual(payload["id"], index)
                    self.assertTrue(payload["won_by_us"])
                    self.assertTrue(payload["email_tray_selected"])
                    self.assertTrue(payload["research_queue_selected"])
                    self.assertEqual(lot.__dict__, before)
                    self.assertTrue(lot._state.adding)

    def test_existing_watchlist_artist_link_override_is_preserved(self):
        chosen_url = "https://www.artprice.com/artist/19928/joan-miro/lots/pasts?idcategory[]=2"
        artist = AuctionWatchArtist(pk=9000, name="Joan Miró", artprice_url=chosen_url)
        lot = AuctionWatchLot(pk=9001, source="Drouot", source_lot_id="credited-miro",
                              artist="Attribué à Joan Miró", artist_watchlist_name="Joan Miró",
                              watchlist_artist=artist, title="Composition")
        lot._state.fields_cache["bid_board_analysis"] = None
        with patch("django.db.backends.utils.CursorWrapper.execute", side_effect=AssertionError("Unexpected database query")), \
                patch("secondstateapp.calendar_views.artist_research_urls", return_value=("", "")):
            payload = _lot_json(lot, ZoneInfo("America/Los_Angeles"))
        self.assertEqual(payload["attribution_label"], "Attributed to")
        self.assertEqual(payload["artist_artprice_url"], chosen_url)
        self.assertEqual(payload["artist_source"], "Joan Miró")
        self.assertEqual(lot.artist, "Attribué à Joan Miró")
        self.assertEqual(artist.artprice_url, chosen_url)
        self.assertTrue(lot._state.adding)
        self.assertTrue(artist._state.adding)
