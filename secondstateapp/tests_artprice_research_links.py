from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from .artprice_research_links import artprice_research_links
from .models import AuctionWatchArtist
from .tests_calendar import watch_lot


class ArtpriceResearchLinkTests(SimpleTestCase):
    def test_bookmarked_artist_scopes_generated_title_search_to_known_id(self):
        links = artprice_research_links(
            "Antoni Tàpies", "Composition (from a suite), 1984",
            "https://www.artprice.com/artist/28011/antoni-tapies/lots/pasts?idcategory=2",
        )
        query = parse_qs(urlsplit(links["artprice_search_url"]).query)
        self.assertEqual(query["idartist"], ["28011"])
        self.assertEqual(query["keyword"], ["Composition"])
        self.assertEqual(query["idcategory"], ["2"])
        self.assertEqual(links["artprice_search_scope"], "artist")

    def test_missing_bookmark_offers_artist_and_unscoped_title_searches(self):
        links = artprice_research_links("New Artist & Partner", "Café table, 1984")
        artist_query = parse_qs(urlsplit(links["artist_artprice_search_url"]).query)
        lot_query = parse_qs(urlsplit(links["artprice_search_url"]).query)
        self.assertEqual(artist_query, {"keyword": ["New Artist & Partner"]})
        self.assertEqual(lot_query["keyword"], ["Cafe-table"])
        self.assertNotIn("idartist", lot_query)
        self.assertEqual(links["artprice_search_scope"], "title")

    def test_untrusted_artist_urls_cannot_supply_an_id(self):
        for url in (
            "https://artprice.com.evil.example/artist/1/another-artist",
            "https://www.artprice.com@evil.example/artist/1/another-artist",
            "https://www.artprice.com/artist/not-numeric/another-artist",
            "https://www.artprice.com/lots/search?idartist=1",
        ):
            with self.subTest(url=url):
                links = artprice_research_links("Another Artist", "Untitled", url)
                self.assertNotIn("idartist", parse_qs(urlsplit(links["artprice_search_url"]).query))
                self.assertEqual(links["artprice_search_scope"], "title")

    def test_empty_names_and_titles_do_not_produce_empty_searches(self):
        links = artprice_research_links("", "(1984)")
        self.assertEqual(links, {
            "artist_artprice_search_url": "",
            "artprice_search_url": "",
            "artprice_search_scope": "",
        })

    def test_catalog_lot_number_placeholders_keep_only_artist_search(self):
        for title in ("Lot 123", "LOT #12A", "Lot  7"):
            for artist_url in ("", "https://www.artprice.com/artist/28011/antoni-tapies/lots/pasts"):
                with self.subTest(title=title, artist_url=artist_url):
                    links = artprice_research_links("Antoni Tàpies", title, artist_url)
                    self.assertTrue(links["artist_artprice_search_url"])
                    self.assertEqual(links["artprice_search_url"], "")
                    self.assertEqual(links["artprice_search_scope"], "")


class CalendarArtpriceResearchLinkTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user("artprice-research-links", is_staff=True)
        self.client.force_login(self.staff)

    def test_unbookmarked_sale_lot_has_searches_without_saving_or_selecting_them(self):
        lot = watch_lot(
            source="Phillips", source_lot_id="phillips-unbookmarked", artist="New Artist",
            artist_watchlist_name="", watchlist_artist=None,
        )

        response = self.client.get(reverse("auction_calendar"), {"month": "2026-07"})

        detail = response.context["calendar_data"]["2026-07-25"][0]
        self.assertEqual(detail["artist_artprice_url"], "")
        self.assertEqual(detail["artprice_search_scope"], "title")
        self.assertIn("keyword=New%20Artist", detail["artist_artprice_search_url"])
        self.assertNotIn("idartist=", detail["artprice_search_url"])
        self.assertEqual(detail["artprice_url"], "")
        self.assertFalse(detail["email_tray_selected"])
        self.assertContains(response, "Search Artprice artist ↗")
        self.assertContains(response, "Search Artprice title ↗")
        lot.refresh_from_db()
        self.assertEqual(lot.artprice_url, "")

    def test_generated_search_keeps_saved_lot_and_bookmark_urls(self):
        artist_url = "https://www.artprice.com/artist/28011/antoni-tapies/lots/pasts?keyword=old"
        saved_lot_url = "https://www.artprice.com/lots/12345/a-saved-result"
        artist = AuctionWatchArtist.objects.create(
            name="Antoni Tàpies", normalized_name="antoni tapies", artprice_url=artist_url,
        )
        lot = watch_lot(watchlist_artist=artist, artist="Antoni Tàpies", artist_watchlist_name="Antoni Tàpies", artprice_url=saved_lot_url)

        response = self.client.get(reverse("auction_calendar"), {"month": "2026-07"})

        detail = response.context["calendar_data"]["2026-07-25"][0]
        self.assertEqual(detail["artprice_url"], saved_lot_url)
        self.assertEqual(detail["artist_artprice_url"], artist_url)
        self.assertEqual(detail["artprice_search_scope"], "artist")
        query = parse_qs(urlsplit(detail["artprice_search_url"]).query)
        self.assertEqual(query["idartist"], ["28011"])
        self.assertEqual(query["keyword"], ["Jeune-fille-aux-papillons"])
        lot.refresh_from_db()
        self.assertEqual(lot.artprice_url, saved_lot_url)
