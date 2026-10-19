"""Scoped mail evidence tests: synthetic MIME only, no Gmail reads or sends."""
import base64
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import tempfile
from unittest import TestCase as UnitTestCase
from unittest.mock import Mock, patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from scripts import coordinate_mail_sync as sync
from scripts.coordinate_worker import APIError, WorkerError
from .coordinate_mail_models import CoordinateMailDelivery, CoordinateMailMessage, CoordinateMailThread
from .coordinate_mail_sync import mail_context
from .models import CoordinateCase, CoordinateDraft, CoordinateJob, CoordinateMessage


def raw_message(identifier="message001", thread="thread001", *, sender="packer@example.com", text="Pickup Friday. Quote USD 150.", when=None, html=False):
    when = when or timezone.now()
    return {"id": identifier, "threadId": thread, "internalDate": str(int(when.timestamp() * 1000)),
            "labelIds": ["INBOX"], "payload": {"mimeType": "text/html" if html else "text/plain",
                "headers": [{"name": "From", "value": "Provider <" + sender + ">"},
                            {"name": "To", "value": "Jeremy <jeremy@secondstate.art>"},
                            {"name": "Subject", "value": "Re: Collection"},
                            {"name": "Message-ID", "value": "<" + identifier + "@example.com>"}],
                "body": {"data": base64.urlsafe_b64encode(text.encode()).decode().rstrip("="), "size": len(text)}}}


class MailMIMETests(UnitTestCase):
    def test_live_connector_snake_case_mime_shape_preserves_decoded_body(self):
        now = timezone.now()
        raw = raw_message(sender=sync.ACCOUNT_EMAIL, text="Line one.\r\n\r\nLine two.", when=now)
        raw["thread_id"] = raw.pop("threadId")
        raw["internal_date"] = raw.pop("internalDate")
        raw["label_ids"] = ["SENT", "INBOX"]
        raw.pop("labelIds")
        payload = raw["payload"]
        payload["mime_type"] = payload.pop("mimeType")
        payload["part_id"], payload["filename"], payload["parts"] = "", "", None
        payload["body"] = {"size": 24, "base64_url_content": None,
                           "content": "Line one.\r\n\r\nLine two.", "attachment_id": None}
        result = sync.normalize_thread({"id": "thread001", "history_id": "123", "messages": [raw]}, now)
        self.assertEqual(result["messages"][0]["body_text"], "Line one.\n\nLine two.")
        self.assertTrue(result["messages"][0]["sent_label"])
        payload["body"]["base64_url_content"] = base64.urlsafe_b64encode(b"Different body").decode()
        with self.assertRaises(ValueError):
            sync.normalize_thread({"id": "thread001", "messages": [raw]}, now)

    def test_connector_alias_conflicts_and_summary_only_are_rejected(self):
        now = timezone.now()
        raw = raw_message(when=now)
        raw["thread_id"] = "different001"
        with self.assertRaises(ValueError):
            sync.normalize_message(raw, "thread001", now)
        with self.assertRaises(ValueError):
            sync.normalize_message({"id": "message001", "thread_id": "thread001",
                "internal_date": str(int(now.timestamp() * 1000)), "snippet": "summary only"}, "thread001", now)

    def test_long_subject_is_rejected_and_bcc_is_retained_for_exact_matching(self):
        now = timezone.now()
        raw = raw_message(when=now)
        raw["payload"]["headers"].append({"name": "Bcc", "value": "hidden@example.com"})
        self.assertTrue(sync.normalize_message(raw, "thread001", now)["has_bcc"])
        for header in raw["payload"]["headers"]:
            if header["name"] == "Subject":
                header["value"] = "A" * 200 + " DIFFERENT"
        with self.assertRaises(ValueError):
            sync.normalize_message(raw, "thread001", now)

    def test_plain_and_html_decode_without_active_markup_or_remote_requests(self):
        now = timezone.now()
        plain = sync.normalize_message(raw_message(when=now), "thread001", now)
        self.assertEqual(plain["body_text"], "Pickup Friday. Quote USD 150.")
        self.assertEqual(plain["from_email"], "packer@example.com")
        html = raw_message(text='<script>bad()</script><p>Pickup <b>Friday</b>.</p><img src="https://tracker.invalid/">', html=True, when=now)
        result = sync.normalize_message(html, "thread001", now)
        self.assertEqual(result["body_text"], "Pickup Friday.")
        self.assertNotIn("tracker", result["body_text"])

    def test_attachment_metadata_only_and_bounded_body(self):
        now = timezone.now()
        raw = raw_message(text="X" * (sync.MAX_BODY + 100), when=now)
        raw["payload"]["parts"] = [{"mimeType": "application/pdf", "filename": "private-invoice.pdf",
                                   "body": {"size": 100, "attachmentId": "never-download", "data": "not-decoded"}}]
        result = sync.normalize_message(raw, "thread001", now)
        self.assertTrue(result["body_truncated"])
        self.assertEqual(len(result["body_text"]), sync.MAX_BODY)
        self.assertEqual(result["attachments"], [{"filename": "private-invoice.pdf", "mime_type": "application/pdf", "size": 100}])
        self.assertNotIn("never-download", json.dumps(result))

    def test_multipart_plain_is_preferred_over_html_duplicate(self):
        now = timezone.now()
        raw = raw_message(when=now)
        raw["payload"]["parts"] = [{"mimeType": "text/html", "body": {
            "data": base64.urlsafe_b64encode(b"<p>Different HTML version</p>").decode()}}]
        result = sync.normalize_message(raw, "thread001", now)
        self.assertEqual(result["body_text"], "Pickup Friday. Quote USD 150.")

    def test_encoded_subject_preserves_reviewed_unicode_wording(self):
        now = timezone.now()
        raw = raw_message(when=now)
        for header in raw["payload"]["headers"]:
            if header["name"] == "Subject":
                header["value"] = "=?utf-8?q?Z=C3=BA=C3=B1iga_collection?="
        self.assertEqual(sync.normalize_message(raw, "thread001", now)["subject"], "Zúñiga collection")

    def test_snippets_wrong_thread_future_or_duplicate_from_are_rejected(self):
        now = timezone.now()
        candidates = [{"id": "message001", "threadId": "thread001", "internalDate": str(int(now.timestamp() * 1000)), "snippet": "not full mail"},
                      raw_message(thread="foreign001", when=now), raw_message(when=now + timedelta(minutes=1))]
        duplicate = raw_message(when=now)
        duplicate["payload"]["headers"].append({"name": "From", "value": "other@example.com"})
        candidates.append(duplicate)
        for raw in candidates:
            with self.subTest(raw=raw.get("id")), self.assertRaises(ValueError):
                sync.normalize_message(raw, "thread001", now)

    def test_cli_keeps_exact_import_for_ambiguous_retry(self):
        now = timezone.now()
        api = Mock(base_url="https://secondstate.example")
        manifest = {"base_url": api.base_url, "status": "prepared", "sync_token": "signed", "threads": [{"gmail_thread_id": "thread001"}]}
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            evidence = Path(directory) / "evidence.json"
            state.write_text(json.dumps(manifest))
            evidence.write_text(json.dumps({"account_email": sync.ACCOUNT_EMAIL, "observed_at": now.isoformat(),
                                           "threads": [{"id": "thread001", "messages": [raw_message(when=now)]}]}))
            api.post.side_effect = [APIError(503), {"imported": 1, "duplicates": 0}]
            with self.assertRaises(APIError):
                sync.complete(api, state, evidence)
            evidence.write_text("no longer needed")
            result = sync.complete(api, state, evidence)
            self.assertEqual(result["imported"], 1)
            self.assertEqual(api.post.call_args_list[0].args, api.post.call_args_list[1].args)
            self.assertEqual(sync.complete(api, state, evidence), result)
            self.assertEqual(api.post.call_count, 2)

    def test_cli_preserves_scoped_snapshot_candidates_and_rejects_incomplete_search(self):
        now = timezone.now()
        api = Mock(base_url="https://secondstate.example")
        api.post.return_value = {"status": "reconciled", "imported": 0, "duplicates": 0}
        query = "in:sent from:jeremy@secondstate.art to:packer@example.com after:1 before:2"
        raw = raw_message(sender=sync.ACCOUNT_EMAIL, when=now)
        raw["labelIds"] = ["SENT"]
        manifest = {"base_url": api.base_url, "status": "prepared", "sync_token": "signed", "threads": [],
                    "reconcile": [{"delivery_id": "synthetic-delivery", "rfc_message_id": "<requested@example.com>",
                                   "fallback_query": query}]}
        evidence = {"account_email": sync.ACCOUNT_EMAIL, "observed_at": now.isoformat(), "threads": [],
                    "deliveries": [{"delivery_id": "synthetic-delivery", "candidates": [raw],
                                    "match_method": "snapshot", "query": query, "search_complete": False}]}
        with tempfile.TemporaryDirectory() as directory:
            state, observed = Path(directory) / "state.json", Path(directory) / "observed.json"
            state.write_text(json.dumps(manifest))
            observed.write_text(json.dumps(evidence))
            with self.assertRaises((ValueError, WorkerError)):
                sync.complete(api, state, observed)
            api.post.assert_not_called()
            evidence["deliveries"][0]["search_complete"] = True
            observed.write_text(json.dumps(evidence))
            result = sync.complete(api, state, observed)
            self.assertEqual(result["reconciled"], 1)
            sent = api.post.call_args.args[1]["reconcile"]
            self.assertEqual(sent["match_method"], "snapshot")
            self.assertEqual(sent["query"], query)
            self.assertEqual(sent["candidates"][0]["rfc_message_id"], "<message001@example.com>")


@override_settings(COORDINATE_DRAFT_WORKFLOW_ENABLED=True, COORDINATE_EMAIL_SYNC_ENABLED=True,
                   COORDINATE_WORKER_TOKEN="synthetic-mail-sync-secret")
class MailSyncImportTests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.staff = get_user_model().objects.create_user("mail-sync-staff", is_staff=True)
        self.case = CoordinateCase.objects.create(title="Synthetic mail coordination", created_by=self.staff)
        self.origin = CoordinateMessage.objects.create(case=self.case, role="staff", body="Please arrange pickup.")
        self.thread = CoordinateMailThread.objects.create(case=self.case, originating_message=self.origin,
            provider_email="packer@example.com", gmail_thread_id="thread001", subject="Collection")
        self.now = timezone.now()

    def post(self, name, data):
        return self.client.post(reverse(name), json.dumps({"worker_id": "manual-codex", **data}), content_type="application/json",
                                HTTP_AUTHORIZATION="Bearer synthetic-mail-sync-secret")

    def manifest(self):
        response = self.post("coordinate_mail_sync_manifest", {})
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def import_data(self, *, raw=None, manifest=None):
        manifest = manifest or self.manifest()
        observed = timezone.now()
        return {"sync_token": manifest["sync_token"], "account_email": sync.ACCOUNT_EMAIL,
                "observed_at": observed.isoformat(), "thread": sync.normalize_thread(
                    {"id": "thread001", "messages": [raw or raw_message(when=self.now)]}, observed)}

    def test_manifest_is_scoped_and_import_deduplicates_deleted_message_tombstone(self):
        manifest = self.manifest()
        self.assertEqual([item["gmail_thread_id"] for item in manifest["threads"]], ["thread001"])
        data = self.import_data(manifest=manifest)
        first = self.post("coordinate_mail_sync_import", data)
        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(first.json()["imported"], 1)
        saved = CoordinateMailMessage.objects.get()
        self.assertEqual(saved.direction, "inbound")
        self.assertEqual(CoordinateJob.objects.filter(message=saved.message).count(), 1)
        self.assertEqual(saved.message.role, "system")
        self.assertNotIn("Quote", saved.message.body)
        CoordinateMessage.objects.filter(pk=saved.message_id).update(deleted_at=timezone.now())
        again = self.post("coordinate_mail_sync_import", data)
        self.assertEqual(again.status_code, 200, again.content)
        self.assertEqual(again.json()["duplicates"], 1)
        self.assertEqual(CoordinateMailMessage.objects.count(), 1)
        self.assertEqual(mail_context(self.case), [])

    def test_wrong_account_thread_participants_future_and_expired_scope_rejected(self):
        original = self.import_data()
        mutations = [lambda value: value.update(account_email="other@example.com"),
                     lambda value: value["thread"].update(gmail_thread_id="foreign001"),
                     lambda value: value["thread"]["messages"][0].update(from_email="stranger@example.com"),
                     lambda value: value["thread"]["messages"][0].update(to_emails=["stranger@example.com"]),
                     lambda value: value["thread"]["messages"][0].update(received_at=(timezone.now() + timedelta(hours=1)).isoformat()),
                     lambda value: value.update(sync_token="forged")]
        for mutate in mutations:
            data = deepcopy(original)
            mutate(data)
            with self.subTest(mutation=mutate):
                self.assertEqual(self.post("coordinate_mail_sync_import", data).status_code, 409)
        self.assertFalse(CoordinateMailMessage.objects.exists())

    def test_own_outbound_does_not_become_provider_reply_or_job(self):
        raw = raw_message(sender=sync.ACCOUNT_EMAIL, when=self.now)
        raw["labelIds"] = ["SENT"]
        response = self.post("coordinate_mail_sync_import", self.import_data(raw=raw))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["skipped"], 1)
        self.assertFalse(CoordinateMailMessage.objects.exists())
        self.assertFalse(CoordinateJob.objects.exists())

    def test_origin_or_case_deleted_after_manifest_prevents_import(self):
        data = self.import_data()
        CoordinateMessage.objects.filter(pk=self.origin.pk).update(deleted_at=timezone.now())
        self.assertEqual(self.post("coordinate_mail_sync_import", data).status_code, 409)
        self.assertEqual(self.manifest()["threads"], [])
        self.assertFalse(CoordinateMailMessage.objects.exists())

    def test_expired_manifest_and_case_trash_cannot_import(self):
        data = self.import_data()
        with patch("django.core.signing.time.time", return_value=timezone.now().timestamp() + 301):
            self.assertEqual(self.post("coordinate_mail_sync_import", data).status_code, 409)
        CoordinateCase.objects.filter(pk=self.case.pk).update(deleted_at=timezone.now())
        self.assertEqual(self.post("coordinate_mail_sync_import", data).status_code, 409)
        self.assertFalse(CoordinateMailMessage.objects.exists())

    def test_private_context_obeys_cutoff_and_origin_reply_visibility(self):
        response = self.post("coordinate_mail_sync_import", self.import_data())
        self.assertEqual(response.status_code, 200, response.content)
        saved = CoordinateMailMessage.objects.get()
        self.assertEqual(mail_context(self.case, max_message_id=self.origin.pk), [])
        context = mail_context(self.case, max_message_id=saved.message_id)
        self.assertEqual(context[0]["source_ref"], "message:" + str(saved.message_id))
        self.assertIn("Quote USD 150", context[0]["text"])
        reply = CoordinateMessage.objects.create(case=self.case, role="assistant", in_reply_to=self.origin, body="Prepared.")
        CoordinateMessage.objects.filter(pk=reply.pk).update(deleted_at=timezone.now())
        self.assertEqual(mail_context(self.case), [])

    def unknown_delivery(self, status="unknown"):
        draft = CoordinateDraft.objects.create(case=self.case, recipient="packer@example.com",
            subject="Re: Collection", body="Pickup Friday. Quote USD 150.")
        return CoordinateMailDelivery.objects.create(draft=draft, request_id=uuid4(), status=status,
            sender_email=sync.ACCOUNT_EMAIL, recipient=draft.recipient, subject=draft.subject,
            body=draft.body, reviewed_digest="0" * 64, rfc_message_id="<deterministic-send@secondstate.art>",
            approval_snapshot={"originating_message_id": self.origin.pk})

    def observed_outbound(self, delivery, identifier="sent001", *, when=None, rfc=None):
        raw = raw_message(identifier, when=when or delivery.requested_at, sender=sync.ACCOUNT_EMAIL,
                          text=delivery.body)
        raw["labelIds"] = ["SENT"]
        for header in raw["payload"]["headers"]:
            if header["name"] == "To":
                header["value"] = delivery.recipient
            elif header["name"] == "Subject":
                header["value"] = delivery.subject
            elif header["name"] == "Message-ID":
                header["value"] = rfc or "<provider-rewritten@example.com>"
        return sync.normalize_message(raw, "thread001", timezone.now())

    def reconcile_data(self, delivery, *, candidates=None, method="snapshot"):
        manifest = self.manifest()
        descriptor = next(item for item in manifest["reconcile"] if item["delivery_id"] == str(delivery.pk))
        return {"sync_token": manifest["sync_token"], "account_email": sync.ACCOUNT_EMAIL,
                "observed_at": timezone.now().isoformat(), "reconcile": {"delivery_id": str(delivery.pk),
                    "candidates": candidates or [self.observed_outbound(delivery)], "match_method": method,
                    "query": descriptor["fallback_query"], "search_complete": True}}

    @patch("secondstateapp.coordinate_mail.send_snapshot")
    def test_rewritten_rfc_reconciles_only_exact_snapshot_and_preserves_observed_headers(self, send):
        delivery = self.unknown_delivery()
        data = self.reconcile_data(delivery)
        self.assertNotIn(delivery.subject, data["reconcile"]["query"])
        response = self.post("coordinate_mail_sync_import", data)
        self.assertEqual(response.status_code, 200, response.content)
        delivery.refresh_from_db()
        mail = CoordinateMailMessage.objects.get()
        self.assertEqual(delivery.rfc_message_id, "<deterministic-send@secondstate.art>")
        self.assertEqual(mail.rfc_message_id, "<provider-rewritten@example.com>")
        self.assertEqual(delivery.sent_at, mail.received_at)
        self.assertEqual(mail.received_at.isoformat(), data["reconcile"]["candidates"][0]["received_at"])
        self.assertFalse(CoordinateJob.objects.exists())
        send.assert_not_called()

    def test_snapshot_fallback_rejects_incomplete_query_time_body_and_candidate_ambiguity(self):
        delivery = self.unknown_delivery()
        data = self.reconcile_data(delivery)
        mutations = [lambda value: value["reconcile"].update(search_complete=False),
                     lambda value: value["reconcile"].update(query="in:sent"),
                     lambda value: value["reconcile"]["candidates"][0].update(body_text="Different body"),
                     lambda value: value["reconcile"]["candidates"][0].update(sent_label=False),
                     lambda value: value["reconcile"]["candidates"][0].update(cc_emails=["other@example.com"]),
                     lambda value: value["reconcile"]["candidates"][0].update(has_bcc=True),
                     lambda value: value["reconcile"]["candidates"][0].update(
                         received_at=(delivery.requested_at - timedelta(seconds=61)).isoformat()),
                     lambda value: value["reconcile"]["candidates"].append(self.observed_outbound(delivery, "sent002"))]
        for mutate in mutations:
            changed = deepcopy(data)
            mutate(changed)
            with self.subTest(mutation=mutate):
                self.assertEqual(self.post("coordinate_mail_sync_import", changed).status_code, 409)
        self.assertFalse(CoordinateMailMessage.objects.exists())

    def test_snapshot_fallback_rejects_two_saved_identical_deliveries(self):
        delivery = self.unknown_delivery()
        other_draft = CoordinateDraft.objects.create(case=self.case, recipient=delivery.recipient,
            subject=delivery.subject, body=delivery.body)
        CoordinateMailDelivery.objects.create(draft=other_draft, request_id=uuid4(), status="unknown",
            sender_email=delivery.sender_email, recipient=delivery.recipient, subject=delivery.subject,
            body=delivery.body, reviewed_digest="1" * 64, rfc_message_id="<second-intent@secondstate.art>",
            approval_snapshot={"originating_message_id": self.origin.pk})
        response = self.post("coordinate_mail_sync_import", self.reconcile_data(delivery))
        self.assertEqual(response.status_code, 409)
        self.assertFalse(CoordinateMailMessage.objects.exists())

    def test_saved_receipt_id_allows_rewritten_rfc_without_search(self):
        delivery = self.unknown_delivery()
        delivery.gmail_message_id, delivery.gmail_thread_id = "sent001", "thread001"
        delivery.save(update_fields=["gmail_message_id", "gmail_thread_id"])
        data = self.reconcile_data(delivery, method="receipt")
        data["reconcile"].pop("query")
        data["reconcile"].pop("search_complete")
        response = self.post("coordinate_mail_sync_import", data)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(CoordinateMailMessage.objects.get().rfc_message_id, "<provider-rewritten@example.com>")

    def test_unusual_email_local_part_has_no_fallback_query(self):
        delivery = self.unknown_delivery()
        delivery.recipient = '"quoted local"@example.com'
        delivery.save(update_fields=["recipient"])
        descriptor = self.manifest()["reconcile"][0]
        self.assertEqual(descriptor["fallback_query"], "")
        self.assertIn("rfc822msgid:", descriptor["query"])

    def test_linked_outbound_refreshes_actual_rfc_without_duplicate_or_private_body_change(self):
        from .coordinate_mail import record_delivery_success
        delivery = self.unknown_delivery()
        record_delivery_success(delivery.pk, "sent001", "thread001")
        mail = CoordinateMailMessage.objects.get()
        self.assertEqual(mail.rfc_message_id, "")
        observed = self.observed_outbound(delivery)
        manifest = self.manifest()
        data = {"sync_token": manifest["sync_token"], "account_email": sync.ACCOUNT_EMAIL,
                "observed_at": timezone.now().isoformat(), "thread": {"gmail_thread_id": "thread001", "messages": [observed]}}
        response = self.post("coordinate_mail_sync_import", data)
        self.assertEqual(response.status_code, 200, response.content)
        mail.refresh_from_db()
        self.assertEqual(mail.rfc_message_id, "<provider-rewritten@example.com>")
        observed["body_text"] = "Wrong body"
        observed["rfc_message_id"] = "<wrong@example.com>"
        self.assertEqual(self.post("coordinate_mail_sync_import", data).status_code, 200)
        mail.refresh_from_db()
        self.assertEqual(mail.rfc_message_id, "<provider-rewritten@example.com>")
        self.assertEqual(CoordinateMailMessage.objects.count(), 1)
        self.assertFalse(CoordinateJob.objects.exists())

    @patch("secondstateapp.coordinate_mail.send_snapshot")
    def test_unknown_delivery_exact_sent_receipt_reconciles_without_resend(self, send):
        delivery = self.unknown_delivery()
        manifest = self.manifest()
        self.assertEqual(manifest["reconcile"][0]["query"], "in:sent rfc822msgid:deterministic-send@secondstate.art")
        raw = raw_message("sent001", when=timezone.now(), sender=sync.ACCOUNT_EMAIL)
        raw["labelIds"] = ["SENT"]
        for header in raw["payload"]["headers"]:
            if header["name"] == "To":
                header["value"] = "packer@example.com"
            if header["name"] == "Message-ID":
                header["value"] = delivery.rfc_message_id
        now = timezone.now()
        message = sync.normalize_message(raw, "thread001", now)
        data = {"sync_token": manifest["sync_token"], "account_email": sync.ACCOUNT_EMAIL,
                "observed_at": now.isoformat(), "reconcile": {"delivery_id": str(delivery.pk), "message": message}}
        wrong = deepcopy(data)
        wrong["reconcile"]["message"]["body_text"] = "Different message"
        self.assertEqual(self.post("coordinate_mail_sync_import", wrong).status_code, 409)
        response = self.post("coordinate_mail_sync_import", data)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["status"], "reconciled")
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, "sent")
        self.assertEqual(CoordinateMailMessage.objects.get().direction, "outbound")
        self.assertFalse(CoordinateJob.objects.exists())
        self.assertEqual(self.post("coordinate_mail_sync_import", data).status_code, 200)
        self.assertEqual(CoordinateMailMessage.objects.count(), 1)
        send.assert_not_called()

    def test_stale_sending_can_be_reconciled_but_active_send_cannot(self):
        delivery = self.unknown_delivery(status="sending")
        self.assertEqual(self.manifest()["reconcile"], [])
        CoordinateMailDelivery.objects.filter(pk=delivery.pk).update(requested_at=timezone.now() - timedelta(seconds=90))
        self.assertEqual(self.manifest()["reconcile"], [])
        CoordinateMailDelivery.objects.filter(pk=delivery.pk).update(requested_at=timezone.now() - timedelta(seconds=301))
        self.assertEqual(self.manifest()["reconcile"][0]["delivery_id"], str(delivery.pk))

    def test_old_history_is_not_imported_and_sync_rotates_least_recent_threads(self):
        old = raw_message(when=self.now - timedelta(hours=1))
        response = self.post("coordinate_mail_sync_import", self.import_data(raw=old))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["skipped"], 1)
        self.thread.refresh_from_db()
        self.assertIsNotNone(self.thread.sync_checked_at)
        self.assertFalse(CoordinateMailMessage.objects.exists())

    def test_delayed_receipt_still_imports_reply_after_authorized_send(self):
        delivery = self.unknown_delivery()
        sent_at = timezone.now() - timedelta(minutes=10)
        CoordinateMailDelivery.objects.filter(pk=delivery.pk).update(thread=self.thread, requested_at=sent_at)
        reply = raw_message(when=sent_at + timedelta(minutes=2))
        response = self.post("coordinate_mail_sync_import", self.import_data(raw=reply))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["imported"], 1)
        old = raw_message("unrelated001", when=sent_at - timedelta(seconds=1))
        response = self.post("coordinate_mail_sync_import", self.import_data(raw=old))
        self.assertEqual(response.json()["skipped"], 1)
        self.assertEqual(CoordinateMailMessage.objects.count(), 1)

    def test_sync_authentication_is_required_and_disabled_mode_is_quiet(self):
        response = Client(enforce_csrf_checks=True).post(reverse("coordinate_mail_sync_manifest"),
            json.dumps({"worker_id": "manual-codex"}), content_type="application/json")
        self.assertEqual(response.status_code, 401)
        with override_settings(COORDINATE_EMAIL_SYNC_ENABLED=False):
            manifest = self.manifest()
        self.assertEqual(manifest["threads"], [])
        self.assertEqual(manifest["reconcile"], [])
        self.assertIn("mail_readiness", manifest)
