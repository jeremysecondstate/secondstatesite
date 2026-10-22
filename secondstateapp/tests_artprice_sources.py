import json
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase
from django.urls import reverse

from secondstateapp.artprice_max_bid import analyze_artprice_html
from secondstateapp.models import AuctionMaxBidAnalysis, LiveArtResaleAnalysis
from secondstateapp.tests_calendar import artprice_html, artprice_upload, stored_analysis, watch_lot


class MultipleArtpriceSourceTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user("multiple-artprice", is_staff=True)
        self.client.force_login(self.staff)
        self.lot = watch_lot()
        self.url = reverse("auction_lot_artprice_analysis", args=(self.lot.pk,))
        self.resale_url = reverse("auction_lot_liveart_analysis", args=(self.lot.pk,))

    def sale(self, identifier, price, **overrides):
        sale = {
            "id": identifier, "title": "Related print", "price": str(price),
            "artistOrAssociation": self.lot.artist, "saleDtStart": "1 Apr 2026",
            "auctioneerName": "Print House", "number": str(identifier), "lotstatus": 1,
        }
        sale.update(overrides)
        return sale

    def add(self, *files, **options):
        return self.client.post(self.url, {"action": "add_sources", "artprice_html": list(files), **options})

    def preview(self):
        return self.client.get(self.resale_url).json()["analysis"]

    def save_selection(self, selected_ids):
        return self.client.post(self.resale_url, json.dumps({
            "action": "save", "selected_ids": selected_ids, "assumptions": {},
        }), content_type="application/json")

    def test_two_searches_share_unique_sales_and_keep_each_file_provenance(self):
        shared = self.sale(102, 6000)
        response = self.add(
            artprice_upload("stabiles.html", lots=[self.sale(101, 1000), shared]),
            artprice_upload("boomer.html", lots=[shared, self.sale(103, 3000)]),
        )
        self.assertEqual(response.status_code, 200)
        analysis = response.json()["analysis"]
        self.assertEqual(analysis["source_count"], 2)
        self.assertEqual(analysis["raw_sold_records_count"], 4)
        self.assertEqual(analysis["sold_records_count"], 3)
        self.assertEqual(analysis["duplicate_records_count"], 1)
        self.assertEqual(analysis["expected_resale_hammer"], "3000.00")
        shared_comp = next(comp for comp in analysis["comparables"] if comp["provider_id"] == "102")
        self.assertEqual(shared_comp["source_filenames"], ["stabiles.html", "boomer.html"])
        preview = self.preview()
        self.assertEqual(len(preview["selected_ids"]), 3)
        self.assertEqual(preview["scenarios"][1]["resale_hammer"], "3000.00")
        summary = preview["source_summary"]
        self.assertEqual(summary["artprice_source_filenames"], ["stabiles.html", "boomer.html"])
        self.assertEqual(summary["artprice_file_duplicate_count"], 1)
        self.assertEqual(summary["artprice_included_count"], 3)
        self.assertEqual([source["included_count"] for source in summary["artprice_sources"]], [2, 2])
        self.assertTrue(all("comparables" not in source for source in analysis["sources"]))
        recalculated = self.client.post(self.url, {"action": "recalculate", "method": "mean"})
        self.assertEqual(recalculated.status_code, 200)
        self.assertEqual(recalculated.json()["analysis"]["sources"], analysis["sources"])
        self.assertEqual(recalculated.json()["analysis"]["comparables"], analysis["comparables"])

    def test_same_upload_is_idempotent_and_new_search_appends_with_saved_selection(self):
        self.add(artprice_upload("first.html", lots=[self.sale(101, 1000), self.sale(102, 2000)]))
        preview = self.preview()
        self.assertEqual(self.save_selection(["artprice:101"]).status_code, 200)
        duplicate = self.add(artprice_upload("first.html", lots=[self.sale(101, 1000), self.sale(102, 2000)]))
        self.assertEqual(duplicate.json()["analysis"]["source_count"], 1)
        self.assertEqual(self.preview()["selected_ids"], ["artprice:101"])
        added = self.add(artprice_upload("second.html", lots=[self.sale(102, 2000), self.sale(103, 4000)]))
        self.assertEqual(added.status_code, 200)
        self.assertEqual(set(self.preview()["selected_ids"]), {"artprice:101", "artprice:103"})
        self.assertEqual(added.json()["analysis"]["source_count"], 2)

    def test_same_html_recovers_old_thumbnails_without_changing_saved_analysis(self):
        images = {
            "101": "https://imgprivate2.artprice.com/lots/first/image/xl",
            "102": "https://imgprivate2.artprice.com/lots/second/image/xl",
            "103": "https://imgprivate2.artprice.com/lots/third/image/xl",
        }
        lots = [
            self.sale(101, 1200, imageUrls=[images["101"]], estimation={"low": "900", "high": "1500"}),
            self.sale(102, 2400, imageUrl=images["102"], estimation={"low": "2000", "high": "3000"}),
            # Older results without a provider ID must retain their sale identity, too.
            self.sale("no-provider", 3600, number="103", imageUrl=images["103"]),
        ]
        response = self.add(
            artprice_upload("saved.html", lots=lots), method="manual", manual_resale_value="2750",
            recent_count="2", inbound_shipping="321", target_profit="234",
            seller_commission_pct="12", outbound_shipping="87", other_resale_costs="65",
            premium_min="24", premium_max="28",
        )
        self.assertEqual(response.status_code, 200)
        saved = self.client.post(self.resale_url, json.dumps({
            "action": "save", "selected_ids": ["artprice:102"],
            "assumptions": {
                "inbound_shipping": "123", "other_buying_costs": "45", "target_profit": "456",
                "seller_commission_pct": "9", "outbound_shipping": "67", "other_resale_costs": "89",
                "premium_min": 25, "premium_max": 27, "downside_factor": "0.75", "upside_factor": "1.25",
            },
        }), content_type="application/json")
        self.assertEqual(saved.status_code, 200)

        def without_images(value):
            if isinstance(value, dict):
                return {key: without_images(item) for key, item in value.items() if key != "image_url"}
            if isinstance(value, list):
                return [without_images(item) for item in value]
            return value

        # Simulate a source saved before thumbnails were extracted from HTML.
        artprice = AuctionMaxBidAnalysis.objects.get(lot=self.lot)
        artprice.sources = without_images(artprice.sources)
        artprice.comparables = without_images(artprice.comparables)
        artprice.save(update_fields=("sources", "comparables"))
        resale = LiveArtResaleAnalysis.objects.get(lot=self.lot)
        resale.candidates = without_images(resale.candidates)
        resale.save(update_fields=("candidates",))
        artprice_before = AuctionMaxBidAnalysis.objects.filter(lot=self.lot).values().get()
        resale_before = LiveArtResaleAnalysis.objects.filter(lot=self.lot).values().get()
        response_before = self.client.get(self.url).json()["analysis"]

        # Re-upload exactly the same HTML. Submitted defaults must not reset saved custom bids.
        refreshed = self.add(artprice_upload("saved.html", lots=lots), method="mean", target_profit="1")
        self.assertEqual(refreshed.status_code, 200)
        analysis = refreshed.json()["analysis"]
        self.assertEqual(without_images(analysis), response_before)
        self.assertEqual(analysis["source_count"], 1)
        self.assertEqual({item["lot_number"]: item["image_url"] for item in analysis["comparables"]}, images)
        self.assertEqual({
            item["lot_number"]: item["image_url"] for item in analysis["source_ledger"][0]["comparables"]
        }, images)
        workbench = self.preview()
        self.assertEqual({item["lot_number"]: item["image_url"] for item in workbench["candidates"]}, images)
        self.assertEqual(workbench["selected_ids"], ["artprice:102"])
        self.assertEqual(workbench["scenarios"], resale_before["scenarios"])
        self.assertEqual(workbench["assumptions"], resale_before["assumptions"])
        # Compare every persisted field, including source IDs, original prices, and timestamps.
        self.assertEqual(without_images(AuctionMaxBidAnalysis.objects.filter(lot=self.lot).values().get()), artprice_before)
        self.assertEqual(without_images(LiveArtResaleAnalysis.objects.filter(lot=self.lot).values().get()), resale_before)

    def test_thumbnails_survive_new_sources_recalculation_and_source_removal(self):
        images = {
            "101": "https://imgprivate2.artprice.com/lots/first/image/xl",
            "102": "https://imgprivate2.artprice.com/lots/shared/image/xl",
            "103": "https://imgprivate2.artprice.com/lots/third/image/xl",
        }
        shared = self.sale(102, 2000, imageUrls=[images["102"]])

        def assert_images(response, expected):
            self.assertEqual(response.status_code, 200)
            analysis = response.json()["analysis"]
            self.assertEqual({item["provider_id"]: item["image_url"] for item in analysis["comparables"]}, expected)
            for source in analysis["source_ledger"]:
                for item in source["comparables"]:
                    self.assertEqual(item["image_url"], expected[item["provider_id"]])
            candidates = self.preview()["candidates"]
            self.assertEqual({item["provider_id"]: item["image_url"] for item in candidates}, expected)
            return analysis

        first = assert_images(self.add(artprice_upload("first.html", lots=[
            self.sale(101, 1000, imageUrl=images["101"]), shared,
        ])), {key: images[key] for key in ("101", "102")})
        self.assertEqual(self.save_selection(["artprice:102"]).status_code, 200)
        added = assert_images(self.add(artprice_upload("second.html", lots=[
            shared, self.sale(103, 6000, imageUrl=images["103"]),
        ])), images)
        self.assertEqual(added["source_count"], 2)
        assert_images(self.client.post(self.url, {"action": "recalculate", "method": "mean"}), images)
        removed = assert_images(self.client.post(self.url, {
            "action": "remove_source", "source_id": first["sources"][0]["id"],
        }), {key: images[key] for key in ("102", "103")})
        self.assertEqual(removed["source_count"], 1)
        self.assertEqual(removed["source_ledger"][0]["filename"], "second.html")
        self.assertEqual(set(self.preview()["selected_ids"]), {"artprice:102", "artprice:103"})
        persisted = LiveArtResaleAnalysis.objects.get(lot=self.lot)
        self.assertEqual({item["provider_id"]: item["image_url"] for item in persisted.candidates}, {
            key: images[key] for key in ("102", "103")
        })

    def test_removing_one_file_preserves_shared_sales_and_refreshes_saved_bids(self):
        response = self.add(
            artprice_upload("first.html", lots=[self.sale(101, 1000), self.sale(102, 2000)]),
            artprice_upload("second.html", lots=[self.sale(102, 2000), self.sale(103, 6000)]),
        )
        sources = response.json()["analysis"]["sources"]
        self.assertEqual(self.save_selection(self.preview()["selected_ids"]).status_code, 200)
        removed = self.client.post(self.url, {"action": "remove_source", "source_id": sources[0]["id"]})
        self.assertEqual(removed.status_code, 200)
        analysis = removed.json()["analysis"]
        self.assertEqual(analysis["source_count"], 1)
        self.assertEqual(analysis["sold_records_count"], 2)
        self.assertEqual(analysis["expected_resale_hammer"], "4000.00")
        self.assertEqual(set(self.preview()["selected_ids"]), {"artprice:102", "artprice:103"})
        shared = next(comp for comp in analysis["comparables"] if comp["provider_id"] == "102")
        self.assertEqual(shared["source_filenames"], ["second.html"])
        last = self.client.post(self.url, {"action": "remove_source", "source_id": sources[1]["id"]})
        self.assertIsNone(last.json()["analysis"])
        self.assertFalse(AuctionMaxBidAnalysis.objects.filter(lot=self.lot).exists())
        saved = LiveArtResaleAnalysis.objects.get(lot=self.lot)
        self.assertEqual(saved.scenarios, [])
        self.assertEqual(saved.source_summary["artprice_included_count"], 0)

    def test_invalid_file_or_failed_combined_refresh_rolls_back_the_whole_batch(self):
        self.add(artprice_upload("first.html", lots=[self.sale(101, 1000)]))
        before = self.client.get(self.url).json()
        response = self.add(
            artprice_upload("valid.html", lots=[self.sale(102, 2000)]),
            SimpleUploadedFile("invalid.html", b"<html>invalid</html>"),
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get(self.url).json(), before)
        from secondstateapp.artprice_max_bid import ArtpriceAnalysisError
        with patch("secondstateapp.calendar_views._refresh_saved_resale_from_artprice", side_effect=ArtpriceAnalysisError("Failed")):
            failed = self.add(artprice_upload("second.html", lots=[self.sale(102, 2000)]))
        self.assertEqual(failed.status_code, 400)
        self.assertEqual(self.client.get(self.url).json(), before)

    def test_file_and_total_byte_limits_preserve_existing_data(self):
        self.add(artprice_upload("first.html", lots=[self.sale(101, 1000)]))
        before = self.client.get(self.url).json()
        too_many = self.add(*[artprice_upload(f"file-{index}.html") for index in range(11)])
        self.assertEqual(too_many.status_code, 400)
        with patch("secondstateapp.calendar_views.MAX_ARTPRICE_UPLOAD_BYTES", 1):
            too_large = self.add(artprice_upload("second.html"))
        self.assertEqual(too_large.status_code, 413)
        self.assertEqual(self.client.get(self.url).json(), before)

    def test_unknown_source_removal_and_foreign_source_do_not_change_data(self):
        self.add(artprice_upload())
        before = self.client.get(self.url).json()
        for source_id in ("", "another-lot-source"):
            response = self.client.post(self.url, {"action": "remove_source", "source_id": source_id})
            self.assertEqual(response.status_code, 404)
        self.assertEqual(self.client.get(self.url).json(), before)

    def test_legacy_source_backfill_preserves_saved_data_and_supports_append(self):
        legacy = stored_analysis(self.lot, created_by=self.staff)
        original_comparables = legacy.comparables
        original_updated_at = legacy.updated_at
        migration = import_module("secondstateapp.migrations.0026_auctionmaxbidanalysis_sources")
        historical_apps = SimpleNamespace(get_model=lambda *_: AuctionMaxBidAnalysis)
        migration.preserve_saved_sources(historical_apps, SimpleNamespace(connection=connection))
        legacy.refresh_from_db()
        self.assertEqual(legacy.comparables, original_comparables)
        self.assertEqual(legacy.updated_at, original_updated_at)
        self.assertEqual(legacy.sources[0]["comparables"], original_comparables)
        self.assertEqual(legacy.sources[0]["filename"], "saved-results.html")
        appended = self.add(artprice_upload("new.html", lots=[self.sale(103, 3000)]))
        self.assertEqual(appended.status_code, 200)
        self.assertEqual(appended.json()["analysis"]["source_count"], 2)
        self.assertEqual(appended.json()["analysis"]["sold_records_count"], 2)
        self.assertEqual(appended.json()["analysis"]["sources"][0]["id"], f"legacy-{legacy.pk}")

    def test_distinct_lots_with_equal_title_date_and_price_remain_distinct(self):
        result = analyze_artprice_html(artprice_html([self.sale(101, 1000), self.sale(102, 1000)]))
        self.assertEqual(result["sold_records_count"], 2)
        response = self.add(
            artprice_upload("first.html", lots=[self.sale(101, 1000)]),
            artprice_upload("second.html", lots=[self.sale(102, 1000)]),
        )
        self.assertEqual(response.json()["analysis"]["sold_records_count"], 2)

    def test_overlap_without_provider_id_uses_sale_details(self):
        first = self.sale("no-provider", 2000, number="42")
        second = {**first, "title": "Alternate spelling from another search"}
        response = self.add(
            artprice_upload("first.html", lots=[first]),
            artprice_upload("second.html", lots=[second]),
        )
        self.assertEqual(response.json()["analysis"]["sold_records_count"], 1)
        self.assertEqual(response.json()["analysis"]["comparables"][0]["source_filenames"], ["first.html", "second.html"])

    def test_removing_primary_file_preserves_selection_when_overlap_provider_id_changes(self):
        for selected in (False, True):
            with self.subTest(selected=selected):
                AuctionMaxBidAnalysis.objects.filter(lot=self.lot).delete()
                LiveArtResaleAnalysis.objects.filter(lot=self.lot).delete()
                response = self.add(
                    artprice_upload("first.html", lots=[self.sale(101, 2000, number="42")]),
                    artprice_upload("second.html", lots=[self.sale(202, 2000, number="42")]),
                )
                sources = response.json()["analysis"]["sources"]
                original_sale_identity = self.preview()["candidates"][0]["sale_identity"]
                self.assertEqual(self.save_selection(["artprice:101"] if selected else []).status_code, 200)
                removed = self.client.post(self.url, {"action": "remove_source", "source_id": sources[0]["id"]})
                self.assertEqual(removed.status_code, 200)
                preview = self.preview()
                self.assertEqual(preview["selected_ids"], ["artprice:202"] if selected else [])
                self.assertEqual(preview["candidates"][0]["sale_identity"], original_sale_identity)

    def test_file_can_be_removed_when_remaining_sales_do_not_support_positive_bid(self):
        response = self.add(
            artprice_upload("higher.html", lots=[self.sale(101, 5000)]),
            artprice_upload("lower.html", lots=[self.sale(102, 100)]),
            inbound_shipping="500", target_profit="100",
        )
        self.assertEqual(response.status_code, 200)
        sources = response.json()["analysis"]["sources"]
        removed = self.client.post(self.url, {"action": "remove_source", "source_id": sources[0]["id"]})
        self.assertEqual(removed.status_code, 200)
        analysis = removed.json()["analysis"]
        self.assertEqual(analysis["expected_resale_hammer"], "100.00")
        self.assertEqual(analysis["net_resale_proceeds"], "100.00")
        self.assertEqual(analysis["assumptions"]["inbound_shipping"], "500.00")
        self.assertTrue(analysis["no_positive_bid"])
        self.assertEqual(analysis["bid_rows"], [])
