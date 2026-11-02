"""Forum's supplied artist bookmarks resolve without changing source credits."""

from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from .artist_research_registry import artist_research_urls
from .calendar_views import _lot_json
from .models import AuctionWatchLot


# Exact artist selections and URLs supplied for the November 4, 2026 sale.
# Four artists occur inside the multi-artist books and remain reusable bookmarks.
_SUPPLIED_ARTISTS = (
    ("Alberto Giacometti", "https://www.artprice.com/artist/11225/alberto-giacometti/lots/pasts?idcategory=2&p=1&sort=datesale_desc"),
    ("Anthony Fry", "https://www.artprice.com/artist/37621/anthony-fry/lots/pasts?idcategory=2&p=1&sort=datesale_desc"),
    ("Armand Guillaumin", "https://www.artprice.com/artist/12307/armand-guillaumin/lots/pasts?idcategory=2&p=1&sort=datesale_desc"),
    ("Beatriz Milhazes", "https://www.artprice.com/artist/64278/beatriz-milhazes/lots/pasts?idcategory=2&p=1&sort=datesale_desc"),
    ("Berthe Morisot", "https://www.artprice.com/artist/20445/berthe-morisot/lots/pasts?idcategory=2&p=1&sort=datesale_desc"),
    ("Bob Dylan", "https://www.artprice.com/artist/78434/bob-dylan/lots/pasts?idcategory=2&p=1&sort=datesale_desc"),
    ("Camille Pissarro", "https://www.artprice.com/artist/23011/camille-pissarro/lots/pasts?idcategory=2&p=1&sort=datesale_desc"),
    ("Caroline Walker", "https://www.artprice.com/artist/290329/caroline-walker/lots/pasts?idcategory=2&p=1&sort=datesale_desc"),
    ("Charles Grignion", "https://www.artprice.com/artist/240874/charles-i-grignion/lots/pasts?idcategory=2&p=1&sort=datesale_desc"),
    ("Craigie Aitchison", "https://www.artprice.com/artist/233/craigie-aitchison/lots/pasts?idcategory=2&p=1&sort=datesale_desc"),
    ("Elisabeth Frink", "https://www.artprice.com/artist/10444/elisabeth-frink/lots/pasts?idcategory=2&p=1&sort=datesale_desc"),
    ("Frank Bowling", "https://www.artprice.com/artist/71265/frank-bowling/lots/pasts?idcategory=2&p=1&sort=datesale_desc"),
    ("Gaston Bernheim de Villers", "https://www.artprice.com/artist/53279/gaston-bernheim-jne-villers-de/lots/pasts?idcategory=2&p=1&sort=datesale_desc"),
    ("Gavin Turk", "https://www.artprice.com/artist/145777/gavin-turk/lots/pasts?idcategory=2&p=1&sort=datesale_desc"),
    ("Georg Scholz", "https://www.artprice.com/artist/42739/georg-scholz/lots/pasts?idcategory=2&p=1&sort=datesale_desc"),
    ("Gino Severini", "https://www.artprice.com/artist/26481/gino-severini/lots/pasts?idcategory=2&p=1&sort=datesale_desc"),
    ("Glenn Ligon", "https://www.artprice.com/artist/125485/glenn-ligon/lots/pasts?idcategory=2&p=1&sort=datesale_desc"),
    ("Grayson Perry", "https://www.artprice.com/artist/241146/grayson-perry/lots/pasts?idcategory=2&p=1&sort=datesale_desc"),
    ("Gustav Klimt", "https://www.artprice.com/artist/15495/gustav-klimt/lots/pasts?idcategory=2&p=1&sort=datesale_desc"),
    ("Howard Hodgkin", "https://www.artprice.com/artist/13628/howard-hodgkin/lots/pasts?idcategory=2&p=1&sort=datesale_desc"),
    ("Invader", "https://www.artprice.com/artist/225783/invader/lots/pasts?idcategory=2&p=1&sort=datesale_desc"),
    ("Jean Dubuffet", "https://www.artprice.com/artist/8175/jean-dubuffet/lots/pasts?idcategory=2&p=1&sort=datesale_desc"),
    ("John Hoyland", "https://www.artprice.com/artist/13967/john-hoyland/lots/pasts?idcategory=2&p=1&sort=datesale_desc"),
    ("Laurence Stephen Lowry", "https://www.artprice.com/artist/17992/laurence-stephen-lowry/lots/pasts?idcategory=2&p=1&sort=datesale_desc"),
    ("Lisa Brice", "https://www.artprice.com/artist/186134/lisa-brice/lots/pasts?idcategory=2&p=1&sort=datesale_desc"),
    ("Lucio Fontana", "https://www.artprice.com/artist/10040/lucio-fontana/lots/pasts?idcategory=2&p=1&sort=datesale_desc"),
    ("Luiz Zerbini", "https://www.artprice.com/artist/187472/luis-zerbini/lots/pasts?idcategory=2&p=1&sort=datesale_desc"),
    ("Marcel Duchamp", "https://www.artprice.com/artist/8191/marcel-duchamp/lots/pasts?idcategory=2&p=1&sort=datesale_desc"),
    ("Marcel Gromaire", "https://www.artprice.com/artist/12051/marcel-gromaire/lots/pasts?idcategory=2&p=1&sort=datesale_desc"),
    ("Marie Laurencin", "https://www.artprice.com/artist/16648/marie-laurencin/lots/pasts?idcategory=2&p=1&sort=datesale_desc"),
    ("Michael Craig-Martin", "https://www.artprice.com/artist/2346/michael-craig-martin/lots/pasts?idcategory=2&p=1&sort=datesale_desc"),
    ("Otto Dix", "https://www.artprice.com/artist/7811/otto-dix/lots/pasts?idcategory=2&p=1&sort=datesale_desc"),
    ("Paul César Helleu", "https://www.artprice.com/artist/13142/paul-cesar-helleu/lots/pasts?idcategory=2&p=1&sort=datesale_desc"),
    ("Paul Cézanne", "https://www.artprice.com/artist/5218/paul-cezanne/lots/pasts?idcategory=2&p=1&sort=datesale_desc"),
    ("Paula Rego", "https://www.artprice.com/artist/24031/paula-rego/lots/pasts?idcategory=2&p=1&sort=datesale_desc"),
    ("Rose Wylie", "https://www.artprice.com/artist/268383/rose-wylie/lots/pasts?idcategory=2&p=1&sort=datesale_desc"),
    ("Tracey Emin", "https://www.artprice.com/artist/135180/tracey-emin/lots/pasts?idcategory=2&p=1&sort=datesale_desc"),
    ("Victor Pasmore", "https://www.artprice.com/artist/22180/victor-pasmore/lots/pasts?idcategory=2&p=1&sort=datesale_desc"),
    ("William Kentridge", "https://www.artprice.com/artist/100942/william-kentridge/lots/pasts?idcategory=2&p=1&sort=datesale_desc"),
    ("Yinka Shonibare", "https://www.artprice.com/artist/145653/yinka-shonibare/lots/pasts?idcategory=2&p=1&sort=datesale_desc"),
    ("Édouard Manet", "https://www.artprice.com/artist/18630/edouard-manet/lots/pasts?idcategory=2&p=1&sort=datesale_desc"),
)

_QUALIFIED_CREDITS = (
    ("Lucio Fontana (1899-1965) after.", "Lucio Fontana after.", "Lucio Fontana", "10040"),
    ("Roy Lichtenstein (1923-1997) after.", "Roy Lichtenstein after.", "Roy Lichtenstein", "17505"),
    ("Marc Chagall (1887-1985) after.", "Marc Chagall after.", "Marc Chagall", "5240"),
    ("Gaston Bernheim de Villers (1870-1853) after. Jacques Villon",
     "Gaston Bernheim de Villers after. Jacques Villon", "Gaston Bernheim de Villers", "53279"),
    ("Marcel Duchamp (1887-1968) after. Jacques Villon",
     "Marcel Duchamp after. Jacques Villon", "Marcel Duchamp", "8191"),
    ("Marcel Gromaire (1892-1971) after. Jacques Villon",
     "Marcel Gromaire after. Jacques Villon", "Marcel Gromaire", "12051"),
    ("Marie Laurencin (1883-1956) after. Jacques Villon",
     "Marie Laurencin after. Jacques Villon", "Marie Laurencin", "16648"),
    ("Joan Miró (1893-1983) after.", "Joan Miró after.", "Joan Miró", "19928"),
    ("Pablo Picasso (1881-1973) after.", "Pablo Picasso after.", "Pablo Picasso", "22796"),
    ("Pablo Picasso (1881-1973) after. Jacques Villon",
     "Pablo Picasso after. Jacques Villon", "Pablo Picasso", "22796"),
    ("Pierre-Auguste Renoir (1841-1919) after. Jacques Villon",
     "Pierre-Auguste Renoir after. Jacques Villon", "Pierre-Auguste Renoir", "24156"),
)


class ForumArtpriceLinkTests(SimpleTestCase):
    def setUp(self):
        self.no_database = patch(
            "django.db.backends.utils.CursorWrapper.execute",
            side_effect=AssertionError("Artist-link lookup must not query the database"),
        )
        self.no_database.start()
        self.addCleanup(self.no_database.stop)

    def payload(self, *, artist, watchlist_name="", title="Composition"):
        lot = AuctionWatchLot(
            pk=91001, source="Forum", source_lot_id="forum-link-test",
            artist=artist, artist_watchlist_name=watchlist_name,
            title=title, lot_number="125", active=True, won_by_us=True,
            artprice_url="https://www.artprice.com/lots/7777/saved-study",
            lot_url="https://www.forumauctions.co.uk/bidding/test-lot",
        )
        lot._state.fields_cache["bid_board_analysis"] = None
        before = dict(lot.__dict__)
        payload = _lot_json(
            lot, ZoneInfo("America/Los_Angeles"), {lot.pk},
            {lot.pk: {"status": "pending"}},
        )
        self.assertEqual(lot.__dict__, before)
        self.assertTrue(lot._state.adding)
        self.assertTrue(payload["won_by_us"])
        self.assertTrue(payload["email_tray_selected"])
        self.assertTrue(payload["research_queue_selected"])
        self.assertEqual(payload["artprice_url"], lot.artprice_url)
        self.assertEqual(payload["lot_url"], lot.lot_url)
        return payload

    def test_all_41_supplied_names_resolve_to_exact_urls_and_scoped_queries(self):
        self.assertEqual(len(_SUPPLIED_ARTISTS), 41)
        for name, expected_url in _SUPPLIED_ARTISTS:
            with self.subTest(name=name):
                self.assertEqual(artist_research_urls(name)[0], expected_url)
                payload = self.payload(artist=name, watchlist_name=name)
                self.assertEqual(payload["artist_artprice_url"], expected_url)
                identifier = urlsplit(expected_url).path.split("/")[2]
                query = parse_qs(urlsplit(payload["artprice_search_url"]).query)
                self.assertEqual(query["idartist"], [identifier])
                self.assertEqual(query["idcategory"], ["2"])
                self.assertEqual(payload["artprice_search_scope"], "artist")
                self.assertEqual(payload["artist_source"], name)
                self.assertEqual(payload["attribution_label"], "")

    def test_audited_after_credits_link_original_artist_and_keep_qualifiers(self):
        for raw, credit, artist, identifier in _QUALIFIED_CREDITS:
            with self.subTest(credit=credit):
                expected_url = artist_research_urls(artist)[0]
                self.assertIn(f"/artist/{identifier}/", expected_url)
                self.assertEqual(artist_research_urls(raw)[0], expected_url)
                self.assertEqual(artist_research_urls(credit)[0], expected_url)
                payload = self.payload(artist=raw, watchlist_name=credit)
                self.assertEqual(payload["artist_source"], credit)
                self.assertEqual(payload["attribution_label"], "After")
                self.assertEqual(payload["artist_artprice_url"], expected_url)
                query = parse_qs(urlsplit(payload["artprice_search_url"]).query)
                self.assertEqual(query["idartist"], [identifier])
                self.assertEqual(payload["artprice_search_scope"], "artist")

    def test_expanded_rembrandt_credit_uses_existing_identity(self):
        for raw in (
            "Rembrandt Harmensz. van Rijn (1661-1669)",
            "Rembrandt Harmensz. van Rijn (1601-1669)",
        ):
            with self.subTest(raw=raw):
                payload = self.payload(artist=raw, watchlist_name="Rembrandt Harmensz. van Rijn")
                self.assertIn("/artist/24103/rembrandt-van-rijn/", payload["artist_artprice_url"])
                self.assertEqual(payload["artist_source"], "Rembrandt Harmensz. van Rijn")
                self.assertEqual(payload["attribution_label"], "")
                self.assertEqual(
                    parse_qs(urlsplit(payload["artprice_search_url"]).query)["idartist"],
                    ["24103"],
                )

    def test_unverified_names_makers_and_collaborations_do_not_pick_an_identity(self):
        for credit in (
            "Lucio Fontana Jr. after.",
            "Lucio Fontana after. Alberto Giacometti",
            "Marcel Duchamp after. Jacques Villon Jr.",
            "Marcel Duchamp after. Unknown Maker",
            "Jacques Villon after. Marcel Duchamp",
            "Jacques Villon after. Pablo Picasso",
            "Gaston Villers de Bernheim after. Jacques Villon",
            "Unknown Artist after. Jacques Villon",
            "Damien Hirst & Invader",
            "Rembrandt Harmensz. van Rijn Jr.",
            "Hubert Robert, Attributed to.",
        ):
            with self.subTest(credit=credit):
                self.assertEqual(artist_research_urls(credit)[0], "")
        self.assertIn("/artist/110693/", artist_research_urls("Damien Hirst")[0])
        self.assertIn("/artist/225783/", artist_research_urls("Invader")[0])
        composite = self.payload(
            artist="Damien Hirst (b.1965) & Invader (b.1969)",
            watchlist_name="Damien Hirst & Invader",
        )
        self.assertEqual(composite["artist_artprice_url"], "")
        self.assertEqual(composite["artist_source"], "Damien Hirst & Invader")
        self.assertEqual(composite["artprice_search_scope"], "title")
        self.assertNotIn("idartist", parse_qs(urlsplit(composite["artprice_search_url"]).query))

    def test_attribution_conflict_and_ordinary_after_title_keep_existing_behavior(self):
        attributed = self.payload(
            artist="Hubert Robert (1733-1808), Attributed to.",
            watchlist_name="Hubert Robert, Attributed to.",
            title="Stair and Fountain in the Park of a Roman Villa",
        )
        self.assertEqual(attributed["attribution_label"], "Attributed to")
        self.assertEqual(attributed["artist_artprice_url"], "")
        self.assertEqual(attributed["artprice_search_scope"], "title")
        self.assertNotIn("37149", attributed["artprice_search_url"])
        ordinary = self.payload(artist="Andy Warhol", watchlist_name="Andy Warhol", title="After the Party")
        self.assertEqual(ordinary["attribution_label"], "")
        self.assertIn("/artist/30269/", ordinary["artist_artprice_url"])
        self.assertEqual(ordinary["artist_source"], "Andy Warhol")
