"""Conversational approval must bind to the displayed, immutable email bundle."""
import json
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import coordinate_mail as mail
from .coordinate_chat_send import chat_send_state, explicit_send
from .models import (CoordinateActivity, CoordinateCase, CoordinateDraft, CoordinateJob,
                     CoordinateMailDelivery, CoordinateMessage, CoordinatePlan, CoordinateQuote)


@override_settings(COORDINATE_DRAFT_WORKFLOW_ENABLED=True, COORDINATE_EMAIL_SENDING_ENABLED=True,
                   COORDINATE_EMAIL_SYNC_ENABLED=True, AUCTION_EMAIL_SENDER="jeremy@secondstate.art",
                   GOOGLE_GMAIL_CLIENT_ID="synthetic-client", GOOGLE_GMAIL_CLIENT_SECRET="synthetic-secret",
                   GOOGLE_GMAIL_REFRESH_TOKEN="synthetic-refresh")
class CoordinateChatSendTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user("chat-send-staff", is_staff=True)
        self.client.force_login(self.staff)
        self.case = CoordinateCase.objects.create(title="Synthetic chat send", created_by=self.staff)
        self.origin = CoordinateMessage.objects.create(case=self.case, role="staff", body="Prepare three emails.")
        self.job = CoordinateJob.objects.create(message=self.origin, status="completed")
        self.reply = CoordinateMessage.objects.create(case=self.case, role="assistant", body="Three drafts are ready.", in_reply_to=self.origin)
        self.plan = CoordinatePlan.objects.create(case=self.case, destination="duarte")
        self.drafts = [CoordinateDraft.objects.create(case=self.case, job=self.job,
            recipient=f"provider{index}@example.test", subject="Packing quote", body=f"Please quote packing for item {index}.")
            for index in range(3)]
        self.url = reverse("coordinate_message", args=[self.case.pk])
        self.transport = patch("secondstateapp.coordinate_mail.send_snapshot", side_effect=self.receipt).start()
        self.addCleanup(patch.stopall)

    def receipt(self, delivery):
        # Snapshots exist before a network call; the whole bundle is reserved.
        self.assertEqual(CoordinateMailDelivery.objects.count(), 3)
        self.assertEqual(CoordinateMailDelivery.objects.get(pk=delivery.pk).body, delivery.body)
        return {"id": f"out-{delivery.pk}", "threadId": f"thread-{delivery.pk}"}

    def post(self, body="Dude this is perfect! Send it!", context=None, token=None):
        return self.client.post(self.url, {"body": body, "client_message_id": str(token or uuid4()),
            "send_context": json.dumps(chat_send_state(self.case) if context is None else context)}, HTTP_ACCEPT="application/json")

    def test_clear_natural_approval_sends_exact_bundle_without_worker_job(self):
        before = CoordinateJob.objects.count()
        token = uuid4()
        response = self.post(token=token)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.transport.call_count, 3)
        self.assertEqual(CoordinateJob.objects.count(), before)
        message = CoordinateMessage.objects.get(client_message_id=token)
        self.assertIn("Sent 3 emails", message.worker_reply.body)
        for delivery in CoordinateMailDelivery.objects.all():
            self.assertEqual(delivery.status, "sent")
            self.assertEqual(delivery.approval_snapshot["approval_method"], "staff_chat")
            self.assertEqual(delivery.approval_snapshot["approval_message_id"], message.pk)
            self.assertEqual(delivery.approval_snapshot["approval_reply_id"], self.reply.pk)
            self.assertEqual(delivery.reviewed_digest, mail.draft_digest(delivery.draft))
        self.assertEqual(response.json()["coordination"]["chat_send"]["reply_id"], self.reply.pk)
        self.assertEqual(len(response.json()["coordination"]["chat_send"]["drafts"]), 3)
        # A retry from an interrupted browser POST is observational only.
        self.assertEqual(self.post(token=token).status_code, 200)
        self.assertEqual(self.transport.call_count, 3)

    def test_affirmative_grammar_excludes_negated_conditional_quoted_and_edited_commands(self):
        for body in ("send it", "I love it! Send it!", "Looks great, send them!",
                     "Yes, please send those emails.", "Go ahead and send it.", "Send them out",
                     "Perfect, let's send them.", "Dude this is perfect! Send it!", "Can you send it?",
                     "Could you please send them?", "Awesome! Send it!", "Love it! Send it! Thanks!",
                     "Send them! 💪🏼", "I love it! Send it! 👍", "Could you please send them? Thanks! 👍🏼"):
            with self.subTest(body=body):
                self.assertTrue(explicit_send(body))
        for body in ("Don't send it", "Do not send it", "Send it if the price is right", "Send it?",
                     "Should I send it?", "She said send it", '"send it"', "`send it`", "Send it, but change the address",
                     "Once I review it send it", "I love it!", "Approved", "send it to other@example.test",
                     "Send them after removing the deadline", "If this is perfect, send it", "Never send it",
                     "Should we send it?", "Did you send it?", "Could you not send them?",
                     "Can you send it if the address is correct?", "Love it! Send it after editing. 👍",
                     "Could you please send them after changing the price?", "She asked: Can you send it?"):
            with self.subTest(body=body):
                self.assertFalse(explicit_send(body))
        response = self.post("Please change the pickup date before sending.")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(CoordinateJob.objects.count(), 2)
        self.transport.assert_not_called()

    def test_direct_question_request_dispatches_displayed_bundle(self):
        response = self.post("Could you please send them? Thanks! 👍🏼")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.transport.call_count, 3)
        self.assertEqual(CoordinateMailDelivery.objects.filter(status="sent").count(), 3)
        self.assertEqual(CoordinateJob.objects.count(), 1)

    def test_missing_or_forged_context_returns_case_result_without_research_or_send(self):
        context = chat_send_state(self.case)
        context["drafts"][0]["content_digest"] = "0" * 64
        for supplied in ({}, context, {**context, "token": None}, {**context, "token": []}):
            response = self.post(context=supplied)
            self.assertEqual(response.status_code, 200)
            self.assertIn("Review the current emails", response.json()["messages"][-1]["body"])
        self.assertEqual(CoordinateJob.objects.count(), 1)
        self.assertFalse(CoordinateMailDelivery.objects.exists())
        self.transport.assert_not_called()

    def test_changed_content_rejects_whole_bundle_and_does_not_approve_earlier_items(self):
        context = chat_send_state(self.case)
        CoordinateDraft.objects.filter(pk=self.drafts[-1].pk).update(body="Changed after display")
        response = self.post(context=context)
        self.assertEqual(response.status_code, 200)
        self.assertIn("changed", response.json()["messages"][-1]["body"])
        self.assertFalse(CoordinateMailDelivery.objects.exists())
        self.assertFalse(CoordinateDraft.objects.filter(status="reviewed").exists())
        self.transport.assert_not_called()

    def test_new_message_or_changed_plan_invalidates_visible_context(self):
        context = chat_send_state(self.case)
        CoordinateMessage.objects.create(case=self.case, role="staff", body="Actually, wait for details.")
        self.post(context=context)
        self.assertFalse(CoordinateMailDelivery.objects.exists())
        context = chat_send_state(self.case)
        CoordinateCase.objects.filter(pk=self.case.pk).update(updated_at=timezone.now())
        self.post(context=context)
        self.transport.assert_not_called()

    def test_manifest_cannot_authorize_text_missing_from_rendered_state(self):
        shown = [{"id": str(d.pk), "current_digest": mail.draft_digest(d)} for d in self.drafts]
        self.assertTrue(chat_send_state(self.case, shown)["token"])
        CoordinateDraft.objects.filter(pk=self.drafts[-1].pk).update(body="Concurrent edit")
        self.assertIsNone(chat_send_state(self.case, shown)["token"])
        self.assertIsNone(chat_send_state(self.case, shown[:1])["token"])

    def test_changed_thread_headers_roll_back_all_approval_records(self):
        # First two deliveries are reserved before the last provider's malformed
        # headers fail; the enclosing bundle savepoint must undo all of them.
        CoordinateDraft.objects.filter(pk=self.drafts[-1].pk).update(subject="Unsafe\nheader")
        response = self.post()
        self.assertIn("invalid headers", response.json()["messages"][-1]["body"])
        self.assertFalse(CoordinateMailDelivery.objects.exists())
        self.assertFalse(CoordinateDraft.objects.filter(status="reviewed").exists())
        self.assertFalse(CoordinateActivity.objects.filter(event="email_draft_reviewed").exists())
        self.transport.assert_not_called()

    def test_other_case_context_and_deleted_origin_cannot_send(self):
        context = chat_send_state(self.case)
        other = CoordinateCase.objects.create(title="Other", created_by=self.staff)
        self.case = other
        self.url = reverse("coordinate_message", args=[other.pk])
        self.post(context=context)
        self.case = self.origin.case
        self.url = reverse("coordinate_message", args=[self.case.pk])
        self.origin.deleted_at = timezone.now()
        self.origin.save()
        self.post(context=context)
        self.transport.assert_not_called()

    def test_later_paused_provider_rolls_back_entire_approval_bundle(self):
        CoordinateQuote.objects.create(case=self.case, provider_name="Paused", provider_email=self.drafts[-1].recipient,
            amount="100", latest_amount="150", accepted_amount="100")
        response = self.post()
        self.assertIn("paused", response.json()["messages"][-1]["body"])
        self.assertFalse(CoordinateMailDelivery.objects.exists())
        self.assertFalse(CoordinateDraft.objects.filter(status="reviewed").exists())
        self.transport.assert_not_called()

    @override_settings(GOOGLE_GMAIL_REFRESH_TOKEN="")
    def test_unconfigured_delivery_rolls_back_approvals_and_records_actionable_reply(self):
        response = self.post()
        self.assertIn("configuration", response.json()["messages"][-1]["body"])
        self.assertFalse(CoordinateMailDelivery.objects.exists())
        self.assertFalse(CoordinateDraft.objects.filter(status="reviewed").exists())
        self.assertFalse(CoordinateActivity.objects.filter(event="email_draft_reviewed").exists())
        self.transport.assert_not_called()

    def test_unknown_outcome_never_retries_and_remains_in_same_visible_bundle(self):
        self.transport.side_effect = TimeoutError("private synthetic failure")
        token = uuid4()
        response = self.post(token=token)
        self.assertNotContains(response, "private synthetic failure")
        self.assertEqual(CoordinateMailDelivery.objects.filter(status="unknown").count(), 3)
        self.post(token=token)
        self.post()
        self.assertEqual(self.transport.call_count, 3)
        state = chat_send_state(self.case)
        self.assertEqual(state["reply_id"], self.reply.pk)
        self.assertEqual({item["id"] for item in state["drafts"]}, {str(d.pk) for d in self.drafts})

    def test_latest_bundle_never_falls_back_to_older_unsent_drafts(self):
        self.post()
        new_origin = CoordinateMessage.objects.create(case=self.case, role="staff", body="New request")
        job = CoordinateJob.objects.create(message=new_origin, status="completed")
        reply = CoordinateMessage.objects.create(case=self.case, role="assistant", body="A new draft", in_reply_to=new_origin)
        draft = CoordinateDraft.objects.create(case=self.case, job=job, recipient="new@example.test", subject="New", body="New email")
        CoordinateDraft.objects.filter(pk=self.drafts[0].pk).update(body="Older draft")
        state = chat_send_state(self.case)
        self.assertEqual(state["reply_id"], reply.pk)
        self.assertEqual([item["id"] for item in state["drafts"]], [str(draft.pk)])

    def test_csrf_staff_and_post_required(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        protected = Client(enforce_csrf_checks=True)
        protected.force_login(self.staff)
        self.assertEqual(protected.post(self.url, {"body": "Send it!"}).status_code, 403)
        self.client.logout()
        self.assertEqual(self.post().status_code, 302)
        self.transport.assert_not_called()

    def test_runtime_policy_is_supplied_with_worker_mail_context(self):
        policy = mail.mail_state(self.case, self.origin.pk)["sending_policy"]
        self.assertIn("signed-in staff", policy)
        self.assertIn("Only persisted sent delivery receipts", policy)
