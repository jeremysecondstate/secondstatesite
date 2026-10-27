"""Browser-sourced LiveArt evidence uses the existing saved-comps workflow."""

import copy
import json
from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .models import AuctionBidBoardAnalysis, LiveArtResaleAnalysis
from .tests_calendar import stored_analysis, watch_lot


class ManualLiveArtEvidenceTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user("web-evidence-staff", is_staff=True)
        self.client.force_login(self.staff)
        self.lot = watch_lot(current_bid="500", bid_count=0)
        self.url = reverse("auction_lot_liveart_analysis", args=(self.lot.pk,))
        self.research_url = reverse("auction_lot_liveart_research", args=(self.lot.pk,))
        self.board_url = reverse("auction_lot_bid_board", args=(self.lot.pk,))
        self.entry = {
            "artist": self.lot.artist,
            "price_basis": "hammer", "currency": "USD",
            "category": "prints_and_multiples", "status": "sold",
            "title": "Jeune fille aux papillons",
            "sale_date": "2024-06-12",
            "auction_house": "Bonhams",
            "lot_number": "72",
            "hammer_usd": "3305.00",
            "provider_url": "https://www.liveart.ai/price-database/artwork/test-sale",
            "evidence_note": "LiveArt sale record: sold; hammer USD 3,305, excluding buyer premium. Prints & Multiples.",
            "original_hammer": "3000.00",
            "original_currency": "CHF",
            "lot_url": "https://www.bonhams.com/auction/12345/lot/72/",
            "medium": "Color lithograph",
            "edition": "10/65",
        }

    def post(self, **payload):
        return self.client.post(self.url, json.dumps(payload), content_type="application/json")

    def add(self, *, entry=None, **overrides):
        payload = {
            "action": "add_manual", "entry": self.entry if entry is None else entry,
            "confirmed": True, "selected_ids": [],
        }
        payload.update(overrides)
        return self.post(**payload)

    def added(self, **overrides):
        response = self.add(**overrides)
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertTrue(data["ok"])
        return data

    def save(self, research):
        response = self.post(action="save", research_id=research["research_id"],
                             selected_ids=[research["added_id"]], assumptions={})
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["analysis"]

    @patch("secondstateapp.calendar_views.LiveArtClient")
    @patch("secondstateapp.calendar_views._research_liveart_lot")
    def test_manual_sale_saves_and_feeds_bid_board_without_api_calls(self, paid_lookup, client_class):
        research = self.added()
        self.assertFalse(LiveArtResaleAnalysis.objects.exists())
        candidate = next(item for item in research["candidates"] if item["id"] == research["added_id"])
        self.assertEqual(research["selected_ids"], [])
        self.assertFalse(candidate["selected"])
        self.assertEqual(candidate["entry_method"], "manual_web")
        self.assertEqual(candidate["match_type"], "liveart_web")
        self.assertEqual(candidate["provider"], "LiveArt")
        self.assertFalse(candidate["credible"])
        self.assertTrue(candidate["manual_selectable"])
        self.assertEqual(candidate["original_currency"], "CHF")
        self.assertEqual(candidate["original_hammer"], "3000.00")
        self.assertEqual(candidate["provider_url"], self.entry["provider_url"])
        self.assertEqual(candidate["evidence_note"], self.entry["evidence_note"])
        self.assertTrue(candidate["retrieved_at"])

        analysis = self.save(research)
        self.assertEqual(analysis["source_summary"]["combined_comp_count"], 1)
        self.assertEqual(analysis["selected_ids"], [candidate["id"]])
        reloaded = self.client.get(self.url).json()["analysis"]
        self.assertEqual(reloaded["candidates"][0]["entry_method"], "manual_web")

        board = self.client.post(self.board_url, json.dumps({"action": "save"}), content_type="application/json")
        self.assertEqual(board.status_code, 200, board.content)
        result = board.json()["analysis"]
        self.assertEqual(result["source_summary"]["combined_comp_count"], 1)
        self.assertEqual(result["cases"][1]["resale_hammer"], "3305.00")
        self.assertTrue(result["rows"])
        saved = AuctionBidBoardAnalysis.objects.get(lot=self.lot)
        self.assertEqual(saved.evidence_snapshot["selected_records"][0]["provider_url"], self.entry["provider_url"])
        self.assertEqual(saved.evidence_snapshot["selected_records"][0]["entry_method"], "manual_web")
        paid_lookup.assert_not_called()
        client_class.assert_not_called()

    def test_staff_and_csrf_are_required(self):
        self.client.logout()
        self.assertEqual(self.add().status_code, 302)
        ordinary = get_user_model().objects.create_user("web-evidence-reader")
        self.client.force_login(ordinary)
        self.assertEqual(self.add().status_code, 302)
        guarded = Client(enforce_csrf_checks=True)
        guarded.force_login(self.staff)
        response = guarded.post(self.url, json.dumps({"action": "add_manual", "entry": self.entry}), content_type="application/json")
        self.assertEqual(response.status_code, 403)
        self.assertFalse(LiveArtResaleAnalysis.objects.exists())

    @patch("secondstateapp.calendar_views.LiveArtClient")
    @patch("secondstateapp.calendar_views._research_liveart_lot")
    def test_drawing_category_persists_through_evidence_and_board_without_relabeling(self, paid_lookup, client_class):
        first = self.added()
        self.save(first)
        board = self.client.post(self.board_url, json.dumps({"action": "save"}), content_type="application/json")
        self.assertEqual(board.status_code, 200, board.content)
        AuctionBidBoardAnalysis.objects.filter(lot=self.lot).update(include_in_email=True)
        subject_medium = self.lot.medium
        drawing = {**self.entry, "category": "works_on_paper", "title": "Pencil study", "lot_number": "73",
                   "medium": "Pencil on paper", "edition": "", "signature": "Signed",
                   "evidence_note": "LiveArt Works on paper; sold; USD hammer 3305 excluding premium."}
        research = self.added(entry=drawing, selected_ids=[first["added_id"]])
        candidate = next(row for row in research["candidates"] if row["id"] == research["added_id"])
        self.assertEqual(candidate["category"], "works_on_paper")
        self.assertEqual(candidate["category_label"], "Drawings / Works on paper")
        self.assertIsNone(candidate["category_id"])
        self.assertEqual(candidate["medium"], "Pencil on paper")
        self.assertEqual(candidate["original_currency"], "CHF")
        self.assertTrue(candidate["manual_selectable"])
        self.assertFalse(candidate["selected"])
        selected = [first["added_id"], candidate["id"]]
        response = self.post(action="save", research_id=research["research_id"], selected_ids=selected, assumptions={})
        self.assertEqual(response.status_code, 200, response.content)
        reloaded = self.client.get(self.url).json()["analysis"]
        self.assertEqual(set(reloaded["selected_ids"]), set(selected))
        saved_drawing = next(row for row in reloaded["candidates"] if row["id"] == candidate["id"])
        self.assertEqual(saved_drawing["category"], "works_on_paper")
        self.assertIsNone(saved_drawing["category_id"])
        self.assertTrue(saved_drawing["manual_selectable"])
        board = self.client.post(self.board_url, json.dumps({"action": "save"}), content_type="application/json")
        self.assertEqual(board.status_code, 200, board.content)
        self.assertEqual(board.json()["analysis"]["source_summary"]["combined_comp_count"], 2)
        self.assertEqual(board.json()["analysis"]["cases"][1]["resale_hammer"], "3305.00")
        saved_board = AuctionBidBoardAnalysis.objects.get(lot=self.lot)
        self.assertTrue(saved_board.include_in_email)
        record = next(row for row in saved_board.evidence_snapshot["selected_records"] if row["id"] == candidate["id"])
        self.assertEqual(record["category"], "works_on_paper")
        self.assertIsNone(record["category_id"])
        self.lot.refresh_from_db()
        self.assertEqual(self.lot.medium, subject_medium)
        paid_lookup.assert_not_called()
        client_class.assert_not_called()

    def test_drawing_entry_keeps_all_sale_and_attestation_requirements(self):
        drawing = {**self.entry, "category": "works_on_paper", "medium": "Pencil on paper"}
        for change in ({"category": "painting"}, {"category": ""}, {"category": {}},
                       {"category_id": 2}, {"status": "unsold"}, {"price_basis": "premium_inclusive"},
                       {"currency": "CHF"}, {"artist": "Pablo Picasso"}, {"sale_date": ""},
                       {"sale_date": (date.today() + timedelta(days=3)).isoformat()}, {"hammer_usd": "0"}):
            with self.subTest(change=change):
                self.assertEqual(self.add(entry={**drawing, **change}).status_code, 400)
        self.assertEqual(self.add(entry=drawing, confirmed=False).status_code, 400)

    def test_saved_drawing_eligibility_is_rechecked_before_selection(self):
        research = self.added(entry={**self.entry, "category": "works_on_paper", "medium": "Pencil on paper"})
        self.save(research)
        saved = LiveArtResaleAnalysis.objects.get(lot=self.lot)
        original = copy.deepcopy(saved.candidates)
        for change in ({"entry_method": "api"}, {"source_confirmed": False}, {"category_id": 2},
                       {"category": "painting"}, {"price_basis": "premium_inclusive"}, {"hammer_currency": "CHF"},
                       {"sale_date": None}, {"sale_date": "bad-date"},
                       {"sale_date": (date.today() + timedelta(days=3)).isoformat()}, {"artist": "Pablo Picasso"}):
            with self.subTest(change=change):
                saved.candidates = [{**original[0], **change}]
                saved.save(update_fields=["candidates"])
                reloaded = self.client.get(self.url).json()["analysis"]
                self.assertFalse(reloaded["candidates"][0]["manual_selectable"])
                self.assertNotIn(research["added_id"], reloaded["selected_ids"])
                self.assertEqual(self.post(action="save", selected_ids=[research["added_id"]], assumptions={}).status_code, 400)
                board = self.client.post(self.board_url, json.dumps({"action": "save", "selected_ids": [research["added_id"]]}), content_type="application/json")
                self.assertEqual(board.status_code, 400, board.content)

    def test_duplicate_sale_cannot_silently_keep_a_conflicting_category(self):
        first = self.added()
        response = self.add(entry={**self.entry, "category": "works_on_paper"}, research_id=first["research_id"])
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("different artwork category", response.json()["error"])
        pending = self.client.session[f"liveart_research_{self.lot.pk}"]
        self.assertEqual(len(pending["candidates"]), 1)
        self.assertEqual(pending["candidates"][0]["category"], "prints_and_multiples")

    def test_required_source_and_sale_identity_fields(self):
        for field in ("artist", "title", "sale_date", "auction_house", "lot_number", "hammer_usd", "provider_url", "evidence_note", "price_basis", "currency", "category", "status"):
            with self.subTest(field=field):
                entry = {key: value for key, value in self.entry.items() if key != field}
                response = self.add(entry=entry)
                self.assertEqual(response.status_code, 400, response.content)
        self.assertNotIn(f"liveart_research_{self.lot.pk}", self.client.session)

    def test_price_sale_category_and_attestation_are_explicit(self):
        for field, value in (("confirmed", False), ("confirmed", "true"), ("confirmed", 1),
                             ("price_basis", "premium_inclusive"), ("currency", "CHF"),
                             ("category", "painting"), ("status", "unsold")):
            with self.subTest(field=field, value=value):
                response = self.add(**{field: value}) if field == "confirmed" else self.add(entry={**self.entry, field: value})
                self.assertEqual(response.status_code, 400, response.content)

    def test_rejects_artist_conflict_future_dates_and_invalid_money(self):
        cases = [("artist", "Pablo Picasso"), ("sale_date", "not a date"),
                 ("sale_date", (date.today() + timedelta(days=3)).isoformat()),
                 *( ("hammer_usd", value) for value in (True, "NaN", "Infinity", "-1", "0", "1000000000001", {}, []))]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                response = self.add(entry={**self.entry, field: value})
                self.assertEqual(response.status_code, 400, response.content)

    def test_source_links_are_safe_liveart_web_records(self):
        for url in ("javascript:alert(1)", "http://www.liveart.ai/sale/1", "https://liveart.ai.evil.example/sale/1",
                    "https://evil.example/sale/1", "https://user:password@liveart.ai/sale/1", "https://127.0.0.1/sale/1",
                    "https://api.liveart.ai/v1/lots?id=1"):
            with self.subTest(url=url):
                response = self.add(entry={**self.entry, "provider_url": url})
                self.assertEqual(response.status_code, 400, response.content)
        response = self.add(entry={**self.entry, "lot_url": "javascript:alert(1)"})
        self.assertEqual(response.status_code, 400, response.content)

    def test_original_hammer_and_currency_must_be_a_complete_valid_pair(self):
        for change in ({"original_currency": ""}, {"original_hammer": ""},
                       {"original_hammer": "NaN"}, {"original_currency": "not currency"},
                       {"original_currency": "USD", "original_hammer": "3306"}):
            with self.subTest(change=change):
                response = self.add(entry={**self.entry, **change})
                self.assertEqual(response.status_code, 400, response.content)

    def test_forged_normalized_flags_and_oversized_fields_rejected(self):
        for change in ({"credible": True}, {"manual_selectable": True}, {"category_id": 2},
                       {"title": "x" * 10000}, {"evidence_note": "x" * 15000}):
            with self.subTest(change=list(change)):
                response = self.add(entry={**self.entry, **change})
                self.assertEqual(response.status_code, 400, response.content)
        response = self.client.post(self.url, "x" * 20001, content_type="application/json")
        self.assertEqual(response.status_code, 413)

    def test_duplicate_replay_keeps_one_candidate_and_conflicting_price_cannot_overwrite(self):
        first = self.added()
        second = self.added(research_id=first["research_id"])
        self.assertEqual(second["added_id"], first["added_id"])
        self.assertEqual(len(second["candidates"]), 1)
        response = self.add(entry={**self.entry, "hammer_usd": "9900"}, research_id=second["research_id"])
        self.assertIn(response.status_code, (400, 409), response.content)
        stored = self.client.session[f"liveart_research_{self.lot.pk}"]
        self.assertEqual(stored["candidates"][0]["hammer_usd"], "3305.00")

    def test_stale_token_and_invalid_selections_do_not_replace_research(self):
        first = self.added()
        original = copy.deepcopy(self.client.session[f"liveart_research_{self.lot.pk}"])
        response = self.add(research_id="stale-tab-token")
        self.assertEqual(response.status_code, 409, response.content)
        response = self.add(research_id=first["research_id"], selected_ids=["forged"])
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(self.client.session[f"liveart_research_{self.lot.pk}"], original)

    def test_adding_another_sale_preserves_saved_selection_and_assumptions(self):
        first = self.added()
        self.save(first)
        saved = LiveArtResaleAnalysis.objects.get(lot=self.lot)
        saved.assumptions["target_profit"] = "432.00"
        saved.save(update_fields=["assumptions"])
        next_entry = {**self.entry, "lot_number": "73", "provider_url": "https://www.liveart.ai/price-database/artwork/another-sale"}
        second = self.added(entry=next_entry, selected_ids=[first["added_id"]])
        self.assertEqual(second["selected_ids"], [first["added_id"]])
        self.assertEqual(len(second["candidates"]), 2)
        saved.refresh_from_db()
        self.assertEqual(saved.selected_ids, [first["added_id"]])
        self.assertEqual(saved.assumptions["target_profit"], "432.00")
        self.assertEqual(len(saved.candidates), 1)

    @patch("secondstateapp.calendar_views._research_liveart_lot")
    def test_api_refresh_preserves_saved_manual_sale_and_selection(self, research_lookup):
        first = self.added()
        self.save(first)
        api_candidate = {"id": "501", "provider": "LiveArt", "category_id": 2, "status": "sold", "credible": True,
                         "artist": self.entry["artist"], "title": "Another print", "hammer_usd": "4000.00",
                         "sale_date": "2023-01-01", "auction_house": "Another house", "lot_number": "99", "match_type": "related_work"}
        research_lookup.return_value = {"candidates": [api_candidate], "selected_ids": [], "subject_matches": [],
                                       "retrieved_at": timezone.now().isoformat(), "data_units_spent": 3}
        response = self.client.post(self.research_url, "{}", content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        refreshed = response.json()
        self.assertEqual({row["id"] for row in refreshed["candidates"]}, {first["added_id"], "501"})
        self.assertIn(first["added_id"], refreshed["selected_ids"])
        self.assertEqual(self.post(action="save", research_id=refreshed["research_id"],
                                   selected_ids=[first["added_id"], "501"], assumptions={}).status_code, 200)
        saved = LiveArtResaleAnalysis.objects.get(lot=self.lot)
        self.assertEqual(saved.source_summary["combined_comp_count"], 2)
        self.assertTrue(any(row.get("entry_method") == "manual_web" for row in saved.candidates))

    def test_drawing_survives_the_existing_api_refresh_and_selection_flow(self):
        self.entry.update(category="works_on_paper", medium="Pencil on paper", edition="")
        self.test_api_refresh_preserves_saved_manual_sale_and_selection()
        saved = LiveArtResaleAnalysis.objects.get(lot=self.lot)
        drawing = next(row for row in saved.candidates if row.get("entry_method") == "manual_web")
        self.assertEqual(drawing["category"], "works_on_paper")
        self.assertIsNone(drawing["category_id"])
        self.assertIn(drawing["id"], saved.selected_ids)

    def test_saved_artprice_and_manual_evidence_share_the_existing_selection_flow(self):
        artprice = stored_analysis(self.lot, created_by=self.staff)
        artprice.comparables[0]["artist"] = self.lot.artist
        artprice.comparables[0]["title"] = self.lot.title
        artprice.save(update_fields=["comparables"])
        preview = self.client.get(self.url).json()["analysis"]
        prior_ids = preview["selected_ids"]
        self.assertEqual(len(prior_ids), 1)
        research = self.added(selected_ids=prior_ids)
        self.assertEqual(research["selected_ids"], prior_ids)
        selected = [*prior_ids, research["added_id"]]
        response = self.post(action="save", research_id=research["research_id"], selected_ids=selected, assumptions={})
        self.assertEqual(response.status_code, 200, response.content)
        summary = response.json()["analysis"]["source_summary"]
        self.assertEqual(summary["combined_comp_count"], 2)
        self.assertEqual(summary["artprice_selected_count"], 1)
        self.assertEqual(summary["liveart_selected_count"], 1)

    @patch("secondstateapp.calendar_views._research_liveart_lot")
    def test_api_refresh_preserves_unsaved_manual_evidence(self, research_lookup):
        first = self.added()
        research_lookup.return_value = {"candidates": [], "selected_ids": [], "subject_matches": [],
                                       "retrieved_at": timezone.now().isoformat(), "data_units_spent": 3}
        response = self.client.post(self.research_url, "{}", content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        refreshed = response.json()
        self.assertIn(first["added_id"], [row["id"] for row in refreshed["candidates"]])
        self.assertNotIn(first["added_id"], refreshed["selected_ids"])
        self.assertFalse(LiveArtResaleAnalysis.objects.exists())
        response = self.post(action="save", research_id=refreshed["research_id"],
                             selected_ids=[first["added_id"]], assumptions={})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["analysis"]["source_summary"]["combined_comp_count"], 1)

    @patch("secondstateapp.calendar_views._research_liveart_lot")
    def test_same_sale_from_api_and_manual_entry_counts_once(self, research_lookup):
        first = self.added()
        self.save(first)
        api_candidate = {
            **first["candidates"][0], "id": "501", "entry_method": "api",
            "credible": True, "match_type": "related_work",
            "provider_url": "https://api.liveart.ai/v1/lots?id=501&limit=1",
        }
        research_lookup.return_value = {"candidates": [api_candidate], "selected_ids": [], "subject_matches": [],
                                       "retrieved_at": timezone.now().isoformat(), "data_units_spent": 3}
        response = self.client.post(self.research_url, "{}", content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        refreshed = response.json()
        self.assertIn(first["added_id"], [row["id"] for row in refreshed["candidates"]])
        selected = [row["id"] for row in refreshed["candidates"] if row.get("credible") or row.get("manual_selectable")]
        response = self.post(action="save", research_id=refreshed["research_id"], selected_ids=selected, assumptions={})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["analysis"]["source_summary"]["combined_comp_count"], 1)

    def test_remove_manual_stages_only_and_preserves_other_sources_and_assumptions(self):
        first = self.added()
        self.save(first)
        saved = LiveArtResaleAnalysis.objects.get(lot=self.lot)
        api = {"id": "501", "provider": "LiveArt", "category_id": 2, "status": "sold", "credible": True,
               "artist": self.lot.artist, "title": "Another print", "hammer_usd": "4000.00",
               "sale_date": "2023-01-01", "auction_house": "Another house", "lot_number": "99", "match_type": "related_work"}
        saved.candidates.append(api)
        saved.selected_ids.append("501")
        saved.assumptions["target_profit"] = "432.00"
        saved.save(update_fields=["candidates", "selected_ids", "assumptions"])
        artprice = stored_analysis(self.lot, created_by=self.staff)
        artprice.comparables[0]["artist"] = self.lot.artist
        artprice.comparables[0]["title"] = self.lot.title
        artprice.save(update_fields=["comparables"])
        before = self.client.get(self.url).json()["analysis"]
        prior_ids = before["selected_ids"]
        self.assertEqual(len(prior_ids), 3)
        response = self.post(action="remove_manual", candidate_id=first["added_id"], selected_ids=prior_ids)
        self.assertEqual(response.status_code, 200, response.content)
        removed = response.json()
        self.assertEqual(removed["removed_id"], first["added_id"])
        expected_ids = set(prior_ids) - {first["added_id"]}
        self.assertEqual(set(removed["selected_ids"]), expected_ids)
        self.assertEqual({row["id"] for row in removed["candidates"]}, expected_ids)
        saved.refresh_from_db()
        self.assertEqual(set(saved.selected_ids), set(prior_ids))
        self.assertEqual(saved.assumptions["target_profit"], "432.00")
        self.assertIn(first["added_id"], [row["id"] for row in saved.candidates])
        response = self.post(action="save", research_id=removed["research_id"],
                             selected_ids=removed["selected_ids"], assumptions=saved.assumptions)
        self.assertEqual(response.status_code, 200, response.content)
        saved.refresh_from_db()
        self.assertEqual(set(saved.selected_ids), expected_ids)
        self.assertEqual(saved.assumptions["target_profit"], "432.00")
        self.assertNotIn(first["added_id"], [row["id"] for row in saved.candidates])
        self.assertEqual(saved.source_summary["combined_comp_count"], 2)

    @patch("secondstateapp.calendar_views._research_liveart_lot")
    def test_removed_sale_does_not_reappear_when_adding_or_refreshing_api(self, research_lookup):
        first = self.added()
        self.save(first)
        response = self.post(action="remove_manual", candidate_id=first["added_id"], selected_ids=[first["added_id"]])
        self.assertEqual(response.status_code, 200, response.content)
        removed = response.json()
        next_entry = {**self.entry, "lot_number": "73", "provider_url": "https://www.liveart.ai/price-database/artwork/another-sale"}
        second = self.added(entry=next_entry, research_id=removed["research_id"])
        self.assertNotIn(first["added_id"], [row["id"] for row in second["candidates"]])
        research_lookup.return_value = {"candidates": [], "selected_ids": [], "subject_matches": [],
                                       "retrieved_at": timezone.now().isoformat(), "data_units_spent": 3}
        response = self.client.post(self.research_url, "{}", content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        refreshed = response.json()
        self.assertEqual([row["id"] for row in refreshed["candidates"]], [second["added_id"]])
        saved = LiveArtResaleAnalysis.objects.get(lot=self.lot)
        self.assertIn(first["added_id"], [row["id"] for row in saved.candidates])
        response = self.post(action="save", research_id=refreshed["research_id"],
                             selected_ids=[second["added_id"]], assumptions={})
        self.assertEqual(response.status_code, 200, response.content)
        saved.refresh_from_db()
        self.assertEqual([row["id"] for row in saved.candidates], [second["added_id"]])

    @patch("secondstateapp.calendar_views._research_liveart_lot")
    def test_removed_sale_can_be_readded_with_corrected_hammer_before_saving(self, research_lookup):
        first = self.added()
        self.save(first)
        response = self.post(action="remove_manual", candidate_id=first["added_id"], selected_ids=[first["added_id"]])
        self.assertEqual(response.status_code, 200, response.content)
        corrected = self.added(entry={**self.entry, "hammer_usd": "3400.00"}, research_id=response.json()["research_id"])
        self.assertFalse(corrected["duplicate"])
        self.assertEqual(corrected["selected_ids"], [])
        self.assertEqual(corrected["candidates"][0]["hammer_usd"], "3400.00")
        research_lookup.return_value = {"candidates": [], "selected_ids": [], "subject_matches": [],
                                       "retrieved_at": timezone.now().isoformat(), "data_units_spent": 3}
        refreshed = self.client.post(self.research_url, "{}", content_type="application/json").json()
        self.assertEqual(len(refreshed["candidates"]), 1)
        self.assertEqual(refreshed["candidates"][0]["hammer_usd"], "3400.00")
        self.assertEqual(refreshed["selected_ids"], [])
        response = self.post(action="save", research_id=refreshed["research_id"],
                             selected_ids=[corrected["added_id"]], assumptions={})
        self.assertEqual(response.status_code, 200, response.content)
        saved = LiveArtResaleAnalysis.objects.get(lot=self.lot)
        self.assertEqual(saved.candidates[0]["hammer_usd"], "3400.00")
        self.assertEqual(saved.source_summary["combined_comp_count"], 1)

    @patch("secondstateapp.calendar_views._research_liveart_lot")
    def test_remove_manual_rejects_api_and_artprice_records(self, research_lookup):
        artprice = stored_analysis(self.lot, created_by=self.staff)
        artprice.comparables[0]["artist"] = self.lot.artist
        artprice.save(update_fields=["comparables"])
        research_lookup.return_value = {"candidates": [{"id": "501", "provider": "LiveArt", "category_id": 2,
            "status": "sold", "credible": True, "artist": self.lot.artist, "title": self.lot.title,
            "hammer_usd": "4000.00", "sale_date": "2023-01-01", "auction_house": "House", "lot_number": "9"}],
            "selected_ids": [], "subject_matches": [], "retrieved_at": timezone.now().isoformat(), "data_units_spent": 3}
        response = self.client.post(self.research_url, "{}", content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        research = response.json()
        prior = copy.deepcopy(self.client.session[f"liveart_research_{self.lot.pk}"])
        self.assertEqual(len(research["candidates"]), 2)
        for candidate in research["candidates"]:
            with self.subTest(provider=candidate["provider"]):
                response = self.post(action="remove_manual", candidate_id=candidate["id"],
                                     research_id=research["research_id"], selected_ids=research["selected_ids"])
                self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(self.client.session[f"liveart_research_{self.lot.pk}"], prior)

    def test_remove_manual_rejects_stale_token_and_unknown_record(self):
        research = self.added()
        prior = copy.deepcopy(self.client.session[f"liveart_research_{self.lot.pk}"])
        response = self.post(action="remove_manual", candidate_id=research["added_id"], research_id="stale-tab-token", selected_ids=[])
        self.assertEqual(response.status_code, 409, response.content)
        response = self.post(action="remove_manual", candidate_id="unknown", research_id=research["research_id"], selected_ids=[])
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(self.client.session[f"liveart_research_{self.lot.pk}"], prior)
