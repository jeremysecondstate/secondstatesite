"""Explicit delivery controls, immutable approval and ambiguous-send recovery."""
import base64
from datetime import timedelta
from email import policy
from email.parser import BytesParser
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import coordinate_mail as mail
from .models import (CoordinateCase, CoordinateDraft, CoordinateJob, CoordinateMessage, CoordinatePlan,
                     CoordinateQuote, CoordinateMailDelivery, CoordinateMailMessage, CoordinateMailThread)


@override_settings(COORDINATE_DRAFT_WORKFLOW_ENABLED=True, COORDINATE_EMAIL_SENDING_ENABLED=True,
                   COORDINATE_EMAIL_SYNC_ENABLED=True, AUCTION_EMAIL_SENDER="jeremy@secondstate.art",
                   GOOGLE_GMAIL_CLIENT_ID="synthetic-client", GOOGLE_GMAIL_CLIENT_SECRET="synthetic-secret",
                   GOOGLE_GMAIL_REFRESH_TOKEN="synthetic-refresh")
class CoordinateMailTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user("mail-staff", is_staff=True)
        self.client.force_login(self.staff)
        self.case = CoordinateCase.objects.create(title="Synthetic correspondence", created_by=self.staff)
        self.origin = CoordinateMessage.objects.create(case=self.case, role="staff", body="Contact provider@example.test")
        self.plan = CoordinatePlan.objects.create(case=self.case, destination="duarte", handling="Keep existing frame")
        self.draft = CoordinateDraft.objects.create(case=self.case, recipient="provider@example.test",
            subject="Collection details", body="Please confirm collection and packing details.", purpose="Ask for details")

    def post(self, name, **data):
        return self.client.post(reverse(name, args=[self.case.pk, self.draft.pk]), data, HTTP_ACCEPT="application/json")

    def review(self):
        response = self.post("coordinate_draft_review", content_digest=mail.draft_digest(self.draft))
        self.assertEqual(response.status_code, 200, response.content)
        self.draft.refresh_from_db()

    def send(self, request_id=None, digest=None):
        return self.post("coordinate_mail_send", content_digest=digest or mail.draft_digest(self.draft),
                         request_id=str(request_id or uuid4()))

    def thread(self):
        thread = CoordinateMailThread.objects.create(case=self.case, originating_message=self.origin,
            provider_email=self.draft.recipient, subject=self.draft.subject, gmail_thread_id="thread-17")
        anchor = CoordinateMessage.objects.create(case=self.case, role="system", body="Received provider email")
        CoordinateMailMessage.objects.create(thread=thread, message=anchor, direction="inbound",
            gmail_message_id="inbound-17", rfc_message_id="<reply-17@provider.example>",
            from_email=self.draft.recipient, to_emails=[mail.SENDER], subject=self.draft.subject,
            body_text="Packing is available.", received_at=timezone.now())
        return thread

    @patch("secondstateapp.coordinate_mail.send_snapshot")
    def test_review_never_sends_and_legacy_or_stale_approval_cannot_send(self, transport):
        self.assertEqual(self.send().status_code, 409)
        self.draft.status, self.draft.reviewed_at, self.draft.reviewed_by = "reviewed", timezone.now(), self.staff
        self.draft.save()
        self.assertEqual(self.send().status_code, 409)
        self.review()
        self.assertEqual(self.send(digest="0" * 64).status_code, 409)
        transport.assert_not_called()
        self.assertFalse(CoordinateMailDelivery.objects.exists())

    @patch("secondstateapp.coordinate_mail.send_snapshot", return_value={"id": "outbound-17", "threadId": "thread-17"})
    def test_explicit_send_commits_exact_snapshot_before_network_and_retries_once(self, transport):
        self.review()
        def check_committed(delivery):
            saved = CoordinateMailDelivery.objects.get(pk=delivery.pk)
            self.assertEqual(saved.status, "sending")
            self.assertEqual(saved.body, self.draft.body)
            self.assertEqual(saved.reviewed_digest, mail.draft_digest(self.draft))
            self.assertEqual(saved.approval_snapshot["reviewed_by_id"], self.staff.pk)
            self.assertTrue(saved.rfc_message_id.endswith("@secondstate.art>"))
            return {"id": "outbound-17", "threadId": "thread-17"}
        transport.side_effect = check_committed
        token = uuid4()
        response = self.send(token)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["delivery"]["status"], "sent")
        self.assertEqual(self.send(token).status_code, 200)
        self.assertEqual(self.send().status_code, 409)
        self.assertEqual(transport.call_count, 1)
        self.assertEqual(CoordinateMailDelivery.objects.count(), 1)
        self.assertEqual(CoordinateMailMessage.objects.count(), 1)
        self.assertEqual(CoordinateMailThread.objects.get().originating_message_id, self.origin.pk)
        self.assertEqual(self.post("coordinate_draft_review", content_digest=mail.draft_digest(self.draft)).status_code, 400)
        self.assertEqual(self.post("coordinate_draft_update", content_digest=mail.draft_digest(self.draft),
                                  recipient=self.draft.recipient, subject=self.draft.subject, body="Changed").status_code, 400)

    @patch("secondstateapp.coordinate_mail.send_snapshot", side_effect=TimeoutError("synthetic-secret bearer private message"))
    def test_ambiguous_outcome_is_locked_and_never_automatically_retried(self, transport):
        self.review()
        token = uuid4()
        response = self.send(token)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["delivery"]["status"], "unknown")
        self.assertNotContains(response, "synthetic-secret")
        self.assertEqual(self.send(token).status_code, 200)
        self.assertEqual(transport.call_count, 1)
        delivery = CoordinateMailDelivery.objects.get()
        self.assertEqual(delivery.error_code, "transport_error")
        self.assertFalse(mail.draft_mail_state(CoordinateDraft.objects.get(pk=self.draft.pk))["editable"])
        receipt = mail.record_delivery_success(delivery.pk, "reconciled-17", "thread-17")
        self.assertEqual(receipt.status, "sent")
        self.assertEqual(mail.record_delivery_success(delivery.pk, "reconciled-17", "thread-17").pk, receipt.pk)
        self.assertEqual(CoordinateMailMessage.objects.count(), 1)

    @override_settings(GOOGLE_GMAIL_REFRESH_TOKEN="")
    @patch("secondstateapp.coordinate_mail.send_snapshot")
    def test_missing_configuration_is_presend_and_retains_editable_draft(self, transport):
        self.review()
        self.assertEqual(self.send().status_code, 409)
        self.assertFalse(CoordinateMailDelivery.objects.exists())
        self.assertTrue(mail.draft_mail_state(self.draft)["editable"])
        transport.assert_not_called()

    @patch("secondstateapp.coordinate_mail.send_snapshot")
    def test_pause_and_changed_plan_block_even_previously_reviewed_draft(self, transport):
        self.review()
        quote = CoordinateQuote.objects.create(case=self.case, provider_name="Provider", provider_email=self.draft.recipient,
            amount="100", latest_amount="150", accepted_amount="100")
        self.assertEqual(self.send().status_code, 409)
        quote.latest_amount = "100"
        quote.save()
        response = self.client.post(reverse("coordinate_plan", args=[self.case.pk]), {
            "stage": "gathering", "destination": "mar_vista", "handling": "New packing", "notes": ""}, HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 200)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.reviewed_digest, "")
        self.assertEqual(self.send().status_code, 409)
        transport.assert_not_called()

    @patch("secondstateapp.coordinate_mail.send_snapshot")
    def test_deleted_origin_reply_and_inherited_mail_context_cannot_send(self, transport):
        job = CoordinateJob.objects.create(message=self.origin, status="completed")
        reply = CoordinateMessage.objects.create(case=self.case, role="assistant", body="Draft saved", in_reply_to=self.origin)
        self.draft.job = job
        self.draft.save()
        self.review()
        reply.deleted_at = timezone.now()
        reply.save()
        self.assertEqual(self.send().status_code, 409)
        reply.deleted_at = None
        reply.save()
        thread = self.thread()
        inbound = thread.mail_messages.get().message
        inbound_job = CoordinateJob.objects.create(message=inbound, status="completed")
        self.draft.job = inbound_job
        self.draft.save()
        self.origin.deleted_at = timezone.now()
        self.origin.save()
        self.assertEqual(self.send().status_code, 409)
        transport.assert_not_called()

    def test_edit_and_review_reject_stale_content_and_thread_mismatches(self):
        digest = mail.draft_digest(self.draft)
        self.draft.body = "Changed by another staff member"
        self.draft.save()
        self.assertEqual(self.post("coordinate_draft_review", content_digest=digest).status_code, 400)
        self.assertEqual(self.post("coordinate_draft_update", content_digest=digest, recipient=self.draft.recipient,
                                  subject=self.draft.subject, body="Another change").status_code, 400)
        thread = self.thread()
        self.draft.mail_thread = thread
        self.draft.recipient = "different@example.test"
        self.draft.save()
        self.assertEqual(self.post("coordinate_draft_review", content_digest=mail.draft_digest(self.draft)).status_code, 400)

    @patch("secondstateapp.coordinate_mail.send_snapshot", return_value={"id": "reply-out-17", "threadId": "thread-17"})
    def test_reply_requires_known_thread_subject_and_valid_latest_rfc_headers(self, transport):
        thread = self.thread()
        self.draft.mail_thread, self.draft.subject = thread, "Re: Collection details"
        self.draft.save()
        self.review()
        response = self.send()
        self.assertEqual(response.status_code, 200, response.content)
        delivery = CoordinateMailDelivery.objects.get()
        self.assertEqual(delivery.in_reply_to, "<reply-17@provider.example>")
        self.assertEqual(delivery.references, "<reply-17@provider.example>")
        self.assertEqual(delivery.thread_id, thread.pk)
        self.assertEqual(CoordinateMailThread.objects.count(), 1)

    @patch("secondstateapp.coordinate_mail.send_snapshot")
    def test_bad_rfc_headers_never_reach_transport(self, transport):
        thread = self.thread()
        CoordinateMailMessage.objects.filter(thread=thread).update(rfc_message_id="<bad@example.test>\r\nBcc: victim@example.test")
        self.draft.mail_thread = thread
        self.draft.save()
        self.review()
        self.assertEqual(self.send().status_code, 409)
        transport.assert_not_called()

    def test_readiness_is_staff_only_and_does_not_expose_secrets(self):
        url = reverse("coordinate_mail_readiness")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ready"])
        self.assertFalse(response.json()["connection_verified"])
        for secret in ("synthetic-client", "synthetic-secret", "synthetic-refresh"):
            self.assertNotContains(response, secret)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)

    @patch("secondstateapp.coordinate_mail.send_snapshot")
    def test_send_requires_staff_csrf_post_and_exact_case(self, transport):
        self.review()
        url = reverse("coordinate_mail_send", args=[self.case.pk, self.draft.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        protected = Client(enforce_csrf_checks=True)
        protected.force_login(self.staff)
        self.assertEqual(protected.post(url, {}).status_code, 403)
        other = CoordinateCase.objects.create(title="Other", created_by=self.staff)
        self.assertEqual(self.client.post(reverse("coordinate_mail_send", args=[other.pk, self.draft.pk]), {}).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.post(url, {}).status_code, 302)
        transport.assert_not_called()

    def test_mail_context_obeys_message_cutoff_and_origin_deletion(self):
        thread = self.thread()
        item = thread.mail_messages.get()
        self.assertEqual(mail.mail_state(self.case, self.origin.pk)["threads"][0]["messages"], [])
        self.assertEqual(len(mail.mail_state(self.case, item.message_id)["threads"][0]["messages"]), 1)
        self.origin.deleted_at = timezone.now()
        self.origin.save()
        self.assertEqual(mail.mail_state(self.case)["threads"], [])

    def test_mail_display_has_total_body_budget_and_worker_state_is_metadata_only(self):
        thread = self.thread()
        for index in range(6):
            anchor = CoordinateMessage.objects.create(case=self.case, role="system", body="Imported mail")
            CoordinateMailMessage.objects.create(thread=thread, message=anchor, direction="inbound",
                gmail_message_id=f"bounded-{index}", from_email=self.draft.recipient, to_emails=[mail.SENDER],
                subject=self.draft.subject, body_text="x" * 24000, received_at=timezone.now())
        visible = mail.mail_state(self.case)["threads"][0]["messages"]
        self.assertEqual(sum(len(item["body"]) for item in visible), 96000)
        self.assertTrue(any(item["body_truncated"] for item in visible))
        worker_state = mail.mail_state(self.case, anchor.pk)["threads"][0]["messages"]
        self.assertTrue(all(item["body"] == "" and item["context_body_omitted"] for item in worker_state))

    @patch("googleapiclient.discovery.build")
    @patch("google_auth_httplib2.AuthorizedHttp")
    @patch("google.oauth2.credentials.Credentials")
    def test_transport_preserves_snapshot_rfc_headers_thread_and_send_only_scope(self, credentials, http, build):
        thread = self.thread()
        self.draft.mail_thread = thread
        self.draft.save()
        self.review()
        delivery, dispatch = mail.prepare_delivery(self.draft.pk, self.staff, mail.draft_digest(self.draft), uuid4())
        self.assertTrue(dispatch)
        sender = build.return_value.users.return_value.messages.return_value.send
        sender.return_value.execute.return_value = {"id": "outbound-test", "threadId": thread.gmail_thread_id}
        self.assertEqual(mail.send_snapshot(delivery)["id"], "outbound-test")
        payload = sender.call_args.kwargs["body"]
        message = BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(payload["raw"]))
        self.assertEqual(payload["threadId"], thread.gmail_thread_id)
        self.assertEqual(str(message["From"]), mail.SENDER)
        self.assertEqual(str(message["To"]), delivery.recipient)
        self.assertEqual(str(message["Message-ID"]), delivery.rfc_message_id)
        self.assertEqual(str(message["In-Reply-To"]), delivery.in_reply_to)
        self.assertEqual(str(message["References"]), delivery.references)
        self.assertEqual(message.get_content().strip(), delivery.body)
        self.assertEqual(credentials.call_args.kwargs["scopes"], [mail.GMAIL_SEND_SCOPE])
        sender.return_value.execute.assert_called_once_with(num_retries=0)

    @override_settings(GOOGLE_GMAIL_CLIENT_ID=" synthetic-client \n", GOOGLE_GMAIL_CLIENT_SECRET=" synthetic-secret ",
                       GOOGLE_GMAIL_REFRESH_TOKEN="\tsynthetic-refresh\n")
    @patch("google.oauth2.credentials.Credentials")
    def test_credentials_normalize_outer_whitespace_without_broadening_scope(self, credentials):
        mail._credentials()
        self.assertEqual(credentials.call_args.kwargs["client_id"], "synthetic-client")
        self.assertEqual(credentials.call_args.kwargs["client_secret"], "synthetic-secret")
        self.assertEqual(credentials.call_args.kwargs["refresh_token"], "synthetic-refresh")
        self.assertEqual(credentials.call_args.kwargs["scopes"], [mail.GMAIL_SEND_SCOPE])

    @patch("secondstateapp.coordinate_mail.check_mail_connection")
    @patch("secondstateapp.coordinate_mail.send_snapshot")
    def test_connection_form_requires_explicit_staff_csrf_post(self, send, check):
        url = reverse("coordinate_mail_check_connection")
        response = self.client.get(url)
        self.assertContains(response, "Check email connection")
        check.assert_not_called()
        protected = Client(enforce_csrf_checks=True)
        protected.force_login(self.staff)
        self.assertEqual(protected.post(url).status_code, 403)
        check.assert_not_called()
        check.return_value = {"code": "ready", "status_text": "No email was sent."}
        self.assertEqual(self.client.post(url, HTTP_ACCEPT="application/json").json()["code"], "ready")
        self.assertContains(self.client.post(url), "No email was sent.")
        self.client.logout()
        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertEqual(check.call_count, 2)
        send.assert_not_called()

    @patch("googleapiclient.discovery.build")
    @patch("google_auth_httplib2.Request")
    @patch("secondstateapp.coordinate_mail._credentials")
    def test_connection_check_only_refreshes_once_with_explicit_send_grant(self, factory, request, build):
        credential = factory.return_value
        credential.valid = True
        credential.granted_scopes = [mail.GMAIL_SEND_SCOPE]
        credential.refresh.side_effect = lambda call: call(mail.OAUTH_TOKEN_URI, method="POST", body=b"synthetic-secret")
        result = mail.check_mail_connection()
        self.assertTrue(result["auth_valid"])
        self.assertTrue(result["send_grant_verified"])
        self.assertFalse(result["account_identity_verified"])
        self.assertFalse(result["sent"])
        self.assertEqual(result["code"], "ready")
        self.assertEqual(request.call_args.args[0].timeout, 10)
        request.return_value.assert_called_once()
        build.assert_not_called()
        self.assertNotIn("synthetic-secret", str(result))

    @patch("secondstateapp.coordinate_mail._credentials")
    def test_connection_check_does_not_claim_unconfirmed_or_missing_scope(self, factory):
        factory.return_value.valid = True
        for granted, expected in ((None, "send_scope_unconfirmed"), (["openid"], "send_scope_missing")):
            with self.subTest(granted=granted):
                factory.return_value.granted_scopes = granted
                result = mail.check_mail_connection()
                self.assertTrue(result["auth_valid"])
                self.assertFalse(result["send_grant_verified"])
                self.assertEqual(result["code"], expected)

    @patch("google_auth_httplib2.Request")
    @patch("secondstateapp.coordinate_mail._credentials")
    def test_connection_refresh_retry_and_redirect_are_bounded_before_second_network_call(self, factory, request):
        def repeated(call):
            call(mail.OAUTH_TOKEN_URI)
            call(mail.OAUTH_TOKEN_URI)
        factory.return_value.refresh.side_effect = repeated
        self.assertEqual(mail.check_mail_connection()["code"], "transport_error")
        request.return_value.assert_called_once()
        request.reset_mock()
        factory.return_value.refresh.side_effect = lambda call: call("https://other.example.test/token")
        self.assertEqual(mail.check_mail_connection()["code"], "transport_error")
        request.return_value.assert_not_called()

    @override_settings(GOOGLE_GMAIL_REFRESH_TOKEN=" ")
    @patch("secondstateapp.coordinate_mail._credentials")
    def test_connection_missing_configuration_never_calls_oauth(self, factory):
        self.assertEqual(mail.check_mail_connection()["code"], "configuration_missing")
        factory.assert_not_called()

    @patch("secondstateapp.coordinate_mail._credentials")
    def test_auth_errors_expose_only_allowlisted_enum_without_provider_text(self, factory):
        from google.auth.exceptions import RefreshError
        error = RefreshError("synthetic-secret token private body", {
            "error": "invalid_grant", "error_description": "synthetic-refresh private body"})
        factory.return_value.refresh.side_effect = error
        result = mail.check_mail_connection()
        self.assertEqual(result["code"], "oauth_invalid_grant")
        self.assertFalse(result["auth_valid"])
        for secret in ("synthetic-secret", "synthetic-refresh", "private body"):
            self.assertNotIn(secret, str(result))
        self.assertEqual(mail.safe_mail_error(RefreshError("sensitive", {"error": "sensitive"})), "oauth_refresh_failed")

    def test_new_delivery_receipt_uses_postgresql_safe_lock_on_nullable_thread_join(self):
        from django.db.backends.postgresql.base import DatabaseWrapper
        from django.db.models.query import QuerySet
        self.review()
        delivery, _ = mail.prepare_delivery(self.draft.pk, self.staff, mail.draft_digest(self.draft), uuid4())
        self.assertIsNone(delivery.thread_id)
        locked = []
        original_get = QuerySet.get

        def capture_get(query, *args, **kwargs):
            if query.model is CoordinateMailDelivery and query.query.select_for_update:
                locked.append(query.query.clone())
            return original_get(query, *args, **kwargs)

        with patch.object(QuerySet, "get", capture_get):
            saved = mail.record_delivery_success(delivery.pk, "postgres-outbound", "postgres-thread")
        self.assertEqual(saved.status, "sent")
        self.assertEqual(len(locked), 1)
        # Compile the actual receipt query using the production database backend,
        # without connecting to a database. SQLite silently omits row locks.
        backend = DatabaseWrapper({"ENGINE": "django.db.backends.postgresql", "NAME": "unused"}, alias="compiler-only")
        with patch.object(backend, "get_autocommit", return_value=False):
            sql, _ = locked[0].get_compiler(connection=backend).as_sql()
        self.assertIn("LEFT OUTER JOIN", sql)
        self.assertIn('FOR UPDATE OF "secondstateapp_coordinatemaildelivery"', sql)
        self.assertNotIn("coordinatemailthread", sql.split("FOR UPDATE", 1)[1])

    def test_observed_rfc_identity_updates_correspondence_without_changing_delivery_snapshot(self):
        self.review()
        delivery, _ = mail.prepare_delivery(self.draft.pk, self.staff, mail.draft_digest(self.draft), uuid4())
        original = delivery.rfc_message_id
        receipt = mail.record_delivery_success(delivery.pk, "observed-outbound", "observed-thread",
            require_visible=True, observed_rfc_message_id="<actual-first@mail.gmail.com>")
        self.assertEqual(receipt.rfc_message_id, original)
        self.assertEqual(CoordinateMailMessage.objects.get().rfc_message_id, "<actual-first@mail.gmail.com>")
        mail.record_delivery_success(delivery.pk, "observed-outbound", "observed-thread",
            require_visible=True, observed_rfc_message_id="<actual-observed@mail.gmail.com>")
        self.assertEqual(CoordinateMailMessage.objects.get().rfc_message_id, "<actual-observed@mail.gmail.com>")
        self.assertEqual(CoordinateMailDelivery.objects.get().rfc_message_id, original)
        self.assertEqual(CoordinateMailMessage.objects.count(), 1)
        with self.assertRaises(ValueError):
            mail.record_delivery_success(delivery.pk, "observed-outbound", "observed-thread",
                observed_rfc_message_id="<malicious@example.test>\r\nBcc: other@example.test")

    def test_database_failure_taxonomy_never_persists_exception_text(self):
        from django.db import DatabaseError
        error = DatabaseError("synthetic-secret private body")
        cause = Exception("sensitive database statement")
        cause.sqlstate = "0A000"
        error.__cause__ = cause
        self.assertEqual(mail.safe_mail_error(error), "receipt_database_unsupported")
        cause.sqlstate = "23505"
        self.assertEqual(mail.safe_mail_error(error), "receipt_duplicate")
        cause.sqlstate = "unexpected-sensitive-code"
        self.assertEqual(mail.safe_mail_error(error), "receipt_persistence_error")

    @patch("secondstateapp.coordinate_mail.send_snapshot", return_value={"id": "durable-outbound", "threadId": "durable-thread"})
    def test_rich_receipt_failure_retains_committed_gmail_ids_and_never_resends(self, transport):
        from django.db import DatabaseError
        self.review()
        request_id = uuid4()
        with patch("secondstateapp.coordinate_mail.record_delivery_success", side_effect=DatabaseError("private server detail")):
            response = self.send(request_id)
        self.assertEqual(response.status_code, 200)
        saved = CoordinateMailDelivery.objects.get()
        self.assertEqual(saved.status, "unknown")
        self.assertEqual(saved.error_code, "receipt_persistence_error")
        self.assertEqual(saved.gmail_message_id, "durable-outbound")
        self.assertEqual(saved.gmail_thread_id, "durable-thread")
        self.assertFalse(CoordinateMailMessage.objects.exists())
        self.assertEqual(self.send(request_id).status_code, 200)
        transport.assert_called_once()
        self.assertNotContains(response, "private server detail")
        with self.assertRaises(ValueError):
            mail.record_provider_receipt(saved.pk, "conflicting-outbound", "durable-thread")
        with self.assertRaises(ValueError):
            mail.record_delivery_success(saved.pk, "conflicting-outbound", "durable-thread")
        mail.record_delivery_success(saved.pk, "durable-outbound", "durable-thread")
        self.assertEqual(CoordinateMailMessage.objects.count(), 1)

    def test_observed_delivery_time_preserves_provider_time_and_rejects_invalid_observation(self):
        self.review()
        delivery, _ = mail.prepare_delivery(self.draft.pk, self.staff, mail.draft_digest(self.draft), uuid4())
        actual = delivery.requested_at - timedelta(seconds=1)
        mail.record_delivery_success(delivery.pk, "timed-outbound", "timed-thread", observed_received_at=actual)
        self.assertEqual(CoordinateMailDelivery.objects.get().sent_at, actual)
        self.assertEqual(CoordinateMailMessage.objects.get().received_at, actual)
        corrected = delivery.requested_at
        mail.record_delivery_success(delivery.pk, "timed-outbound", "timed-thread", observed_received_at=corrected)
        self.assertEqual(CoordinateMailDelivery.objects.get().sent_at, corrected)
        self.assertEqual(CoordinateMailMessage.objects.get().received_at, corrected)
        for invalid in (timezone.now() + timedelta(minutes=2), delivery.requested_at - timedelta(minutes=2),
                        delivery.requested_at.replace(tzinfo=None)):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                mail.record_delivery_success(delivery.pk, "timed-outbound", "timed-thread", observed_received_at=invalid)

    @patch("secondstateapp.coordinate_mail.send_snapshot")
    def test_immediate_reply_cannot_dispatch_until_actual_parent_rfc_header_is_observed(self, transport):
        self.review()
        delivery, _ = mail.prepare_delivery(self.draft.pk, self.staff, mail.draft_digest(self.draft), uuid4())
        sent = mail.record_delivery_success(delivery.pk, "unobserved-outbound", "unobserved-thread")
        self.assertEqual(CoordinateMailMessage.objects.get().rfc_message_id, "")
        self.assertTrue(CoordinateMailDelivery.objects.get().rfc_message_id.startswith("<coordinate-"))
        self.draft = CoordinateDraft.objects.create(case=self.case, recipient=sent.recipient,
            subject="Re: " + sent.subject, body="Please confirm the window.", purpose="Follow up", mail_thread=sent.thread)
        self.review()
        response = self.send()
        self.assertEqual(response.status_code, 409)
        self.assertIn("verified message header", response.json()["error"])
        transport.assert_not_called()
        self.assertEqual(CoordinateMailDelivery.objects.count(), 1)
        mail.record_delivery_success(sent.pk, "unobserved-outbound", "unobserved-thread", require_visible=True,
            observed_rfc_message_id="<actual-sent@mail.gmail.com>")
        transport.return_value = {"id": "followup-outbound", "threadId": "unobserved-thread"}
        self.assertEqual(self.send().status_code, 200)
        transport.assert_called_once()
        followup = CoordinateMailDelivery.objects.get(draft=self.draft)
        self.assertEqual(followup.in_reply_to, "<actual-sent@mail.gmail.com>")
