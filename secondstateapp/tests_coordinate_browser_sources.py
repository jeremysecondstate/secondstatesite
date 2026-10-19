"""Browser evidence provenance and the existing public-worker compatibility boundary."""

import hashlib
import json
from datetime import timedelta
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .coordinate_shipping import validate_worker_artifacts
from .models import CoordinateActivity, CoordinateCase, CoordinateDraft, CoordinateJob, CoordinateMessage, CoordinateResearch


def browser_record(**changes):
    return {
        "source_url": "https://auction.example/lot/17",
        "final_url": "https://www.invaluable.com/auction-lot/example-17",
        "source_kind": "browser",
        "public_error": "Public page requires browser rendering.",
        "title": "Synthetic lot 17",
        "text": "Oil on canvas; framed dimensions 30 x 40 inches.",
        "fetched_at": timezone.now().isoformat(),
        "error": "",
        **changes,
    }


@override_settings(COORDINATE_DRAFT_WORKFLOW_ENABLED=True)
class BrowserSourceContractTests(SimpleTestCase):
    def validate(self, **changes):
        research, drafts = validate_worker_artifacts({"research": [browser_record(**changes)]})
        self.assertEqual(drafts, [])
        return research[0]

    def test_browser_fallback_preserves_public_failure_and_exact_original_url(self):
        source = "http://auction.example:80/lot/17?ref=staff&sort=asc"
        record = self.validate(source_url=source)
        self.assertEqual(record["source_url"], source)
        self.assertEqual(record["source_kind"], "browser")
        self.assertEqual(record["public_error"], "Public page requires browser rendering.")
        self.assertEqual(record["error"], "")
        self.assertTrue(timezone.is_aware(record["fetched_at"]))

    def test_browser_destination_accepts_original_host_www_equivalent_or_invaluable(self):
        for final in (
            "https://auction.example/lot/17/details",
            "https://www.auction.example/lot/17",
            "https://invaluable.com/auction-lot/example-17",
            "https://www.invaluable.com:443/auction-lot/example-17",
        ):
            with self.subTest(final=final):
                self.assertEqual(self.validate(final_url=final)["final_url"], final)

    def test_browser_destination_rejects_unrelated_or_deceptive_hosts(self):
        for final in (
            "https://unrelated.example/lot/17", "https://auction.example.attacker.test/lot/17",
            "https://invaluable.com.attacker.test/lot/17", "https://login.invaluable.com/",
            "https://www.www.invaluable.com/lot/17",
        ):
            with self.subTest(final=final), self.assertRaises(ValueError):
                self.validate(final_url=final)

    def test_browser_urls_reject_credentials_ports_ambiguous_whitespace_and_schemes(self):
        for field in ("source_url", "final_url"):
            for url in (
                "https://user:password@auction.example/lot/17",
                "https://@auction.example/lot/17", "https://auction.example:8443/lot/17",
                "javascript:alert(1)", "ftp://auction.example/lot/17",
                "https://auction.example\\@invaluable.com/lot/17",
                "https://auction.example/lot/1\n7", " https://auction.example/lot/17",
                "https://auction.example/lot/17 ",
            ):
                with self.subTest(field=field, url=url), self.assertRaises(ValueError):
                    self.validate(**{field: url})
        for error in ("", "Browser access failed"):
            with self.subTest(error=error), self.assertRaises(ValueError):
                self.validate(final_url="http://auction.example/lot/17", error=error, text="", title="")

    def test_success_requires_observed_final_url_text_and_public_failure(self):
        for changes in ({"final_url": ""}, {"text": " "}, {"public_error": ""}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.validate(**changes)

    def test_failure_is_saved_without_evidence_and_cannot_carry_success_text(self):
        record = self.validate(error="Browser session unavailable.", title="", text="", final_url="")
        self.assertEqual(record["error"], "Browser session unavailable.")
        self.assertEqual(record["text"], "")
        self.assertTrue(record["public_error"])
        for changes in ({"text": "Unverified evidence", "title": ""}, {"text": "", "title": "Unverified title"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.validate(error="Browser access failed.", **changes)

    def test_invalid_kinds_bounds_and_future_timestamp_are_rejected(self):
        for changes in (
            {"source_kind": "signed-in"}, {"source_kind": None}, {"source_kind": []},
            {"text": "x" * 6001}, {"public_error": "x" * 201}, {"error": "x" * 201},
            {"fetched_at": (timezone.now() + timedelta(minutes=6)).isoformat()},
            {"fetched_at": "2026-01-01T12:00:00"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.validate(**changes)
        with self.assertRaises(ValueError):
            validate_worker_artifacts({"research": [browser_record(source_url=f"https://auction.example/lot/{i}") for i in range(9)]})
        with self.assertRaises(ValueError):
            validate_worker_artifacts({"research": [browser_record(), browser_record()]})

    def test_legacy_public_clients_default_to_public_without_browser_requirements(self):
        record = browser_record(source_kind="public", public_error="", final_url="", text="")
        record.pop("source_kind")
        record.pop("public_error")
        cleaned, _ = validate_worker_artifacts({"research": [record]})
        self.assertEqual(cleaned[0]["source_kind"], "public")
        self.assertEqual(cleaned[0]["public_error"], "")
        with self.assertRaises(ValueError):
            self.validate(source_kind="public", public_error="A prior fetch failed")


@override_settings(
    COORDINATE_DRAFT_WORKFLOW_ENABLED=True,
    COORDINATE_WORKER_TOKEN="synthetic-browser-worker-secret",
    COORDINATE_SHIPPING_PLAYBOOK="Synthetic policy. Drafts only.",
    COORDINATE_PACKING_PLAYBOOK="Synthetic handling reference.",
)
class BrowserSourcePersistenceTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user("browser-evidence-staff", is_staff=True)
        self.client.force_login(self.staff)
        self.worker = Client(enforce_csrf_checks=True)
        self.case = CoordinateCase.objects.create(title="Synthetic lot research", created_by=self.staff)
        self.message = CoordinateMessage.objects.create(
            case=self.case, author=self.staff, role="staff", body="Check https://auction.example/lot/17",
            client_message_id=uuid4(),
        )
        self.job = CoordinateJob.objects.create(message=self.message)

    def worker_post(self, name, payload, job_id=None):
        return self.worker.post(
            reverse(name, args=[job_id] if job_id else []), json.dumps(payload), content_type="application/json",
            HTTP_AUTHORIZATION="Bearer synthetic-browser-worker-secret",
        )

    def claim(self):
        response = self.worker_post("coordinate_worker_claim", {"worker_id": "manual-codex"})
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def complete(self, claim, record, **changes):
        job = claim["job"]
        return self.worker_post("coordinate_worker_complete", {
            "claim_token": job["claim_token"], "case_id": job["case_id"], "message_id": job["message_id"],
            "worker_id": "manual-codex", "body": "Retrieved the lot details for review.", "research": [record], **changes,
        }, job_id=job["id"])

    def test_completion_persists_provenance_and_retries_without_duplicate_evidence(self):
        claim, record = self.claim(), browser_record()
        first = self.complete(claim, record)
        self.assertEqual(first.status_code, 200, first.content)
        retry = self.complete(claim, record)
        self.assertEqual(retry.status_code, 200)
        self.assertTrue(retry.json()["already_completed"])
        self.assertEqual(first.json()["reply_id"], retry.json()["reply_id"])
        saved = CoordinateResearch.objects.get()
        self.assertEqual(saved.source_kind, "browser")
        self.assertEqual(saved.public_error, record["public_error"])
        self.assertEqual(saved.source_url, record["source_url"])
        self.assertEqual(saved.final_url, record["final_url"])
        self.assertEqual(CoordinateActivity.objects.filter(event="research_and_drafts_saved").count(), 1)
        self.assertEqual(CoordinateMessage.objects.filter(in_reply_to=self.message).count(), 1)
        changed = {**record, "public_error": "Different public failure"}
        self.assertEqual(self.complete(claim, changed).status_code, 409)
        self.assertEqual(CoordinateResearch.objects.get().public_error, record["public_error"])

        state = self.client.get(reverse("coordinate_state"), {"case": str(self.case.pk)}).json()
        visible = state["coordination"]["research"][0]
        self.assertEqual(visible["source_kind"], "browser")
        self.assertEqual(visible["public_error"], record["public_error"])
        followup = CoordinateMessage.objects.create(case=self.case, role="staff", body="Continue with these source notes.")
        CoordinateJob.objects.create(message=followup)
        next_claim = self.claim()
        self.assertEqual(next_claim["research"][0], visible)
        self.assertEqual(next_claim["coordination"]["research"][0], visible)

    def test_old_public_payload_is_persisted_and_labelled_public(self):
        record = browser_record()
        record.pop("source_kind")
        record.pop("public_error")
        self.assertEqual(self.complete(self.claim(), record).status_code, 200)
        saved = CoordinateResearch.objects.get()
        self.assertEqual(saved.source_kind, "public")
        self.assertEqual(saved.public_error, "")
        page = self.client.get(reverse("coordinate_case", args=[self.case.pk]))
        self.assertContains(page, "Public source")
        self.assertNotContains(page, "Browser source")

    def test_predeployment_public_completion_digest_can_replay_only_the_original_payload(self):
        claim, record = self.claim(), browser_record()
        record.pop("source_kind")
        record.pop("public_error")
        first = self.complete(claim, record)
        self.assertEqual(first.status_code, 200)
        research, drafts = validate_worker_artifacts({"research": [record]})
        legacy_research = [{key: value for key, value in item.items() if key not in ("source_kind", "public_error")}
                           for item in research]
        legacy_digest = hashlib.sha256(json.dumps({
            "body": "Retrieved the lot details for review.", "artifacts": (legacy_research, drafts),
        }, sort_keys=True, default=str).encode()).hexdigest()
        CoordinateJob.objects.filter(pk=self.job.pk).update(completion_digest=legacy_digest)

        retry = self.complete(claim, record)
        self.assertEqual(retry.status_code, 200, retry.content)
        self.assertTrue(retry.json()["already_completed"])
        self.assertEqual(retry.json()["reply_id"], first.json()["reply_id"])
        self.assertEqual(CoordinateResearch.objects.count(), 1)
        self.assertEqual(CoordinateMessage.objects.filter(in_reply_to=self.message).count(), 1)
        for changes in (
            {"source_kind": "public"}, {"public_error": ""},
            {"source_kind": "browser", "public_error": "Public access failed"},
            {"text": "Changed evidence"},
        ):
            with self.subTest(changes=changes):
                self.assertEqual(self.complete(claim, {**record, **changes}).status_code, 409)
        self.assertEqual(self.complete(claim, record, body="Changed reply").status_code, 409)
        self.assertEqual(CoordinateResearch.objects.get().text, record["text"])

    def test_failed_browser_evidence_is_rejected_without_completing_the_job(self):
        response = self.complete(self.claim(), browser_record(error="Browser page unavailable."))
        self.assertEqual(response.status_code, 400)
        self.assertFalse(CoordinateResearch.objects.exists())
        self.assertFalse(CoordinateMessage.objects.filter(in_reply_to=self.message).exists())
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, "processing")

    def test_successful_browser_evidence_supports_a_draft_despite_public_failure(self):
        response = self.complete(self.claim(), browser_record(text="For collection contact packer@example.test."), drafts=[{
            "recipient": "packer@example.test", "subject": "Collection details",
            "body": "Please share the collection details.", "purpose": "Staff review",
        }])
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(CoordinateDraft.objects.get().status, "draft")
        self.assertFalse(CoordinateActivity.objects.get(event="research_and_drafts_saved").details["sent"])

    def test_failed_browser_record_persists_without_exposing_success_evidence(self):
        record = browser_record(error='<script>alert("failure")</script>', text="", title="", final_url="")
        self.assertEqual(self.complete(self.claim(), record).status_code, 200)
        saved = CoordinateResearch.objects.get()
        self.assertEqual(saved.error, record["error"])
        self.assertEqual(saved.text, "")
        self.assertEqual(saved.public_error, record["public_error"])
        page = self.client.get(reverse("coordinate_case", args=[self.case.pk]))
        self.assertContains(page, "Browser source")
        self.assertContains(page, "&lt;script&gt;alert(&quot;failure&quot;)&lt;/script&gt;")
        self.assertNotContains(page, '<script>alert("failure")</script>')

    def test_source_panel_escapes_title_excerpt_failure_and_urls(self):
        record = browser_record(
            source_url="https://auction.example/lot/17?ref=staff&sort=asc",
            final_url="https://www.invaluable.com/auction-lot/example-17?ref=staff&sort=asc",
            title='<img src=x onerror="alert(1)">',
            text='<script>alert("excerpt")</script>\nSecond line.',
            public_error='<img src=x onerror="alert(2)">',
        )
        self.assertEqual(self.complete(self.claim(), record).status_code, 200)
        page = self.client.get(reverse("coordinate_case", args=[self.case.pk]))
        self.assertContains(page, "Browser source")
        self.assertContains(page, "Viewed page")
        self.assertContains(page, 'href="https://auction.example/lot/17?ref=staff&amp;sort=asc"')
        self.assertContains(page, 'href="https://www.invaluable.com/auction-lot/example-17?ref=staff&amp;sort=asc"')
        self.assertContains(page, "&lt;script&gt;alert(&quot;excerpt&quot;)&lt;/script&gt;<br>Second line.")
        self.assertContains(page, "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;")
        self.assertContains(page, "Public access: &lt;img src=x onerror=&quot;alert(2)&quot;&gt;")
        self.assertNotContains(page, '<script>alert("excerpt")</script>')
        self.assertNotContains(page, "<img src=x")
