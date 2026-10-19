"""Staff-only, bounded document intake and safe worker text context."""

from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import UUID, uuid4

from django.contrib.admin.views.decorators import staff_member_required
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.db.models.functions import Substr
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from .coordinate_intake_models import CoordinateDocument
from .coordinate_shipping import enabled
from .models import CoordinateCase, CoordinateMessage


MAX_PDF_BYTES = 5 * 1024 * 1024
MAX_CASE_BYTES = 20 * 1024 * 1024
MAX_TEXT = 24000
MAX_CONTEXT_TEXT = 96000
PDF_TIMEOUT = 10


def active_documents(case, max_message_id=None):
    query = CoordinateDocument.objects.filter(case_id=case.pk, case__deleted_at__isnull=True,
                                               message__deleted_at__isnull=True).defer("original_pdf")
    if max_message_id is not None:
        query = query.filter(message_id__lte=max_message_id)
    return query


def validate_document_restore(case, message):
    """Call under the case write lock before restoring a document's message."""
    if not message.deleted_at:
        return
    document = CoordinateDocument.objects.filter(message_id=message.pk, case_id=case.pk).only("byte_size").first()
    if document is None:
        return
    total = active_documents(case).aggregate(total=Sum("byte_size"))["total"] or 0
    if total + document.byte_size > MAX_CASE_BYTES:
        raise IntakeError("Restoring this document would exceed the case's 20 MiB active-document limit.")


def _metadata(document):
    return {"id": str(document.pk), "source_ref": "document:" + str(document.pk),
            "message_id": document.message_id, "title": document.title, "kind": document.kind,
            "filename": document.filename, "byte_size": document.byte_size,
            "extraction_status": document.extraction_status, "status": document.extraction_status,
            "extraction_error": document.extraction_error, "created_at": document.created_at.isoformat()}


def intake_state(case):
    if not case or case.deleted_at or not enabled():
        return {"documents": [], "add_url": "", "submission_token": str(uuid4()),
                "max_pdf_bytes": MAX_PDF_BYTES, "max_text_chars": MAX_TEXT}
    documents = []
    # The page polls frequently; fetch only the displayed excerpt, not every
    # document's complete extracted text or original bytes on each refresh.
    for document in active_documents(case).annotate(preview_text=Substr("text", 1, 1200)).defer("text"):
        documents.append({**_metadata(document), "text_excerpt": document.preview_text,
                          "download_url": reverse("coordinate_intake_download", args=[case.pk, document.pk])})
    return {"documents": documents, "add_url": reverse("coordinate_intake_add", args=[case.pk]),
            "submission_token": str(uuid4()), "max_pdf_bytes": MAX_PDF_BYTES, "max_text_chars": MAX_TEXT}


def intake_context(case, max_message_id):
    """At most eight readable and eight unreadable records; no future inputs or bytes."""
    if not case or case.deleted_at or not enabled():
        return []
    query = active_documents(case, max_message_id)
    readable = list(query.filter(extraction_status__in=["ready", "truncated"]).exclude(text="")[:8])
    unreadable = list(query.filter(extraction_status="no_text")[:8])
    remaining = MAX_CONTEXT_TEXT
    result = []
    for document in sorted(readable + unreadable, key=lambda item: item.message_id, reverse=True):
        text = document.text[:remaining] if document.extraction_status in ("ready", "truncated") else ""
        remaining -= len(text)
        result.append({**_metadata(document), "text": text,
                       "context_truncated": len(text) < len(document.text)})
    return result


def extract_pdf(content):
    """Run the parser outside Django, with bounded time and no document diagnostics."""
    script = Path(__file__).resolve().parents[1] / "scripts" / "coordinate_pdf_extract.py"
    environment = {key: value for key, value in os.environ.items()
                   if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG", "LC_ALL"}}
    try:
        process = subprocess.run([sys.executable, "-I", str(script)], input=content, capture_output=True,
                                 timeout=PDF_TIMEOUT, cwd=script.parent, env=environment)
        # ensure_ascii output can use twelve bytes per supplementary character.
        if process.returncode or len(process.stdout) > MAX_TEXT * 12 + 4096:
            raise ValueError
        result = json.loads(process.stdout)
        if not isinstance(result, dict):
            raise ValueError
        if result.get("status") not in ("ready", "truncated", "no_text"):
            message = result.get("error")
            if isinstance(message, str) and 1 <= len(message) <= 300:
                raise IntakeError(message)
            raise ValueError
        if (not isinstance(result.get("text"), str) or len(result["text"]) > MAX_TEXT
                or not isinstance(result.get("error"), str) or len(result["error"]) > 300
                or (result["status"] == "no_text" and result["text"])
                or (result["status"] != "no_text" and not result["text"])):
            raise ValueError
        return result
    except IntakeError:
        raise
    except subprocess.TimeoutExpired:
        raise IntakeError("PDF extraction exceeded 10 seconds. Paste the relevant text instead.") from None
    except (OSError, ValueError, UnicodeError):
        raise IntakeError("PDF extraction is unavailable. Upload a simpler PDF or paste its text.") from None


class IntakeError(ValueError):
    pass


def _input(request):
    title = request.POST.get("title", "").strip()
    if not title or len(title) > 200 or "\x00" in title:
        raise IntakeError("Provide a document title between 1 and 200 characters.")
    try:
        token = UUID(request.POST.get("client_message_id", ""))
    except (ValueError, TypeError, AttributeError):
        raise IntakeError("A valid submission identifier is required. Reload and try again.") from None
    text = request.POST.get("text", "").strip()
    upload = request.FILES.get("pdf")
    if any(key != "pdf" for key in request.FILES) or len(request.FILES.getlist("pdf")) > 1:
        raise IntakeError("Upload one PDF at a time.")
    if (upload is None) == (not text):
        raise IntakeError("Upload one PDF or paste document text.")
    if len(text) > MAX_TEXT or "\x00" in text:
        raise IntakeError("Paste no more than 24,000 characters of document text.")
    filename = ""
    if upload:
        filename = upload.name.replace("\\", "/").rsplit("/", 1)[-1]
        filename = "".join(character for character in filename if ord(character) >= 32)[:200]
        if not filename.lower().endswith(".pdf"):
            raise IntakeError("Upload a PDF file or paste its text.")
        if upload.size > MAX_PDF_BYTES:
            raise IntakeError("PDF files must be no larger than 5 MiB.")
        content = upload.read(MAX_PDF_BYTES + 1)
        if len(content) > MAX_PDF_BYTES or not content.startswith(b"%PDF-"):
            raise IntakeError("Upload a valid PDF no larger than 5 MiB.")
        kind = "pdf"
    else:
        content, kind = text.encode("utf-8"), "text"
    digest = sha256(json.dumps([title, kind, filename], ensure_ascii=False).encode("utf-8") + b"\0" + content).hexdigest()
    return {"title": title, "token": token, "text": text, "content": content,
            "kind": kind, "filename": filename, "digest": digest}


def _duplicate(request, case, data):
    message = CoordinateMessage.objects.select_related("case").filter(client_message_id=data["token"]).first()
    if message is None:
        return None
    document = CoordinateDocument.objects.filter(message=message).only("content_digest").first()
    if (not document or message.case_id != case.pk or message.author_id != request.user.pk
            or document.content_digest != data["digest"]):
        return JsonResponse({"error": "This submission identifier was already used for different content."}, status=409)
    if message.deleted_at or message.case.deleted_at:
        return JsonResponse({"error": "This document was deleted. Restore its message before continuing."}, status=409)
    from .coordinate_views import _saved_response
    return _saved_response(request, message)


@never_cache
@staff_member_required
@require_POST
def add_document(request, case_id):
    from .coordinate_views import _database_retry, _form_error, _locked_case, _save_message, _saved_response

    case = get_object_or_404(CoordinateCase, pk=case_id)
    if not enabled():
        return JsonResponse({"error": "Shipping workspace is not enabled."}, status=503)
    if case.deleted_at:
        return JsonResponse({"error": "Restore this case before adding documents."}, status=409)
    try:
        data = _input(request)
        duplicate = _duplicate(request, case, data)
        if duplicate is not None:
            return duplicate
        # Avoid launching an expensive parser when capacity is already exhausted.
        # The same check remains under the case lock to handle concurrent uploads.
        total = active_documents(case).aggregate(total=Sum("byte_size"))["total"] or 0
        if total + len(data["content"]) > MAX_CASE_BYTES:
            raise IntakeError("Active case documents may total at most 20 MiB. Remove an older document first.")
        extraction = extract_pdf(data["content"]) if data["kind"] == "pdf" else {
            "text": data["text"], "status": "ready", "error": "",
        }

        @_database_retry
        def save():
            with transaction.atomic():
                locked = _locked_case(case.pk)
                if locked.deleted_at:
                    return JsonResponse({"error": "Restore this case before adding documents."}, status=409)
                duplicate = _duplicate(request, locked, data)
                if duplicate is not None:
                    return duplicate
                total = active_documents(locked).aggregate(total=Sum("byte_size"))["total"] or 0
                if total + len(data["content"]) > MAX_CASE_BYTES:
                    raise IntakeError("Active case documents may total at most 20 MiB. Remove an older document first.")
                document_id = uuid4()
                body = f"Added case document: {data['title']}\nSource: document:{document_id}"
                if extraction["error"]:
                    body += "\n" + extraction["error"]
                message = _save_message(locked, body, data["token"], request.user)
                CoordinateDocument.objects.create(
                    id=document_id, case=locked, message=message, title=data["title"], kind=data["kind"],
                    text=extraction["text"], original_pdf=data["content"] if data["kind"] == "pdf" else b"",
                    filename=data["filename"], byte_size=len(data["content"]), content_digest=data["digest"],
                    extraction_status=extraction["status"], extraction_error=extraction["error"],
                )
            return _saved_response(request, message)

        try:
            return save()
        except IntegrityError:
            duplicate = _duplicate(request, case, data)
            if duplicate is not None:
                return duplicate
            raise
    except IntakeError as exc:
        return _form_error(request, str(exc), case)


@never_cache
@staff_member_required
@require_GET
def download_document(request, case_id, document_id):
    document = get_object_or_404(CoordinateDocument, pk=document_id, case_id=case_id,
                                 case__deleted_at__isnull=True, message__deleted_at__isnull=True)
    content = bytes(document.original_pdf) if document.kind == "pdf" else document.text.encode("utf-8")
    filename = document.filename if document.kind == "pdf" else "case-document.txt"
    response = FileResponse(BytesIO(content), as_attachment=True, filename=filename,
                            content_type="application/pdf" if document.kind == "pdf" else "text/plain; charset=utf-8")
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store, max-age=0"
    return response
