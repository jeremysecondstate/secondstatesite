import json
import os
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from . import catalog_api_views, views
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
            "end_at": None,
            "timezone": "America/New_York",
            "location": "New York",
            "online_format": "Live and online",
            "sale_type": "dedicated",
            "print_lot_count": 24,
            "count_kind": "verified",
            "count_evidence": "The official catalog lists lots 1 through 24.",
            "category_evidence": "The official page is titled Prints & Multiples.",
            "date_evidence": "The official page lists the sale date and time.",
            "print_types": ["etchings", "screenprints"],
            "official_sale_url": "https://example-auctions.test/sales/prints",
            "supporting_sources": ["https://example-auctions.test/sales/prints"],
        }
        data.update(overrides)
        return data

    def openai_payload(self, sales, *, web_search=True, response_id="resp_test", status="completed"):
        output = []
        if web_search:
            output.extend(
                [
                    {
                        "type": "web_search_call",
                        "id": "ws_search",
                        "status": "completed",
                        "action": {
                            "type": "search",
                            "queries": ["upcoming print auctions", "prints multiples auction calendar"],
                            "sources": [
                                {
                                    "type": "url",
                                    "url": "https://research-source.test/calendar",
                                    "title": "Auction calendar",
                                    "snippet": "Upcoming sales",
                                }
                            ],
                        },
                    },
                    {
                        "type": "web_search_call",
                        "id": "ws_open",
                        "status": "completed",
                        "action": {
                            "type": "open_page",
                            "url": "https://example-auctions.test/sales/prints",
                            "sources": [
                                {
                                    "type": "url",
                                    "url": "https://example-auctions.test/sales/prints",
                                    "title": "Prints & Multiples",
                                }
                            ],
                        },
                    },
                    {
                        "type": "web_search_call",
                        "id": "ws_find",
                        "status": "completed",
                        "action": {"type": "find_in_page", "pattern": "prints"},
                    },
                ]
            )
        output.append(
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps({"sales": sales}),
                        "annotations": [
                            {
                                "type": "url_citation",
                                "url": "https://research-source.test/calendar",
                                "title": "Calendar",
                            }
                        ],
                    }
                ],
            }
        )
        return {
            "id": response_id,
            "status": status,
            "model": "gpt-5.6-sol",
            "output_text": json.dumps({"sales": sales}),
            "output": output,
        }

    def http_response(self, payload):
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = json.dumps(payload).encode("utf-8")
        return response

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
    def test_search_filters_deduplicates_sorts_and_returns_diagnostics(self, mock_openai):
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
            start_at="2026-07-10T12:00:00-07:00",
            end_at="2026-07-12T17:59:59-07:00",
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
        self.assertEqual(result["research_meta"]["web_search_call_count"], 3)
        self.assertEqual(result["research_meta"]["search_count"], 1)
        self.assertEqual(result["research_meta"]["open_page_count"], 1)
        self.assertEqual(result["research_meta"]["find_in_page_count"], 1)
        self.assertEqual(result["research_meta"]["raw_candidate_count"], 5)
        self.assertEqual(result["research_meta"]["qualified_count"], 2)
        self.assertEqual(result["research_meta"]["filtered_counts"]["mixed_below_threshold"], 1)
        self.assertEqual(result["research_meta"]["filtered_counts"]["ended"], 1)
        self.assertEqual(result["research_meta"]["filtered_counts"]["duplicate"], 1)
        self.assertEqual(
            result["research_meta"]["queries"],
            ["upcoming print auctions", "prints multiples auction calendar"],
        )
        self.assertEqual(result["research_meta"]["source_count"], 2)
        self.assertEqual(result["research_meta"]["sources"][0]["snippet"], "Upcoming sales")
        self.assertEqual(result["research_meta"]["response_id"], "resp_test")
        self.assertEqual(result["research_meta"]["response_status"], "completed")
        self.assertEqual(result["research_meta"]["model"], "gpt-5.6-sol")
        self.assertEqual(result["research_meta"]["reasoning_effort"], "xhigh")
        self.assertEqual(result["research_meta"]["warnings"], [])
        called_config = mock_openai.call_args.args[0]
        self.assertEqual(called_config["minimum_print_lots"], 10)
        self.assertEqual(called_config["region"], "North America")

    @patch("secondstateapp.catalog_api_views._call_auction_search_api")
    def test_dedicated_sale_with_unknown_count_and_strong_evidence_qualifies(self, mock_openai):
        mock_openai.return_value = self.openai_payload(
            [
                self.sale(
                    print_lot_count=None,
                    count_kind="unknown",
                    count_evidence="The official page does not publish a lot count yet.",
                )
            ]
        )

        response = self.post()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["auction_count"], 1)
        self.assertIsNone(response.json()["sales"][0]["print_lot_count"])
        self.assertIn("Unknown (unknown)", response.json()["markdown"])

    @patch("secondstateapp.catalog_api_views._call_auction_search_api")
    def test_mixed_sale_with_unknown_count_is_rejected(self, mock_openai):
        mock_openai.return_value = self.openai_payload(
            [
                self.sale(
                    sale_type="mixed",
                    print_lot_count=None,
                    count_kind="unknown",
                    count_evidence="No defensible count was available.",
                )
            ]
        )

        response = self.post()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["auction_count"], 0)
        self.assertEqual(response.json()["research_meta"]["filtered_counts"]["mixed_count_unknown"], 1)

    @patch("secondstateapp.catalog_api_views._call_auction_search_api")
    def test_earlier_started_sale_closing_in_window_qualifies_and_ended_sale_does_not(self, mock_openai):
        closing_in_window = self.sale(
            sale_title="Timed Prints",
            start_at="2026-07-10T10:00:00-07:00",
            end_at="2026-07-14T10:00:00-07:00",
        )
        ended = self.sale(
            sale_title="Closed Prints",
            start_at="2026-07-09T10:00:00-07:00",
            end_at="2026-07-12T17:00:00-07:00",
            official_sale_url="https://example-auctions.test/sales/closed",
            supporting_sources=["https://example-auctions.test/sales/closed"],
        )
        mock_openai.return_value = self.openai_payload([closing_in_window, ended])

        response = self.post()

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["auction_count"], 1)
        self.assertEqual(result["sales"][0]["end_at"], "2026-07-14T10:00:00-07:00")
        self.assertIn("Timed Prints", result["markdown"])
        self.assertNotIn("Closed Prints", result["markdown"])
        self.assertEqual(result["research_meta"]["filtered_counts"]["ended"], 1)

    @patch("secondstateapp.catalog_api_views._call_auction_search_api")
    def test_legitimate_zero_after_real_web_search_returns_deterministic_markdown(self, mock_openai):
        mock_openai.return_value = self.openai_payload([])

        response = self.post(self.payload(horizon_days=3, region=""))

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["auction_count"], 0)
        self.assertEqual(result["window"]["end"], "2026-07-15T18:00:00-07:00")
        self.assertIn("No qualifying upcoming print auctions were found", result["markdown"])
        self.assertEqual(result["research_meta"]["web_search_call_count"], 3)

    @patch("secondstateapp.catalog_api_views._call_auction_search_api")
    def test_missing_web_search_retries_once_then_succeeds_with_warning(self, mock_openai):
        mock_openai.side_effect = [
            self.openai_payload([], web_search=False, response_id="resp_first"),
            self.openai_payload([], response_id="resp_retry"),
        ]

        response = self.post()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_openai.call_count, 2)
        self.assertFalse(mock_openai.call_args_list[0].kwargs["discovery_retry"])
        self.assertTrue(mock_openai.call_args_list[1].kwargs["discovery_retry"])
        self.assertEqual(response.json()["research_meta"]["attempt_count"], 2)
        self.assertIn("retried once", response.json()["research_meta"]["warnings"][0])

    @patch("secondstateapp.catalog_api_views._call_auction_search_api")
    def test_missing_web_search_after_bounded_retry_returns_research_error(self, mock_openai):
        mock_openai.side_effect = [
            self.openai_payload([], web_search=False, response_id="resp_first"),
            self.openai_payload([], web_search=False, response_id="resp_retry"),
        ]

        response = self.post()

        self.assertEqual(response.status_code, 502)
        self.assertEqual(mock_openai.call_count, 2)
        self.assertIn("no web-search activity", response.json()["error"].lower())
        self.assertEqual(response.json()["research_meta"]["web_search_call_count"], 0)
        self.assertNotIn("auction_count", response.json())

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

    @patch("secondstateapp.catalog_api_views.urllib.request.urlopen")
    def test_openai_request_defaults_to_gpt_5_6_required_search_and_strict_schema(self, mock_urlopen):
        mock_urlopen.return_value = self.http_response(self.openai_payload([]))
        config = catalog_api_views._validate_auction_search_request(self.payload())
        env = {
            "OPENAI_AUCTION_SEARCH_MODEL": "",
            "OPENAI_AUCTION_SEARCH_REASONING_EFFORT": "",
            "OPENAI_AUCTION_SEARCH_RETURN_TOKEN_BUDGET": "",
            "OPENAI_AUCTION_SEARCH_MAX_OUTPUT_TOKENS": "",
        }

        with patch.dict(os.environ, env, clear=False):
            catalog_api_views._call_auction_search_api(config)

        openai_request = mock_urlopen.call_args.args[0]
        request_body = json.loads(openai_request.data.decode("utf-8"))
        self.assertEqual(request_body["model"], "gpt-5.6-sol")
        self.assertEqual(request_body["reasoning"], {"effort": "xhigh"})
        self.assertEqual(
            request_body["tools"],
            [{"type": "web_search", "search_context_size": "high", "return_token_budget": "unlimited"}],
        )
        self.assertEqual(request_body["tool_choice"], "required")
        self.assertEqual(request_body["include"], ["web_search_call.action.sources"])
        self.assertEqual(request_body["max_output_tokens"], 20000)
        self.assertTrue(request_body["background"])
        self.assertEqual(request_body["text"]["format"]["type"], "json_schema")
        self.assertTrue(request_body["text"]["format"]["strict"])
        schema = request_body["text"]["format"]["schema"]
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["sales"]["items"]["properties"]["end_at"]["type"], ["string", "null"])
        self.assertEqual(
            schema["properties"]["sales"]["items"]["properties"]["print_lot_count"]["type"],
            ["integer", "null"],
        )

    @patch.dict(
        os.environ,
        {
            "OPENAI_AUCTION_SEARCH_MODEL": "gpt-auction-test",
            "OPENAI_AUCTION_SEARCH_REASONING_EFFORT": "high",
            "OPENAI_AUCTION_SEARCH_RETURN_TOKEN_BUDGET": "default",
            "OPENAI_AUCTION_SEARCH_MAX_OUTPUT_TOKENS": "12345",
        },
        clear=False,
    )
    @patch("secondstateapp.catalog_api_views.urllib.request.urlopen")
    def test_openai_request_supports_model_reasoning_budget_and_output_overrides(self, mock_urlopen):
        mock_urlopen.return_value = self.http_response(self.openai_payload([]))
        config = catalog_api_views._validate_auction_search_request(self.payload())

        catalog_api_views._call_auction_search_api(config)

        request_body = json.loads(mock_urlopen.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(request_body["model"], "gpt-auction-test")
        self.assertEqual(request_body["reasoning"]["effort"], "high")
        self.assertEqual(request_body["tools"][0]["return_token_budget"], "default")
        self.assertEqual(request_body["max_output_tokens"], 12345)

    @patch("secondstateapp.catalog_api_views.time.sleep")
    @patch("secondstateapp.catalog_api_views.urllib.request.urlopen")
    def test_background_response_polls_queued_and_in_progress_until_completed(self, mock_urlopen, mock_sleep):
        response_id = "resp_background"
        mock_urlopen.side_effect = [
            self.http_response({"id": response_id, "status": "queued", "model": "gpt-5.6-sol", "output": []}),
            self.http_response(
                {"id": response_id, "status": "in_progress", "model": "gpt-5.6-sol", "output": []}
            ),
            self.http_response(self.openai_payload([], response_id=response_id)),
        ]
        config = catalog_api_views._validate_auction_search_request(self.payload())

        result = catalog_api_views._call_auction_search_api(config)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(mock_urlopen.call_count, 3)
        self.assertEqual(mock_urlopen.call_args_list[0].args[0].get_method(), "POST")
        self.assertEqual(mock_urlopen.call_args_list[1].args[0].get_method(), "GET")
        self.assertEqual(mock_urlopen.call_args_list[2].args[0].full_url, f"https://api.openai.com/v1/responses/{response_id}")
        self.assertEqual(mock_sleep.call_count, 2)

    def test_failed_cancelled_and_incomplete_background_responses_are_errors(self):
        config = catalog_api_views._validate_auction_search_request(self.payload())
        cases = [
            ("failed", {"message": "provider failed"}, None, "failed"),
            ("cancelled", None, None, "cancelled"),
            ("incomplete", None, {"reason": "max_output_tokens"}, "incomplete"),
        ]
        for status, error, incomplete_details, expected_text in cases:
            with self.subTest(status=status):
                payload = {
                    "id": f"resp_{status}",
                    "status": status,
                    "model": "gpt-5.6-sol",
                    "output": [],
                    "error": error,
                    "incomplete_details": incomplete_details,
                }
                with patch(
                    "secondstateapp.catalog_api_views._openai_json_request",
                    return_value=payload,
                ):
                    with self.assertRaises(catalog_api_views.AuctionSearchUpstreamError) as context:
                        catalog_api_views._call_auction_search_api(config)
                self.assertIn(expected_text, str(context.exception).lower())
                self.assertEqual(context.exception.research_meta["response_status"], status)

    @patch("secondstateapp.catalog_api_views._call_auction_search_api")
    def test_malformed_model_output_returns_bad_gateway(self, mock_openai):
        mock_openai.return_value = self.openai_payload([])
        mock_openai.return_value["output_text"] = "not-json"

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


@patch.dict(os.environ, {"OPENAI_API_KEY": "not-used-in-tests"}, clear=False)
class DescriptionOutputLimitTests(TestCase):
    def response(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = json.dumps({"output_text": "Description."}).encode("utf-8")
        return response

    def artwork(self):
        return Artwork(
            artist="Test Artist",
            title="Test Print",
            medium="Screenprint",
            price=Decimal("100.00"),
        )

    def test_description_requests_restore_450_token_limit(self):
        with patch("secondstateapp.catalog_api_views.urllib.request.urlopen", return_value=self.response()) as mock_api:
            catalog_api_views._generate_description(self.artwork(), use_web=False)
        api_body = json.loads(mock_api.call_args.args[0].data.decode("utf-8"))

        with patch("secondstateapp.views.urllib.request.urlopen", return_value=self.response()) as mock_view:
            views._generate_catalog_description(self.artwork(), use_web=False)
        view_body = json.loads(mock_view.call_args.args[0].data.decode("utf-8"))

        self.assertEqual(api_body["max_output_tokens"], 450)
        self.assertEqual(view_body["max_output_tokens"], 450)
