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
