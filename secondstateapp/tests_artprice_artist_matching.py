"""Regression coverage for the saved Neiman Artprice results in Calendar."""

import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import AuctionMaxBidAnalysis, LiveArtResaleAnalysis
from .tests_calendar import artprice_upload, watch_lot


# Normalized public sale metadata from neiman-frank.html, without page/session data.
NEIMAN_SALES = (
    ("37124799", "1500.00", "11 Mar 2025", "Clark's Fine Art & Auctioneers Inc.", "85", "Frank Sinatra, Duets"),
    ("35103078", "1700.00", "09 Sep 2024", "Bonhams Skinner Marlborough", "54", "Frank Sinatra, Duets"),
    ("26277501", "3000.00", "03 Mar 2022", "Mroczek Brothers Auctioneers & Associates", "12", '"Duets" (Frank Sinatra)'),
    ("6763189", "1500.00", "14 Jan 2012", "Brunk Auctions", "230", "Frank Sinatra Duets"),
)


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
