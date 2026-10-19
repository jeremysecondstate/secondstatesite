import json
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from .artist_research_registry import artist_research_urls
from .tests_calendar import watch_lot


class ArtistResearchRegistryTests(SimpleTestCase):
    def test_all_supplied_artists_resolve_from_project_bookmarks(self):
        artists = {
            "Adolph Gottlieb": "11716", "Gottlieb": "11716", "ARMAN": "788",
            "Charles Sheeler": "26539", "Chuck Close": "5928", "Claudio Bravo": "3762",
            "Damien Hirst": "110693", "Ellsworth Kelly": "15231",
            "Giovanni Battista Piranesi": "22998",
        }
        for name, identifier in artists.items():
            with self.subTest(name=name):
                artprice, invaluable = artist_research_urls(name)
                self.assertIn(f"/artist/{identifier}/", artprice)
                self.assertEqual(parse_qs(urlsplit(artprice).query)["idcategory"], ["2"])
                if name not in {"Charles Sheeler", "Claudio Bravo"}:
                    self.assertIn("https://www.invaluable.com/search?artistName=", invaluable)

    def test_cached_registry_reloads_and_rejects_ambiguous_and_unsafe_links(self):
        with TemporaryDirectory() as directory, self.settings(BASE_DIR=Path(directory)):
            docs = Path(directory) / "docs"
            docs.mkdir()
            self.assertEqual(artist_research_urls("Jane Example"), ("", ""))
            generated = docs / "artprice-artist-links.json"
            generated.write_text(json.dumps({"version": 1, "artists": [
                {"name": "Jane Example", "url": "https://www.artprice.com/artist/100/jane-example/lots/pasts",
                 "source_url": "https://www.artprice.com/artist/100/jane-example"},
                {"name": "John Example", "url": "https://www.artprice.com/artist/200/john-example/lots/pasts",
                 "source_url": "https://www.artprice.com/artist/200/john-example"},
                {"name": "Unsafe Artist", "url": "https://artprice.com.evil.test/artist/300/unsafe-artist",
                 "source_url": "https://artprice.com.evil.test/artist/300/unsafe-artist"},
            ]}), encoding="utf-8")
            self.assertIn("/artist/100/", artist_research_urls("Example, Jane")[0])
            self.assertEqual(artist_research_urls("Example"), ("", ""))
            self.assertEqual(artist_research_urls("Unsafe Artist"), ("", ""))
            generated.write_text("not valid json", encoding="utf-8")
            self.assertEqual(artist_research_urls("Jane Example"), ("", ""))

    def test_omitted_middle_initial_does_not_match_a_conflicting_initial(self):
        with TemporaryDirectory() as directory, self.settings(BASE_DIR=Path(directory)):
            docs = Path(directory) / "docs"
            docs.mkdir()
            url = "https://www.artprice.com/artist/100/john-a-smith"
            (docs / "artprice-artist-links.json").write_text(json.dumps({"version": 1, "artists": [
                {"name": "John A. Smith", "url": url + "/lots/pasts", "source_url": url},
            ]}), encoding="utf-8")
            self.assertEqual(artist_research_urls("John B. Smith"), ("", ""))
            self.assertEqual(artist_research_urls("John Smith")[0], url + "/lots/pasts")

    def test_surname_ambiguity_spans_curated_and_generated_artists(self):
        with TemporaryDirectory() as directory, self.settings(BASE_DIR=Path(directory)):
            docs = Path(directory) / "docs"
            docs.mkdir()
            curated = "https://www.artprice.com/artist/15231/ellsworth-kelly"
            generated = "https://www.artprice.com/artist/100/jane-kelly"
            (docs / "artist-links.html").write_text(
                '<DL><DT><H3>ARTPRICE</H3><DL><DT><A HREF="' + curated
                + '">Kelly, Ellsworth</A></DL></DL>', encoding="utf-8",
            )
            (docs / "artprice-artist-links.json").write_text(json.dumps({"version": 1, "artists": [
                {"name": "Jane Kelly", "url": generated, "source_url": generated},
            ]}), encoding="utf-8")
            self.assertEqual(artist_research_urls("Kelly"), ("", ""))
            self.assertEqual(artist_research_urls("Ellsworth Kelly")[0], curated)
            self.assertEqual(artist_research_urls("Jane Kelly")[0], generated)

    def test_invalid_generated_name_or_source_path_is_ignored_per_record(self):
        with TemporaryDirectory() as directory, self.settings(BASE_DIR=Path(directory)):
            docs = Path(directory) / "docs"
            docs.mkdir()
            kelly = "https://www.artprice.com/artist/15231/ellsworth-kelly"
            jane = "https://www.artprice.com/artist/100/jane-example"
            (docs / "artprice-artist-links.json").write_text(json.dumps({"version": 1, "artists": [
                {"name": "Wrong Artist", "url": kelly, "source_url": kelly},
                {"name": "Ellsworth Kelly", "url": kelly,
                 "source_url": "https://www.artprice.com/artist/15231/kelly-ellsworth"},
                {"name": "Jane Example", "url": jane, "source_url": jane},
            ]}), encoding="utf-8")
            self.assertEqual(artist_research_urls("Wrong Artist"), ("", ""))
            self.assertEqual(artist_research_urls("Ellsworth Kelly"), ("", ""))
            self.assertEqual(artist_research_urls("Jane Example")[0], jane)


class CalendarBookmarkFallbackTests(TestCase):
    def test_whole_sale_artist_gets_both_links_and_scoped_search_without_mutation(self):
        self.client.force_login(get_user_model().objects.create_user("bookmark-calendar", is_staff=True))
        saved_lot_url = "https://www.artprice.com/lots/12345/saved-work"
        lots = [watch_lot(
            source=source, source_lot_id=f"{source}-gottlieb",
            artist="Adolph Gottlieb", artist_watchlist_name="", watchlist_artist=None,
            artprice_url=saved_lot_url,
        ) for source in ("Doyle", "Phillips", "Heritage")]
        response = self.client.get(reverse("auction_calendar"), {"month": "2026-07"})
        details = {row["id"]: row for row in response.context["calendar_data"]["2026-07-25"]}
        for lot in lots:
            detail = details[lot.pk]
            self.assertIn("/artist/11716/adolph-gottlieb/", detail["artist_artprice_url"])
            self.assertIn("artistName=Adolph%2520Gottlieb", detail["artist_invaluable_url"])
            self.assertEqual(parse_qs(urlsplit(detail["artprice_search_url"]).query)["idartist"], ["11716"])
            self.assertEqual(detail["artprice_url"], saved_lot_url)
            self.assertFalse(detail["email_tray_selected"])
            lot.refresh_from_db()
            self.assertIsNone(lot.watchlist_artist_id)
            self.assertEqual(lot.artprice_url, saved_lot_url)
        self.assertContains(response, "Invaluable prints ↗")
