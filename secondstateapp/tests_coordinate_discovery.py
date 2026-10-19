"""Discovery provenance, partial research, and explicit operator recovery."""
from datetime import timedelta
from uuid import uuid4

from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from scripts.coordinate_evidence import validate_evidence_provenance
from .coordinate_shipping import research_state, validate_worker_artifacts
from .models import CoordinateActivity, CoordinateJob, CoordinateMessage, CoordinateResearch
from .tests_coordinate_browser_sources import BrowserSourcePersistenceTests, browser_record


def discovered_record(**changes):
    return browser_record(
        source_kind="public_browser", final_url="https://marketplace.example/lots/17",
        discovery_method="search", discovery_query="Synthetic artist Synthetic title auction 2026 lot 17",
        discovery_url="", match_reason="Artist, title, house, auction date and lot number match the requested sale.",
        identity_match={"artist": "Synthetic Artist", "title": "Synthetic Title", "auction_house": "Synthetic Auction",
                        "auction_date": "2026-10-17", "lot_number": "17", "status": "exact"},
        attempts=[{"method": "browser_launch", "status": "tool_unavailable", "query": "", "url": "",
                   "observed_at": timezone.now().isoformat(), "detail": "No existing browser window; public search continued."}],
    ) | changes


@override_settings(COORDINATE_DRAFT_WORKFLOW_ENABLED=True)
class DiscoveryContractTests(SimpleTestCase):
    def test_alternate_domains_require_observed_discovery_and_match_provenance(self):
        cleaned, _ = validate_worker_artifacts({"research": [discovered_record()]})
        self.assertEqual(cleaned[0]["discovery_query"], discovered_record()["discovery_query"])
        for changes in ({"discovery_query": ""}, {"match_reason": ""}, {"discovery_method": "direct"},
                        {"discovery_method": "link", "discovery_url": ""}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_worker_artifacts({"research": [discovered_record(**changes)]})
        linked = discovered_record(discovery_method="link", discovery_query="", discovery_url="https://auction.example/results")
        self.assertEqual(validate_evidence_provenance(linked)["discovery_url"], linked["discovery_url"])

    def test_wrong_sale_year_or_lot_cannot_be_exact_but_can_be_historical(self):
        record = discovered_record()
        for key, value in (("auction_date", "2025-10-17"), ("lot_number", "18"), ("artist", "Different Artist")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_evidence_provenance(record, expected_identity={key: value})
        historical = discovered_record(identity_match={**record["identity_match"], "status": "historical"})
        self.assertEqual(validate_evidence_provenance(historical, expected_identity={"auction_date": "2025-10-17"})["identity_match"]["status"], "historical")
        self.assertEqual(validate_evidence_provenance(record, expected_identity={"lot_number": "Lot 017"})["identity_match"]["lot_number"], "17")

    def test_search_only_is_explicitly_unverified(self):
        with self.assertRaises(ValueError):
            validate_evidence_provenance(discovered_record(source_kind="search_only"))
        record = discovered_record(source_kind="search_only", identity_match={"status": "unverified"})
        self.assertEqual(validate_evidence_provenance(record)["identity_match"]["status"], "unverified")

    def test_multi_source_limits_keep_original_url_and_forbid_duplicate_observations(self):
        records = [discovered_record(final_url=f"https://marketplace.example/{i}") for i in range(6)]
        self.assertEqual(len(validate_worker_artifacts({"research": records})[0]), 6)
        for invalid in (records + [discovered_record(final_url="https://marketplace.example/7")], [records[0], records[0]]):
            with self.assertRaises(ValueError):
                validate_worker_artifacts({"research": invalid})

    def test_observed_urls_reject_local_and_ambiguous_destinations(self):
        for url in ("https://127.0.0.1/", "https://[::1]/", "https://169.254.169.254/", "https://localhost/",
                    "https://router.local/", "https://user:password@marketplace.example/", "https://marketplace.example:8443/",
                    "https://marketplace.example\\@evil.example/", " https://marketplace.example/", "http://marketplace.example/",
                    "https://127.1/", "https://0177.0.0.1/", "https://0x7f.0.0.1/", "https://2130706433/",
                    "https://invalid_host.example/", "https://-invalid.example/", "https://invalid..example/"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_evidence_provenance(discovered_record(final_url=url))

    def test_attempts_are_bounded_and_launch_failure_is_separate_from_page_evidence(self):
        record = discovered_record()
        self.assertEqual(validate_evidence_provenance(record)["attempts"][0]["method"], "browser_launch")
        self.assertEqual(record["error"], "")
        for attempts in ([record["attempts"][0]] * 17, [{"method": "arbitrary", "status": "success"}]):
            with self.assertRaises(ValueError):
                validate_evidence_provenance(discovered_record(attempts=attempts))


@override_settings(
    COORDINATE_DRAFT_WORKFLOW_ENABLED=True, COORDINATE_WORKER_TOKEN="synthetic-browser-worker-secret",
    COORDINATE_SHIPPING_PLAYBOOK="Synthetic policy. Drafts only.", COORDINATE_PACKING_PLAYBOOK="Synthetic packing.",
)
class DiscoveryPersistenceTests(TestCase):
    setUp = BrowserSourcePersistenceTests.setUp
    worker_post = BrowserSourcePersistenceTests.worker_post
    claim = BrowserSourcePersistenceTests.claim
    complete = BrowserSourcePersistenceTests.complete

    def test_multiple_sources_and_partial_lot_failure_persist_with_idempotent_retry(self):
        self.message.body += " https://auction.example/lot/18"
        self.message.save()
        claim = self.claim()
        first = discovered_record()
        second = discovered_record(final_url="https://auction.example/shipping", discovery_method="link",
                                   discovery_url=first["final_url"], identity_match={"status": "context"})
        failed = discovered_record(source_url="https://auction.example/lot/18", final_url="", title="", text="",
                                   error="Public browser tool unavailable; other lot research retained.", identity_match={"status": "unverified"})
        records = [first, second, failed]
        response = self.complete(claim, first, research=records)
        self.assertEqual(response.status_code, 200, response.content)
        retry = self.complete(claim, first, research=records)
        self.assertTrue(retry.json()["already_completed"])
        self.assertEqual(CoordinateResearch.objects.count(), 3)
        self.assertEqual(CoordinateMessage.objects.filter(in_reply_to=self.message).count(), 1)
        self.assertEqual(len(research_state(self.case)), 3)
        page = self.client.get(reverse("coordinate_case", args=[self.case.pk]))
        self.assertContains(page, "Public browser")
        self.assertContains(page, "Research attempts (1)")
        self.assertContains(page, "browser_launch")
        self.assertContains(page, first["discovery_query"])
        changed = [{**first, "match_reason": "Changed identity rationale"}, second, failed]
        self.assertEqual(self.complete(claim, first, research=changed).status_code, 409)

    def test_search_only_cannot_authorize_a_draft_recipient(self):
        record = discovered_record(source_kind="search_only", text="Shipping contact unverified@example.test",
                                   identity_match={"status": "unverified"})
        response = self.complete(self.claim(), record, drafts=[{
            "recipient": "unverified@example.test", "subject": "Collection", "body": "Request for review", "purpose": "Draft",
        }])
        self.assertEqual(response.status_code, 400)
        self.assertFalse(CoordinateResearch.objects.exists())

    def test_future_or_deleted_submitted_links_do_not_enter_current_job(self):
        deleted = CoordinateMessage.objects.create(case=self.case, role="staff", body="https://auction.example/deleted",
                                                   deleted_at=timezone.now())
        claim = self.claim()
        future = CoordinateMessage.objects.create(case=self.case, role="staff", body="https://auction.example/future")
        for url in (deleted.body, future.body, "https://auction.example/not-submitted"):
            with self.subTest(url=url):
                response = self.complete(claim, discovered_record(source_url=url))
                self.assertEqual(response.status_code, 400, response.content)
        self.assertFalse(CoordinateResearch.objects.exists())

    def test_server_rejects_stale_evidence_and_conflicting_direct_sale_identity(self):
        claim = self.claim()
        self.assertEqual(self.complete(claim, discovered_record(fetched_at=(timezone.now() - timedelta(days=2)).isoformat())).status_code, 400)
        direct = discovered_record(source_kind="public_fetch", final_url=self.message.body.split()[-1],
                                   discovery_method="direct", text="Auction date: 2025-10-17\nLot 17\nArtist: Synthetic Artist")
        response = self.complete(claim, direct, research=[direct, discovered_record()])
        self.assertEqual(response.status_code, 400, response.content)
        self.assertFalse(CoordinateResearch.objects.exists())

    def test_deleted_reply_hides_all_discovered_sources_and_job_cutoff_is_preserved(self):
        claim = self.claim()
        self.assertEqual(self.complete(claim, discovered_record()).status_code, 200)
        self.assertEqual(len(research_state(self.case)), 1)
        self.assertEqual(research_state(self.case, self.message.pk - 1), [])
        reply = CoordinateMessage.objects.get(in_reply_to=self.message)
        reply.deleted_at = timezone.now()
        reply.save()
        self.assertEqual(research_state(self.case), [])

    def review(self, request_id=None, expected=None):
        return self.worker_post("coordinate_worker_research_review", {
            "worker_id": "manual-codex", "request_id": str(request_id or uuid4()),
            "expected_message_id": expected or self.case.messages.filter(deleted_at__isnull=True).latest("pk").pk,
        }, job_id=self.case.pk)

    def test_explicit_review_queues_new_job_once_and_uses_visible_context(self):
        self.assertEqual(self.complete(self.claim(), browser_record()).status_code, 200)
        previous = self.case.messages.latest("pk").pk
        request_id = uuid4()
        response = self.review(request_id, previous)
        self.assertEqual(response.status_code, 200, response.content)
        retry = self.review(request_id, previous)
        self.assertTrue(retry.json()["already_queued"])
        self.assertEqual(response.json()["job_id"], retry.json()["job_id"])
        self.assertEqual(CoordinateActivity.objects.filter(event="research_review_queued").count(), 1)
        self.assertEqual(CoordinateJob.objects.filter(status="queued").count(), 1)
        claim = self.claim()
        self.assertEqual(claim["job"]["id"], response.json()["job_id"])
        self.assertEqual(claim["messages"][-1]["role"], "system")
        self.assertIn(self.message.body, [m["body"] for m in claim["messages"]])

    def test_review_rejects_pending_deleted_or_changed_case_and_missing_public_inputs(self):
        self.assertEqual(self.review().status_code, 409)
        self.assertEqual(self.complete(self.claim(), browser_record()).status_code, 200)
        self.assertEqual(self.review(expected=self.message.pk).status_code, 409)
        self.case.deleted_at = timezone.now()
        self.case.save()
        self.assertEqual(self.review().status_code, 409)
        self.case.deleted_at = None
        self.case.save()
        self.message.deleted_at = timezone.now()
        self.message.save()
        self.assertEqual(self.review().status_code, 400)

    def test_review_requires_worker_auth_and_post(self):
        url = reverse("coordinate_worker_research_review", args=[self.case.pk])
        self.assertEqual(self.client.post(url, {}).status_code, 401)
        self.assertEqual(self.worker.get(url, HTTP_AUTHORIZATION="Bearer synthetic-browser-worker-secret").status_code, 405)
