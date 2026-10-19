"""Draft-only shipping workflow contracts with synthetic staff and source data."""

import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .coordinate_shipping import quote_paused
from .models import (
    CoordinateActivity, CoordinateCase, CoordinateDraft, CoordinateJob,
    CoordinateMessage, CoordinatePlan, CoordinateQuote, CoordinateResearch,
)


@override_settings(
    COORDINATE_DRAFT_WORKFLOW_ENABLED=True,
    COORDINATE_PRICE_REVIEWER_USERNAME="jeremy",
    COORDINATE_WORKER_TOKEN="synthetic-shipping-worker-secret",
    COORDINATE_SHIPPING_PLAYBOOK="Synthetic shipping policy. Drafts only.\n",
    COORDINATE_PACKING_PLAYBOOK="Synthetic packing reference. Ask before handling.\n",
)
class CoordinateShippingTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user("shipping-staff", is_staff=True)
        self.jeremy = get_user_model().objects.create_user("jeremy", is_staff=True)
        self.ordinary = get_user_model().objects.create_user("shipping-member")
        self.client.force_login(self.staff)
        self.worker = Client(enforce_csrf_checks=True)
        self.case, self.message = self.create_case()

    def create_case(self, body="Gather a quote from packer@example.test", title="Synthetic shipment"):
        token = uuid4()
        response = self.client.post(reverse("coordinate_create"), {
            "title": title, "body": body, "client_message_id": str(token),
        })
        self.assertEqual(response.status_code, 302)
        message = CoordinateMessage.objects.get(client_message_id=token)
        return message.case, message

    def post(self, name, data=None, *, case=None, record=None):
        args = [str((case or self.case).pk)]
        if record:
            args.append(str(record.pk))
        return self.client.post(reverse(name, args=args), data or {}, HTTP_ACCEPT="application/json")

    def plan(self, **changes):
        response = self.post("coordinate_plan", {
            "stage": "gathering", "destination": "duarte", "handling": "Synthetic approved handling",
            "pickup_deadline": "", "notes": "Synthetic plan notes", **changes,
        })
        self.assertEqual(response.status_code, 200, response.content)
        return CoordinatePlan.objects.get(case=self.case)

    def quote(self, amount="100", email="packer@example.test", *, case=None):
        case = case or self.case
        response = self.post("coordinate_quote_add", {
            "provider_name": "Synthetic Packer", "provider_email": email, "amount": amount, "currency": "USD",
        }, case=case)
        self.assertEqual(response.status_code, 200, response.content)
        return CoordinateQuote.objects.filter(case=case).latest("created_at")

    def draft(self, *, quote=None, case=None):
        case = case or self.case
        response = self.post("coordinate_draft_add", {
            "recipient": quote.provider_email if quote else "packer@example.test",
            "subject": "synthetic packing request", "body": "hi! please share the pickup details.",
            "quote_id": str(quote.pk) if quote else "", "purpose": "Synthetic request",
        }, case=case)
        self.assertEqual(response.status_code, 200, response.content)
        return CoordinateDraft.objects.filter(case=case).latest("created_at")

    def worker_post(self, name, payload, *, job_id=None):
        return self.worker.post(
            reverse(name, args=[job_id] if job_id else []), json.dumps(payload), content_type="application/json",
            HTTP_AUTHORIZATION="Bearer synthetic-shipping-worker-secret",
        )

    def claim(self):
        response = self.worker_post("coordinate_worker_claim", {"worker_id": "manual-codex"})
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def complete(self, claim, **changes):
        job = claim["job"]
        return self.worker_post("coordinate_worker_complete", {
            "claim_token": job["claim_token"], "case_id": job["case_id"], "message_id": job["message_id"],
            "worker_id": "manual-codex", "body": "Saved a draft for staff review. Nothing has been sent.", **changes,
        }, job_id=job["id"])

    def artifacts(self, recipient="packer@example.test"):
        return {
            "research": [{"source_url": "https://example.test/auction/lot-17", "final_url": "https://example.test/auction/lot-17",
                          "title": "Synthetic lot page", "text": "Synthetic source description.",
                          "fetched_at": timezone.now().isoformat(), "error": ""}],
            "drafts": [{"recipient": recipient, "subject": "synthetic packing request",
                        "body": "hi! could you share a packing quote?", "purpose": "Request information"}],
        }

    def state(self):
        response = self.client.get(reverse("coordinate_state"), {"case": str(self.case.pk)})
        self.assertEqual(response.status_code, 200)
        return response.json()

    def actions(self, quote, draft):
        return [
            ("coordinate_plan", None, {"stage": "gathering", "destination": "duarte", "handling": "Synthetic handling"}),
            ("coordinate_quote_add", None, {"provider_name": "Other", "provider_email": "other@example.test", "amount": "20"}),
            ("coordinate_quote_update", quote, {"latest_amount": "150"}),
            ("coordinate_quote_accept", quote, {}),
            ("coordinate_quote_resolve", quote, {"note": "Synthetic review"}),
            ("coordinate_draft_add", None, {"recipient": "packer@example.test", "subject": "hello", "body": "test"}),
            ("coordinate_draft_update", draft, {"recipient": "packer@example.test", "subject": "hello", "body": "test"}),
            ("coordinate_draft_review", draft, {}),
        ]

    def test_shipping_actions_require_active_staff_post_and_csrf(self):
        quote, draft = self.quote(), self.draft()
        inactive = get_user_model().objects.create_user("shipping-inactive", is_staff=True, is_active=False)
        for user in (None, self.ordinary, inactive):
            browser = Client()
            if user:
                browser.force_login(user)
            for name, record, data in self.actions(quote, draft):
                args = [self.case.pk] + ([record.pk] if record else [])
                with self.subTest(name=name, user=user):
                    self.assertIn(browser.post(reverse(name, args=args), data).status_code, (302, 403))
        protected = Client(enforce_csrf_checks=True)
        protected.force_login(self.staff)
        for name, record, data in self.actions(quote, draft):
            args = [self.case.pk] + ([record.pk] if record else [])
            url = reverse(name, args=args)
            self.assertEqual(self.client.get(url).status_code, 405)
            self.assertEqual(protected.post(url, data, HTTP_AUTHORIZATION="Bearer synthetic-shipping-worker-secret").status_code, 403)
        self.assertEqual(CoordinateQuote.objects.count(), 1)
        self.assertEqual(CoordinateDraft.objects.count(), 1)

    def test_shipping_records_cannot_be_addressed_through_another_case(self):
        quote, draft = self.quote(), self.draft()
        other, _ = self.create_case(title="Other synthetic shipment")
        for name, record, data in self.actions(quote, draft):
            if not record or name == "coordinate_quote_resolve":
                continue
            with self.subTest(name=name):
                self.assertEqual(self.post(name, data, case=other, record=record).status_code, 404)
        self.client.force_login(self.jeremy)
        self.assertEqual(self.post("coordinate_quote_resolve", {"note": "review"}, case=other, record=quote).status_code, 404)
        self.assertEqual(self.post("coordinate_draft_add", {
            "recipient": "packer@example.test", "subject": "test", "body": "test", "quote_id": str(quote.pk),
        }, case=other).status_code, 404)

    def test_trashed_case_rejects_every_shipping_write_and_hides_workspace(self):
        quote, draft = self.quote(), self.draft()
        self.assertEqual(self.post("coordinate_delete_case").status_code, 200)
        for name, record, data in self.actions(quote, draft):
            with self.subTest(name=name):
                self.assertEqual(self.post(name, data, record=record).status_code, 409)
        self.assertIsNone(self.state()["coordination"])
        self.assertIsNone(self.claim()["job"])

    @override_settings(COORDINATE_DRAFT_WORKFLOW_ENABLED=False)
    def test_disabled_workspace_refuses_actions_and_worker_artifacts(self):
        response = self.post("coordinate_quote_add", {
            "provider_name": "Synthetic", "provider_email": "packer@example.test", "amount": "100",
        })
        self.assertEqual(response.status_code, 503)
        claim = self.claim()
        self.assertTrue(claim["test_mode"])
        self.assertEqual(self.complete(claim, **self.artifacts()).status_code, 400)
        self.assertFalse(CoordinateResearch.objects.exists())

    def test_quotes_reject_invalid_amounts_and_non_usd_currency(self):
        for amount in ("-1", "1.001", "NaN", "Infinity", "999999999.00", "1e309", "USD 10", ""):
            with self.subTest(amount=amount):
                response = self.post("coordinate_quote_add", {
                    "provider_name": "Synthetic", "provider_email": "packer@example.test", "amount": amount,
                })
                self.assertEqual(response.status_code, 400, response.content)
        self.assertFalse(CoordinateQuote.objects.exists())
        self.assertEqual(self.post("coordinate_quote_add", {
            "provider_name": "Synthetic", "provider_email": "packer@example.test", "amount": "100", "currency": "EUR",
        }).status_code, 400)
        quote = self.quote("0.01")
        self.assertEqual(quote.amount, Decimal("0.01"))
        self.assertEqual(self.post("coordinate_quote_update", {"latest_amount": "NaN"}, record=quote).status_code, 400)
        quote.refresh_from_db()
        self.assertEqual(quote.latest_amount, Decimal("0.01"))

    @patch("secondstateapp.auction_email.send_auction_email")
    @patch("django.core.mail.send_mail")
    def test_cumulative_price_pause_requires_jeremy_review_and_never_sends(self, send_mail, auction_send):
        self.plan()
        quote = self.quote("100")
        self.assertEqual(self.post("coordinate_quote_accept", record=quote).status_code, 200)
        draft = self.draft(quote=quote)
        self.assertEqual(self.post("coordinate_quote_update", {"latest_amount": "130"}, record=quote).status_code, 200)
        quote.refresh_from_db()
        self.assertFalse(quote_paused(quote))
        self.assertEqual(self.post("coordinate_draft_review", record=draft).status_code, 200)
        response = self.post("coordinate_quote_update", {"latest_amount": "150"}, record=quote)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["coordination"]["quotes"][0]["paused"])
        self.assertTrue(response.json()["coordination"]["drafts"][0]["blocked"])
        draft.refresh_from_db()
        self.assertEqual(draft.status, "draft")
        self.assertEqual(self.post("coordinate_draft_review", record=draft).status_code, 400)
        self.assertEqual(self.post("coordinate_quote_resolve", {"note": "Other staff reviewed"}, record=quote).status_code, 400)
        self.client.force_login(self.jeremy)
        self.assertEqual(self.post("coordinate_draft_review", record=draft).status_code, 400)
        self.assertEqual(self.post("coordinate_quote_resolve", {"note": "I reviewed the cumulative increase."}, record=quote).status_code, 200)
        self.assertEqual(self.post("coordinate_draft_review", record=draft).status_code, 200)
        quote.refresh_from_db()
        self.assertEqual(quote.accepted_amount, Decimal("100"))
        self.assertEqual(quote.increase_reviewed_amount, Decimal("150"))
        self.assertFalse(quote_paused(quote))
        events = list(CoordinateActivity.objects.filter(event__in=["shipping_quote_selected", "provider_thread_paused", "provider_increase_reviewed"]))
        self.assertTrue(events)
        self.assertTrue(all(event.details["payment_authorized"] is False for event in events))
        self.assertFalse(CoordinateActivity.objects.get(event="email_draft_added").details["sent"])
        self.assertTrue(all(event.details["sent"] is False for event in CoordinateActivity.objects.filter(event="email_draft_reviewed")))
        send_mail.assert_not_called()
        auction_send.assert_not_called()

    @override_settings(COORDINATE_PRICE_REVIEWER_USERNAME="")
    def test_missing_designated_price_reviewer_fails_closed(self):
        self.plan()
        quote = self.quote()
        self.post("coordinate_quote_accept", record=quote)
        self.post("coordinate_quote_update", {"latest_amount": "150"}, record=quote)
        self.client.force_login(self.jeremy)
        self.assertEqual(self.post("coordinate_quote_resolve", {"note": "Review"}, record=quote).status_code, 400)
        quote.refresh_from_db()
        self.assertTrue(quote_paused(quote))

    def test_provider_reselection_and_handling_changes_do_not_reset_accepted_baseline(self):
        self.plan()
        original = self.quote("100")
        other = self.quote("80", "other@example.test")
        self.post("coordinate_quote_accept", record=original)
        self.post("coordinate_quote_update", {"latest_amount": "150"}, record=original)
        self.post("coordinate_quote_accept", record=other)
        self.post("coordinate_quote_accept", record=original)
        original.refresh_from_db()
        self.assertEqual(original.accepted_amount, Decimal("100"))
        self.assertTrue(quote_paused(original))
        self.plan(handling="New synthetic handling")
        original.refresh_from_db()
        self.assertFalse(original.accepted)
        self.post("coordinate_quote_accept", record=original)
        original.refresh_from_db()
        self.assertEqual(original.accepted_amount, Decimal("100"))
        self.assertTrue(quote_paused(original))
        self.assertEqual(CoordinateQuote.objects.filter(case=self.case, accepted=True).count(), 1)

    def test_selecting_quote_requires_destination_and_handling(self):
        quote = self.quote()
        self.assertEqual(self.post("coordinate_quote_accept", record=quote).status_code, 400)
        self.plan(destination="undecided")
        self.assertEqual(self.post("coordinate_quote_accept", record=quote).status_code, 400)
        self.plan(handling="")
        self.assertEqual(self.post("coordinate_quote_accept", record=quote).status_code, 400)

    def test_plan_update_invalidates_inflight_claim_and_refreshes_worker_context(self):
        stale = self.claim()
        self.assertFalse(stale["test_mode"])
        self.assertTrue(stale["draft_only"])
        self.plan(notes="A new staff decision")
        self.assertEqual(self.complete(stale).status_code, 409)
        fresh = self.claim()
        self.assertNotEqual(stale["job"]["claim_token"], fresh["job"]["claim_token"])
        self.assertEqual(fresh["coordination"]["plan"]["notes"], "A new staff decision")
        self.assertEqual(self.complete(fresh).status_code, 200)

    def test_deadline_check_enqueues_once_without_another_staff_message(self):
        self.assertEqual(self.complete(self.claim()).status_code, 200)
        deadline = (timezone.now() + timedelta(hours=6)).isoformat()
        self.plan(pickup_deadline=deadline)
        claim = self.claim()
        reminder = CoordinateMessage.objects.get(pk=claim["job"]["message_id"])
        self.assertEqual(reminder.role, "system")
        self.assertEqual(CoordinateMessage.objects.filter(role="staff").count(), 1)
        self.assertIn(reminder.pk, [row["id"] for row in claim["messages"]])
        self.assertEqual(self.complete(claim).status_code, 200)
        self.assertIsNone(self.claim()["job"])
        self.plan(pickup_deadline=deadline)
        self.assertIsNone(self.claim()["job"])
        self.assertEqual(CoordinateActivity.objects.filter(event="pickup_deadline_review_queued").count(), 1)
        self.assertEqual(CoordinateMessage.objects.filter(role="system").count(), 1)

    def test_completed_or_trashed_cases_do_not_enqueue_deadline_checks(self):
        self.assertEqual(self.complete(self.claim()).status_code, 200)
        self.plan(stage="received", pickup_deadline=(timezone.now() + timedelta(hours=2)).isoformat())
        self.assertIsNone(self.claim()["job"])
        self.plan(stage="gathering", pickup_deadline=(timezone.now() + timedelta(hours=2)).isoformat())
        self.post("coordinate_delete_case")
        self.assertIsNone(self.claim()["job"])
        self.assertFalse(CoordinateMessage.objects.filter(role="system").exists())

    def test_worker_completion_saves_research_and_drafts_once_with_full_payload_idempotence(self):
        claim = self.claim()
        artifacts = self.artifacts()
        first = self.complete(claim, **artifacts)
        self.assertEqual(first.status_code, 200, first.content)
        retry = self.complete(claim, **artifacts)
        self.assertEqual(retry.status_code, 200)
        self.assertTrue(retry.json()["already_completed"])
        self.assertEqual(first.json()["reply_id"], retry.json()["reply_id"])
        self.assertEqual(CoordinateResearch.objects.count(), 1)
        self.assertEqual(CoordinateDraft.objects.count(), 1)
        self.assertEqual(CoordinateMessage.objects.filter(in_reply_to=self.message).count(), 1)
        self.assertEqual(CoordinateActivity.objects.filter(event="research_and_drafts_saved").count(), 1)
        artifacts["drafts"][0]["body"] = "changed artifact body"
        self.assertEqual(self.complete(claim, **artifacts).status_code, 409)
        self.assertEqual(CoordinateDraft.objects.get().body, "hi! could you share a packing quote?")

    def test_unsupported_worker_recipient_rolls_back_reply_research_and_completion(self):
        claim = self.claim()
        response = self.complete(claim, **self.artifacts("unsupported@example.test"))
        self.assertEqual(response.status_code, 400, response.content)
        job = CoordinateJob.objects.get(pk=claim["job"]["id"])
        self.assertEqual(job.status, "processing")
        self.assertIsNone(job.completed_at)
        self.assertEqual(job.completion_digest, "")
        self.assertFalse(CoordinateDraft.objects.exists())
        self.assertFalse(CoordinateResearch.objects.exists())
        self.assertFalse(CoordinateMessage.objects.filter(in_reply_to=self.message).exists())
        self.assertFalse(CoordinateActivity.objects.filter(event="research_and_drafts_saved").exists())

    def test_worker_recipient_from_public_evidence_is_permitted_but_does_not_send(self):
        claim = self.claim()
        artifacts = self.artifacts("evidence@example.test")
        artifacts["research"][0]["text"] = "Synthetic public source lists evidence@example.test for packing."
        self.assertEqual(self.complete(claim, **artifacts).status_code, 200)
        draft = CoordinateDraft.objects.get()
        self.assertEqual(draft.recipient, "evidence@example.test")
        self.assertEqual(draft.status, "draft")
        self.assertFalse(CoordinateActivity.objects.get(event="research_and_drafts_saved").details["sent"])

    def test_worker_recipient_explicitly_saved_in_plan_notes_is_permitted(self):
        self.plan(notes="Please ask notes-provider@example.test for packing details.")
        response = self.complete(self.claim(), **self.artifacts("notes-provider@example.test"))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(CoordinateDraft.objects.get().recipient, "notes-provider@example.test")

    def test_failed_incoming_research_cannot_supply_recipient_evidence(self):
        claim = self.claim()
        artifacts = self.artifacts("unverified@example.test")
        artifacts["research"][0].update(text="Contact unverified@example.test", error="Fetch failed")
        response = self.complete(claim, **artifacts)
        self.assertEqual(response.status_code, 400, response.content)
        self.assertFalse(CoordinateDraft.objects.exists())
        self.assertFalse(CoordinateResearch.objects.exists())
        self.assertFalse(CoordinateMessage.objects.filter(in_reply_to=self.message).exists())
        self.assertEqual(CoordinateJob.objects.get(pk=claim["job"]["id"]).status, "processing")

    def test_failed_saved_research_cannot_supply_recipient_evidence(self):
        artifacts = self.artifacts()
        artifacts["research"][0].update(text="Contact unverified@example.test", error="Fetch failed")
        artifacts["drafts"] = []
        self.assertEqual(self.complete(self.claim(), **artifacts).status_code, 200)
        self.assertEqual(CoordinateResearch.objects.count(), 1)
        response = self.post("coordinate_message", {
            "body": "Please continue gathering details.", "client_message_id": str(uuid4()),
        })
        self.assertEqual(response.status_code, 200)
        response = self.complete(self.claim(), **self.artifacts("unverified@example.test"))
        self.assertEqual(response.status_code, 400, response.content)
        self.assertFalse(CoordinateDraft.objects.exists())
        self.assertEqual(CoordinateResearch.objects.count(), 1)

    def test_any_paused_quote_blocks_generated_provider_drafts_and_counts_only_saved_drafts(self):
        self.plan()
        paused = self.quote("100", "PACKER@example.test")
        self.assertEqual(self.post("coordinate_quote_accept", record=paused).status_code, 200)
        self.assertEqual(self.post("coordinate_quote_update", {"latest_amount": "150"}, record=paused).status_code, 200)
        selected = self.quote("120")
        self.assertEqual(self.post("coordinate_quote_accept", record=selected).status_code, 200)
        paused.refresh_from_db()
        selected.refresh_from_db()
        self.assertFalse(paused.accepted)
        self.assertTrue(quote_paused(paused))
        self.assertTrue(selected.accepted)
        self.assertFalse(quote_paused(selected))
        self.quote("75", "other-provider@example.test")
        artifacts = self.artifacts()
        artifacts["drafts"].append({**artifacts["drafts"][0], "recipient": "other-provider@example.test"})
        claim = self.claim()
        self.assertEqual(self.complete(claim, **artifacts).status_code, 200)
        self.assertEqual(list(CoordinateDraft.objects.values_list("recipient", flat=True)), ["other-provider@example.test"])
        event = CoordinateActivity.objects.get(event="research_and_drafts_saved")
        self.assertEqual(event.details, {"research_count": 1, "draft_count": 1, "sent": False})
        self.assertEqual(self.complete(claim, **artifacts).status_code, 200)
        self.assertEqual(CoordinateDraft.objects.count(), 1)

    def test_failed_standard_http_research_does_not_poison_completion(self):
        artifacts = self.artifacts()
        artifacts["research"] = [
            {**artifacts["research"][0], "source_url": url, "final_url": url, "text": "", "error": "HTTPS required for fetching"}
            for url in ("http://example.test/lot-17", "http://example.test:80/lot-18", "https://example.test:443/lot-19")
        ]
        response = self.complete(self.claim(), **artifacts)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(CoordinateResearch.objects.count(), 3)
        self.assertEqual(CoordinateDraft.objects.count(), 1)

    def test_successful_http_research_is_rejected(self):
        claim = self.claim()
        for field in ("source_url", "final_url"):
            with self.subTest(field=field):
                artifacts = self.artifacts()
                artifacts["research"][0][field] = "http://example.test/lot-17"
                self.assertEqual(self.complete(claim, **artifacts).status_code, 400)
        self.assertFalse(CoordinateResearch.objects.exists())
        self.assertFalse(CoordinateDraft.objects.exists())

    def test_failed_research_still_rejects_credentials_nonstandard_ports_and_other_schemes(self):
        claim = self.claim()
        for url in ("http://user@example.test/lot", "https://user:password@example.test/lot",
                    "http://@example.test/lot", "http://example.test:443/lot",
                    "https://example.test:80/lot", "https://example.test:8443/lot", "ftp://example.test/lot"):
            for field in ("source_url", "final_url"):
                with self.subTest(url=url, field=field):
                    artifacts = self.artifacts()
                    artifacts["research"][0].update(error="Fetch failed")
                    artifacts["research"][0][field] = url
                    self.assertEqual(self.complete(claim, **artifacts).status_code, 400)
        self.assertFalse(CoordinateResearch.objects.exists())
        self.assertFalse(CoordinateDraft.objects.exists())

    def test_artifacts_are_hidden_when_source_input_or_whole_case_is_deleted(self):
        claim = self.claim()
        self.assertEqual(self.complete(claim, **self.artifacts()).status_code, 200)
        self.assertEqual(len(self.state()["coordination"]["drafts"]), 1)
        self.post("coordinate_delete_message", record=self.message)
        hidden = self.state()["coordination"]
        self.assertEqual(hidden["drafts"], [])
        self.assertEqual(hidden["research"], [])
        self.post("coordinate_restore_message", record=self.message)
        self.assertEqual(len(self.state()["coordination"]["drafts"]), 1)
        self.post("coordinate_delete_case")
        self.assertIsNone(self.state()["coordination"])
        self.assertEqual(CoordinateDraft.objects.count(), 1)
        self.assertEqual(CoordinateResearch.objects.count(), 1)

    def test_artifacts_are_hidden_when_generated_reply_is_deleted_and_restored_with_it(self):
        claim = self.claim()
        self.assertEqual(self.complete(claim, **self.artifacts()).status_code, 200)
        reply = CoordinateMessage.objects.get(in_reply_to=self.message)
        self.post("coordinate_delete_message", record=reply)
        hidden = self.state()["coordination"]
        self.assertEqual(hidden["drafts"], [])
        self.assertEqual(hidden["research"], [])
        self.post("coordinate_restore_message", record=reply)
        self.assertEqual(len(self.state()["coordination"]["drafts"]), 1)
        self.assertEqual(len(self.state()["coordination"]["research"]), 1)

    def test_malformed_draft_quote_identifier_returns_validation_error(self):
        response = self.post("coordinate_draft_add", {
            "recipient": "packer@example.test", "subject": "synthetic", "body": "synthetic", "quote_id": "not-a-uuid",
        })
        self.assertEqual(response.status_code, 400)
        self.assertFalse(CoordinateDraft.objects.exists())
