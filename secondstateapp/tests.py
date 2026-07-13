import json
import os
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from . import catalog_api_views
from .models import Artwork


@patch.dict(os.environ, {"CATALOG_API_KEY": "test-key"}, clear=False)
class ArtworkOrderingTests(TestCase):
    def create_artwork(self, title, display_order, is_available=True):
        return Artwork.objects.create(
            title=title,
            artist="Test Artist",
            medium="Screenprint",
            price=Decimal("100.00"),
            display_order=display_order,
            is_available=is_available,
        )

    def test_default_queryset_orders_by_display_order_then_id(self):
        third = self.create_artwork("Third", 2)
        first = self.create_artwork("First", 0)
        second = self.create_artwork("Second", 1)

        self.assertEqual(list(Artwork.objects.values_list("id", flat=True)), [first.id, second.id, third.id])

    def test_manage_json_includes_display_order_and_reorder_updates_order(self):
        first = self.create_artwork("First", 0)
        second = self.create_artwork("Second", 1)
        third = self.create_artwork("Third", 2)

        response = self.client.get(reverse("artwork_manage_list"), HTTP_X_API_KEY="test-key")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.json()["artworks"]], [first.id, second.id, third.id])
        self.assertEqual([item["display_order"] for item in response.json()["artworks"]], [0, 1, 2])

        response = self.client.get(reverse("artwork_list"), {"format": "json"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.json()["artworks"]], [first.id, second.id, third.id])
        self.assertEqual([item["display_order"] for item in response.json()["artworks"]], [0, 1, 2])

        response = self.client.post(
            reverse("reorder_artworks"),
            data=json.dumps({"order": [third.id, first.id, second.id]}),
            content_type="application/json",
            HTTP_X_API_KEY="test-key",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual([item["id"] for item in payload["artworks"]], [third.id, first.id, second.id])
        self.assertEqual([item["display_order"] for item in payload["artworks"]], [0, 1, 2])
        self.assertEqual(list(Artwork.objects.values_list("id", flat=True)), [third.id, first.id, second.id])

    def test_reorder_rejects_missing_and_unknown_ids(self):
        first = self.create_artwork("First", 0)
        self.create_artwork("Second", 1)

        response = self.client.post(
            reverse("reorder_artworks"),
            data=json.dumps({"order": [first.id, 999999]}),
            content_type="application/json",
            HTTP_X_API_KEY="test-key",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("unknown ids", response.json()["error"])
        self.assertIn("missing ids", response.json()["error"])

    def test_upload_appends_artwork_to_end(self):
        first = self.create_artwork("First", 0)
        second = self.create_artwork("Second", 1)

        response = self.client.post(
            reverse("upload_artwork"),
            data={
                "title": "Uploaded",
                "artist": "Upload Artist",
                "price": "250",
            },
            HTTP_X_API_KEY="test-key",
        )

        self.assertEqual(response.status_code, 201)
        uploaded = Artwork.objects.get(id=response.json()["id"])
        self.assertEqual(uploaded.display_order, 2)
        self.assertEqual(list(Artwork.objects.values_list("id", flat=True)), [first.id, second.id, uploaded.id])

    def test_gallery_template_keeps_saved_order_with_mosaic_classes(self):
        third = self.create_artwork("Third", 2)
        first = self.create_artwork("First", 0)
        second = self.create_artwork("Second", 1)
        fifth = self.create_artwork("Fifth", 4, is_available=False)
        fourth = self.create_artwork("Fourth", 3)

        response = self.client.get(reverse("gallery"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "auction-mosaic-grid")
        self.assertContains(response, "auction-card--feature")
        self.assertContains(response, "auction-card--wide")
        self.assertContains(response, "4 available works")
        html = response.content.decode()
        rendered_positions = [
            html.index(f'data-artwork-id="{artwork.id}"')
            for artwork in [first, second, third, fourth, fifth]
        ]
        self.assertEqual(rendered_positions, sorted(rendered_positions))

    def test_gallery_uses_default_artwork_image_when_image_is_missing(self):
        self.create_artwork("Missing Image", 0)

        response = self.client.get(reverse("gallery"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "/static/secondstateapp/etching_press.jpg")

    def test_gallery_edit_link_remains_staff_only(self):
        artwork = self.create_artwork("Staff Editable", 0)
        edit_url = reverse("artwork_edit", args=[artwork.id])

        response = self.client.get(reverse("gallery"))
        self.assertNotContains(response, edit_url)

        staff_user = User.objects.create_user(username="staff", password="password", is_staff=True)
        self.client.force_login(staff_user)
        response = self.client.get(reverse("gallery"))

        self.assertContains(response, edit_url)


@patch.dict(os.environ, {"CATALOG_API_KEY": "test-key", "OPENAI_API_KEY": "not-used-in-tests"}, clear=False)
class UpcomingPrintAuctionSearchTests(TestCase):
    endpoint_name = "search_upcoming_print_auctions"

    def payload(self, **overrides):
        data = {
            "horizon_days": 7,
            "minimum_print_lots": 10,
            "region": "North America",
            "additional_instructions": "Prioritize West Coast sales.",
            "client_now": "2026-07-12T18:00:00-07:00",
        }
        data.update(overrides)
        return data

    def sale(self, **overrides):
        data = {
            "auction_house": "Example Auctions",
            "sale_title": "Prints & Multiples",
            "start_at": "2026-07-15T10:00:00-04:00",
            "timezone": "America/New_York",
            "location": "New York",
            "online_format": "Live and online",
            "sale_type": "dedicated",
            "print_lot_count": 24,
            "count_kind": "verified",
            "count_evidence": "The official catalog lists lots 1 through 24.",
            "print_types": ["etchings", "screenprints"],
            "official_sale_url": "https://example-auctions.test/sales/prints",
            "supporting_sources": ["https://example-auctions.test/sales/prints"],
        }
        data.update(overrides)
        return data

    def openai_payload(self, sales, citation_url="https://research-source.test/calendar"):
        return {
            "output_text": json.dumps({"sales": sales}),
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "annotations": [
                                {"type": "url_citation", "url": citation_url, "title": "Calendar"}
                            ],
                        }
                    ],
                }
            ],
        }

    def post(self, payload=None, authenticated=True):
        headers = {"HTTP_X_API_KEY": "test-key"} if authenticated else {}
        return self.client.post(
            reverse(self.endpoint_name),
            data=json.dumps(payload if payload is not None else self.payload()),
            content_type="application/json",
            **headers,
        )

    def test_endpoint_requires_catalog_authentication(self):
        response = self.post(authenticated=False)

        self.assertEqual(response.status_code, 401)

    @patch("secondstateapp.catalog_api_views._call_auction_search_api")
    def test_search_computes_exact_window_filters_deduplicates_and_sorts(self, mock_openai):
        later_dedicated = self.sale()
        earlier_mixed = self.sale(
            auction_house="Pacific Auctions",
            sale_title="Modern Art including Prints",
            start_at="2026-07-13T09:00:00-07:00",
            timezone="America/Los_Angeles",
            location="Los Angeles",
            sale_type="mixed",
            print_lot_count=10,
            count_kind="estimated",
            count_evidence="Ten catalog lots are identified as lithographs or screenprints.",
            official_sale_url="https://pacific-auctions.test/sale/modern",
            supporting_sources=["https://pacific-auctions.test/sale/modern"],
        )
        below_threshold = self.sale(
            sale_title="Mixed Art",
            sale_type="mixed",
            print_lot_count=9,
            official_sale_url="https://example-auctions.test/sales/mixed",
            supporting_sources=["https://example-auctions.test/sales/mixed"],
        )
        ended = self.sale(
            sale_title="Already Ended",
            start_at="2026-07-12T17:59:59-07:00",
            official_sale_url="https://example-auctions.test/sales/ended",
            supporting_sources=["https://example-auctions.test/sales/ended"],
        )
        duplicate = self.sale(official_sale_url="https://example-auctions.test/sales/prints/?tracking=1")
        mock_openai.return_value = self.openai_payload(
            [later_dedicated, earlier_mixed, below_threshold, ended, duplicate]
        )

        response = self.post()

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(
            result["window"],
            {
                "start": "2026-07-12T18:00:00-07:00",
                "end": "2026-07-19T18:00:00-07:00",
                "horizon_days": 7,
                "timezone": "UTC-07:00",
            },
        )
        self.assertEqual(result["auction_count"], 2)
        self.assertIn("10 (estimated)", result["markdown"])
        self.assertIn("24 (verified)", result["markdown"])
        self.assertNotIn("Already Ended", result["markdown"])
        self.assertNotIn("Mixed Art", result["markdown"])
        self.assertLess(result["markdown"].index("Pacific Auctions"), result["markdown"].index("Example Auctions"))
        self.assertIn("https://research-source.test/calendar", result["source_urls"])
        called_config = mock_openai.call_args.args[0]
        self.assertEqual(called_config["minimum_print_lots"], 10)
        self.assertEqual(called_config["region"], "North America")

    @patch("secondstateapp.catalog_api_views._call_auction_search_api")
    def test_dedicated_sale_qualifies_below_mixed_sale_threshold(self, mock_openai):
        mock_openai.return_value = self.openai_payload([self.sale(print_lot_count=4)])

        response = self.post()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["auction_count"], 1)

    @patch("secondstateapp.catalog_api_views._call_auction_search_api")
    def test_no_results_returns_deterministic_markdown(self, mock_openai):
        mock_openai.return_value = self.openai_payload([])

        response = self.post(self.payload(horizon_days=3, region=""))

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["auction_count"], 0)
        self.assertEqual(result["window"]["end"], "2026-07-15T18:00:00-07:00")
        self.assertIn("No qualifying upcoming print auctions were found", result["markdown"])

    def test_request_validation_rejects_invalid_horizon_count_and_naive_timestamp(self):
        invalid_payloads = [
            self.payload(horizon_days=5),
            self.payload(horizon_days=3.5),
            self.payload(minimum_print_lots=0),
            self.payload(minimum_print_lots=10.5),
            self.payload(client_now="2026-07-12T18:00:00"),
        ]

        with patch("secondstateapp.catalog_api_views._call_auction_search_api") as mock_openai:
            for payload in invalid_payloads:
                with self.subTest(payload=payload):
                    response = self.post(payload)
                    self.assertEqual(response.status_code, 400)
            mock_openai.assert_not_called()

    @patch.dict(os.environ, {"OPENAI_AUCTION_SEARCH_MODEL": "gpt-auction-test"}, clear=False)
    @patch("secondstateapp.catalog_api_views.urllib.request.urlopen")
    def test_openai_request_uses_configured_model_web_search_and_schema(self, mock_urlopen):
        mock_response = mock_urlopen.return_value.__enter__.return_value
        mock_response.read.return_value = json.dumps(self.openai_payload([])).encode("utf-8")
        config = catalog_api_views._validate_auction_search_request(self.payload())

        catalog_api_views._call_auction_search_api(config)

        openai_request = mock_urlopen.call_args.args[0]
        request_body = json.loads(openai_request.data.decode("utf-8"))
        self.assertEqual(request_body["model"], "gpt-auction-test")
        self.assertEqual(request_body["tools"], [{"type": "web_search", "search_context_size": "high"}])
        self.assertEqual(request_body["include"], ["web_search_call.action.sources"])
        self.assertEqual(request_body["text"]["format"]["type"], "json_schema")
        self.assertTrue(request_body["text"]["format"]["strict"])

    @patch("secondstateapp.catalog_api_views._call_auction_search_api")
    def test_malformed_model_output_returns_bad_gateway(self, mock_openai):
        mock_openai.return_value = {"output_text": "not-json"}

        response = self.post()

        self.assertEqual(response.status_code, 502)
        self.assertIn("malformed", response.json()["error"].lower())

    @patch("secondstateapp.catalog_api_views._call_auction_search_api")
    def test_timeout_and_upstream_failures_return_clean_errors(self, mock_openai):
        mock_openai.side_effect = catalog_api_views.AuctionSearchTimeout("timed out")
        timeout_response = self.post()
        self.assertEqual(timeout_response.status_code, 504)
        self.assertEqual(timeout_response.json()["error"], "Auction research timed out. Please try again.")

        mock_openai.side_effect = catalog_api_views.AuctionSearchUpstreamError("provider unavailable")
        upstream_response = self.post()
        self.assertEqual(upstream_response.status_code, 502)
        self.assertEqual(upstream_response.json()["error"], "provider unavailable")
