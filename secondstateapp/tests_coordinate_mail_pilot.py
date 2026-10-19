"""Self-addressed quote tests remain scoped to their observed private thread."""
from datetime import timedelta
from django.test import TestCase, override_settings
from django.utils import timezone
from uuid import uuid4

from scripts.coordinate_mail_sync import ACCOUNT_EMAIL
from .coordinate_mail_sync import mail_context
from .models import CoordinateDraft, CoordinateJob, CoordinateMailDelivery, CoordinateMailMessage, CoordinateMailThread, CoordinateMessage
from . import tests_coordinate_mail_sync as sync_fixtures


@override_settings(COORDINATE_DRAFT_WORKFLOW_ENABLED=True, COORDINATE_EMAIL_SYNC_ENABLED=True,
                   COORDINATE_WORKER_TOKEN="synthetic-mail-sync-secret")
class QuotePilotMailTests(TestCase):
    post = sync_fixtures.MailSyncImportTests.post
    manifest = sync_fixtures.MailSyncImportTests.manifest
    import_data = sync_fixtures.MailSyncImportTests.import_data

    def setUp(self):
        sync_fixtures.MailSyncImportTests.setUp(self)
        self.thread.provider_email = ACCOUNT_EMAIL
        self.thread.save(update_fields=["provider_email"])
        self.draft = CoordinateDraft.objects.create(case=self.case, recipient="real-packer@example.com",
            subject="[quote test] Collection", body="Synthetic nonbinding quote inquiry.")
        self.delivery = CoordinateMailDelivery.objects.create(draft=self.draft, thread=self.thread,
            request_id=uuid4(), status="sent", sender_email=ACCOUNT_EMAIL, recipient=ACCOUNT_EMAIL,
            subject=self.draft.subject, body=self.draft.body, reviewed_digest="0" * 64,
            rfc_message_id="<requested-pilot@secondstate.art>", gmail_message_id="pilot001", gmail_thread_id="thread001",
            approval_snapshot={"authorization": "initial_quote_test", "intended_recipient": self.draft.recipient,
                               "originating_message_id": self.origin.pk})
        CoordinateMailDelivery.objects.filter(pk=self.delivery.pk).update(requested_at=timezone.now() - timedelta(seconds=2))
        self.anchor = CoordinateMessage.objects.create(case=self.case, role="system", body="Synthetic pilot sent.")
        self.outbound = CoordinateMailMessage.objects.create(thread=self.thread, message=self.anchor,
            direction="outbound", gmail_message_id="pilot001", rfc_message_id="<observed-pilot@gmail.example>",
            from_email=ACCOUNT_EMAIL, to_emails=[ACCOUNT_EMAIL], subject=self.draft.subject,
            body_text=self.draft.body, received_at=timezone.now())

    def reply(self, identifier="pilotreply001", *, parent="<observed-pilot@gmail.example>", sender=ACCOUNT_EMAIL, recipient=ACCOUNT_EMAIL):
        raw = sync_fixtures.raw_message(identifier, sender=sender, when=timezone.now(), text="Mock provider reply: conditional packing quote USD 150.")
        raw["labelIds"] = ["SENT", "INBOX"]
        for header in raw["payload"]["headers"]:
            if header["name"] == "To":
                header["value"] = recipient
        if parent:
            raw["payload"]["headers"].append({"name": "In-Reply-To", "value": parent})
        return raw

    def test_gmail_cannot_merge_different_intended_providers_into_one_pilot_thread(self):
        from .coordinate_mail import record_delivery_success
        draft = CoordinateDraft.objects.create(case=self.case, recipient="different-packer@example.com",
            subject="Another pilot", body="Another non-binding quote request")
        delivery = CoordinateMailDelivery.objects.create(draft=draft, request_id=uuid4(), status="sending",
            sender_email=ACCOUNT_EMAIL, recipient=ACCOUNT_EMAIL, subject=draft.subject, body=draft.body,
            reviewed_digest="1" * 64, rfc_message_id="<second-request@secondstate.art>",
            approval_snapshot={"authorization": "initial_quote_test", "intended_recipient": draft.recipient,
                               "originating_message_id": self.origin.pk})
        with self.assertRaisesRegex(ValueError, "different intended providers"):
            record_delivery_success(delivery.pk, "secondpilotmail", "thread001")
        self.assertFalse(CoordinateMailMessage.objects.filter(gmail_message_id="secondpilotmail").exists())
        delivery.refresh_from_db()
        self.assertIsNone(delivery.thread_id)

    def test_authorized_exact_observed_parent_imports_sent_labeled_self_reply_once(self):
        data = self.import_data(raw=self.reply())
        response = self.post("coordinate_mail_sync_import", data)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["imported"], 1)
        reply = CoordinateMailMessage.objects.get(gmail_message_id="pilotreply001")
        self.assertEqual(reply.direction, "inbound")
        self.assertIn("Test provider reply received from Jeremy", reply.message.body)
        self.assertEqual(CoordinateJob.objects.filter(message=reply.message).count(), 1)
        context = next(item for item in mail_context(self.case) if item["id"] == str(reply.pk))
        self.assertTrue(context["quote_test"])
        self.assertEqual(context["intended_provider"], "real-packer@example.com")
        self.assertEqual(context["from_address"], ACCOUNT_EMAIL)
        self.assertEqual(context["source_ref"], "message:" + str(reply.message_id))
        duplicate = self.post("coordinate_mail_sync_import", data)
        self.assertEqual(duplicate.json()["duplicates"], 1)
        self.assertEqual(CoordinateJob.objects.count(), 1)
        reply.message.deleted_at = timezone.now()
        reply.message.save(update_fields=["deleted_at"])
        self.assertEqual(self.post("coordinate_mail_sync_import", data).json()["duplicates"], 1)
        self.assertEqual(CoordinateMailMessage.objects.count(), 2)
        self.assertNotIn(str(reply.pk), {item["id"] for item in mail_context(self.case)})

    def test_unknown_requested_or_foreign_parent_cannot_turn_outbound_mail_into_reply(self):
        foreign = CoordinateMailThread.objects.create(case=self.case, originating_message=self.origin,
            provider_email=ACCOUNT_EMAIL, gmail_thread_id="foreignthread", subject="Unrelated")
        anchor = CoordinateMessage.objects.create(case=self.case, role="system", body="Other thread")
        CoordinateMailMessage.objects.create(thread=foreign, message=anchor, direction="outbound",
            gmail_message_id="foreignmail", rfc_message_id="<foreign-observed@gmail.example>", from_email=ACCOUNT_EMAIL,
            to_emails=[ACCOUNT_EMAIL], subject="Unrelated", body_text="Unrelated body", received_at=timezone.now())
        for parent in ("", "<unknown@gmail.example>", self.delivery.rfc_message_id, "<foreign-observed@gmail.example>"):
            with self.subTest(parent=parent):
                response = self.post("coordinate_mail_sync_import", self.import_data(raw=self.reply(parent=parent)))
                self.assertEqual(response.status_code, 200, response.content)
                self.assertEqual(response.json()["skipped"], 1)
        self.assertFalse(CoordinateMailMessage.objects.filter(direction="inbound").exists())
        self.assertFalse(CoordinateJob.objects.exists())

    def test_pilot_authorization_sender_and_recipient_are_all_required(self):
        for authorization in ("", "initial_quote_live", "reviewed_email"):
            self.delivery.approval_snapshot["authorization"] = authorization
            self.delivery.save(update_fields=["approval_snapshot"])
            response = self.post("coordinate_mail_sync_import", self.import_data(raw=self.reply()))
            self.assertEqual(response.status_code, 200, response.content)
            self.assertEqual(response.json()["skipped"], 1)
        self.delivery.approval_snapshot["authorization"] = "initial_quote_test"
        self.delivery.save(update_fields=["approval_snapshot"])
        for changes in ({"sender": "other@example.com"}, {"recipient": "other@example.com"}):
            with self.subTest(changes=changes):
                response = self.post("coordinate_mail_sync_import", self.import_data(raw=self.reply(**changes)))
                self.assertEqual(response.status_code, 200, response.content)
                self.assertEqual(response.json()["skipped"], 1)
        self.assertFalse(CoordinateJob.objects.exists())

    def test_normal_thread_never_receives_pilot_context_marker(self):
        self.delivery.approval_snapshot["authorization"] = "initial_quote_live"
        self.delivery.save(update_fields=["approval_snapshot"])
        self.assertTrue(mail_context(self.case))
        self.assertTrue(all("quote_test" not in item for item in mail_context(self.case)))
