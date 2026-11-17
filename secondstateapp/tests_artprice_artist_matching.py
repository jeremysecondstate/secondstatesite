"""Saved Artprice sales stay selectable regardless of their artist credit."""

import json
from copy import deepcopy
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from .liveart_resale import resale_candidate_selectable
from .models import AuctionBidBoardAnalysis, AuctionMaxBidAnalysis, LiveArtResaleAnalysis
from .tests_calendar import artprice_upload, watch_lot


# Normalized public sale metadata from neiman-frank.html, without page/session data.
NEIMAN_SALES = (
    ("37124799", "1500.00", "11 Mar 2025", "Clark's Fine Art & Auctioneers Inc.", "85", "Frank Sinatra, Duets"),
    ("35103078", "1700.00", "09 Sep 2024", "Bonhams Skinner Marlborough", "54", "Frank Sinatra, Duets"),
    ("26277501", "3000.00", "03 Mar 2022", "Mroczek Brothers Auctioneers & Associates", "12", '"Duets" (Frank Sinatra)'),
    ("6763189", "1500.00", "14 Jan 2012", "Brunk Auctions", "230", "Frank Sinatra Duets"),
)


# Normalized public sale metadata from nieto-chick.html, without page/session data.
NIETO_SALES = (
    ("41688921", "4800.00", "14 Apr 2026", "Bonhams", "133", '"Chicken"'),
    ("37506510", "1900.00", "26 Apr 2025", "Larsen Art Auction", "283", "Chicken"),
    ("33489348", "450.00", "10 Apr 2024", "Grant Zahajko Auctions, LLC", "15", "Gallo"),
    ("3796299", "275.00", "06 Aug 2005", "Susanin's", "5065", "Gallo"),
)


class NietoArtpriceArtistMatchingTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user("artprice-nieto", is_staff=True)
        self.client.force_login(self.staff)
        self.lot = watch_lot(
            artist="John W Nieto", artist_watchlist_name="John W Nieto",
            title="Chicken", medium="Serigraph", current_bid="100", bid_count=0,
        )
        self.analysis_url = reverse("auction_lot_liveart_analysis", args=(self.lot.pk,))
        self.board_url = reverse("auction_lot_bid_board", args=(self.lot.pk,))
        self.ids = [f"artprice:{sale[0]}" for sale in NIETO_SALES]
        liveart_patch = patch("secondstateapp.calendar_views.LiveArtClient")
        self.liveart_client = liveart_patch.start()
        self.addCleanup(liveart_patch.stop)
        self.addCleanup(self.liveart_client.assert_not_called)
        response = self.client.post(reverse("auction_lot_artprice_analysis", args=(self.lot.pk,)), {
            "action": "add_sources",
            "artprice_html": artprice_upload("nieto-chick.html", lots=[
                {
                    "id": identifier, "price": hammer, "saleDtStart": date,
                    "auctioneerName": house, "number": number, "title": title,
                    "artistOrAssociation": "John NIETO", "lotstatus": 1,
                }
                for identifier, hammer, date, house, number, title in NIETO_SALES
            ]),
        })
        self.assertEqual(response.status_code, 200, response.content)

    def preview(self):
        response = self.client.get(self.analysis_url)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["analysis"]

    def save_board(self, selected_ids):
        return self.client.post(self.board_url, json.dumps({
            "action": "save", "selected_ids": selected_ids,
        }), content_type="application/json")

    def assert_nieto_hammers(self, candidates):
        self.assertEqual(len(candidates), 4)
        self.assertEqual(
            {item["provider_id"]: item["hammer_usd"] for item in candidates},
            {identifier: hammer for identifier, hammer, *_ in NIETO_SALES},
        )
        self.assertTrue(all(item["credible"] for item in candidates))
        self.assertTrue(all(not item["exclusion_reasons"] for item in candidates))

    def test_nieto_middle_initial_accepts_all_four_sales_for_bid_board(self):
        preview = self.preview()
        self.assert_nieto_hammers(preview["candidates"])
        self.assertCountEqual(preview["selected_ids"], self.ids)

        response = self.save_board(self.ids)

        self.assertEqual(response.status_code, 200, response.content)
        board = response.json()["analysis"]
        self.assertEqual(board["source_summary"]["artprice_included_count"], 4)
        self.assertTrue(board["rows"])
        self.assertTrue(all(case["resale_hammer"] is not None for case in board["cases"]))
        saved = AuctionBidBoardAnalysis.objects.get(lot=self.lot)
        self.assertCountEqual(saved.selected_ids, self.ids)
        self.assert_nieto_hammers(saved.evidence_snapshot["selected_records"])
        self.assertCountEqual(self.client.get(self.board_url).json()["analysis"]["selected_ids"], self.ids)

    def test_saved_nieto_exclusions_refresh_and_retain_new_selections(self):
        old_candidates = [
            {
                **candidate, "credible": False, "selected": False,
                "exclusion_reasons": ["Artprice artist differs from this Calendar artist"],
                "match_notes": ["Artprice artist differs from this Calendar artist"],
            }
            for candidate in self.preview()["candidates"]
        ]
        saved = LiveArtResaleAnalysis.objects.create(
            lot=self.lot, candidates=old_candidates, selected_ids=[],
            source_summary={"artprice_included_count": 0}, retrieved_at=timezone.now(),
        )

        refreshed = self.preview()

        self.assert_nieto_hammers(refreshed["candidates"])
        saved.refresh_from_db()
        self.assert_nieto_hammers(saved.candidates)
        chosen = self.ids[:2]
        response = self.save_board(chosen)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["analysis"]["source_summary"]["artprice_included_count"], 2)
        refreshed = self.preview()
        self.assert_nieto_hammers(refreshed["candidates"])
        self.assertEqual(refreshed["selected_ids"], chosen)
        self.assertEqual(
            [item["id"] for item in refreshed["candidates"] if item["selected"]], chosen,
        )
        source = AuctionMaxBidAnalysis.objects.get(lot=self.lot)
        self.assertEqual(source.source_filename, "nieto-chick.html")
        self.assertEqual(source.sold_records_count, 4)

    def test_other_nieto_credits_can_be_selected_for_bid_board(self):
        source = AuctionMaxBidAnalysis.objects.get(lot=self.lot)
        for artist in ("John A Nieto", "John Nieto Jr", "After John Nieto"):
            with self.subTest(artist=artist):
                for comparable in source.comparables:
                    comparable["artist"] = artist
                source.save(update_fields=("comparables",))
                preview = self.preview()
                self.assert_nieto_hammers(preview["candidates"])
                response = self.save_board(self.ids)
                self.assertEqual(response.status_code, 200, response.content)
                self.assertEqual(response.json()["analysis"]["source_summary"]["artprice_included_count"], 4)
        self.assertCountEqual(AuctionBidBoardAnalysis.objects.get(lot=self.lot).selected_ids, self.ids)


class ArtpriceArtistMatchingTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user("artprice-neiman", is_staff=True)
        self.client.force_login(self.staff)
        self.lot = watch_lot(
            artist="Leroy Neimann",
            artist_watchlist_name="Leroy Neimann",
            title='1994, \'Frank Sinatra, Duets\', H 28.75" W 28.75"',
            medium="Serigraph in colors",
        )
        self.artprice_url = reverse("auction_lot_artprice_analysis", args=(self.lot.pk,))
        self.analysis_url = reverse("auction_lot_liveart_analysis", args=(self.lot.pk,))
        liveart_patch = patch("secondstateapp.calendar_views.LiveArtClient")
        self.liveart_client = liveart_patch.start()
        self.addCleanup(liveart_patch.stop)
        self.addCleanup(self.liveart_client.assert_not_called)

    def upload(self, *, artist="LeRoy NEIMAN"):
        lots = [
            {
                "id": identifier,
                "price": hammer,
                "saleDtStart": date,
                "auctioneerName": house,
                "number": number,
                "title": title,
                "artistOrAssociation": artist,
                "lotstatus": 1,
            }
            for identifier, hammer, date, house, number, title in NEIMAN_SALES
        ]
        response = self.client.post(self.artprice_url, {
            "action": "add_sources",
            "artprice_html": artprice_upload("neiman-frank.html", lots=lots),
        })
        self.assertEqual(response.status_code, 200, response.content)
        return AuctionMaxBidAnalysis.objects.get(lot=self.lot)

    def preview(self):
        response = self.client.get(self.analysis_url)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["analysis"]

    def save(self, selected_ids):
        return self.client.post(self.analysis_url, json.dumps({
            "action": "save", "selected_ids": selected_ids, "assumptions": {},
        }), content_type="application/json")

    def assert_neiman_hammers(self, candidates):
        self.assertEqual(len(candidates), 4)
        self.assertEqual(
            {item["provider_id"]: item["hammer_usd"] for item in candidates},
            {identifier: hammer for identifier, hammer, *_ in NEIMAN_SALES},
        )
        self.assertTrue(all(item["credible"] for item in candidates))
        self.assertTrue(all(not item["exclusion_reasons"] for item in candidates))

    def test_neimann_calendar_artist_accepts_all_four_saved_neiman_sales(self):
        self.upload()
        preview = self.preview()
        self.assert_neiman_hammers(preview["candidates"])
        ids = [f"artprice:{sale[0]}" for sale in NEIMAN_SALES]
        self.assertCountEqual(preview["selected_ids"], ids)

        response = self.save(ids)

        self.assertEqual(response.status_code, 200, response.content)
        saved = response.json()["analysis"]
        self.assert_neiman_hammers(saved["candidates"])
        self.assertEqual(saved["source_summary"]["artprice_included_count"], 4)
        self.assertTrue(saved["scenarios"])
        self.assertTrue(all(item["selected_comp_count"] == 4 for item in saved["scenarios"]))

    def test_bearden_full_and_short_names_share_saved_sale_validation(self):
        self.lot.artist = "Romare Howard Bearden"
        self.lot.artist_watchlist_name = "Romare Howard Bearden"
        self.lot.title = "Early Carolina Morning"
        self.lot.save(update_fields=("artist", "artist_watchlist_name", "title"))
        response = self.client.post(self.artprice_url, {
            "action": "add_sources",
            "artprice_html": artprice_upload("bearden-test.html", lots=[{
                "id": "bearden-print", "title": self.lot.title,
                "artistOrAssociation": "Romare Bearden", "price": "1600.00",
                "saleDtStart": "19 Nov 2022", "auctioneerName": "Test auction house",
                "number": "1", "lotstatus": 1,
            }]),
        })
        self.assertEqual(response.status_code, 200, response.content)
        source = AuctionMaxBidAnalysis.objects.get(lot=self.lot)
        for artist in ("Romare Bearden", "Romare Howard BEARDEN"):
            with self.subTest(artist=artist):
                source.comparables[0]["artist"] = artist
                source.save(update_fields=("comparables",))
                preview = self.preview()
                candidate = preview["candidates"][0]
                self.assertTrue(candidate["credible"])
                self.assertEqual(candidate["hammer_usd"], "1600.00")
                response = self.save([candidate["id"]])
                self.assertEqual(response.status_code, 200, response.content)
                self.assertEqual(response.json()["analysis"]["source_summary"]["artprice_included_count"], 1)

    def test_legacy_excluded_candidates_refresh_without_reupload_or_liveart(self):
        source = self.upload()
        preview = self.preview()
        old_candidates = [
            {
                **candidate,
                "credible": False,
                "selected": False,
                "hammer_usd": None,
                "exclusion_reasons": ["Artprice artist differs from this Calendar artist"],
                "match_notes": ["Artprice artist differs from this Calendar artist"],
            }
            for candidate in preview["candidates"]
        ]
        saved = LiveArtResaleAnalysis.objects.create(
            lot=self.lot, candidates=old_candidates, selected_ids=[],
            source_summary={"artprice_included_count": 0},
            assumptions=preview["assumptions"], retrieved_at=timezone.now(),
        )

        refreshed = self.preview()

        self.assert_neiman_hammers(refreshed["candidates"])
        saved.refresh_from_db()
        self.assert_neiman_hammers(saved.candidates)
        source.refresh_from_db()
        self.assertEqual(source.source_filename, "neiman-frank.html")
        self.assertEqual(source.sold_records_count, 4)
        response = self.save([candidate["id"] for candidate in refreshed["candidates"]])
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["analysis"]["source_summary"]["artprice_included_count"], 4)

    def test_refresh_keeps_explicitly_unchecked_artprice_sales_unselected(self):
        self.upload()
        ids = [f"artprice:{sale[0]}" for sale in NEIMAN_SALES]
        chosen = ids[:2]
        response = self.save(chosen)
        self.assertEqual(response.status_code, 200, response.content)

        refreshed = self.preview()

        self.assert_neiman_hammers(refreshed["candidates"])
        self.assertEqual(refreshed["selected_ids"], chosen)
        self.assertEqual(
            [candidate["id"] for candidate in refreshed["candidates"] if candidate["selected"]],
            chosen,
        )
        self.assertEqual(refreshed["source_summary"]["artprice_included_count"], 2)

    def test_different_artist_credits_remain_selectable_for_valuation(self):
        source = self.upload()
        for artist in ("Paul Neiman", "Leroy Neiman Jr", "Leroy Neimann Jr", "Leroy Nieman"):
            with self.subTest(artist=artist):
                for comparable in source.comparables:
                    comparable["artist"] = artist
                source.save(update_fields=("comparables",))
                preview = self.preview()
                self.assert_neiman_hammers(preview["candidates"])
                chosen = [candidate["id"] for candidate in preview["candidates"]]
                response = self.save(chosen)
                self.assertEqual(response.status_code, 200, response.content)
                analysis = response.json()["analysis"]
                self.assertEqual(analysis["source_summary"]["artprice_included_count"], 4)
                self.assertTrue(all(scenario["selected_comp_count"] == 4 for scenario in analysis["scenarios"]))

    def test_invalid_hammers_or_non_usd_stay_ineligible_despite_artist_alias(self):
        source = self.upload()
        for currency, hammer in (
            ("EUR", "1500.00"), ("USD", None), ("USD", "0"),
            ("USD", "-1500"), ("USD", "NaN"), ("USD", "Infinity"),
        ):
            with self.subTest(currency=currency, hammer=hammer):
                source.currency = currency
                for comparable in source.comparables:
                    comparable["hammer_price"] = hammer
                source.save(update_fields=("currency", "comparables"))
                preview = self.preview()
                self.assertEqual(preview["selected_ids"], [])
                self.assertEqual(preview["scenarios"], [])
                for candidate in preview["candidates"]:
                    self.assertIsNone(candidate["hammer_usd"])
                    self.assertFalse(candidate["credible"])
                    self.assertFalse(candidate["selectable"])
                    self.assertEqual(self.save([candidate["id"]]).status_code, 400)


class UploadedArtpriceSelectionTests(TestCase):
    """An upload belongs to a dossier; the user chooses its valuation evidence."""

    def setUp(self):
        self.staff = get_user_model().objects.create_user("mixed-artprice", is_staff=True)
        self.client.force_login(self.staff)
        self.lot = watch_lot(
            artist="Pablo Picasso", artist_watchlist_name="Pablo Picasso",
            title="A print being researched", medium="Lithograph",
            current_bid="100", bid_count=0,
        )
        self.analysis_url = reverse("auction_lot_liveart_analysis", args=(self.lot.pk,))
        self.board_url = reverse("auction_lot_bid_board", args=(self.lot.pk,))
        self.ids = [f"artprice:88000{index}" for index in range(1, 5)]
        api_patch = patch("secondstateapp.calendar_views.LiveArtClient")
        self.liveart_client = api_patch.start()
        self.addCleanup(api_patch.stop)
        self.addCleanup(self.liveart_client.assert_not_called)
        response = self.client.post(reverse("auction_lot_artprice_analysis", args=(self.lot.pk,)), {
            "action": "add_sources",
            "artprice_html": artprice_upload("user-chosen-sales.html", lots=[
                {
                    "id": f"88000{index}", "title": title,
                    "artistOrAssociation": artist, "price": hammer,
                    "saleDtStart": f"{index:02} May 2025",
                    "auctioneerName": "Synthetic auction house", "number": str(index),
                    "lotstatus": 1,
                }
                for index, (artist, title, hammer) in enumerate((
                    ("Pablo Picasso", "Picasso sale", "600.00"),
                    ("Joan Miró", "Miró first sale", "1200.00"),
                    ("Joan Miró", "Miró second sale", "2400.00"),
                    ("Paul Hambleton Landacre", "Landacre sale", "1800.00"),
                ), start=1)
            ]),
        })
        self.assertEqual(response.status_code, 200, response.content)
        self.source_before = AuctionMaxBidAnalysis.objects.filter(lot=self.lot).values().get()

    def preview(self):
        response = self.client.get(self.analysis_url)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["analysis"]

    def save_board(self, selected_ids):
        return self.client.post(self.board_url, json.dumps({
            "action": "save", "selected_ids": selected_ids,
        }), content_type="application/json")

    def assert_all_uploaded_sales_eligible(self, candidates):
        self.assertCountEqual([candidate["id"] for candidate in candidates], self.ids)
        self.assertTrue(all(candidate["credible"] for candidate in candidates))
        self.assertTrue(all(candidate["selectable"] for candidate in candidates))
        self.assertTrue(all(not candidate["exclusion_reasons"] for candidate in candidates))
        self.assertEqual(
            {candidate["id"]: candidate["hammer_usd"] for candidate in candidates},
            dict(zip(self.ids, ("600.00", "1200.00", "2400.00", "1800.00"))),
        )

    def assert_source_unchanged(self):
        self.assertEqual(
            AuctionMaxBidAnalysis.objects.filter(lot=self.lot).values().get(),
            self.source_before,
        )

    def test_miro_sales_selected_in_picasso_dossier_drive_valuation_and_board(self):
        self.assert_all_uploaded_sales_eligible(self.preview()["candidates"])
        chosen = self.ids[1:3]

        response = self.client.post(self.analysis_url, json.dumps({
            "action": "save", "selected_ids": chosen, "assumptions": {},
        }), content_type="application/json")

        self.assertEqual(response.status_code, 200, response.content)
        analysis = response.json()["analysis"]
        self.assertEqual(analysis["selected_ids"], chosen)
        self.assertEqual(analysis["source_summary"]["artprice_included_count"], 2)
        typical = next(item for item in analysis["scenarios"] if item["name"] == "typical")
        self.assertEqual(typical["resale_hammer"], "1800.00")
        self.assertEqual(typical["selected_comp_count"], 2)

        board_response = self.save_board(chosen)

        self.assertEqual(board_response.status_code, 200, board_response.content)
        board = AuctionBidBoardAnalysis.objects.get(lot=self.lot)
        self.assertEqual(board.selected_ids, chosen)
        selected = board.evidence_snapshot["selected_records"]
        self.assertCountEqual([item["id"] for item in selected], chosen)
        self.assertTrue(all(item["artist"] == "Joan Miró" for item in selected))
        self.assertCountEqual([item["hammer_usd"] for item in selected], ["1200.00", "2400.00"])
        self.assertEqual(self.preview()["selected_ids"], chosen)
        self.assertEqual(self.client.get(self.board_url).json()["analysis"]["selected_ids"], chosen)
        self.assert_source_unchanged()

    def test_old_artist_exclusions_rehydrate_without_reupload_or_changing_choices(self):
        preview = self.preview()
        stale = deepcopy(preview["candidates"])
        for candidate in stale:
            candidate["selected"] = candidate["id"] == self.ids[0]
            if candidate["id"] in self.ids[2:]:
                candidate.update(
                    credible=False, hammer_usd=None,
                    exclusion_reasons=["Artprice artist differs from this Calendar artist"],
                    match_notes=["Artprice artist differs from this Calendar artist"],
                )
        assumptions = {**preview["assumptions"], "inbound_shipping": "321.00"}
        saved = LiveArtResaleAnalysis.objects.create(
            lot=self.lot, candidates=stale, selected_ids=self.ids[:1],
            assumptions=assumptions, source_summary={"artprice_included_count": 1},
            retrieved_at=timezone.now(),
        )

        refreshed = self.preview()

        self.assert_all_uploaded_sales_eligible(refreshed["candidates"])
        self.assertEqual(refreshed["selected_ids"], self.ids[:1])
        self.assertEqual(refreshed["assumptions"], assumptions)
        saved.refresh_from_db()
        self.assert_all_uploaded_sales_eligible(saved.candidates)
        self.assertEqual(saved.selected_ids, self.ids[:1])
        self.assertEqual(saved.assumptions, assumptions)
        chosen = self.ids[1:3]
        response = self.save_board(chosen)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["analysis"]["source_summary"]["artprice_included_count"], 2)
        self.assertEqual(self.preview()["selected_ids"], chosen)
        self.assert_source_unchanged()

    def test_landacre_full_name_is_selectable_in_short_name_dossier(self):
        self.lot.artist = "Paul Landacre"
        self.lot.artist_watchlist_name = "Paul Landacre"
        self.lot.save(update_fields=("artist", "artist_watchlist_name"))
        candidate = next(item for item in self.preview()["candidates"] if item["id"] == self.ids[3])
        self.assertEqual(candidate["artist"], "Paul Hambleton Landacre")
        self.assertTrue(candidate["credible"])
        self.assertEqual(candidate["exclusion_reasons"], [])

        response = self.save_board([candidate["id"]])

        self.assertEqual(response.status_code, 200, response.content)
        selected = AuctionBidBoardAnalysis.objects.get(lot=self.lot).evidence_snapshot["selected_records"]
        self.assertEqual([item["id"] for item in selected], [candidate["id"]])
        self.assertEqual(selected[0]["hammer_usd"], "1800.00")
        self.assertEqual(self.preview()["selected_ids"], [candidate["id"]])
        self.assert_source_unchanged()

    def test_legacy_empty_summary_does_not_reselect_explicitly_unchecked_sales(self):
        preview = self.preview()
        saved = LiveArtResaleAnalysis.objects.create(
            lot=self.lot,
            candidates=[{**candidate, "selected": False} for candidate in preview["candidates"]],
            selected_ids=[], source_summary={}, assumptions=preview["assumptions"],
            retrieved_at=timezone.now(),
        )

        refreshed = self.preview()

        self.assert_all_uploaded_sales_eligible(refreshed["candidates"])
        self.assertEqual(refreshed["selected_ids"], [])
        self.assertFalse(any(candidate["selected"] for candidate in refreshed["candidates"]))
        self.assertEqual(refreshed["source_summary"]["artprice_included_count"], 0)
        saved.refresh_from_db()
        self.assertEqual(saved.selected_ids, [])
        self.assert_source_unchanged()


class UploadedArtpriceEligibilityTests(SimpleTestCase):
    def test_saved_relevance_flags_do_not_veto_valid_uploaded_hammer(self):
        candidate = {
            "provider": "Artprice", "status": "sold", "artist": "Joan Miró",
            "original_currency": "USD", "hammer_usd": "1200.00",
            "credible": False, "manual_selectable": False,
            "exclusion_reasons": ["Artprice artist differs from this Calendar artist"],
        }
        self.assertTrue(resale_candidate_selectable(candidate))
        self.assertFalse(resale_candidate_selectable({**candidate, "provider": "LiveArt"}))
        for override in (
            {"status": "upcoming"}, {"original_currency": "EUR"},
            {"hammer_usd": None}, {"hammer_usd": "0"}, {"hammer_usd": "-1"},
            {"hammer_usd": "NaN"}, {"hammer_usd": "Infinity"},
        ):
            with self.subTest(override=override):
                self.assertFalse(resale_candidate_selectable({**candidate, **override}))
