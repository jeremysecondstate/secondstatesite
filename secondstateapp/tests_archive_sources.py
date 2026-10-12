"""Archive source provenance and external links; no live service requests."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase, TestCase
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from .artprice_max_bid import analyze_artprice_comparables, analyze_artprice_html, merge_artprice_sources
from .calendar_views import _calendar_image_url, _lot_json
from .liveart_resale import normalize_candidate, subject_matches
from .models import AuctionMaxBidAnalysis, LiveArtResaleAnalysis
from .tests_artprice_react_store import react_store_html
from .tests_calendar import artprice_upload, watch_lot
from .tests_liveart_resale import artwork, lot


class ArchiveSourceNormalizationTests(SimpleTestCase):
    def source_lot(self, **extra):
        return {
            "id": 431, "title": "A print", "artistOrAssociation": "Artist Name",
            "price": "1500", "saleDtStart": "1 Jan 2025", "auctioneerName": "A House",
            "number": "23", "technique": "Lithograph", "dimension": "20 x 30 cm",
            "numberAndEdition": "10/50", "saleCity": "London", "saleCountry": "United Kingdom",
            "signature": "Signed in pencil", "condition": "A crease at lower edge",
            "url": "/artist/12/artist-name/print-multiple/431/a-print", **extra,
        }

    def test_all_available_fields_survive_roundtrip_without_running_scripts(self):
        source = react_store_html({"431": self.source_lot()}) + '<script>throw new Error("do not execute")</script>'
        result = analyze_artprice_html(source)
        comp = result["comparables"][0]
        self.assertEqual(comp["signature"], "Signed in pencil")
        self.assertEqual(comp["condition"], "A crease at lower edge")
        self.assertEqual(comp["location"], "London, United Kingdom")
        self.assertEqual(comp["currency"], "USD")
        self.assertEqual(analyze_artprice_comparables([comp])["comparables"], [comp])
        self.assertNotIn("do not execute", str(result))

    def test_missing_fields_stay_missing_and_dedup_retains_source_provenance(self):
        first = analyze_artprice_html(react_store_html({"431": self.source_lot(signature=None, condition=None)}))["comparables"]
        second = analyze_artprice_html(react_store_html({"431": self.source_lot()}))["comparables"]
        self.assertNotIn("signature", first[0])
        combined = merge_artprice_sources([
            {"id": "a", "filename": "first.html", "currency": "USD", "comparables": first},
            {"id": "b", "filename": "second.html", "currency": "USD", "comparables": second},
        ])
        self.assertEqual(len(combined), 1)
        self.assertEqual(combined[0]["source_ids"], ["a", "b"])
        self.assertEqual(combined[0]["source_filenames"], ["first.html", "second.html"])
        self.assertEqual(combined[0]["signature"], "Signed in pencil")

    def test_unsafe_artprice_links_do_not_survive_parsing(self):
        for url in ("javascript:alert(1)", "https://evil.example/artist/12/work", "https://www.artprice.com@evil.example/artist/12/work", "https://www.artprice.com/artist/12/a\\evil", "https://www.artprice.com:bad/artist/12/work"):
            with self.subTest(url=url):
                comp = analyze_artprice_html(react_store_html({"431": self.source_lot(url=url)}))["comparables"][0]
                self.assertNotIn("provider_url", comp)

    def test_image_url_rejects_malformed_hosts_and_browser_normalization(self):
        for value in ("https://[invalid/lot.jpg", "https://www.invaluable.com:bad/lot.jpg", "https://www.invaluable.com\\@evil.example/a.jpg", "https://www.invaluable.com/a\n.jpg"):
            self.assertEqual(_calendar_image_url(value), "")

    def test_liveart_links_use_real_lot_and_documented_artwork_uid_filter(self):
        target = SimpleNamespace(artist="Pablo Picasso", title="Test Print", medium="screenprint on paper")
        raw_artwork = artwork(100)
        self.assertIsNone(subject_matches(target, [raw_artwork])[0]["provider_url"])
        raw_artwork["uid"] = "artwork-uid"
        self.assertEqual(subject_matches(target, [raw_artwork])[0]["provider_url"], "https://api.liveart.ai/v1/artworks?uid=artwork-uid&limit=1")
        candidate = lot(501, sale_date="2025-01-01")
        candidate["sale"].update(location="New York", auction_url="https://house.example/sale/88")
        normalized = normalize_candidate(candidate, calendar_lot=target, subject=None)
        self.assertEqual(normalized["lot_url"], "https://auction.example/lots/501")
        self.assertEqual(normalized["sale_url"], "https://house.example/sale/88")
        self.assertEqual(normalized["location"], "New York")
        for url in ("https://house.example/", "javascript:alert(1)", "https://house.example:bad/lot/1", "https://user:password@house.example/lot/1"):
            candidate["lot_url"] = url
            self.assertIsNone(normalize_candidate(candidate, calendar_lot=target, subject=None)["lot_url"])


class ArchiveSourcePersistenceTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user("archive-source", is_staff=True))
        self.lot = watch_lot()

    def test_source_details_survive_upload_recalculation_and_resale_adapter(self):
        source = ArchiveSourceNormalizationTests().source_lot(artistOrAssociation=self.lot.artist)
        url = reverse("auction_lot_artprice_analysis", args=(self.lot.pk,))
        response = self.client.post(url, {"action": "add_sources", "artprice_html": artprice_upload("source.html", lots=[source])})
        self.assertEqual(response.status_code, 200)
        saved = AuctionMaxBidAnalysis.objects.get(lot=self.lot)
        self.assertEqual(saved.comparables[0]["location"], "London, United Kingdom")
        response = self.client.get(reverse("auction_lot_liveart_analysis", args=(self.lot.pk,)))
        candidate = response.json()["analysis"]["candidates"][0]
        self.assertEqual(candidate["signature"], "Signed in pencil")
        self.assertEqual(candidate["condition"], "A crease at lower edge")
        self.assertEqual(candidate["source_filenames"], ["source.html"])
        self.assertNotIn("signature", candidate["missing_data"])

    def test_lot_has_only_its_real_validated_image_and_raw_bid_metadata(self):
        self.lot.refresh_from_db()
        self.lot.image_url = "https://www.invaluable.com/images/lot.jpg"
        self.lot.current_bid = Decimal("1200.00")
        # URL name is supplied by the independent Bid Board implementation.
        with patch("secondstateapp.calendar_views.reverse", return_value="/calendar/lot/endpoint/"):
            serialized = _lot_json(self.lot, ZoneInfo("America/New_York"))
            self.assertEqual(serialized["image_urls"], [self.lot.image_url])
            self.assertEqual(serialized["images"], serialized["image_urls"])
            self.assertEqual(serialized["current_bid"], "1200.00")
            self.assertEqual(serialized["lot_url"], self.lot.lot_url)
            self.lot.image_url = ""
            self.assertEqual(_lot_json(self.lot, ZoneInfo("America/New_York"))["image_urls"], [])

    def test_ledger_keeps_each_files_original_details_after_deduplication(self):
        record = ArchiveSourceNormalizationTests().source_lot(artistOrAssociation=self.lot.artist)
        url = reverse("auction_lot_artprice_analysis", args=(self.lot.pk,))
        response = self.client.post(url, {"action": "add_sources", "artprice_html": [
            artprice_upload("first.html", lots=[{**record, "signature": None}]),
            artprice_upload("second.html", lots=[record]),
        ]})
        self.assertEqual(response.status_code, 200)
        analysis = response.json()["analysis"]
        self.assertEqual(analysis["sold_records_count"], 1)
        self.assertEqual(analysis["comparables"][0]["signature"], "Signed in pencil")
        self.assertEqual(analysis["comparables"][0]["source_filenames"], ["first.html", "second.html"])
        ledger = analysis["source_ledger"]
        self.assertNotIn("signature", ledger[0]["comparables"][0])
        self.assertEqual(ledger[1]["comparables"][0]["signature"], "Signed in pencil")
        self.assertTrue(all("comparables" not in source for source in analysis["sources"]))
        self.assertEqual(self.client.get(url).json()["analysis"]["source_ledger"], ledger)

    def test_saved_legacy_artwork_id_links_are_omitted_without_guessing_uid(self):
        legacy = {"id": "16050", "artwork_id": "16050", "title": "Print", "provider_url": "https://api.liveart.ai/v1/artworks?id=16050&limit=1"}
        valid = {"id": "16051", "artwork_id": "16051", "title": "Another print", "provider_url": "https://api.liveart.ai/v1/artworks?uid=real-provider-uid&limit=1"}
        saved = LiveArtResaleAnalysis.objects.create(
            lot=self.lot, subject_match=legacy, subject_matches=[legacy, valid],
            candidates=[], selected_ids=[], assumptions={}, scenarios=[],
            retrieved_at=timezone.now(),
        )
        with patch("secondstateapp.calendar_views._research_liveart_lot") as paid_search:
            response = self.client.get(reverse("auction_lot_liveart_analysis", args=(self.lot.pk,)))
        self.assertEqual(response.status_code, 200)
        analysis = response.json()["analysis"]
        self.assertIsNone(analysis["subject_match"]["provider_url"])
        self.assertEqual(analysis["subject_match"]["artwork_id"], "16050")
        self.assertIsNone(analysis["subject_matches"][0]["provider_url"])
        self.assertEqual(analysis["subject_matches"][1]["provider_url"], valid["provider_url"])
        self.assertNotIn("artworks?id=", response.content.decode())
        paid_search.assert_not_called()
        saved.refresh_from_db()
        self.assertEqual(saved.subject_match, legacy)
