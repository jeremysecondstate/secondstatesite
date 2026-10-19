"""Private intake, provenance, retry, and bounded PDF parsing contracts."""

from io import BytesIO
import json
import subprocess
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from .coordinate_intake import (IntakeError, MAX_CASE_BYTES, MAX_PDF_BYTES, extract_pdf,
                                intake_context, intake_state, validate_document_restore)
from .coordinate_intake_models import CoordinateDocument
from .models import CoordinateCase, CoordinateJob, CoordinateMessage


def fixture_pdf(text="", pages=1, encrypted=False):
    writer = PdfWriter()
    for _ in range(pages):
        page = writer.add_blank_page(width=300, height=300)
        if text:
            font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                                     NameObject("/Subtype"): NameObject("/Type1"),
                                     NameObject("/BaseFont"): NameObject("/Helvetica")})
            page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({
                NameObject("/F1"): writer._add_object(font),
            })})
            stream = DecodedStreamObject()
            escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            stream.set_data(("BT /F1 12 Tf 20 260 Td (" + escaped + ") Tj ET").encode("ascii"))
            page[NameObject("/Contents")] = writer._add_object(stream)
    if encrypted:
        writer.encrypt("synthetic-password")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


class CoordinatePDFExtractionTests(SimpleTestCase):
    def test_real_subprocess_extracts_visible_text(self):
        result = extract_pdf(fixture_pdf("Lot 17. Sheet 8 x 10 inches. Framed."))
        self.assertEqual(result["status"], "ready")
        self.assertIn("8 x 10 inches", result["text"])
        self.assertEqual(result["error"], "")

    def test_empty_page_retains_explicit_no_ocr_status(self):
        result = extract_pdf(fixture_pdf())
        self.assertEqual(result["status"], "no_text")
        self.assertEqual(result["text"], "")
        self.assertIn("OCR was not performed", result["error"])

    def test_page_and_character_limits_report_partial_text(self):
        result = extract_pdf(fixture_pdf("Synthetic lot facts. " * 100, pages=21))
        self.assertEqual(result["status"], "truncated")
        self.assertLessEqual(len(result["text"]), 24000)
        self.assertIn("20 pages", result["error"])

    def test_encrypted_and_malformed_pdfs_are_rejected_without_raw_diagnostics(self):
        with self.assertRaisesRegex(IntakeError, "Encrypted PDFs"):
            extract_pdf(fixture_pdf("private synthetic text", encrypted=True))
        with self.assertRaises(IntakeError) as failure:
            extract_pdf(b"%PDF-1.7\nprivate-synthetic-parser-content")
        self.assertNotIn("private-synthetic-parser-content", str(failure.exception))

    def test_timeout_and_process_failure_do_not_expose_diagnostics(self):
        with patch("secondstateapp.coordinate_intake.subprocess.run", side_effect=subprocess.TimeoutExpired("parser", 10)):
            with self.assertRaisesRegex(IntakeError, "10 seconds"):
                extract_pdf(b"%PDF-1.7")
        with patch("secondstateapp.coordinate_intake.subprocess.run", return_value=subprocess.CompletedProcess([], 1, b"secret", b"private stderr")):
            with self.assertRaises(IntakeError) as failure:
                extract_pdf(b"%PDF-1.7")
            self.assertNotIn("secret", str(failure.exception))

    def test_full_length_non_ascii_extraction_fits_output_bound(self):
        result = {"text": "\U0001f4e6" * 24000, "status": "ready", "error": ""}
        output = json.dumps(result).encode("ascii")
        with patch("secondstateapp.coordinate_intake.subprocess.run", return_value=subprocess.CompletedProcess([], 0, output, b"")):
            self.assertEqual(extract_pdf(b"%PDF-1.7")["text"], result["text"])


@override_settings(COORDINATE_DRAFT_WORKFLOW_ENABLED=True)
class CoordinateIntakeTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user("intake-staff", is_staff=True)
        self.case = CoordinateCase.objects.create(title="Synthetic intake case", created_by=self.staff)
        self.client.force_login(self.staff)

    def add(self, *, case=None, token=None, title="Synthetic invoice", text="Lot 17, pickup by Friday.", pdf=None):
        data = {"title": title, "client_message_id": str(token or uuid4())}
        if text is not None:
            data["text"] = text
        if pdf is not None:
            data["pdf"] = SimpleUploadedFile("invoice.pdf", pdf, content_type="application/pdf")
        return self.client.post(reverse("coordinate_intake_add", args=[(case or self.case).pk]),
                                data, HTTP_ACCEPT="application/json")

    def direct_document(self, text="Synthetic lot facts", status="ready", case=None):
        case = case or self.case
        message = CoordinateMessage.objects.create(case=case, role="staff", author=self.staff,
                                                    body="Added synthetic document", client_message_id=uuid4())
        return CoordinateDocument.objects.create(case=case, message=message, title="Synthetic document",
            kind="text", text=text, byte_size=len(text.encode()), content_digest="a" * 64,
            extraction_status=status)

    def test_text_intake_creates_one_staff_message_and_job_and_private_download(self):
        response = self.add(text="lot 17\nprovider@example.com\nready for pickup")
        self.assertEqual(response.status_code, 200, response.content)
        document = CoordinateDocument.objects.get()
        self.assertEqual(document.message.author_id, self.staff.pk)
        self.assertEqual(CoordinateJob.objects.filter(message=document.message).count(), 1)
        self.assertEqual(document.kind, "text")
        self.assertEqual(document.original_pdf, b"")
        self.assertIn("document:" + str(document.pk), document.message.body)
        state = intake_state(self.case)["documents"][0]
        self.assertNotIn("original_pdf", state)
        self.assertNotIn("/media/", state["download_url"])
        download = self.client.get(state["download_url"])
        self.assertEqual(download.status_code, 200)
        self.assertEqual(b"".join(download.streaming_content).decode(), document.text)
        self.assertIn("attachment", download["Content-Disposition"])
        self.assertEqual(download["X-Content-Type-Options"], "nosniff")
        self.assertIn("private", download["Cache-Control"])
        self.assertIn("no-store", download["Cache-Control"])

    def test_idempotency_binds_full_document_author_and_case(self):
        token = uuid4()
        self.assertEqual(self.add(token=token).status_code, 200)
        self.assertEqual(self.add(token=token).status_code, 200)
        self.assertEqual(CoordinateDocument.objects.count(), 1)
        self.assertEqual(CoordinateJob.objects.count(), 1)
        self.assertEqual(self.add(token=token, text="changed facts").status_code, 409)
        other = CoordinateCase.objects.create(title="Other", created_by=self.staff)
        self.assertEqual(self.add(case=other, token=token).status_code, 409)
        colleague = get_user_model().objects.create_user("intake-colleague", is_staff=True)
        self.client.force_login(colleague)
        self.assertEqual(self.add(token=token).status_code, 409)

    def test_pdf_original_and_no_text_status_are_retained(self):
        content = fixture_pdf()
        response = self.add(text=None, pdf=content)
        self.assertEqual(response.status_code, 200, response.content)
        document = CoordinateDocument.objects.get()
        self.assertEqual(bytes(document.original_pdf), content)
        self.assertEqual(document.extraction_status, "no_text")
        context = intake_context(self.case, document.message_id)[0]
        self.assertEqual(context["text"], "")
        self.assertEqual(context["status"], "no_text")
        self.assertIn("OCR", context["extraction_error"])
        download = self.client.get(reverse("coordinate_intake_download", args=[self.case.pk, document.pk]))
        self.assertEqual(b"".join(download.streaming_content), content)
        self.assertEqual(download["Content-Type"], "application/pdf")

    def test_pdf_retry_does_not_repeat_extraction(self):
        token, content = uuid4(), fixture_pdf("A synthetic shipping invoice")
        self.assertEqual(self.add(token=token, text=None, pdf=content).status_code, 200)
        with patch("secondstateapp.coordinate_intake.extract_pdf") as extraction:
            self.assertEqual(self.add(token=token, text=None, pdf=content).status_code, 200)
        extraction.assert_not_called()
        self.assertEqual(CoordinateJob.objects.count(), 1)

    def test_invalid_empty_conflicting_or_oversized_intake_creates_no_records(self):
        for values in ({"text": ""}, {"title": "x" * 201}, {"text": "x" * 24001},
                       {"text": "text and file", "pdf": fixture_pdf()},
                       {"text": None, "pdf": b"not a PDF"},
                       {"text": None, "pdf": b"%PDF-" + b"x" * MAX_PDF_BYTES},
                       {"text": None, "pdf": fixture_pdf(encrypted=True)},
                       {"token": "invalid-token"}):
            with self.subTest(values=list(values)):
                self.assertEqual(self.add(**values).status_code, 400)
        self.assertEqual(CoordinateDocument.objects.count(), 0)
        self.assertEqual(CoordinateMessage.objects.count(), 0)
        self.assertEqual(CoordinateJob.objects.count(), 0)

    def test_active_case_total_limit_excludes_trashed_messages(self):
        document = self.direct_document()
        document.byte_size = MAX_CASE_BYTES
        document.save(update_fields=["byte_size"])
        self.assertEqual(self.add().status_code, 400)
        document.message.deleted_at = timezone.now()
        document.message.save(update_fields=["deleted_at"])
        self.assertEqual(self.add().status_code, 200)

    def test_restoring_document_observes_the_same_active_capacity_limit(self):
        document = self.direct_document()
        document.message.deleted_at = timezone.now()
        document.message.save(update_fields=["deleted_at"])
        active = self.direct_document()
        active.byte_size = MAX_CASE_BYTES
        active.save(update_fields=["byte_size"])
        with self.assertRaisesRegex(IntakeError, "20 MiB"):
            validate_document_restore(self.case, document.message)
        active.message.deleted_at = timezone.now()
        active.message.save(update_fields=["deleted_at"])
        validate_document_restore(self.case, document.message)

    def test_restore_post_refuses_over_capacity_without_restoring_context_or_job(self):
        self.assertEqual(self.add().status_code, 200)
        document = CoordinateDocument.objects.get()
        delete_url = reverse("coordinate_delete_message", args=[self.case.pk, document.message_id])
        restore_url = reverse("coordinate_restore_message", args=[self.case.pk, document.message_id])
        self.assertEqual(self.client.post(delete_url, HTTP_ACCEPT="application/json").status_code, 200)
        active = self.direct_document()
        active.byte_size = MAX_CASE_BYTES
        active.save(update_fields=["byte_size"])
        response = self.client.post(restore_url, HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 409)
        self.assertIn("20 MiB", response.json()["error"])
        document.message.refresh_from_db()
        self.assertIsNotNone(document.message.deleted_at)
        self.assertEqual(CoordinateJob.objects.get(message=document.message).status, "cancelled")
        download_url = reverse("coordinate_intake_download", args=[self.case.pk, document.pk])
        self.assertEqual(self.client.get(download_url).status_code, 404)
        self.assertNotIn(str(document.pk), json.dumps(intake_context(self.case, active.message_id)))
        self.assertEqual(self.client.post(reverse("coordinate_delete_message", args=[self.case.pk, active.message_id]),
                                         HTTP_ACCEPT="application/json").status_code, 200)
        self.assertEqual(self.client.post(restore_url, HTTP_ACCEPT="application/json").status_code, 200)
        self.assertEqual(CoordinateJob.objects.get(message=document.message).status, "queued")
        self.assertEqual(self.client.get(download_url).status_code, 200)

    def test_multiple_files_are_not_silently_ignored_and_full_cases_skip_parser(self):
        url = reverse("coordinate_intake_add", args=[self.case.pk])
        content = fixture_pdf()
        data = {"title": "Two files", "client_message_id": str(uuid4()), "pdf": [
            SimpleUploadedFile("one.pdf", content), SimpleUploadedFile("two.pdf", content),
        ]}
        self.assertEqual(self.client.post(url, data, HTTP_ACCEPT="application/json").status_code, 400)
        self.assertEqual(CoordinateDocument.objects.count(), 0)
        document = self.direct_document()
        document.byte_size = MAX_CASE_BYTES
        document.save(update_fields=["byte_size"])
        with patch("secondstateapp.coordinate_intake.extract_pdf") as extraction:
            self.assertEqual(self.add(text=None, pdf=content).status_code, 400)
        extraction.assert_not_called()

    def test_only_active_staff_can_upload_or_download_and_csrf_is_enforced(self):
        document = self.direct_document()
        urls = [reverse("coordinate_intake_add", args=[self.case.pk]),
                reverse("coordinate_intake_download", args=[self.case.pk, document.pk])]
        for user in (None, get_user_model().objects.create_user("ordinary"),
                     get_user_model().objects.create_user("inactive", is_staff=True, is_active=False)):
            client = Client()
            if user:
                client.force_login(user)
            for method, url in zip((client.post, client.get), urls):
                with self.subTest(user=user, url=url):
                    self.assertIn(method(url).status_code, (302, 401, 403))
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.staff)
        self.assertEqual(csrf_client.post(urls[0], {"title": "No CSRF", "text": "Facts", "client_message_id": str(uuid4())}).status_code, 403)

    def test_download_cannot_cross_cases_or_read_trashed_input_or_case(self):
        document = self.direct_document()
        other = CoordinateCase.objects.create(title="Other", created_by=self.staff)
        self.assertEqual(self.client.get(reverse("coordinate_intake_download", args=[other.pk, document.pk])).status_code, 404)
        document.message.deleted_at = timezone.now()
        document.message.save(update_fields=["deleted_at"])
        url = reverse("coordinate_intake_download", args=[self.case.pk, document.pk])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(intake_context(self.case, document.message_id), [])
        document.message.deleted_at = None
        document.message.save(update_fields=["deleted_at"])
        self.case.deleted_at = timezone.now()
        self.case.save(update_fields=["deleted_at"])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.add().status_code, 409)

    def test_existing_message_delete_and_restore_control_document_visibility(self):
        self.assertEqual(self.add().status_code, 200)
        document = CoordinateDocument.objects.get()
        for name, count in (("coordinate_delete_message", 0), ("coordinate_restore_message", 1)):
            response = self.client.post(reverse(name, args=[self.case.pk, document.message_id]), HTTP_ACCEPT="application/json")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(intake_context(self.case, document.message_id)), count)

    def test_worker_context_excludes_future_other_case_and_binary_and_bounds_text(self):
        documents = [self.direct_document(text=f"Doc {index}: " + "x" * 23990) for index in range(10)]
        other = CoordinateCase.objects.create(title="Other", created_by=self.staff)
        self.direct_document(text="not this case", case=other)
        future = self.direct_document(text="future document")
        result = intake_context(self.case, documents[-1].message_id)
        self.assertEqual(len(result), 8)
        self.assertEqual(result[0]["id"], str(documents[-1].pk))
        self.assertLessEqual(sum(len(item["text"]) for item in result), 96000)
        serialized = json.dumps(result)
        self.assertNotIn(str(future.pk), serialized)
        self.assertNotIn("not this case", serialized)
        self.assertNotIn("original_pdf", serialized)
        self.assertTrue(any(item["context_truncated"] for item in result))

    @override_settings(COORDINATE_DRAFT_WORKFLOW_ENABLED=False)
    def test_disabled_workflow_does_not_accept_or_supply_documents(self):
        document = self.direct_document()
        self.assertEqual(self.add().status_code, 503)
        self.assertEqual(intake_context(self.case, document.message_id), [])
