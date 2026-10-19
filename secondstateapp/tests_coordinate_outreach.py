"""Initial inquiry authorization, freshness, routing and once-only delivery."""
from copy import deepcopy
from datetime import timedelta
import json
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .coordinate_brief import save_brief
from .coordinate_outreach import MAX_PACKET_CHARS, outreach_state, prepare_next, quote_packet
from . import coordinate_mail as mail
from . import tests_coordinate_brief as brief_fixtures
from .models import (CoordinateBrief, CoordinateCase, CoordinateDraft, CoordinateJob, CoordinateMailDelivery,
    CoordinateMailMessage, CoordinateMailThread, CoordinateMessage, CoordinateOutreachPolicy, CoordinatePlan, CoordinateQuoteInquiry, CoordinateResearch)


@override_settings(COORDINATE_DRAFT_WORKFLOW_ENABLED=True, COORDINATE_EMAIL_SENDING_ENABLED=True,
    COORDINATE_LIVE_QUOTE_OUTREACH_ENABLED=False, COORDINATE_WORKER_TOKEN="synthetic-outreach-secret",
    AUCTION_EMAIL_SENDER="jeremy@secondstate.art", GOOGLE_GMAIL_CLIENT_ID="synthetic-client",
    GOOGLE_GMAIL_CLIENT_SECRET="synthetic-secret", GOOGLE_GMAIL_REFRESH_TOKEN="synthetic-refresh")
class InitialQuoteOutreachTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user("outreach-staff", is_staff=True)
        self.client.force_login(self.staff)
        self.worker = Client(enforce_csrf_checks=True)
        self.case = CoordinateCase.objects.create(title="Synthetic quote preparation", created_by=self.staff)
        self.origin = CoordinateMessage.objects.create(case=self.case, role="staff", author=self.staff,
            body="Review https://auction.example/lot/17 for collection.")
        self.job = CoordinateJob.objects.create(message=self.origin, status="completed")
        self.reply = CoordinateMessage.objects.create(case=self.case, role="assistant", in_reply_to=self.origin, body="Evidence saved.")
        self.plan = CoordinatePlan.objects.create(case=self.case, destination="duarte", handling="Keep original mats")
        self.source = "https://auction.example/lot/17"
        self.listing = CoordinateResearch.objects.create(case=self.case, job=self.job,
            source_url=self.source, final_url=self.source, source_kind="public_browser", fetched_at=timezone.now(),
            text="Synthetic Artist. Synthetic Print. Synthetic Auction, lot 17. Artwork 10 x 12 inches. Framed 15 x 17 inches. Scottsdale, Arizona, USA.",
            identity_match={"status": "exact", "artist": "Synthetic Artist", "title": "Synthetic Print",
                "auction_house": "Synthetic Auction", "auction_date": "2026-10-17", "lot_number": "17"})
        self.providers = []
        self.contact_sources = []
        for index in range(4):
            ref = f"https://provider{index}.example/services"
            provider = {"name": f"Provider {index}", "email": f"provider{index}@example.test", "service_type": "full_service",
                "published_capability": f"Provider {index}: we pack and transport artwork.", "contact_quote": f"Provider {index}: provider{index}@example.test",
                "source_refs": [ref]}
            self.providers.append(provider)
            self.contact_sources.append(CoordinateResearch.objects.create(case=self.case, job=self.job,
                source_url=self.source, final_url=ref, source_kind="public_browser", fetched_at=timezone.now(),
                text=provider["contact_quote"] + "\n" + provider["published_capability"], identity_match={"status": "context"}))
        self.brief = brief_fixtures.fixture_brief(self.source, shipping={
            "working_currency": {"code": "USD", "basis": "inferred", "note": "US collection context.", "source_refs": [self.source]},
            "quote_readiness": {"status": "conditional_ready", "note": "Initial quotes can use listed dimensions."},
            "actions": [], "providers": self.providers, "site_checks": []})
        self.brief["lots"][0].update(artist="Synthetic Artist", title="Synthetic Print", lot_number="17",
            auction_house="Synthetic Auction", auction_date="2026-10-17", dimensions="10 x 12 inches",
            framed_dimensions="15 x 17 inches", pickup_location="Scottsdale, Arizona")
        save_brief(self.job, self.brief)

    def configure(self, **changes):
        return self.client.post(reverse("coordinate_outreach_settings", args=[self.case.pk]),
            {"mode": "test", "destination": "duarte", "destination_address": "123 Synthetic Avenue, Duarte CA 91010", **changes},
            HTTP_ACCEPT="application/json")

    def dispatch(self, request_id=None):
        return self.worker.post(reverse("coordinate_outreach_dispatch"),
            json.dumps({"worker_id": "manual-codex", "request_id": str(request_id or uuid4())}),
            content_type="application/json", HTTP_AUTHORIZATION="Bearer synthetic-outreach-secret")

    def test_configuration_requires_staff_csrf_context_and_complete_destination(self):
        url = reverse("coordinate_outreach_settings", args=[self.case.pk])
        protected = Client(enforce_csrf_checks=True)
        protected.force_login(self.staff)
        self.assertEqual(protected.post(url, {}).status_code, 403)
        for changes in ({"mode": "live"}, {"mode": "invalid"}, {"destination": "undecided"},
                        {"destination_address": "short"}, {"destination_address": "x" * 601},
                        {"mode": "off", "destination_address": "x" * 601}):
            self.assertEqual(self.configure(**changes).status_code, 400)
        self.assertFalse(CoordinateOutreachPolicy.objects.exists())
        self.assertEqual(self.configure().status_code, 200)
        self.assertEqual(CoordinateOutreachPolicy.objects.get().mode, "test")
        self.client.logout()
        self.assertEqual(self.client.post(url, {}).status_code, 302)

    @patch("secondstateapp.coordinate_mail.send_snapshot")
    def test_every_test_inquiry_uses_only_jeremy_and_persisted_request_is_idempotent(self, transport):
        self.assertEqual(self.configure().status_code, 200)
        seen = []
        def sent(delivery):
            self.assertEqual(delivery.recipient, "jeremy@secondstate.art")
            self.assertEqual(CoordinateMailDelivery.objects.get(pk=delivery.pk).status, "sending")
            self.assertIn("no provider has been contacted", delivery.body)
            self.assertIn("non-binding quote request only", delivery.body)
            self.assertIn("original mats retained", delivery.body)
            self.assertIn("artwork dimensions as listed: 10 x 12 inches", delivery.body)
            self.assertIn("framed dimensions as listed: 15 x 17 inches", delivery.body)
            self.assertIn("working currency assumption", delivery.body)
            seen.append(delivery.approval_snapshot["intended_recipient"])
            return {"id": "outbound-" + str(len(seen)), "threadId": "thread-" + str(len(seen))}
        transport.side_effect = sent
        for _ in range(3):
            token = uuid4()
            response = self.dispatch(token)
            self.assertEqual(response.status_code, 200, response.content)
            self.assertEqual(response.json()["status"], "sent")
            self.assertEqual(response.json()["actual_recipient"], "jeremy@secondstate.art")
            self.assertEqual(self.dispatch(token).json()["delivery_id"], response.json()["delivery_id"])
        self.assertEqual(self.dispatch().json()["status"], "outreach_idle")
        self.assertEqual(len(set(seen)), 3)
        self.assertEqual(transport.call_count, 3)
        self.assertEqual(CoordinateQuoteInquiry.objects.count(), 3)
        self.assertEqual(CoordinateMailMessage.objects.count(), 3)
        self.assertTrue(all(item.to_emails == ["jeremy@secondstate.art"] for item in CoordinateMailMessage.objects.all()))
        state = mail.draft_mail_state(CoordinateDraft.objects.first())
        self.assertTrue(state["quote_test"])
        self.assertEqual(state["actual_recipient"], "jeremy@secondstate.art")
        self.assertIn(state["intended_recipient"], seen)

    @patch("secondstateapp.coordinate_mail.send_snapshot", side_effect=TimeoutError("private body synthetic-secret"))
    def test_unknown_delivery_counts_against_cap_and_never_retries_transport(self, transport):
        self.configure()
        token = uuid4()
        response = self.dispatch(token)
        self.assertEqual(response.json()["status"], "unknown")
        self.assertNotContains(response, "synthetic-secret")
        self.assertEqual(self.dispatch(token).json()["status"], "unknown")
        transport.assert_called_once()
        self.assertEqual(CoordinateQuoteInquiry.objects.count(), 1)
        self.assertEqual(CoordinateMailDelivery.objects.count(), 1)

    def test_no_permission_or_disabled_email_or_live_gate_cannot_prepare(self):
        self.assertIsNone(prepare_next("manual-codex", uuid4()))
        self.configure()
        with override_settings(COORDINATE_EMAIL_SENDING_ENABLED=False):
            self.assertIsNone(prepare_next("manual-codex", uuid4()))
        CoordinateOutreachPolicy.objects.update(mode="live")
        self.assertIsNone(prepare_next("manual-codex", uuid4()))
        self.assertFalse(CoordinateMailDelivery.objects.exists())

    def test_permission_change_invalidates_an_older_running_claim(self):
        running = CoordinateJob.objects.create(message=CoordinateMessage.objects.create(
            case=self.case, role="system", body="Refresh the case."), status="processing", claim_token=uuid4())
        self.assertEqual(self.configure().status_code, 200)
        running.refresh_from_db()
        self.assertEqual(running.status, "retry")
        self.assertIsNone(running.claim_token)

    def test_pilot_subjects_remain_provider_specific_at_the_header_length_limit(self):
        self.configure()
        policy = CoordinateOutreachPolicy.objects.get()
        brief = deepcopy(self.brief)
        brief["lots"][0]["auction_house"] = "A" * 200
        subjects = [quote_packet(brief, provider, policy)[0] for provider in self.providers]
        self.assertEqual(len(set(subjects)), 4)
        self.assertTrue(all(len(subject) <= 200 for subject in subjects))
        policy.case_id = uuid4()
        self.assertNotIn(quote_packet(brief, self.providers[0], policy)[0], subjects)

    @patch("secondstateapp.coordinate_outreach.quote_packet")
    def test_overlong_packet_and_invalid_headers_never_create_dispatch_intent(self, packet):
        self.configure()
        for value in (("Safe subject", "x" * (MAX_PACKET_CHARS + 1)), ("Subject\nBcc: another@example.test", "body")):
            packet.return_value = value
            self.assertIsNone(prepare_next("manual-codex", uuid4()))
        self.assertFalse(CoordinateMailDelivery.objects.exists())
        self.assertFalse(CoordinateQuoteInquiry.objects.exists())

    def test_brief_from_mail_anchor_keeps_the_original_staff_visibility_root(self):
        self.configure()
        thread = CoordinateMailThread.objects.create(case=self.case, originating_message=self.origin,
            provider_email="earlier@example.test", subject="Earlier correspondence", gmail_thread_id="earlier-thread")
        anchor = CoordinateMessage.objects.create(case=self.case, role="system", body="A private reply arrived.")
        CoordinateMailMessage.objects.create(thread=thread, message=anchor, direction="inbound", gmail_message_id="earlier-mail",
            from_email="earlier@example.test", to_emails=[mail.SENDER], body_text="Reply", received_at=timezone.now())
        next_job = CoordinateJob.objects.create(message=anchor, status="completed")
        save_brief(next_job, self.brief)
        delivery, send = prepare_next("manual-codex", uuid4())
        self.assertTrue(send)
        self.assertEqual(delivery.approval_snapshot["originating_message_id"], self.origin.pk)

    def test_pending_retry_or_newer_unprocessed_staff_context_prevents_dispatch(self):
        self.configure()
        later = CoordinateMessage.objects.create(case=self.case, role="staff", body="Change the delivery request.")
        self.assertIsNone(prepare_next("manual-codex", uuid4()))
        future_job = CoordinateJob.objects.create(message=later, status="retry")
        for status in ("queued", "processing", "retry", "failed", "completed", "cancelled"):
            future_job.status = status
            future_job.save(update_fields=["status"])
            self.assertIsNone(prepare_next("manual-codex", uuid4()))
        CoordinateMessage.objects.filter(pk=later.pk).update(created_at=timezone.now() + timedelta(hours=1))
        self.assertIsNone(prepare_next("manual-codex", uuid4()))
        self.assertFalse(CoordinateMailDelivery.objects.exists())

    def test_deleted_origin_reply_and_changed_destination_stop_inquiries(self):
        self.configure()
        for hidden in (self.origin, self.reply):
            hidden.deleted_at = timezone.now()
            hidden.save(update_fields=["deleted_at"])
            self.assertIsNone(prepare_next("manual-codex", uuid4()))
            self.assertEqual(outreach_state(self.case)["mode"], "off")
            hidden.deleted_at = None
            hidden.save(update_fields=["deleted_at"])
        self.plan.destination = "mar_vista"
        self.plan.save()
        self.assertIsNone(prepare_next("manual-codex", uuid4()))
        self.plan.destination, self.plan.stage = "duarte", "received"
        self.plan.save()
        self.assertIsNone(prepare_next("manual-codex", uuid4()))
        self.assertFalse(CoordinateMailDelivery.objects.exists())

    def test_contact_freshness_requires_exact_public_wording_not_just_same_email(self):
        self.configure()
        original_time = self.contact_sources[0].fetched_at
        for change in ({"fetched_at": timezone.now() - timedelta(hours=25)}, {"fetched_at": timezone.now() + timedelta(minutes=1)},
                       {"source_kind": "authenticated_browser"}, {"source_kind": "search_only"}, {"error": "Unavailable"}):
            with self.subTest(change=change):
                CoordinateResearch.objects.filter(pk__in=[source.pk for source in self.contact_sources]).update(**change)
                self.assertIsNone(prepare_next("manual-codex", uuid4()))
                CoordinateResearch.objects.filter(pk__in=[source.pk for source in self.contact_sources]).update(
                    fetched_at=original_time, source_kind="public_browser", error="")
        # Keep old validated contact evidence; a fresh footer containing the same
        # address does not refresh the provider-name/contact relationship.
        CoordinateResearch.objects.filter(pk__in=[source.pk for source in self.contact_sources]).update(fetched_at=timezone.now() - timedelta(hours=25))
        for source, provider in zip(self.contact_sources, self.providers):
            # Save it on the same claimed source job to stay inside the cutoff.
            CoordinateResearch.objects.create(case=self.case, job=self.job, source_url=self.source, final_url=source.final_url,
                source_kind="public_fetch", fetched_at=timezone.now(), identity_match={"status": "context"},
                text="General unrelated footer: " + provider["email"])
        self.assertIsNone(prepare_next("manual-codex", uuid4()))
        self.assertFalse(CoordinateMailDelivery.objects.exists())

    def test_missing_dimensions_and_nonready_brief_do_not_prepare(self):
        self.configure()
        saved = CoordinateBrief.objects.get(job=self.job)
        original = deepcopy(saved.payload)
        for status in ("not_assessed", "needs_destination", "needs_public_research"):
            saved.payload = deepcopy(original)
            saved.payload["shipping"]["quote_readiness"]["status"] = status
            saved.save()
            self.assertIsNone(prepare_next("manual-codex", uuid4()))
        saved.payload = deepcopy(original)
        saved.payload["lots"][0].update(dimensions="", framed_dimensions="")
        saved.save()
        self.assertIsNone(prepare_next("manual-codex", uuid4()))

    @patch("secondstateapp.coordinate_mail.send_snapshot")
    def test_cutoff_and_deleted_retry_context_do_not_leak_or_resend(self, transport):
        self.configure()
        token = uuid4()
        delivery, send = prepare_next("manual-codex", token)
        self.assertTrue(send)
        before = outreach_state(self.case, self.origin.pk - 1)
        self.assertEqual(before["mode"], "off")
        self.assertEqual(before["inquiries"], [])
        self.assertEqual(len(outreach_state(self.case)["inquiries"]), 1)
        self.origin.deleted_at = timezone.now()
        self.origin.save()
        self.assertEqual(self.dispatch(token).status_code, 409)
        self.assertEqual(outreach_state(self.case)["inquiries"], [])
        transport.assert_not_called()

    @patch("secondstateapp.coordinate_mail.send_snapshot")
    def test_dispatch_identifiers_cannot_reuse_manual_delivery(self, transport):
        self.configure()
        token = uuid4()
        delivery, _ = prepare_next("manual-codex", token)
        CoordinateMailDelivery.objects.filter(pk=delivery.pk).update(approval_snapshot={"authorization": "manual"})
        self.assertEqual(self.dispatch(token).status_code, 409)
        transport.assert_not_called()
