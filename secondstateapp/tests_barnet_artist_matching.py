"""Verified Barnet aliases keep saved sales usable without broad fuzzy matching."""

import json
from copy import deepcopy
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from .liveart_artist import liveart_artist_names_match, liveart_artist_search_name
from .models import AuctionBidBoardAnalysis, AuctionMaxBidAnalysis, LiveArtResaleAnalysis
from .tests_calendar import artprice_upload, watch_lot


class BarnetArtistNameTests(SimpleTestCase):
    def test_verified_middle_initial_and_normalized_variants_match_both_ways(self):
        for source_name in (
            "Will R Barnet", "Will R. BARNET", "Barnet, Will R.",
            "BARNET, WILL R. (1911–2012)", "Will R (1911) Barnet",
        ):
            with self.subTest(source_name=source_name):
                self.assertEqual(liveart_artist_search_name(source_name), "Will Barnet")
                self.assertTrue(liveart_artist_names_match(source_name, "Will Barnet"))
                self.assertTrue(liveart_artist_names_match("Barnet, Will", source_name))

    def test_alias_does_not_remove_other_initials_or_identity_qualifiers(self):
        for other_name in (
            "Will A Barnet", "Will Robert Barnet", "William Barnet", "Will Barnett",
            "Will Barnet Jr", "Will R Barnet Jr", "After Will Barnet",
            "Attributed to Will R Barnet", "School of Will Barnet",
        ):
            with self.subTest(other_name=other_name):
                self.assertEqual(liveart_artist_search_name(other_name), other_name)
                self.assertFalse(liveart_artist_names_match(other_name, "Will Barnet"))
                self.assertFalse(liveart_artist_names_match("Will R. Barnet", other_name))
        self.assertFalse(liveart_artist_names_match("John R Smith", "John Smith"))
        self.assertFalse(liveart_artist_names_match("John Robert Smith", "John Smith"))


class BarnetSavedArtpriceTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user("barnet-research", is_staff=True)
        self.client.force_login(self.staff)
        self.lot = watch_lot(
            artist="Will Barnet", artist_watchlist_name="Will Barnet",
            title="Silent Seasons: Summer", medium="Screenprint",
            current_bid="100", bid_count=0,
        )
        self.preview_url = reverse("auction_lot_liveart_analysis", args=(self.lot.pk,))
        self.board_url = reverse("auction_lot_bid_board", args=(self.lot.pk,))
        self.ids = ["artprice:990001", "artprice:990002", "artprice:990003"]
        self.other_id = "artprice:990004"
        api_patch = patch("secondstateapp.calendar_views.LiveArtClient")
        self.liveart_client = api_patch.start()
        self.addCleanup(api_patch.stop)
        self.addCleanup(self.liveart_client.assert_not_called)
        # Synthetic sale metadata, not saved page or session contents.
        response = self.client.post(
            reverse("auction_lot_artprice_analysis", args=(self.lot.pk,)),
            {
                "action": "add_sources",
                "artprice_html": artprice_upload("barnet-seasons-test.html", lots=[
                    {
                        "id": identifier, "title": "Silent Seasons: Summer",
                        "artistOrAssociation": artist, "price": price,
                        "saleDtStart": f"{index + 1:02} Feb 2025",
                        "auctioneerName": "Synthetic auction house",
                        "number": str(index + 1), "lotstatus": 1,
                    }
                    for index, (identifier, artist, price) in enumerate((
                        ("990001", "Will Barnet", "800.00"),
                        ("990002", "Will R. BARNET", "1200.00"),
                        ("990003", "BARNET, WILL R.", "1600.00"),
                        ("990004", "Will A Barnet", "900.00"),
                    ))
                ]),
            },
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.source_before = AuctionMaxBidAnalysis.objects.filter(lot=self.lot).values().get()

    def preview(self):
        response = self.client.get(self.preview_url)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["analysis"]

    def save_board(self, selected_ids):
        return self.client.post(self.board_url, json.dumps({
            "action": "save", "selected_ids": selected_ids,
        }), content_type="application/json")

    def assert_source_unchanged(self):
        self.assertEqual(
            AuctionMaxBidAnalysis.objects.filter(lot=self.lot).values().get(),
            self.source_before,
        )

    def assert_barnet_candidates_eligible(self, candidates):
        candidates_by_id = {candidate["id"]: candidate for candidate in candidates}
        for identifier, hammer in zip(self.ids, ("800.00", "1200.00", "1600.00")):
            candidate = candidates_by_id[identifier]
            self.assertTrue(candidate["credible"])
            self.assertEqual(candidate["exclusion_reasons"], [])
            self.assertEqual(candidate["hammer_usd"], hammer)
        other = candidates_by_id[self.other_id]
        self.assertFalse(other["credible"])
        self.assertEqual(other["hammer_usd"], "900.00")
        self.assertIn("Artprice artist differs", " ".join(other["exclusion_reasons"]))

    def test_saved_exclusions_rehydrate_without_changing_choices_or_source(self):
        preview = self.preview()
        stale_candidates = deepcopy(preview["candidates"])
        for candidate in stale_candidates:
            candidate["selected"] = candidate["id"] == self.ids[0]
            if candidate["id"] == self.ids[2]:
                candidate.update(
                    credible=False,
                    exclusion_reasons=["Artprice artist differs from this Calendar artist"],
                    match_notes=["Artprice artist differs from this Calendar artist"],
                )
        # One chosen sale, one explicitly unchecked sale, and one old exclusion.
        assumptions = {**preview["assumptions"], "inbound_shipping": "321.00"}
        saved = LiveArtResaleAnalysis.objects.create(
            lot=self.lot, candidates=stale_candidates, selected_ids=self.ids[:1],
            assumptions=assumptions, source_summary={"artprice_included_count": 1},
            retrieved_at=timezone.now(),
        )

        refreshed = self.preview()

        self.assert_barnet_candidates_eligible(refreshed["candidates"])
        self.assertEqual(refreshed["selected_ids"], self.ids[:1])
        self.assertEqual(refreshed["assumptions"], assumptions)
        self.assertEqual(
            [item["id"] for item in refreshed["candidates"] if item["selected"]],
            self.ids[:1],
        )
        saved.refresh_from_db()
        self.assert_barnet_candidates_eligible(saved.candidates)
        self.assertEqual(saved.selected_ids, self.ids[:1])
        self.assertEqual(saved.assumptions, assumptions)
        self.assert_source_unchanged()
        self.assertFalse(AuctionBidBoardAnalysis.objects.filter(lot=self.lot).exists())

    def test_explicitly_selected_barnet_sales_feed_board_and_retain_choices(self):
        self.assert_barnet_candidates_eligible(self.preview()["candidates"])
        chosen = self.ids[1:]

        response = self.save_board(chosen)

        self.assertEqual(response.status_code, 200, response.content)
        board = response.json()["analysis"]
        self.assertEqual(board["source_summary"]["artprice_included_count"], 2)
        self.assertTrue(board["rows"])
        self.assertTrue(all(case["resale_hammer"] is not None for case in board["cases"]))
        saved = AuctionBidBoardAnalysis.objects.get(lot=self.lot)
        self.assertEqual(saved.selected_ids, chosen)
        self.assertCountEqual(
            [item["id"] for item in saved.evidence_snapshot["selected_records"]], chosen,
        )
        saved_before = AuctionBidBoardAnalysis.objects.filter(pk=saved.pk).values().get()
        refreshed = self.preview()
        self.assertEqual(refreshed["selected_ids"], chosen)
        self.assertEqual(self.client.get(self.board_url).json()["analysis"]["selected_ids"], chosen)
        self.assertEqual(AuctionBidBoardAnalysis.objects.filter(pk=saved.pk).values().get(), saved_before)
        self.assert_source_unchanged()

    def test_other_artist_cannot_be_selected_for_the_board(self):
        self.assert_barnet_candidates_eligible(self.preview()["candidates"])

        response = self.save_board([self.other_id])

        self.assertEqual(response.status_code, 400, response.content)
        self.assertFalse(AuctionBidBoardAnalysis.objects.filter(lot=self.lot).exists())
        self.assert_source_unchanged()
