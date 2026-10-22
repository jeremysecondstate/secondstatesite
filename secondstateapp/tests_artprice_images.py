"""Saved Artprice artwork thumbnails remain attached to their source sale records."""

import json
from unittest import TestCase

from .artprice_max_bid import (
    _artprice_image_url,
    analyze_artprice_comparables,
    analyze_artprice_html,
    merge_artprice_sources,
    parse_auction_results,
)
from .tests_artprice_react_store import react_store_html


class ArtpriceImageTests(TestCase):
    first_image = "https://imgprivate2.artprice.com/lots/opaque-sale/first-image/xl"
    second_image = "https://imgprivate2.artprice.com/lots/opaque-sale/second-image/xl"

    def lot(self, provider_id=101, **changes):
        return {
            "id": provider_id, "title": "Same artwork title", "price": "$1,000",
            "saleDtStart": "1 Oct 2026", "auctioneerName": "Test House",
            "number": str(provider_id), "lotstatus": 1, **changes,
        }

    def test_react_carousel_image_stays_with_correct_sale_even_with_matching_titles(self):
        lots = {
            "101": self.lot(imageUrls=[self.first_image, self.second_image], imageUrl=self.second_image),
            "102": self.lot(102, imageUrls=[self.second_image]),
            "103": self.lot(103),
        }
        html = react_store_html(lots, active_lot_ids=[101, 102, 103], nested=True)
        # Saved browser markup points to local files, but the original per-record URLs are in JSON.
        html += '<div id="lot-101"><img src="./saved_files/xl"></div><script>throw new Error("Do not execute");</script>'
        results = {result.provider_id: result for result in parse_auction_results(html)}
        self.assertEqual(results["101"].image_url, self.first_image)
        self.assertEqual(results["102"].image_url, self.second_image)
        self.assertIsNone(results["103"].image_url)
        comparables = {item["provider_id"]: item for item in analyze_artprice_html(html)["comparables"]}
        self.assertEqual(comparables["101"]["image_url"], self.first_image)
        self.assertEqual(comparables["102"]["image_url"], self.second_image)
        self.assertNotIn("image_url", comparables["103"])

    def test_legacy_state_and_recalculation_preserve_image_url(self):
        state = {"preferences": {"currency": "USD"}, "search": {"lots": {
            "101": self.lot(imageUrl=self.first_image),
        }}}
        html = f"<script>window.__PRELOADED_STATE__ = {json.dumps(state)};</script>"
        analysis = analyze_artprice_html(html)
        self.assertEqual(analysis["comparables"][0]["image_url"], self.first_image)
        recalculated = analyze_artprice_comparables(analysis["comparables"])
        self.assertEqual(recalculated["comparables"], analysis["comparables"])
        self.assertEqual(recalculated["expected_resale_hammer"], analysis["expected_resale_hammer"])

    def test_uses_first_valid_carousel_image_then_single_image_fallback(self):
        for changes in (
            {"imageUrls": ["javascript:alert(1)", self.first_image]},
            {"imageUrls": ["./saved_files/xl"], "imageUrl": self.first_image},
            {"imageUrls": "not-an-array", "imageUrl": self.first_image},
        ):
            with self.subTest(changes=changes):
                html = react_store_html({"101": self.lot(**changes)})
                self.assertEqual(analyze_artprice_html(html)["comparables"][0]["image_url"], self.first_image)

    def test_image_validation_rejects_local_unsafe_and_unrelated_urls(self):
        for image in (
            None, True, 123, {}, [], "", "./saved_files/xl", "/lots/first/xl",
            "//imgprivate2.artprice.com/lots/first/xl", "javascript:alert(1)", "data:image/png;base64,aaa",
            "file:///tmp/image.jpg", "http://imgprivate2.artprice.com/lots/first/xl",
            "https://imgprivate2.artprice.com.evil.example/lots/first/xl",
            "https://imgprivate2.artprice.com@evil.example/lots/first/xl",
            "https://user:secret@imgprivate2.artprice.com/lots/first/xl",
            "https://imgprivate2.artprice.com:444/lots/first/xl",
            "https://localhost/lots/first/xl", "https://www.artprice.com/lots/first/xl",
            "https://imgpublic.artprice.com/img/logo.svg", "https://imgprivate2.artprice.com/lots/",
            "https://imgprivate2.artprice.com/lots/../account", "https://imgprivate2.artprice.com/lots/%2e%2e/account",
            "https://imgprivate2.artprice.com/lots/first\\image/xl",
            "https://imgprivate2.artprice.com/lots/first%5Cimage/xl",
            "https://imgprivate2.artprice.com/lots/first\nimage/xl",
            "https://imgprivate2.artprice.com/lots/first image/xl",
            "https://imgprivate2.artprice.com/lots/first/xl#fragment",
        ):
            with self.subTest(image=image):
                self.assertIsNone(_artprice_image_url(image))
        self.assertEqual(_artprice_image_url(self.first_image), self.first_image)
        public_image = "https://imgpublic.artprice.com/lots/sale/artwork.jpg"
        self.assertEqual(_artprice_image_url(public_image), public_image)

    def test_cached_results_are_revalidated_before_recalculation(self):
        comp = analyze_artprice_html(react_store_html({"101": self.lot()}))["comparables"][0]
        for image in ("https://unrelated.example/work.jpg", "./saved_files/xl", "javascript:alert(1)"):
            with self.subTest(image=image):
                updated = analyze_artprice_comparables([{**comp, "image_url": image}])
                self.assertNotIn("image_url", updated["comparables"][0])

    def test_duplicate_sources_fill_missing_image_and_preserve_sale_price_and_provenance(self):
        original = analyze_artprice_html(react_store_html({"101": self.lot()}))["comparables"][0]
        photographed = {**original, "image_url": self.first_image, "hammer_price": "2000.00"}
        sources = [
            {"id": "first", "filename": "first.html", "currency": "USD", "comparables": [original]},
            {"id": "second", "filename": "second.html", "currency": "USD", "comparables": [photographed]},
        ]
        merged = merge_artprice_sources(sources)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["image_url"], self.first_image)
        self.assertEqual(merged[0]["hammer_price"], "1000.00")
        self.assertEqual(merged[0]["source_ids"], ["first", "second"])
        self.assertEqual(merged[0]["source_filenames"], ["first.html", "second.html"])
        self.assertEqual(analyze_artprice_comparables(merged)["comparables"], merged)
        self.assertNotIn("image_url", original)
        sources[1]["comparables"][0] = {**photographed, "image_url": "https://unrelated.example/work.jpg"}
        self.assertNotIn("image_url", merge_artprice_sources(sources)[0])
