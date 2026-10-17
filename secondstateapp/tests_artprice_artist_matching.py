"""Regression coverage for verified artist aliases in saved Artprice results."""

import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

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

    def test_other_nieto_artists_cannot_enter_bid_board(self):
        source = AuctionMaxBidAnalysis.objects.get(lot=self.lot)
        for artist in ("John A Nieto", "John Nieto Jr", "After John Nieto"):
            with self.subTest(artist=artist):
                for comparable in source.comparables:
                    comparable["artist"] = artist
                source.save(update_fields=("comparables",))
                preview = self.preview()
                self.assertEqual(preview["selected_ids"], [])
                self.assertTrue(all(not item["credible"] for item in preview["candidates"]))
                self.assertEqual(self.save_board(self.ids).status_code, 400)
        self.assertFalse(AuctionBidBoardAnalysis.objects.filter(lot=self.lot).exists())


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

    def test_different_artist_retains_usd_hammer_but_cannot_enter_valuation(self):
        source = self.upload()
        for artist in ("Paul Neiman", "Leroy Neiman Jr", "Leroy Neimann Jr", "Leroy Nieman"):
            with self.subTest(artist=artist):
                for comparable in source.comparables:
                    comparable["artist"] = artist
                source.save(update_fields=("comparables",))
                preview = self.preview()
                self.assertEqual(preview["selected_ids"], [])
                self.assertEqual(preview["scenarios"], [])
                self.assertEqual(
                    {item["provider_id"]: item["hammer_usd"] for item in preview["candidates"]},
                    {identifier: hammer for identifier, hammer, *_ in NEIMAN_SALES},
                )
                for candidate in preview["candidates"]:
                    self.assertFalse(candidate["credible"])
                    self.assertIn("Artprice artist differs", " ".join(candidate["exclusion_reasons"]))
                    self.assertEqual(self.save([candidate["id"]]).status_code, 400)
        self.assertFalse(LiveArtResaleAnalysis.objects.filter(lot=self.lot).exists())

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
                    self.assertEqual(self.save([candidate["id"]]).status_code, 400)
