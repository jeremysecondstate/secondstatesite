import copy
import json
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .calendar_views import _artprice_candidates
from .liveart_resale import normalize_candidate
from .models import LiveArtResaleAnalysis
from .tests_calendar import liveart_lot, stored_analysis, watch_lot


class LiveArtPendingRecoveryTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user("recovery-staff", is_staff=True)
        self.client.force_login(self.staff)
        self.lot = watch_lot()
        self.url = reverse("auction_lot_liveart_research", args=(self.lot.pk,))
        self.key = f"liveart_research_{self.lot.pk}"
        candidate = normalize_candidate(liveart_lot("pending-sale"), None, self.lot)
        self.pending = {
            "research_id": "completed-response-reference", "retrieved_at": "2026-10-12T12:00:00+00:00",
            "candidates": [candidate], "selected_ids": ["pending-sale"],
            "subject_match": None, "subject_matches": [], "requires_subject_choice": False,
            "data_units_spent": 8.5, "search_terms_used": ["papillons"],
            "search_summary": [{"term": "papillons", "returned_count": 1, "has_more": False}],
            "search_category": {"id": "2", "label": "Prints & Multiples"},
        }
        self.api_patch = patch("secondstateapp.calendar_views.LiveArtClient")
        self.api = self.api_patch.start()
        self.addCleanup(self.api_patch.stop)

    def store_pending(self, value=None):
        session = self.client.session
        session[self.key] = copy.deepcopy(self.pending if value is None else value)
        session.save()

    def test_repeated_get_recovers_receipt_without_api_session_or_saved_analysis_writes(self):
        saved = LiveArtResaleAnalysis.objects.create(
            lot=self.lot, candidates=[{"id": "saved-sale"}], selected_ids=["saved-sale"],
            assumptions={"inbound_shipping": "300.00"}, search_context={"search_terms_used": ["older"]},
            retrieved_at=timezone.now(), data_units_spent=Decimal("7.0"),
        )
        before_saved = LiveArtResaleAnalysis.objects.filter(pk=saved.pk).values().get()
        self.store_pending()
        before_session = dict(self.client.session)
        first = self.client.get(self.url)
        second = self.client.get(self.url)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json(), second.json())
        payload = first.json()
        self.assertTrue(payload["pending_found"])
        for key in ("research_id", "retrieved_at", "data_units_spent", "search_terms_used", "search_summary", "search_category"):
            self.assertEqual(payload[key], self.pending[key])
        self.assertEqual(payload["selected_ids"], ["pending-sale"])
        self.assertEqual(payload["candidates"][0]["id"], "pending-sale")
        self.assertTrue(payload["candidates"][0]["selected"])
        self.assertIn("no-store", first.headers["Cache-Control"])
        self.assertEqual(dict(self.client.session), before_session)
        self.assertEqual(LiveArtResaleAnalysis.objects.filter(pk=saved.pk).values().get(), before_saved)
        self.api.assert_not_called()

    def test_empty_success_and_unknown_usage_are_recoverable(self):
        pending = {**self.pending, "candidates": [], "selected_ids": [], "data_units_spent": None}
        self.store_pending(pending)
        payload = self.client.get(self.url).json()
        self.assertTrue(payload["pending_found"])
        self.assertEqual(payload["candidates"], [])
        self.assertIsNone(payload["data_units_spent"])
        self.api.assert_not_called()

    def test_recovery_retains_saved_artprice_selections_and_rejections(self):
        source = stored_analysis(self.lot, created_by=self.staff)
        source.comparables = [
            {**source.comparables[0], "artist": self.lot.artist, "provider_id": "chosen"},
            {**source.comparables[0], "artist": self.lot.artist, "provider_id": "rejected", "lot_number": "43"},
        ]
        source.save(update_fields=("comparables",))
        source_candidates = _artprice_candidates(self.lot)
        saved = LiveArtResaleAnalysis.objects.create(
            lot=self.lot, candidates=source_candidates, selected_ids=["artprice:chosen"],
            source_summary={"Artprice": {"count": 1}}, retrieved_at=timezone.now(),
        )
        self.store_pending()
        before = LiveArtResaleAnalysis.objects.filter(pk=saved.pk).values().get()
        payload = self.client.get(self.url).json()
        self.assertEqual(set(payload["selected_ids"]), {"pending-sale", "artprice:chosen"})
        self.assertFalse(next(row for row in payload["candidates"] if row["id"] == "artprice:rejected")["selected"])
        self.assertEqual(LiveArtResaleAnalysis.objects.filter(pk=saved.pk).values().get(), before)
        self.api.assert_not_called()

    def test_absent_or_invalid_pending_does_not_invent_zero_charges_or_create_state(self):
        for pending in (None, "not a receipt", {}, {"research_id": "x", "candidates": None}):
            with self.subTest(pending=pending):
                session = self.client.session
                session.pop(self.key, None)
                if pending is not None:
                    session[self.key] = pending
                session.save()
                before = dict(self.client.session)
                payload = self.client.get(self.url).json()
                self.assertFalse(payload["pending_found"])
                self.assertIn("does not establish whether an earlier request consumed Data Units", payload["message"])
                self.assertNotIn("data_units_spent", payload)
                self.assertEqual(dict(self.client.session), before)
                self.assertFalse(LiveArtResaleAnalysis.objects.filter(lot=self.lot).exists())
        self.api.assert_not_called()

    def test_recovery_is_staff_only_and_isolated_to_lot_and_browser_session(self):
        self.store_pending()
        other_lot = watch_lot(source_lot_id="other-lot", lot_number="26")
        other_url = reverse("auction_lot_liveart_research", args=(other_lot.pk,))
        self.assertFalse(self.client.get(other_url).json()["pending_found"])
        separate_session = Client()
        separate_session.force_login(self.staff)
        self.assertFalse(separate_session.get(self.url).json()["pending_found"])
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)
        ordinary = get_user_model().objects.create_user("recovery-reader")
        self.client.force_login(ordinary)
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.api.assert_not_called()

    def test_missing_lot_returns_404_and_other_methods_remain_disallowed(self):
        missing = reverse("auction_lot_liveart_research", args=(self.lot.pk + 10000,))
        self.assertEqual(self.client.get(missing).status_code, 404)
        self.assertEqual(self.client.put(self.url, json.dumps({}), content_type="application/json").status_code, 405)
        self.api.assert_not_called()
