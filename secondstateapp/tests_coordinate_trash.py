"""Emptying Coordinate trash is explicit, snapshot-scoped and irreversible in the UI."""

from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4
import time

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    CoordinateActivity, CoordinateBrief, CoordinateCase, CoordinateDocument,
    CoordinateDraft, CoordinateJob, CoordinateMailDelivery, CoordinateMessage,
    CoordinateOutreachPolicy, CoordinatePlan, CoordinateQuoteInquiry, CoordinateResearch,
)


class CoordinateEmptyTrashTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user("trash-staff", is_staff=True)
        self.client.force_login(self.staff)
        self.url = reverse("coordinate_empty_trash")

    def case(self, *, trashed=True, status="processing"):
        case = CoordinateCase.objects.create(
            title="Synthetic trash case", created_by=self.staff,
            deleted_at=timezone.now() if trashed else None,
            deleted_by=self.staff if trashed else None,
        )
        message = CoordinateMessage.objects.create(
            case=case, role="staff", body="Synthetic case contents.",
            author=self.staff, client_message_id=uuid4(),
        )
        job = CoordinateJob.objects.create(
            message=message, status=status, claim_token=uuid4(),
            lease_expires_at=timezone.now() + timedelta(minutes=10),
        )
        return case, message, job

    def confirmation(self, client=None):
        response = (client or self.client).get(self.url)
        self.assertEqual(response.status_code, 200)
        return response.context["trash_token"]

    def empty(self, token, client=None, **fields):
        return (client or self.client).post(self.url, {
            "trash_token": token, "confirm_empty_trash": "yes", **fields,
        })

    def test_visible_control_links_to_confirmation_without_removing_anything(self):
        case, _, job = self.case()
        response = self.client.get(reverse("coordinate"))
        self.assertContains(response, self.url)
        self.assertContains(response, "Empty trash")
        response = self.client.get(self.url)
        self.assertContains(response, 'name="trash_token"')
        self.assertContains(response, 'name="confirm_empty_trash"')
        case.refresh_from_db()
        job.refresh_from_db()
        self.assertIsNone(case.purged_at)
        self.assertEqual(job.status, "processing")

    def test_only_signed_trashed_snapshot_is_purged_and_jobs_are_cancelled(self):
        active, _, active_job = self.case(trashed=False)
        first, _, pending = self.case()
        second, _, complete = self.case(status="completed")
        token = self.confirmation()
        later, _, later_job = self.case()

        response = self.empty(token)
        self.assertEqual(response.status_code, 302)
        for case in (first, second):
            case.refresh_from_db()
            self.assertIsNotNone(case.purged_at)
            self.assertIsNotNone(case.deleted_at)
            audit = CoordinateActivity.objects.get(case=case, event="case_purged")
            self.assertEqual(audit.details["actor_id"], self.staff.pk)
        pending.refresh_from_db()
        complete.refresh_from_db()
        self.assertEqual(pending.status, "cancelled")
        self.assertEqual(complete.status, "completed")
        for job in (pending, complete):
            self.assertIsNone(job.claim_token)
            self.assertIsNone(job.lease_expires_at)
        for case, job in ((active, active_job), (later, later_job)):
            case.refresh_from_db()
            job.refresh_from_db()
            self.assertIsNone(case.purged_at)
            self.assertEqual(job.status, "processing")

    def test_repeated_confirmation_is_idempotent(self):
        case, _, _ = self.case()
        token = self.confirmation()
        self.assertEqual(self.empty(token).status_code, 302)
        case.refresh_from_db()
        purged_at = case.purged_at
        self.assertEqual(self.empty(token).status_code, 302)
        case.refresh_from_db()
        self.assertEqual(case.purged_at, purged_at)
        self.assertEqual(CoordinateActivity.objects.filter(case=case, event="case_purged").count(), 1)

    def test_restored_snapshot_is_rejected_without_partially_purging_other_cases(self):
        first, _, _ = self.case()
        second, _, _ = self.case()
        token = self.confirmation()
        CoordinateCase.objects.filter(pk=first.pk).update(deleted_at=None, deleted_by=None)
        self.assertEqual(self.empty(token).status_code, 409)
        for case in (first, second):
            case.refresh_from_db()
            self.assertIsNone(case.purged_at)
        self.assertFalse(CoordinateActivity.objects.filter(event="case_purged").exists())

    def test_restored_then_retrashed_snapshot_is_rejected(self):
        case, _, _ = self.case()
        token = self.confirmation()
        CoordinateCase.objects.filter(pk=case.pk).update(deleted_at=case.deleted_at + timedelta(seconds=1))
        self.assertEqual(self.empty(token).status_code, 409)
        case.refresh_from_db()
        self.assertIsNone(case.purged_at)

    def test_confirmation_token_and_checkbox_are_required(self):
        case, _, _ = self.case()
        token = self.confirmation()
        for payload in ({}, {"trash_token": token}, {"trash_token": token, "confirm_empty_trash": "no"},
                        {"trash_token": "invalid", "confirm_empty_trash": "yes"}):
            self.assertEqual(self.client.post(self.url, payload).status_code, 400)
        case.refresh_from_db()
        self.assertIsNone(case.purged_at)

    def test_confirmation_is_bound_to_the_staff_member(self):
        case, _, _ = self.case()
        token = self.confirmation()
        other = get_user_model().objects.create_user("other-trash-staff", is_staff=True)
        self.client.force_login(other)
        self.assertEqual(self.empty(token).status_code, 400)
        case.refresh_from_db()
        self.assertIsNone(case.purged_at)

    def test_expired_confirmation_cannot_empty_trash(self):
        case, _, _ = self.case()
        token = self.confirmation()
        with patch("django.core.signing.time.time", return_value=time.time() + 86400):
            self.assertEqual(self.empty(token).status_code, 400)
        case.refresh_from_db()
        self.assertIsNone(case.purged_at)

    def test_staff_authentication_and_csrf_are_required(self):
        case, _, _ = self.case()
        token = self.confirmation()
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.assertEqual(self.empty(token).status_code, 302)
        ordinary = get_user_model().objects.create_user("trash-member")
        self.client.force_login(ordinary)
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.assertEqual(self.empty(token).status_code, 302)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.staff)
        token = self.confirmation(csrf_client)
        self.assertEqual(self.empty(token, csrf_client).status_code, 403)
        case.refresh_from_db()
        self.assertIsNone(case.purged_at)

    def test_purged_cases_disappear_from_case_and_trash_views_and_cannot_restore(self):
        active, _, _ = self.case(trashed=False)
        purged, _, _ = self.case()
        self.assertEqual(self.empty(self.confirmation()).status_code, 302)
        state = self.client.get(reverse("coordinate_state"), {"case": str(active.pk)}).json()
        self.assertEqual([case["id"] for case in state["cases"]], [str(active.pk)])
        self.assertEqual(state["trash_cases"], [])
        page = self.client.get(reverse("coordinate"))
        self.assertEqual(page.context["selected_case"]["id"], str(active.pk))
        self.assertNotContains(page, str(purged.pk))
        self.assertEqual(self.client.get(reverse("coordinate_case", args=[purged.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("coordinate_state"), {"case": str(purged.pk)}).status_code, 404)
        self.assertEqual(self.client.post(reverse("coordinate_restore_case", args=[purged.pk])).status_code, 404)

    def test_removing_last_trashed_case_redirects_to_a_usable_new_case_page(self):
        case, _, _ = self.case()
        response = self.empty(self.confirmation())
        self.assertEqual(response.status_code, 302)
        landing = self.client.get(response.url)
        self.assertEqual(landing.status_code, 200)
        self.assertIsNone(landing.context["selected_case"])
        self.assertEqual(landing.context["trash_cases"], [])

    def test_case_records_receipts_and_private_document_bytes_are_retained(self):
        case, message, job = self.case(status="completed")
        plan = CoordinatePlan.objects.create(case=case, notes="Synthetic saved plan.")
        draft = CoordinateDraft.objects.create(case=case, job=job, recipient="packer@example.test",
            subject="Synthetic quote request", body="Synthetic immutable wording.")
        brief = CoordinateBrief.objects.create(case=case, job=job, payload={"summary": "Synthetic brief."})
        research = CoordinateResearch.objects.create(case=case, job=job, source_url="https://example.test/lot/1",
            text="Synthetic source excerpt.", fetched_at=timezone.now())
        document = CoordinateDocument.objects.create(case=case, message=message, title="Synthetic PDF",
            kind="pdf", original_pdf=b"%PDF-synthetic", text="Synthetic document text.",
            byte_size=14, content_digest="a" * 64, extraction_status="ready")
        policy = CoordinateOutreachPolicy.objects.create(case=case, mode="test", destination="duarte",
            destination_address="Synthetic test destination", authorized_by=self.staff, originating_message=message)
        inquiry = CoordinateQuoteInquiry.objects.create(case=case, mode="test", provider_email=draft.recipient,
            provider_name="Synthetic Packer", draft=draft)
        delivery = CoordinateMailDelivery.objects.create(draft=draft, request_id=uuid4(), status="sent",
            sender_email="jeremy@secondstate.art", recipient=draft.recipient, subject=draft.subject,
            body=draft.body, reviewed_digest="b" * 64, approval_snapshot={"originating_message_id": message.pk},
            rfc_message_id=f"<synthetic-{uuid4()}@example.test>", gmail_message_id="saved-receipt",
            gmail_thread_id="saved-thread")
        before = {"request_id": delivery.request_id, "body": delivery.body, "rfc_message_id": delivery.rfc_message_id,
                  "gmail_message_id": delivery.gmail_message_id, "gmail_thread_id": delivery.gmail_thread_id}
        submission_id = message.client_message_id
        self.assertEqual(self.empty(self.confirmation()).status_code, 302)
        for record in (case, message, job, plan, draft, brief, research, document, policy, inquiry, delivery):
            record.refresh_from_db()
        self.assertEqual(document.original_pdf, b"%PDF-synthetic")
        self.assertEqual(message.client_message_id, submission_id)
        for field, value in before.items():
            self.assertEqual(getattr(delivery, field), value)
        self.assertEqual(delivery.status, "sent")
        download = reverse("coordinate_intake_download", args=[case.pk, document.pk])
        self.assertEqual(self.client.get(download).status_code, 404)

    def test_late_provider_receipt_can_finalize_without_reopening_purged_case(self):
        from .coordinate_mail import record_delivery_success, record_provider_receipt

        case, message, job = self.case(status="completed")
        draft = CoordinateDraft.objects.create(case=case, job=job, recipient="packer@example.test",
            subject="Synthetic in-flight request", body="Synthetic approved body.")
        delivery = CoordinateMailDelivery.objects.create(draft=draft, request_id=uuid4(), status="sending",
            sender_email="jeremy@secondstate.art", recipient=draft.recipient, subject=draft.subject,
            body=draft.body, reviewed_digest="c" * 64, approval_snapshot={"originating_message_id": message.pk},
            rfc_message_id=f"<synthetic-{uuid4()}@example.test>")
        self.assertEqual(self.empty(self.confirmation()).status_code, 302)
        record_provider_receipt(delivery.pk, "late-receipt", "late-thread")
        record_delivery_success(delivery.pk, "late-receipt", "late-thread")
        delivery.refresh_from_db()
        case.refresh_from_db()
        self.assertEqual(delivery.status, "sent")
        self.assertEqual(delivery.gmail_message_id, "late-receipt")
        self.assertIsNotNone(case.purged_at)
        self.assertIsNotNone(case.deleted_at)
        self.assertEqual(self.client.get(reverse("coordinate_case", args=[case.pk])).status_code, 404)
