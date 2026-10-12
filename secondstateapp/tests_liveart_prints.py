"""Calendar prints-only research uses mocked LiveArt responses, never credits."""

import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from .liveart_resale import is_prints_and_multiples
from .models import LiveArtResaleAnalysis
from .tests_calendar import liveart_artwork, liveart_lot, liveart_page, stored_analysis, watch_lot


PRINTS_CATEGORY = {"id": 2, "label": "Prints & Multiples"}


class LiveArtPrintCategoryTests(SimpleTestCase):
    def test_accepts_explicit_print_category_in_artwork_and_lot_response_shapes(self):
        artworks = [
            {"category_id": 2},
            {"category_id": "2"},
            {"category": {"id": 2}},
            {"description": {"category_id": 2}},
            {"description": {"category": {"id": "2"}}},
        ]
        for artwork in artworks:
            for raw in (artwork, {"artwork": artwork}):
                with self.subTest(raw=raw):
                    self.assertTrue(is_prints_and_multiples(raw))

    def test_missing_unknown_or_conflicting_category_does_not_infer_from_medium(self):
        invalid = [
            {}, {"materials": "Lithograph, signed and numbered"},
            {"category": {"label": "Prints & Multiples"}},
            {"category_id": None}, {"category_id": True}, {"category_id": 3},
            {"category_id": "unknown"}, {"category_id": "2,3"},
            {"category_id": 3, "description": {"category_id": 2}},
        ]
        for artwork in invalid:
            for raw in (artwork, {"artwork": artwork}):
                with self.subTest(raw=raw):
                    self.assertFalse(is_prints_and_multiples(raw))


class LiveArtPrintResearchTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user("print-research", is_staff=True)
        self.client.force_login(self.staff)
        self.lot = watch_lot()
        self.research_url = reverse("auction_lot_liveart_research", args=(self.lot.pk,))
        self.analysis_url = reverse("auction_lot_liveart_analysis", args=(self.lot.pk,))
        self.subject = liveart_artwork()
        self.sale = liveart_lot("print-sale")
        self.sale["artwork_id"] = self.subject["id"]
        self.sale["artwork"]["id"] = self.subject["id"]
        api_patch = patch("secondstateapp.calendar_views.LiveArtClient")
        self.api = api_patch.start().return_value
        self.addCleanup(api_patch.stop)
        self.api.list_artists.return_value = liveart_page([{"id": "artist-miro", "name": "Joan Miró"}])
        self.api.list_artworks.return_value = liveart_page([self.subject])
        self.api.list_lots.return_value = liveart_page([self.sale])

    def research(self, **payload):
        return self.client.post(self.research_url, json.dumps(payload), content_type="application/json")

    def save(self, research=None, **overrides):
        payload = {"action": "save", "selected_ids": ["print-sale"], "assumptions": {}}
        if research is not None:
            payload["research_id"] = research["research_id"]
        payload.update(overrides)
        return self.client.post(self.analysis_url, json.dumps(payload), content_type="application/json")

    def assert_print_requests(self):
        for request in self.api.list_artworks.call_args_list + self.api.list_lots.call_args_list:
            self.assertEqual(request.kwargs["category_id"], 2)

    def test_default_lookup_exact_history_and_related_search_are_all_filtered(self):
        nonprint = liveart_lot("painting", category_id=1, medium="Oil on canvas", lot_num="26")
        unknown = liveart_lot("unknown", category_id=None, lot_num="27")
        self.api.list_lots.return_value = liveart_page([self.sale, nonprint, unknown])
        response = self.research()
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["subject_match"]["id"], self.subject["id"])
        self.assertEqual([row["id"] for row in data["candidates"]], ["print-sale"])
        self.assertEqual(data["search_category"], PRINTS_CATEGORY)
        self.assertEqual(data["excluded_category_count"], 4)
        self.assertEqual(self.api.list_artworks.call_count, 1)
        self.assertEqual(self.api.list_lots.call_count, 2)
        self.assertTrue(any("artwork_id" in call.kwargs for call in self.api.list_lots.call_args_list))
        self.assertTrue(any("artist_id" in call.kwargs for call in self.api.list_lots.call_args_list))
        self.assert_print_requests()

    def test_wrong_and_unknown_artwork_categories_never_become_reference_choices(self):
        for category in (1, 3, None):
            with self.subTest(category=category):
                self.api.reset_mock()
                self.api.list_artworks.return_value = liveart_page([liveart_artwork("not-print", category_id=category)])
                response = self.research()
                self.assertEqual(response.status_code, 200)
                data = response.json()
                self.assertIsNone(data["subject_match"])
                self.assertEqual(data["subject_matches"], [])
                self.assertEqual(data["excluded_category_count"], 1)
                self.api.list_lots.assert_called_once()
                self.assertNotIn("artwork_id", self.api.list_lots.call_args.kwargs)
                self.assert_print_requests()
                self.api.list_lots.reset_mock()
                rejected = self.research(subject_id="not-print")
                self.assertEqual(rejected.status_code, 400)
                self.api.list_lots.assert_not_called()

    def test_manual_print_reference_history_keeps_category_filter(self):
        self.api.list_artworks.return_value = liveart_page([self.subject, liveart_artwork("another-print")])
        response = self.research(subject_id=self.subject["id"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["subject_match"]["id"], self.subject["id"])
        self.assertTrue(any("artwork_id" in call.kwargs for call in self.api.list_lots.call_args_list))
        self.assert_print_requests()

    def test_term_search_reports_only_prints_and_excluded_category_counts(self):
        nonprint = liveart_lot("painting", category_id=1, lot_num="26")
        unknown = liveart_lot("unknown", category_id=None, lot_num="27")
        first = liveart_page([nonprint, self.sale, unknown])
        first.has_more = True
        first.total_count = 42
        self.api.list_lots.side_effect = [first, liveart_page([self.sale])]
        data = self.research(search_terms="butterfly portrait").json()
        self.assertEqual([row["id"] for row in data["candidates"]], ["print-sale"])
        self.assertEqual(data["candidates"][0]["search_terms"], ["butterfly", "portrait"])
        self.assertEqual(data["search_category"], PRINTS_CATEGORY)
        self.assertEqual(data["excluded_category_count"], 2)
        self.assertEqual(data["search_summary"][0], {
            "term": "butterfly", "returned_count": 1, "excluded_count": 2,
            "has_more": True, "total_count": 42,
        })
        self.api.list_artworks.assert_not_called()
        self.assertEqual(self.api.list_lots.call_count, 2)
        self.assert_print_requests()
        rejected = self.save(data, selected_ids=["painting"])
        self.assertEqual(rejected.status_code, 400)

    def test_empty_results_and_unmatched_artist_still_record_applied_scope(self):
        self.api.list_lots.return_value = liveart_page([])
        empty = self.research(search_terms="missing").json()
        self.assertEqual(empty["candidates"], [])
        self.assertEqual(empty["search_category"], PRINTS_CATEGORY)
        self.api.list_artists.return_value = liveart_page([])
        self.api.reset_mock()
        unmatched = self.research().json()
        self.assertEqual(unmatched["search_category"], PRINTS_CATEGORY)
        self.api.list_artworks.assert_not_called()
        self.api.list_lots.assert_not_called()

    def test_filter_provenance_survives_save_reload_cost_edit_and_artprice_refresh(self):
        self.api.list_lots.return_value = liveart_page([
            self.sale, liveart_lot("not-print", category_id=1, lot_num="26"),
        ])
        research = self.research(search_terms="butterfly").json()
        self.assertEqual(self.save(research).status_code, 200)
        saved = self.client.get(self.analysis_url).json()["analysis"]
        self.assertEqual(saved["search_category"], PRINTS_CATEGORY)
        self.assertEqual(saved["excluded_category_count"], 1)
        changed = self.save(assumptions={"inbound_shipping": "200"}).json()["analysis"]
        self.assertEqual(changed["search_category"], PRINTS_CATEGORY)
        self.assertEqual(changed["excluded_category_count"], 1)
        stored_analysis(self.lot)
        refreshed = self.client.get(self.analysis_url).json()["analysis"]
        self.assertTrue(any(row["provider"] == "Artprice" for row in refreshed["candidates"]))
        self.assertEqual(refreshed["search_category"], PRINTS_CATEGORY)
        self.assertEqual(refreshed["excluded_category_count"], 1)

    def test_legacy_saved_analysis_is_not_relabelled_as_category_filtered(self):
        research = self.research().json()
        self.assertEqual(self.save(research).status_code, 200)
        analysis = LiveArtResaleAnalysis.objects.get(lot=self.lot)
        analysis.search_context = {"search_title_used": self.lot.title}
        analysis.save(update_fields=("search_context",))
        self.api.reset_mock()
        for data in (
            self.client.get(self.analysis_url).json()["analysis"],
            self.save(assumptions={"inbound_shipping": "100"}).json()["analysis"],
        ):
            self.assertNotIn("search_category", data)
            self.assertNotIn("excluded_category_count", data)
        self.api.list_artists.assert_not_called()
        self.api.list_artworks.assert_not_called()
        self.api.list_lots.assert_not_called()
