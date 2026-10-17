import json
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from .liveart_artist import liveart_artist_names_match, liveart_artist_search_name
from .liveart_search import merge_search_lots, parse_search_terms, search_query_limits
from .models import LiveArtResaleAnalysis
from .tests_calendar import liveart_artwork, liveart_lot, liveart_page, stored_analysis, watch_lot


class LiveArtSearchParsingTests(SimpleTestCase):
    def test_verified_nieto_middle_initial_matches_only_john_nieto(self):
        for source_name in (
            "John W Nieto", "John W. NIETO", "Nieto, John W.",
            "John W (1936) Nieto", "NIETO, JOHN W. (1936–2018)",
        ):
            with self.subTest(source_name=source_name):
                self.assertEqual(liveart_artist_search_name(source_name), "John Nieto")
                self.assertTrue(liveart_artist_names_match(source_name, "John NIETO"))
                self.assertTrue(liveart_artist_names_match("Nieto, John", source_name))
        for other_name in (
            "John A Nieto", "John William Nieto", "John Nieto Jr", "John W Nieto Jr",
            "Paul Nieto", "ATTRIBUTED TO JOHN W NIETO", "After John Nieto",
        ):
            with self.subTest(other_name=other_name):
                self.assertEqual(liveart_artist_search_name(other_name), other_name)
                self.assertFalse(liveart_artist_names_match(other_name, "John Nieto"))
                self.assertFalse(liveart_artist_names_match("John W Nieto", other_name))
        self.assertFalse(liveart_artist_names_match("John W Smith", "John Smith"))
        self.assertFalse(liveart_artist_names_match("John William Smith", "John Smith"))

    def test_verified_bearden_full_name_matches_only_romare_bearden(self):
        for source_name in (
            "Romare Howard Bearden", "ROMARE HOWARD BEARDEN", "Bearden, Romare Howard",
            "Romare (1911) Howard Bearden", "BEARDEN, ROMARE HOWARD (1911–1988)",
        ):
            with self.subTest(source_name=source_name):
                self.assertEqual(liveart_artist_search_name(source_name), "Romare Bearden")
                self.assertTrue(liveart_artist_names_match(source_name, "Romare Bearden"))
                self.assertTrue(liveart_artist_names_match("Romare Bearden", source_name))
        for other_name in (
            "Romare Bearden Jr", "Romare Howard Bearden Jr", "Howard Bearden",
            "Romare Henry Bearden", "ATTRIBUTED TO ROMARE HOWARD BEARDEN",
            "After Romare Bearden",
        ):
            with self.subTest(other_name=other_name):
                self.assertEqual(liveart_artist_search_name(other_name), other_name)
                self.assertFalse(liveart_artist_names_match(other_name, "Romare Bearden"))
                self.assertFalse(liveart_artist_names_match("Romare Howard Bearden", other_name))
        self.assertFalse(liveart_artist_names_match("John Howard Smith", "John Smith"))

    def test_verified_neimann_spelling_matches_only_leroy_neiman(self):
        for source_name in (
            "Leroy Neimann", "LeRoy NEIMANN", "Neimann, LeRoy",
            "Leroy (1921) Neimann", "NEIMANN, LEROY (1921–2012)",
        ):
            with self.subTest(source_name=source_name):
                self.assertEqual(liveart_artist_search_name(source_name), "Leroy Neiman")
                self.assertTrue(liveart_artist_names_match(source_name, "Leroy Neiman"))
                self.assertTrue(liveart_artist_names_match("Leroy Neiman", source_name))
        for other_name in ("Leroy Neimann Jr", "Leroy Neiman Jr", "Paul Neimann", "Leroy Nieman"):
            with self.subTest(other_name=other_name):
                self.assertFalse(liveart_artist_names_match(other_name, "Leroy Neiman"))
                self.assertFalse(liveart_artist_names_match("Leroy Neimann", other_name))

    def test_documented_hundertwasser_alias_keeps_other_artists_out(self):
        self.assertEqual(
            liveart_artist_search_name("Friedensreich HUNDERTWASSER"), "Friedrich Hundertwasser",
        )
        self.assertTrue(liveart_artist_names_match("Hundertwasser, Friedensreich", "Friedrich Hundertwasser"))
        self.assertFalse(liveart_artist_names_match("Friedensreich Hundertwasser Jr", "Friedrich Hundertwasser"))
        self.assertFalse(liveart_artist_names_match("Friedensreich Hundertwasser", "Friedrich Müller"))

    def test_words_phrases_separators_and_apostrophes(self):
        self.assertEqual(
            parse_search_terms('Boomerangs Stabiles,boomerangs;“Very Gay Nose and Ears”\nL\'oiseau'),
            ("Boomerangs", "Stabiles", "Very Gay Nose and Ears", "L'oiseau"),
        )
        self.assertEqual(parse_search_terms('"Café   noir" "Cafe noir"'), ("Café noir",))
        self.assertEqual(parse_search_terms(" \n\t"), ())

    def test_invalid_input_does_not_silently_drop_words(self):
        for value in (None, False, 7, [], {}, "x" * 201, "one two three four five six", '"unclosed phrase', '""', '"blue"red', 'red"blue"', "!!!", ", ;"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_search_terms(value)

    def test_request_allowance_is_shared_across_all_terms(self):
        for count in range(1, 6):
            limits = search_query_limits(count)
            self.assertEqual(len(limits), count)
            self.assertEqual(sum(limits), 20)
            self.assertLessEqual(max(limits) - min(limits), 1)

    def test_overlapping_ids_and_nested_sale_ids_merge_query_provenance(self):
        rows = [
            {"id": "a", "sale": {"id": "sale"}, "lot_num": "1", "_search_terms": ["Boomerangs"]},
            {"id": "b", "sale": {"id": "sale"}, "lot_num": "2", "_search_terms": ["Stabiles"]},
            {"id": "a", "sale_id": "sale", "lot_num": "2", "_search_terms": ["Prints"]},
            {"id": "c", "sale_id": "sale", "lot_num": "3", "_search_terms": ["Stabiles"]},
        ]
        results = merge_search_lots(rows)
        self.assertEqual([row["id"] for row in results], ["a", "c"])
        self.assertEqual(results[0]["_search_terms"], ["Boomerangs", "Stabiles", "Prints"])


class LiveArtTermSearchViewTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user("liveart-term-search", is_staff=True)
        self.client.force_login(self.staff)
        self.lot = watch_lot(artist="Alexander (1898) Calder", artist_watchlist_name="Alexander Calder", title="Boomerangs")
        self.url = reverse("auction_lot_liveart_research", args=(self.lot.pk,))
        self.analysis_url = reverse("auction_lot_liveart_analysis", args=(self.lot.pk,))
        self.api_patch = patch("secondstateapp.calendar_views.LiveArtClient")
        self.api_class = self.api_patch.start()
        self.addCleanup(self.api_patch.stop)
        self.api = self.api_class.return_value
        self.api.list_artists.return_value = liveart_page([{"id": "calder", "name": "Alexander Calder"}], data_units=Decimal("3"))
        self.api.list_lots.return_value = liveart_page([])
        self.api.list_artworks.return_value = liveart_page([])

    def sale(self, identifier, **overrides):
        options = {"artist_id": "calder", "artist": "Alexander Calder", "title": "Boomerangs", "lot_num": str(identifier)}
        options.update(overrides)
        return liveart_lot(str(identifier), **options)

    def research(self, **payload):
        return self.client.post(self.url, json.dumps(payload), content_type="application/json")

    def save(self, research, selected):
        return self.client.post(self.analysis_url, json.dumps({
            "action": "save", "research_id": research["research_id"],
            "selected_ids": selected, "assumptions": {},
        }), content_type="application/json")

    def test_words_fetch_both_sale_histories_without_one_artwork_choice(self):
        self.api.list_lots.side_effect = [
            liveart_page([self.sale(1)], data_units=Decimal("3.5")),
            liveart_page([self.sale(2, title="Stabiles")], data_units=Decimal("4")),
        ]
        response = self.research(search_terms="Boomerangs Stabiles")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual({row["title"] for row in payload["candidates"]}, {"Boomerangs", "Stabiles"})
        self.assertEqual(payload["search_terms_used"], ["Boomerangs", "Stabiles"])
        self.assertEqual(payload["selected_ids"], [])
        self.assertTrue(all(not row["selected"] for row in payload["candidates"]))
        self.assertTrue(all(row["match_type"] == "related_work" for row in payload["candidates"]))
        self.assertTrue(all(row["credible"] for row in payload["candidates"]))
        self.assertIsNone(payload["subject_match"])
        self.assertEqual(payload["subject_matches"], [])
        self.assertFalse(payload["requires_subject_choice"])
        self.assertEqual(payload["data_units_spent"], 10.5)
        self.api.list_artworks.assert_not_called()
        self.api.list_artists.assert_called_once_with(q="Alexander Calder", limit=3)
        self.assertEqual([call.kwargs for call in self.api.list_lots.call_args_list], [
            {"artist_id": "calder", "status": "sold", "search": term, "category_id": 2, "sort": "SALE_DATE_DESC", "limit": 10}
            for term in ("Boomerangs", "Stabiles")
        ])

    def test_nieto_middle_initial_finds_prints_and_rejects_artist_conflicts(self):
        self.lot.artist = "John W. NIETO"
        self.lot.artist_watchlist_name = "John W Nieto"
        self.lot.title = "Chicken"
        self.lot.medium = "Serigraph"
        self.lot.save(update_fields=("artist", "artist_watchlist_name", "title", "medium"))
        # These are synthetic provider identities; the request must stay mocked.
        self.api.list_artists.return_value = liveart_page([
            {"id": "nieto-attributed", "name": "ATTRIBUTED TO JOHN W NIETO"},
            {"id": "nieto-other", "name": "John A Nieto"},
            {"id": "nieto", "name": "John Nieto"},
        ])
        self.api.list_lots.return_value = liveart_page([
            liveart_lot(
                "nieto-print", artist_id="nieto", artist="John NIETO", title="Chicken",
                medium="Serigraph", lot_num="133", hammer_usd=4800,
            ),
            liveart_lot(
                "nieto-attributed-print", artist_id="nieto-attributed",
                artist="ATTRIBUTED TO JOHN W NIETO", title="Chicken",
                medium="Serigraph", lot_num="134", hammer_usd=900,
            ),
            liveart_lot(
                "nieto-other-print", artist_id="nieto-other", artist="John A Nieto",
                title="Chicken", medium="Serigraph", lot_num="135", hammer_usd=800,
            ),
        ])

        response = self.research(search_terms="Chicken")

        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.api.list_artists.assert_called_once_with(q="John Nieto", limit=3)
        self.api.list_artworks.assert_not_called()
        self.api.list_lots.assert_called_once_with(
            artist_id="nieto", status="sold", search="Chicken", category_id=2,
            sort="SALE_DATE_DESC", limit=20,
        )
        candidates = {row["id"]: row for row in payload["candidates"]}
        self.assertEqual(set(candidates), {"nieto-print", "nieto-attributed-print", "nieto-other-print"})
        self.assertTrue(candidates["nieto-print"]["credible"])
        self.assertEqual(candidates["nieto-print"]["hammer_usd"], "4800.00")
        for identifier in ("nieto-attributed-print", "nieto-other-print"):
            with self.subTest(identifier=identifier):
                self.assertFalse(candidates[identifier]["credible"])
                self.assertFalse(candidates[identifier]["manual_selectable"])
                self.assertEqual(self.save(payload, [identifier]).status_code, 400)
        self.assertEqual(payload["selected_ids"], [])
        self.assertFalse(LiveArtResaleAnalysis.objects.filter(lot=self.lot).exists())
        saved = self.save(payload, ["nieto-print"])
        self.assertEqual(saved.status_code, 200, saved.content)
        self.assertEqual(saved.json()["analysis"]["selected_ids"], ["nieto-print"])
        self.assertEqual(LiveArtResaleAnalysis.objects.get(lot=self.lot).selected_ids, ["nieto-print"])

    def test_bearden_full_name_finds_carolina_prints_and_rejects_attributed_artist(self):
        self.lot.artist = "Romare Howard Bearden"
        self.lot.artist_watchlist_name = "Romare Howard Bearden"
        self.lot.title = (
            "Romare Bearden (American, 1911-1988) Serigraph in Colors on Wove Paper 1995, "
            "'Early Carolina Morning', H 20.5\" W 29.5\""
        )
        self.lot.medium = "Serigraph"
        self.lot.save(update_fields=("artist", "artist_watchlist_name", "title", "medium"))
        self.api.list_artists.return_value = liveart_page([
            {"id": 1500540, "name": "ATTRIBUTED TO ROMARE HOWARD BEARDEN"},
            {"id": 11328, "uid": "8Bwp9T", "name": "Romare Bearden"},
        ])
        sale = liveart_lot(
            "carolina-print", artist_id=11328, artist="Romare Bearden",
            title="Early Carolina Morning", medium="Serigraph and silkscreen on Coventry rag paper",
            hammer_usd=1600,
        )
        attributed_sale = liveart_lot(
            "carolina-attributed", artist_id=1500540, artist="ATTRIBUTED TO ROMARE HOWARD BEARDEN",
            title="Early Carolina Morning", medium="Serigraph", lot_num="26", hammer_usd=900,
        )
        self.api.list_lots.return_value = liveart_page([sale, attributed_sale])

        response = self.research(search_terms='"Early Carolina Morning"')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.api.list_artists.assert_called_once_with(q="Romare Bearden", limit=3)
        self.api.list_artworks.assert_not_called()
        self.api.list_lots.assert_called_once_with(
            artist_id=11328, status="sold", search="Early Carolina Morning", category_id=2,
            sort="SALE_DATE_DESC", limit=20,
        )
        candidates = {row["id"]: row for row in payload["candidates"]}
        self.assertEqual(set(candidates), {"carolina-print", "carolina-attributed"})
        self.assertTrue(candidates["carolina-print"]["credible"])
        self.assertEqual(candidates["carolina-print"]["search_terms"], ["Early Carolina Morning"])
        self.assertFalse(candidates["carolina-attributed"]["credible"])
        self.assertFalse(candidates["carolina-attributed"]["manual_selectable"])
        self.assertEqual(payload["selected_ids"], [])
        self.assertEqual(self.save(payload, ["carolina-attributed"]).status_code, 400)
        self.assertFalse(LiveArtResaleAnalysis.objects.filter(lot=self.lot).exists())
        saved = self.save(payload, ["carolina-print"])
        self.assertEqual(saved.status_code, 200, saved.content)
        self.assertEqual(saved.json()["analysis"]["selected_ids"], ["carolina-print"])
        self.assertEqual(LiveArtResaleAnalysis.objects.get(lot=self.lot).selected_ids, ["carolina-print"])

    def test_bearden_full_name_also_finds_default_artwork_and_sale_history(self):
        self.lot.artist = "Romare Howard Bearden"
        self.lot.artist_watchlist_name = "Romare Howard Bearden"
        self.lot.title = "Early Carolina Morning"
        self.lot.medium = "Serigraph"
        self.lot.save(update_fields=("artist", "artist_watchlist_name", "title", "medium"))
        self.api.list_artists.return_value = liveart_page([
            {"id": 11328, "uid": "8Bwp9T", "name": "Romare Bearden"},
        ])
        artwork = liveart_artwork(
            "carolina-artwork", artist_id=11328, artist="Romare Bearden",
            title="Early Carolina Morning", medium="Serigraph",
        )
        sale = liveart_lot(
            "carolina-sale", artist_id=11328, artist="Romare Bearden",
            title="Early Carolina Morning", medium="Serigraph",
        )
        sale["artwork_id"] = artwork["id"]
        sale["artwork"]["id"] = artwork["id"]
        self.api.list_artworks.return_value = liveart_page([artwork])
        self.api.list_lots.return_value = liveart_page([sale])

        response = self.research(search_terms="")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["subject_match"]["id"], "carolina-artwork")
        self.assertEqual(payload["subject_match"]["artist_id"], 11328)
        self.assertEqual([row["id"] for row in payload["candidates"]], ["carolina-sale"])
        self.assertTrue(payload["candidates"][0]["credible"])
        self.api.list_artists.assert_called_once_with(q="Romare Bearden", limit=3)
        self.api.list_artworks.assert_called_once_with(
            artist_id=11328, search="Early Carolina Morning", category_id=2, limit=5,
        )
        self.api.list_lots.assert_any_call(
            artwork_id="carolina-artwork", status="sold", category_id=2, limit=10,
        )

    def test_neimann_spelling_finds_sinatra_sales_and_rejects_other_artists(self):
        self.lot.artist = "Leroy Neimann"
        self.lot.artist_watchlist_name = "Leroy Neimann"
        self.lot.title = (
            "Leroy Neiman (American, 1921-2012) Serigraph on Paper, Ca. 1994, "
            "'Frank Sinatra, Duets', H 28.75\" W 28.75\""
        )
        self.lot.medium = "Serigraph"
        self.lot.save(update_fields=("artist", "artist_watchlist_name", "title", "medium"))
        self.api.list_artists.return_value = liveart_page([
            {"id": 999, "name": "Paul Neiman"},
            {"id": 25667, "uid": "c9GBTz", "name": "Leroy Neiman"},
        ])
        sale = liveart_lot(
            "sinatra-print", artist_id=25667, artist="Leroy Neiman",
            title="FRANK SINATRA, DUETS", medium="Screenprint in colors, on wove paper",
            hammer_usd=2400,
        )
        wrong_artist_sale = liveart_lot(
            "other-sinatra", artist_id=999, artist="Leroy Neimann Jr",
            title="FRANK SINATRA, DUETS", medium="Screenprint in colors, on wove paper",
            lot_num="26", hammer_usd=1800,
        )
        self.api.list_lots.side_effect = [
            liveart_page([sale]), liveart_page([sale, wrong_artist_sale]),
        ]

        response = self.research(search_terms='"Frank Sinatra, Duets" "Frank Sinatra"')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.api.list_artists.assert_called_once_with(q="Leroy Neiman", limit=3)
        self.api.list_artworks.assert_not_called()
        self.assertEqual([call.kwargs for call in self.api.list_lots.call_args_list], [
            {"artist_id": 25667, "status": "sold", "search": term, "category_id": 2,
             "sort": "SALE_DATE_DESC", "limit": 10}
            for term in ("Frank Sinatra, Duets", "Frank Sinatra")
        ])
        candidates = {row["id"]: row for row in payload["candidates"]}
        self.assertEqual(set(candidates), {"sinatra-print", "other-sinatra"})
        self.assertTrue(candidates["sinatra-print"]["credible"])
        self.assertEqual(candidates["sinatra-print"]["search_terms"], ["Frank Sinatra, Duets", "Frank Sinatra"])
        self.assertFalse(candidates["other-sinatra"]["credible"])
        self.assertFalse(candidates["other-sinatra"]["manual_selectable"])
        self.assertEqual(payload["selected_ids"], [])
        self.assertEqual(self.save(payload, ["other-sinatra"]).status_code, 400)
        self.assertFalse(LiveArtResaleAnalysis.objects.filter(lot=self.lot).exists())
        saved = self.save(payload, ["sinatra-print"])
        self.assertEqual(saved.status_code, 200, saved.content)
        self.assertEqual(saved.json()["analysis"]["selected_ids"], ["sinatra-print"])
        self.assertEqual(LiveArtResaleAnalysis.objects.get(lot=self.lot).selected_ids, ["sinatra-print"])

    def test_neimann_spelling_also_finds_default_artwork_and_sale_history(self):
        self.lot.artist = "Leroy Neimann"
        self.lot.artist_watchlist_name = "Leroy Neimann"
        self.lot.title = "Frank Sinatra, Duets"
        self.lot.save(update_fields=("artist", "artist_watchlist_name", "title"))
        self.api.list_artists.return_value = liveart_page([
            {"id": 25667, "uid": "c9GBTz", "name": "Leroy Neiman"},
        ])
        artwork = liveart_artwork(
            "sinatra-artwork", artist_id=25667, artist="Leroy Neiman", title="Frank Sinatra, Duets",
        )
        sale = liveart_lot(
            "sinatra-sale", artist_id=25667, artist="Leroy Neiman", title="Frank Sinatra, Duets",
        )
        sale["artwork_id"] = artwork["id"]
        sale["artwork"]["id"] = artwork["id"]
        self.api.list_artworks.return_value = liveart_page([artwork])
        self.api.list_lots.return_value = liveart_page([sale])

        response = self.research(search_terms="")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["subject_match"]["id"], "sinatra-artwork")
        self.assertEqual(payload["subject_match"]["artist_id"], 25667)
        self.assertEqual([row["id"] for row in payload["candidates"]], ["sinatra-sale"])
        self.assertTrue(payload["candidates"][0]["credible"])
        self.api.list_artists.assert_called_once_with(q="Leroy Neiman", limit=3)
        self.api.list_artworks.assert_called_once_with(
            artist_id=25667, search="Frank Sinatra, Duets", category_id=2, limit=5,
        )
        self.api.list_lots.assert_any_call(
            artwork_id="sinatra-artwork", status="sold", category_id=2, limit=10,
        )

    def test_hundertwasser_alias_finds_and_accepts_burning_winter_sales(self):
        self.lot.artist = "Friedensreich HUNDERTWASSER"
        self.lot.artist_watchlist_name = "Friedensreich Hundertwasser"
        self.lot.title = "Burning Winter (Winter lichterloh)"
        self.lot.save(update_fields=("artist", "artist_watchlist_name", "title"))
        self.api.list_artists.return_value = liveart_page([
            {"id": "other", "name": "Friedrich Müller"},
            {"id": "hundertwasser", "name": "Friedrich Hundertwasser"},
        ])
        self.api.list_lots.side_effect = [
            liveart_page([liveart_lot(
                "41", artist_id="hundertwasser", artist="Friedrich Hundertwasser",
                title="Burning Winter (Winter Lichterloh)", lot_num="41", hammer_usd=3200,
            )]),
            liveart_page([liveart_lot(
                "42", artist_id="hundertwasser", artist="Friedrich Hundertwasser",
                title="BURNING WINTER (KOSCHATZKY 67)", lot_num="42", hammer_usd=3125,
            )]),
        ]

        research = self.research(search_terms="Burning Winter")

        self.assertEqual(research.status_code, 200)
        payload = research.json()
        self.api.list_artists.assert_called_once_with(q="Friedrich Hundertwasser", limit=3)
        self.assertEqual(
            [call.kwargs["artist_id"] for call in self.api.list_lots.call_args_list],
            ["hundertwasser", "hundertwasser"],
        )
        self.assertEqual({row["id"] for row in payload["candidates"]}, {"41", "42"})
        self.assertTrue(all(row["credible"] for row in payload["candidates"]))
        self.assertEqual(payload["selected_ids"], [])
        self.assertEqual(self.save(payload, ["41", "42"]).status_code, 200)

    def test_hundertwasser_alias_also_works_for_default_artwork_search(self):
        self.lot.artist = "Friedensreich HUNDERTWASSER"
        self.lot.title = "Burning Winter"
        self.lot.save(update_fields=("artist", "title"))
        self.api.list_artists.return_value = liveart_page([
            {"id": "hundertwasser", "name": "Friedrich Hundertwasser"},
        ])
        artwork = liveart_artwork(
            "burning-winter", artist_id="hundertwasser", artist="Friedrich Hundertwasser",
            title="Burning Winter",
        )
        sale = liveart_lot(
            "43", artist_id="hundertwasser", artist="Friedrich Hundertwasser",
            title="Burning Winter", hammer_usd=3628,
        )
        sale["artwork_id"] = artwork["id"]
        sale["artwork"]["id"] = artwork["id"]
        self.api.list_artworks.return_value = liveart_page([artwork])
        self.api.list_lots.return_value = liveart_page([sale])

        response = self.research(search_terms="")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["subject_match"]["id"], "burning-winter")
        self.assertTrue(payload["candidates"][0]["credible"])
        self.api.list_artists.assert_called_once_with(q="Friedrich Hundertwasser", limit=3)

    def test_old_hundertwasser_print_can_be_selected_after_manual_review(self):
        self.lot.artist = "Friedensreich HUNDERTWASSER"
        self.lot.artist_watchlist_name = "Friedensreich Hundertwasser"
        self.lot.title = "Burning Winter (Winter Lichterloh)"
        self.lot.medium = "screenprint on paper"
        self.lot.save(update_fields=("artist", "artist_watchlist_name", "title", "medium"))
        self.api.list_artists.return_value = liveart_page([
            {"id": "hundertwasser", "name": "Friedrich Hundertwasser"},
        ])
        old_sale = liveart_lot(
            "252", artist_id="hundertwasser", artist="Friedrich Hundertwasser",
            title="Burning winter", medium="", sale_date="2000-12-06T12:00:00Z",
            hammer_usd=4026,
        )
        old_sale["auction_house_name"] = "Sotheby's"
        self.api.list_lots.return_value = liveart_page([old_sale])

        response = self.research(search_terms="Burning")
        self.assertEqual(response.status_code, 200)
        research = response.json()
        candidate = research["candidates"][0]
        self.assertFalse(candidate["credible"])
        self.assertTrue(candidate["manual_selectable"])
        self.assertFalse(candidate["selected"])
        self.assertEqual(research["selected_ids"], [])
        self.assertEqual(candidate["hammer_usd"], "4026.00")

        # A session created before this field existed is rechecked without a new API call.
        session = self.client.session
        session[f"liveart_research_{self.lot.pk}"]["candidates"][0].pop("manual_selectable")
        session.save()
        list_lots_calls = self.api.list_lots.call_count
        saved = self.save(research, ["252"])
        self.assertEqual(saved.status_code, 200, saved.content)
        analysis = saved.json()["analysis"]
        self.assertEqual(analysis["selected_ids"], ["252"])
        self.assertTrue(analysis["candidates"][0]["manual_selectable"])
        self.assertEqual(analysis["scenarios"][1]["resale_hammer"], "4026.00")
        self.assertEqual(self.api.list_lots.call_count, list_lots_calls)

        stored = LiveArtResaleAnalysis.objects.get(lot=self.lot)
        stored.candidates[0].pop("manual_selectable")
        stored.save(update_fields=["candidates"])
        reloaded = self.client.get(self.analysis_url).json()["analysis"]
        self.assertEqual(reloaded["selected_ids"], ["252"])
        self.assertTrue(reloaded["candidates"][0]["manual_selectable"])
        self.assertEqual(reloaded["scenarios"][1]["resale_hammer"], "4026.00")
        self.assertEqual(self.api.list_lots.call_count, list_lots_calls)

    def test_empty_first_term_still_fetches_second_and_reports_limited_page(self):
        second = liveart_page([self.sale(2, title="Stabiles")])
        second.has_more = True
        second.total_count = None
        self.api.list_lots.side_effect = [liveart_page([]), second]
        payload = self.research(search_terms="missing Stabiles").json()
        self.assertEqual([row["id"] for row in payload["candidates"]], ["2"])
        self.assertEqual(payload["search_summary"], [
            {"term": "missing", "returned_count": 0, "has_more": False, "total_count": 0},
            {"term": "Stabiles", "returned_count": 1, "has_more": True},
        ])

    def test_duplicate_sales_are_counted_once_and_provenance_survives_saving(self):
        first = self.sale(11)
        same_sale = self.sale(12, lot_num="11")
        same_sale.pop("sale_id")
        self.api.list_lots.side_effect = [
            liveart_page([first]), liveart_page([same_sale, self.sale(13, title="Stabiles")]),
        ]
        research = self.research(search_terms="Boomerangs Stabiles").json()
        self.assertEqual(len(research["candidates"]), 2)
        merged = next(row for row in research["candidates"] if row["id"] == "11")
        self.assertEqual(merged["search_terms"], ["Boomerangs", "Stabiles"])
        saved = self.save(research, ["11", "13"])
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["analysis"]["source_summary"]["liveart_selected_count"], 2)
        stored = LiveArtResaleAnalysis.objects.get(lot=self.lot)
        self.assertEqual(stored.candidates[0]["search_terms"], ["Boomerangs", "Stabiles"])
        reloaded = self.client.get(self.analysis_url).json()["analysis"]
        self.assertEqual(reloaded["candidates"][0]["search_terms"], ["Boomerangs", "Stabiles"])

    def test_zero_result_term_and_has_more_survive_save_reload_and_cost_edit(self):
        page = liveart_page([self.sale(1)])
        page.has_more = True
        page.total_count = 31
        self.api.list_lots.side_effect = [liveart_page([]), page]
        research = self.research(search_terms="Missing Boomerangs").json()
        self.assertEqual(self.save(research, ["1"]).status_code, 200)
        reloaded = self.client.get(self.analysis_url).json()["analysis"]
        self.assertEqual(reloaded["search_terms_used"], ["Missing", "Boomerangs"])
        self.assertEqual(reloaded["search_summary"], research["search_summary"])
        self.assertTrue(reloaded["search_summary"][1]["has_more"])
        edited = self.client.post(self.analysis_url, json.dumps({
            "action": "save", "selected_ids": ["1"], "assumptions": {"inbound_shipping": "300"},
        }), content_type="application/json")
        self.assertEqual(edited.status_code, 200)
        self.assertEqual(edited.json()["analysis"]["search_summary"], research["search_summary"])
        self.assertEqual(LiveArtResaleAnalysis.objects.get(lot=self.lot).search_context["search_terms_used"], ["Missing", "Boomerangs"])
        stored_analysis(self.lot)
        refreshed = self.client.get(self.analysis_url).json()["analysis"]
        self.assertTrue(any(row["provider"] == "Artprice" for row in refreshed["candidates"]))
        self.assertEqual(refreshed["search_summary"], research["search_summary"])

    def test_term_search_keeps_twenty_five_selected_sale_limit(self):
        self.api.list_lots.return_value = liveart_page([self.sale(1)])
        payload = self.research(search_terms="Boomerangs").json()
        self.assertEqual(self.save(payload, ["1"] * 26).status_code, 400)

    def test_five_queries_share_twenty_results_and_metered_units(self):
        self.api.list_artists.return_value.data_units = Decimal("5")
        def lots(**filters):
            return liveart_page([
                self.sale(f"{filters['search']}-{index}") for index in range(filters["limit"])
            ], data_units=Decimal(2 + filters["limit"]))
        self.api.list_lots.side_effect = lots
        payload = self.research(search_terms="one two three four five").json()
        self.assertEqual(len(payload["candidates"]), 20)
        self.assertEqual(len(self.api.list_lots.call_args_list), 5)
        self.assertEqual(sum(call.kwargs["limit"] for call in self.api.list_lots.call_args_list), 20)
        self.assertEqual(payload["data_units_spent"], 35)
        self.api.list_artworks.assert_not_called()

    def test_phrase_is_one_query_and_normalized_duplicates_do_not_spend_more(self):
        response = self.research(search_terms='“Very Gay Nose and Ears” "very gay nose and ears"')
        self.assertEqual(response.status_code, 200)
        self.api.list_lots.assert_called_once_with(
            artist_id="calder", status="sold", search="Very Gay Nose and Ears", category_id=2, sort="SALE_DATE_DESC", limit=20,
        )

    def test_invalid_terms_and_unsupported_subject_do_not_call_provider(self):
        for value in (None, False, 7, [], {}, "x" * 201, "one two three four five six", '"unclosed'):
            with self.subTest(value=value):
                self.assertEqual(self.research(search_terms=value).status_code, 400)
        self.assertEqual(self.research(search_terms="Boomerangs", subject_id="some-artwork").status_code, 400)
        self.api_class.assert_not_called()

    def test_wrong_artist_and_premium_only_results_cannot_enter_bid_math(self):
        wrong = self.sale(31, artist="Joan Miró", artist_id="miro")
        premium_only = self.sale(32, hammer_usd=None)
        premium_only["price"]["premium"] = 2000
        self.api.list_lots.return_value = liveart_page([wrong, premium_only])
        payload = self.research(search_terms="Boomerangs").json()
        self.assertTrue(all(not row["credible"] for row in payload["candidates"]))
        self.assertEqual(self.save(payload, ["31"]).status_code, 400)
        self.assertEqual(self.save(payload, ["32"]).status_code, 400)
        self.assertFalse(LiveArtResaleAnalysis.objects.filter(lot=self.lot).exists())

    def test_legacy_research_with_unverified_print_category_cannot_be_selected(self):
        self.api.list_lots.return_value = liveart_page([self.sale(33)])
        for category_id in ("1", None):
            with self.subTest(category_id=category_id):
                research = self.research(search_terms="Boomerangs").json()
                self.assertTrue(research["candidates"][0]["credible"])
                session = self.client.session
                session[f"liveart_research_{self.lot.pk}"]["candidates"][0]["category_id"] = category_id
                session.save()
                self.assertEqual(self.save(research, ["33"]).status_code, 400)
        self.assertFalse(LiveArtResaleAnalysis.objects.filter(lot=self.lot).exists())

    def test_unknown_usage_remains_unknown(self):
        self.api.list_lots.return_value = liveart_page([self.sale(1)], data_units=None)
        self.assertIsNone(self.research(search_terms="Boomerangs").json()["data_units_spent"])

    def test_new_term_search_invalidates_old_research_snapshot(self):
        self.api.list_lots.return_value = liveart_page([self.sale(1)])
        first = self.research(search_terms="Boomerangs").json()
        second = self.research(search_terms="Stabiles").json()
        self.assertNotEqual(first["research_id"], second["research_id"])
        self.assertEqual(self.save(first, ["1"]).status_code, 409)
        self.assertEqual(self.save(second, ["1"]).status_code, 200)

    def test_empty_terms_and_legacy_title_keep_existing_full_title_path(self):
        self.assertEqual(self.research(search_terms="  ").status_code, 200)
        self.api.list_artworks.assert_called_once_with(artist_id="calder", search="Boomerangs", category_id=2, limit=5)
        self.api.list_artworks.reset_mock()
        self.assertEqual(self.research(search_title="Very Gay Nose and Ears").status_code, 200)
        self.api.list_artworks.assert_called_once_with(artist_id="calder", search="Very Gay Nose and Ears", category_id=2, limit=5)

    def test_unmatched_artist_does_not_query_other_artists_sales(self):
        self.api.list_artists.return_value = liveart_page([{"id": "miro", "name": "Joan Miró"}])
        payload = self.research(search_terms="Boomerangs Stabiles").json()
        self.assertEqual(payload["candidates"], [])
        self.assertEqual(payload["search_terms_used"], ["Boomerangs", "Stabiles"])
        self.assertEqual(payload["search_summary"], [])
        self.api.list_lots.assert_not_called()
        self.api.list_artworks.assert_not_called()
