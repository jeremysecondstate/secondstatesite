import json
import os
import uuid
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from catalogapp import catalogapp_inv_ui
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import catalog_api_views, views
from .models import Artwork, AuctionSearchJob


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

    def start(self, payload=None, authenticated=True):
        headers = {"HTTP_X_API_KEY": "test-key"} if authenticated else {}
        return self.client.post(
            reverse(self.endpoint_name),
            data=json.dumps(payload if payload is not None else self.payload()),
            content_type="application/json",
            **headers,
        )

    def poll(self, job, authenticated=True):
        headers = {"HTTP_X_API_KEY": "test-key"} if authenticated else {}
        return self.client.get(
            reverse("search_upcoming_print_auctions_status", args=[job.id]),
            **headers,
        )

    def create_job(
        self,
        *,
        payload=None,
        response_id="resp_initial",
        provider_status="queued",
        attempt_count=1,
        retry_warning="",
        deadline=None,
    ):
        config = catalog_api_views._validate_auction_search_request(payload or self.payload())
        return AuctionSearchJob.objects.create(
            requester_fingerprint=catalog_api_views._catalog_api_requester_fingerprint(),
            openai_response_id=response_id,
            openai_status=provider_status,
            config=catalog_api_views._auction_config_for_storage(config),
            openai_settings=catalog_api_views._configured_auction_search_settings(),
            attempt_count=attempt_count,
            retry_warning=retry_warning,
            timeout_seconds=420,
            attempt_deadline_at=deadline or timezone.now() + timedelta(seconds=420),
        )

    def assert_json_error(self, response, status):
        self.assertEqual(response.status_code, status)
        self.assertTrue(response["Content-Type"].startswith("application/json"))
        payload = response.json()
        self.assertIn("error", payload)
        self.assertEqual(response["X-Correlation-ID"], payload["correlation_id"])
        return payload

    @patch("secondstateapp.catalog_api_views._create_auction_search_response")
    def test_start_auth_method_and_validation_errors_are_json_and_correlated(self, mock_create):
        with self.assertLogs("secondstateapp.catalog_api_views", level="WARNING") as logs:
            unauthorized = self.start(authenticated=False)
        unauthorized_payload = self.assert_json_error(unauthorized, 401)
        self.assertIn(unauthorized_payload["correlation_id"], "\n".join(logs.output))

        wrong_method = self.client.get(reverse(self.endpoint_name), HTTP_X_API_KEY="test-key")
        self.assert_json_error(wrong_method, 405)
        self.assertEqual(wrong_method["Allow"], "POST")

        for invalid_payload in [
            self.payload(horizon_days=5),
            self.payload(horizon_days=3.5),
            self.payload(minimum_print_lots=0),
            self.payload(minimum_print_lots=10.5),
            self.payload(client_now="2026-07-12T18:00:00"),
        ]:
            with self.subTest(payload=invalid_payload):
                self.assert_json_error(self.start(invalid_payload), 400)
        mock_create.assert_not_called()

    @patch("secondstateapp.catalog_api_views._create_auction_search_response")
    def test_start_returns_202_with_opaque_job_id_and_persists_state(self, mock_create):
        mock_create.return_value = {
            "id": "resp_server_only",
            "status": "queued",
            "model": "gpt-5.6-sol",
            "output": [],
        }

        response = self.start()

        self.assertEqual(response.status_code, 202)
        result = response.json()
        uuid.UUID(result["job_id"])
        self.assertNotIn("resp_server_only", response.content.decode("utf-8"))
        self.assertEqual(result["status"], "queued")
        self.assertEqual(
            result["status_url"],
            reverse("search_upcoming_print_auctions_status", args=[result["job_id"]]),
        )
        self.assertEqual(response["X-Correlation-ID"], result["correlation_id"])

        job = AuctionSearchJob.objects.get(pk=result["job_id"])
        self.assertEqual(job.openai_response_id, "resp_server_only")
        self.assertEqual(job.requester_fingerprint, catalog_api_views._catalog_api_requester_fingerprint())
        self.assertEqual(job.attempt_count, 1)
        self.assertEqual(job.config["minimum_print_lots"], 10)
        self.assertEqual(job.openai_settings["model"], "gpt-5.6-sol")
        self.assertEqual(str(job.correlation_id), result["correlation_id"])
        mock_create.assert_called_once()
        self.assertFalse(mock_create.call_args.kwargs.get("discovery_retry", False))

    @patch(
        "secondstateapp.catalog_api_views._create_auction_search_response",
        side_effect=catalog_api_views.AuctionSearchUpstreamError("provider unavailable"),
    )
    def test_start_upstream_failure_is_json_and_does_not_create_job(self, _mock_create):
        response = self.start()

        payload = self.assert_json_error(response, 502)
        self.assertEqual(payload["error"], "provider unavailable")
        self.assertEqual(AuctionSearchJob.objects.count(), 0)

    def test_status_requires_auth_and_returns_json_for_unknown_job_and_wrong_method(self):
        missing_id = uuid.uuid4()
        endpoint = reverse("search_upcoming_print_auctions_status", args=[missing_id])

        self.assert_json_error(self.client.get(endpoint), 401)
        self.assert_json_error(self.client.get(endpoint, HTTP_X_API_KEY="test-key"), 404)
        wrong_method = self.client.post(endpoint, HTTP_X_API_KEY="test-key")
        self.assert_json_error(wrong_method, 405)
        self.assertEqual(wrong_method["Allow"], "GET")

    @patch("secondstateapp.catalog_api_views._retrieve_auction_search_response")
    def test_authenticated_principal_cannot_poll_another_principals_job(self, mock_retrieve):
        job = self.create_job()
        job.requester_fingerprint = "user:999999"
        job.save()

        response = self.poll(job)

        self.assert_json_error(response, 404)
        mock_retrieve.assert_not_called()

    @patch("secondstateapp.catalog_api_views._retrieve_auction_search_response")
    def test_each_active_status_poll_performs_exactly_one_openai_fetch(self, mock_retrieve):
        job = self.create_job()
        mock_retrieve.return_value = {
            "id": job.openai_response_id,
            "status": "queued",
            "model": "gpt-5.6-sol",
            "output": [],
        }

        queued_response = self.poll(job)

        self.assertEqual(queued_response.status_code, 200)
        self.assertEqual(queued_response.json()["status"], "queued")
        mock_retrieve.assert_called_once_with(job.openai_response_id, timeout=25)

        mock_retrieve.reset_mock()
        mock_retrieve.return_value = {
            "id": job.openai_response_id,
            "status": "in_progress",
            "model": "gpt-5.6-sol",
            "output": [],
        }
        in_progress_response = self.poll(job)

        self.assertEqual(in_progress_response.json()["status"], "in_progress")
        mock_retrieve.assert_called_once_with(job.openai_response_id, timeout=25)

    @patch("secondstateapp.catalog_api_views._retrieve_auction_search_response")
    def test_completed_status_preserves_filtering_closing_times_and_diagnostics(self, mock_retrieve):
        job = self.create_job()
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
        closing_in_window = self.sale(
            auction_house="Timed Auctions",
            sale_title="Timed Prints",
            start_at="2026-07-10T10:00:00-07:00",
            end_at="2026-07-14T10:00:00-07:00",
            timezone="America/Los_Angeles",
            official_sale_url="https://timed-auctions.test/sales/prints",
            supporting_sources=["https://timed-auctions.test/sales/prints"],
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
        mock_retrieve.return_value = self.openai_payload(
            [later_dedicated, earlier_mixed, closing_in_window, below_threshold, ended, duplicate],
            response_id=job.openai_response_id,
        )

        response = self.poll(job)

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["auction_count"], 3)
        self.assertLess(result["markdown"].index("Pacific Auctions"), result["markdown"].index("Timed Auctions"))
        self.assertLess(result["markdown"].index("Timed Auctions"), result["markdown"].index("Example Auctions"))
        self.assertIn("Closes/ends:** 2026-07-14 10:00 -0700", result["markdown"])
        self.assertNotIn("Already Ended", result["markdown"])
        self.assertNotIn("Mixed Art", result["markdown"])
        self.assertEqual(result["research_meta"]["web_search_call_count"], 3)
        self.assertEqual(result["research_meta"]["search_count"], 1)
        self.assertEqual(result["research_meta"]["open_page_count"], 1)
        self.assertEqual(result["research_meta"]["find_in_page_count"], 1)
        self.assertEqual(result["research_meta"]["raw_candidate_count"], 6)
        self.assertEqual(result["research_meta"]["qualified_count"], 3)
        self.assertEqual(result["research_meta"]["filtered_counts"]["mixed_below_threshold"], 1)
        self.assertEqual(result["research_meta"]["filtered_counts"]["ended"], 1)
        self.assertEqual(result["research_meta"]["filtered_counts"]["duplicate"], 1)
        self.assertEqual(result["research_meta"]["model"], "gpt-5.6-sol")
        self.assertIn("https://research-source.test/calendar", result["source_urls"])

        job.refresh_from_db()
        self.assertEqual(job.state, AuctionSearchJob.State.COMPLETED)
        mock_retrieve.reset_mock()
        cached_response = self.poll(job)
        self.assertEqual(cached_response.status_code, 200)
        self.assertEqual(cached_response.json()["markdown"], result["markdown"])
        mock_retrieve.assert_not_called()

    @patch("secondstateapp.catalog_api_views._retrieve_auction_search_response")
    def test_dedicated_unknown_count_and_researched_zero_still_work(self, mock_retrieve):
        unknown_count_job = self.create_job()
        mock_retrieve.return_value = self.openai_payload(
            [
                self.sale(
                    print_lot_count=None,
                    count_kind="unknown",
                    count_evidence="The official page does not publish a lot count yet.",
                )
            ],
            response_id=unknown_count_job.openai_response_id,
        )
        unknown_count_response = self.poll(unknown_count_job)
        self.assertEqual(unknown_count_response.json()["auction_count"], 1)
        self.assertIsNone(unknown_count_response.json()["sales"][0]["print_lot_count"])
        self.assertIn("Unknown (unknown)", unknown_count_response.json()["markdown"])

        zero_job = self.create_job(payload=self.payload(horizon_days=3, region=""), response_id="resp_zero")
        mock_retrieve.return_value = self.openai_payload([], response_id=zero_job.openai_response_id)
        zero_response = self.poll(zero_job)
        self.assertEqual(zero_response.status_code, 200)
        self.assertEqual(zero_response.json()["auction_count"], 0)
        self.assertEqual(zero_response.json()["window"]["end"], "2026-07-15T18:00:00-07:00")
        self.assertIn("No qualifying upcoming print auctions were found", zero_response.json()["markdown"])

    @patch("secondstateapp.catalog_api_views._create_auction_search_response")
    @patch("secondstateapp.catalog_api_views._retrieve_auction_search_response")
    def test_missing_web_search_starts_one_retry_then_completes_with_warning(
        self,
        mock_retrieve,
        mock_create,
    ):
        job = self.create_job()
        mock_retrieve.return_value = self.openai_payload(
            [],
            web_search=False,
            response_id=job.openai_response_id,
        )
        mock_create.return_value = {
            "id": "resp_retry",
            "status": "queued",
            "model": "gpt-5.6-sol",
            "output": [],
        }

        retry_response = self.poll(job)

        self.assertEqual(retry_response.status_code, 200)
        self.assertEqual(retry_response.json()["status"], "retrying")
        self.assertEqual(retry_response.json()["attempt_count"], 2)
        mock_retrieve.assert_called_once()
        mock_create.assert_called_once()
        self.assertTrue(mock_create.call_args.kwargs["discovery_retry"])

        job.refresh_from_db()
        self.assertEqual(job.openai_response_id, "resp_retry")
        self.assertEqual(job.attempt_count, 2)
        mock_retrieve.reset_mock()
        mock_create.reset_mock()
        mock_retrieve.return_value = self.openai_payload([], response_id="resp_retry")

        completed_response = self.poll(job)

        self.assertEqual(completed_response.status_code, 200)
        self.assertEqual(completed_response.json()["status"], "completed")
        self.assertEqual(completed_response.json()["research_meta"]["attempt_count"], 2)
        self.assertIn("retried once", completed_response.json()["research_meta"]["warnings"][0])
        mock_retrieve.assert_called_once_with("resp_retry", timeout=25)
        mock_create.assert_not_called()

    @patch("secondstateapp.catalog_api_views._retrieve_auction_search_response")
    def test_missing_web_search_after_bounded_retry_is_json_error(self, mock_retrieve):
        job = self.create_job(
            response_id="resp_retry",
            attempt_count=2,
            retry_warning=catalog_api_views.AUCTION_SEARCH_RETRY_WARNING,
        )
        mock_retrieve.return_value = self.openai_payload(
            [],
            web_search=False,
            response_id=job.openai_response_id,
        )

        response = self.poll(job)

        payload = self.assert_json_error(response, 502)
        self.assertIn("no web-search activity", payload["error"].lower())
        self.assertEqual(payload["research_meta"]["web_search_call_count"], 0)
        self.assertEqual(payload["research_meta"]["attempt_count"], 2)
        self.assertNotIn("auction_count", payload)
        job.refresh_from_db()
        self.assertEqual(job.state, AuctionSearchJob.State.FAILED)

    @patch("secondstateapp.catalog_api_views._retrieve_auction_search_response")
    def test_failed_cancelled_and_incomplete_responses_are_terminal_json_errors(self, mock_retrieve):
        cases = [
            ("failed", {"message": "provider failed"}, None, "failed"),
            ("cancelled", None, None, "cancelled"),
            ("incomplete", None, {"reason": "max_output_tokens"}, "incomplete"),
        ]
        for index, (status, error, incomplete_details, expected_text) in enumerate(cases):
            with self.subTest(status=status):
                job = self.create_job(response_id=f"resp_{status}_{index}")
                mock_retrieve.return_value = {
                    "id": job.openai_response_id,
                    "status": status,
                    "model": "gpt-5.6-sol",
                    "output": [],
                    "error": error,
                    "incomplete_details": incomplete_details,
                }

                response = self.poll(job)

                payload = self.assert_json_error(response, 502)
                self.assertIn(expected_text, payload["error"].lower())
                self.assertEqual(payload["research_meta"]["response_status"], status)
                job.refresh_from_db()
                self.assertEqual(job.state, AuctionSearchJob.State.FAILED)

    @patch("secondstateapp.catalog_api_views._retrieve_auction_search_response")
    def test_expired_job_times_out_without_openai_fetch(self, mock_retrieve):
        job = self.create_job(deadline=timezone.now() - timedelta(seconds=1))

        response = self.poll(job)

        payload = self.assert_json_error(response, 504)
        self.assertIn("timed out", payload["error"].lower())
        mock_retrieve.assert_not_called()
        job.refresh_from_db()
        self.assertEqual(job.state, AuctionSearchJob.State.TIMED_OUT)

    @patch("secondstateapp.catalog_api_views._retrieve_auction_search_response")
    def test_malformed_output_is_a_json_bad_gateway(self, mock_retrieve):
        job = self.create_job()
        payload = self.openai_payload([], response_id=job.openai_response_id)
        payload["output_text"] = "not-json"
        mock_retrieve.return_value = payload

        response = self.poll(job)

        result = self.assert_json_error(response, 502)
        self.assertIn("malformed", result["error"].lower())

    @patch(
        "secondstateapp.catalog_api_views._retrieve_auction_search_response",
        side_effect=RuntimeError("unexpected internal detail"),
    )
    def test_unexpected_status_exception_is_json_and_logged_with_job_correlation(self, _mock_retrieve):
        job = self.create_job()

        with self.assertLogs("secondstateapp.catalog_api_views", level="ERROR") as logs:
            response = self.poll(job)

        payload = self.assert_json_error(response, 500)
        self.assertNotIn("unexpected internal detail", payload["error"])
        self.assertEqual(payload["correlation_id"], str(job.correlation_id))
        self.assertIn(str(job.correlation_id), "\n".join(logs.output))

    @patch("secondstateapp.catalog_api_views.urllib.request.urlopen")
    def test_openai_create_preserves_sol_required_search_strict_schema_and_background(self, mock_urlopen):
        mock_urlopen.return_value = self.http_response(
            {"id": "resp_created", "status": "queued", "model": "gpt-5.6-sol", "output": []}
        )
        config = catalog_api_views._validate_auction_search_request(self.payload())
        env = {
            "OPENAI_AUCTION_SEARCH_MODEL": "",
            "OPENAI_AUCTION_SEARCH_REASONING_EFFORT": "",
            "OPENAI_AUCTION_SEARCH_RETURN_TOKEN_BUDGET": "",
            "OPENAI_AUCTION_SEARCH_MAX_OUTPUT_TOKENS": "",
        }

        with patch.dict(os.environ, env, clear=False):
            result = catalog_api_views._create_auction_search_response(config)

        self.assertEqual(result["id"], "resp_created")
        self.assertEqual(mock_urlopen.call_count, 1)
        openai_request = mock_urlopen.call_args.args[0]
        request_body = json.loads(openai_request.data.decode("utf-8"))
        self.assertEqual(openai_request.get_method(), "POST")
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
        self.assertTrue(request_body["store"])
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
    def test_openai_create_supports_existing_server_side_overrides(self, mock_urlopen):
        mock_urlopen.return_value = self.http_response(
            {"id": "resp_created", "status": "queued", "model": "gpt-auction-test", "output": []}
        )
        config = catalog_api_views._validate_auction_search_request(self.payload())

        catalog_api_views._create_auction_search_response(config)

        request_body = json.loads(mock_urlopen.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(request_body["model"], "gpt-auction-test")
        self.assertEqual(request_body["reasoning"]["effort"], "high")
        self.assertEqual(request_body["tools"][0]["return_token_budget"], "default")
        self.assertEqual(request_body["max_output_tokens"], 12345)


class AuctionSearchDesktopHelperTests(TestCase):
    def response(self, status_code, payload=None, *, correlation_id="", json_error=False, text=""):
        response = MagicMock()
        response.status_code = status_code
        response.headers = {"X-Correlation-ID": correlation_id} if correlation_id else {}
        response.text = text
        if json_error:
            response.json.side_effect = ValueError("not json")
        else:
            response.json.return_value = payload
        return response

    @patch.object(catalogapp_inv_ui, "BASE_URL", "https://secondstate.test")
    @patch.object(catalogapp_inv_ui, "CATALOG_API_KEY", "desktop-key")
    def test_worker_helper_starts_then_polls_until_completed(self):
        request_client = MagicMock()
        job_id = "1d6ba6a4-1463-418f-a201-07e0d2e1de66"
        request_client.post.return_value = self.response(
            202,
            {
                "job_id": job_id,
                "status": "queued",
                "attempt_count": 1,
                "correlation_id": "corr-start",
            },
        )
        request_client.get.side_effect = [
            self.response(200, {"job_id": job_id, "status": "queued", "attempt_count": 1}),
            self.response(200, {"job_id": job_id, "status": "retrying", "attempt_count": 2}),
            self.response(
                200,
                {
                    "job_id": job_id,
                    "status": "completed",
                    "attempt_count": 2,
                    "markdown": "# Result",
                    "auction_count": 0,
                    "research_meta": {},
                },
            ),
        ]
        progress = []
        sleep_fn = MagicMock()

        result = catalogapp_inv_ui.request_upcoming_auction_search(
            {"horizon_days": 3},
            request_client=request_client,
            progress_callback=progress.append,
            sleep_fn=sleep_fn,
            timeout_seconds=60,
        )

        self.assertEqual(result["markdown"], "# Result")
        self.assertEqual([item["status"] for item in progress], ["queued", "queued", "retrying", "completed"])
        self.assertEqual(request_client.get.call_count, 3)
        expected_status_url = (
            "https://secondstate.test/artworks/search_upcoming_print_auctions/"
            f"{job_id}/status/"
        )
        self.assertTrue(all(call.args[0] == expected_status_url for call in request_client.get.call_args_list))
        self.assertEqual(sleep_fn.call_count, 2)
        self.assertEqual(
            request_client.post.call_args.kwargs["headers"]["X-API-KEY"],
            "desktop-key",
        )

    @patch.object(catalogapp_inv_ui, "BASE_URL", "https://secondstate.test")
    def test_non_json_html_error_is_never_exposed_to_desktop(self):
        request_client = MagicMock()
        request_client.post.return_value = self.response(
            500,
            correlation_id="corr-html",
            json_error=True,
            text="<html><body>Internal Server Error secret traceback</body></html>",
        )

        with self.assertRaises(catalogapp_inv_ui.AuctionSearchClientError) as context:
            catalogapp_inv_ui.request_upcoming_auction_search(
                {},
                request_client=request_client,
                sleep_fn=MagicMock(),
                timeout_seconds=60,
            )

        message = str(context.exception)
        self.assertIn("HTTP 500", message)
        self.assertIn("corr-html", message)
        self.assertNotIn("<html", message)
        self.assertNotIn("secret traceback", message)

    @patch.object(catalogapp_inv_ui, "BASE_URL", "https://secondstate.test")
    def test_json_status_error_includes_safe_correlation_reference(self):
        request_client = MagicMock()
        job_id = "job-safe"
        request_client.post.return_value = self.response(
            202,
            {"job_id": job_id, "status": "queued", "correlation_id": "corr-start"},
        )
        request_client.get.return_value = self.response(
            502,
            {"error": "Provider unavailable.", "correlation_id": "corr-status"},
        )

        with self.assertRaises(catalogapp_inv_ui.AuctionSearchClientError) as context:
            catalogapp_inv_ui.request_upcoming_auction_search(
                {},
                request_client=request_client,
                sleep_fn=MagicMock(),
                timeout_seconds=60,
            )

        self.assertIn("Provider unavailable.", str(context.exception))
        self.assertIn("corr-status", str(context.exception))

    def test_tkinter_progress_updates_are_scheduled_with_after(self):
        app = object.__new__(catalogapp_inv_ui.ArtCatalogApp)
        app.master = MagicMock()
        app._update_auction_search_progress = MagicMock()

        app._schedule_auction_search_progress({"status": "retrying", "attempt_count": 2})

        app.master.after.assert_called_once()
        delay, callback = app.master.after.call_args.args
        self.assertEqual(delay, 0)
        callback()
        app._update_auction_search_progress.assert_called_once()
        self.assertIn("attempt 2 of 2", app._update_auction_search_progress.call_args.args[0])


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
