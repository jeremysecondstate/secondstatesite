"""Case-scoped mail: immutable approvals, explicit dispatch, bounded safe state."""
import base64
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import format_datetime
import hashlib
import importlib.util
import json
import re
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from .coordinate_mail_models import CoordinateMailDelivery, CoordinateMailMessage, CoordinateMailThread
from .models import CoordinateActivity, CoordinateCase, CoordinateDraft, CoordinateMessage, CoordinatePlan
from .coordinate_shipping import draft_blocked, invalidate_context, visible_artifacts

SENDER = "jeremy@secondstate.art"
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,255}\Z")
RFC_ID_PATTERN = re.compile(r"<[^<>\s\x00-\x1f\x7f]+@[^<>\s\x00-\x1f\x7f]+>\Z")


def mail_readiness():
    enabled = bool(settings.COORDINATE_DRAFT_WORKFLOW_ENABLED and settings.COORDINATE_EMAIL_SENDING_ENABLED)
    configured = {name: bool(str(getattr(settings, name, "") or "").strip()) for name in (
        "GOOGLE_GMAIL_CLIENT_ID", "GOOGLE_GMAIL_CLIENT_SECRET", "GOOGLE_GMAIL_REFRESH_TOKEN")}
    dependencies = all(importlib.util.find_spec(name) is not None for name in ("googleapiclient", "google_auth_httplib2", "httplib2"))
    sender_ok = str(settings.AUCTION_EMAIL_SENDER or "").strip().casefold() == SENDER
    ready = enabled and all(configured.values()) and dependencies and sender_ok
    status = ("Reviewed email sending is disabled." if not enabled else
              "Reviewed email sending is ready; Gmail credentials are configured." if ready else
              "Email sending needs server configuration.")
    return {"enabled": enabled, "sync_enabled": bool(settings.COORDINATE_EMAIL_SYNC_ENABLED), "ready": ready,
            "sender": SENDER, "status_text": status, "configured": configured,
            "dependencies_available": dependencies, "sender_matches": sender_ok,
            "connection_verified": False}


def draft_digest(draft):
    data = {"recipient": draft.recipient, "subject": draft.subject, "body": draft.body,
            "purpose": draft.purpose, "quote_id": str(draft.quote_id or ""),
            "thread_id": str(draft.mail_thread_id or "")}
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def draft_delivery(draft):
    try:
        return draft.mail_delivery
    except CoordinateMailDelivery.DoesNotExist:
        return None


def visible_threads(case=None):
    query = CoordinateMailThread.objects.filter(case__deleted_at__isnull=True,
        originating_message__deleted_at__isnull=True,
        originating_message__worker_reply__deleted_at__isnull=True).exclude(originating_message=None)
    return query.filter(case=case) if case is not None else query


def thread_visible(thread, max_message_id=None):
    query = visible_threads().filter(pk=thread.pk)
    if max_message_id is not None:
        query = query.filter(originating_message_id__lte=max_message_id)
    return query.exists()


mail_thread_visible = thread_visible


def require_draft_visible(draft):
    if draft.case.deleted_at or not visible_artifacts(CoordinateDraft.objects.filter(pk=draft.pk)).exists():
        raise ValueError("This draft's case or originating conversation is no longer visible.")
    if draft.job_id:
        parent = CoordinateMailMessage.objects.select_related("thread").filter(message_id=draft.job.message_id).first()
        if parent and not thread_visible(parent.thread):
            raise ValueError("The email conversation supporting this draft is no longer visible.")


def require_draft_editable(draft):
    require_draft_visible(draft)
    if draft_delivery(draft):
        raise ValueError("An email submitted for delivery is immutable. Create a new draft for another message.")


def require_current_digest(draft, supplied):
    if not isinstance(supplied, str) or supplied != draft_digest(draft):
        raise ValueError("The draft changed or its review is stale. Reload and review the current wording.")


def _subject_key(value):
    return re.sub(r"^(?:\s*re\s*:\s*)+", "", value, flags=re.I).strip().casefold()


def validate_draft_thread(draft):
    if not draft.mail_thread_id:
        return None
    thread = draft.mail_thread
    if (thread.case_id != draft.case_id or not thread_visible(thread) or not thread.gmail_thread_id
            or thread.provider_email.casefold() != draft.recipient.casefold() or thread.sender_email.casefold() != SENDER):
        raise ValueError("Choose a visible thread for this case and the exact recipient.")
    if _subject_key(draft.subject) != _subject_key(thread.subject):
        raise ValueError("A reply must keep the selected email thread's subject.")
    return thread


def _headers_for_thread(thread):
    if thread is None:
        return "", ""
    latest = thread.mail_messages.filter(message__deleted_at__isnull=True).order_by("-received_at", "-message_id").first()
    if not latest or not RFC_ID_PATTERN.fullmatch(latest.rfc_message_id):
        raise ValueError("The selected thread needs a verified message header before replying.")
    refs = latest.references.split() if latest.references else []
    if any(not RFC_ID_PATTERN.fullmatch(ref) for ref in refs):
        raise ValueError("The selected thread has invalid reply headers.")
    refs = list(dict.fromkeys([*refs, latest.rfc_message_id]))[-20:]
    while len(" ".join(refs)) > 4000:
        refs.pop(0)
    return latest.rfc_message_id, " ".join(refs)


def prepare_delivery(draft_id, user, content_digest, request_id):
    """Commit dispatch intent before network I/O; retries never send a second time."""
    from .coordinate_views import _locked_case
    try:
        request_id = UUID(str(request_id))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("A valid send request ID is required.") from None
    identity = CoordinateDraft.objects.only("case_id").get(pk=draft_id)
    with transaction.atomic(durable=True):
        case = _locked_case(identity.case_id)
        draft = CoordinateDraft.objects.select_related("case", "job__message", "mail_thread").get(pk=draft_id)
        require_draft_visible(draft)
        require_current_digest(draft, content_digest)
        existing = draft_delivery(draft)
        if existing:
            if existing.request_id != request_id or existing.reviewed_digest != content_digest:
                raise ValueError("This draft already has a delivery record. It cannot be sent again.")
            return existing, False
        if CoordinateMailDelivery.objects.filter(request_id=request_id).exists():
            raise ValueError("This send request ID belongs to a different draft.")
        if draft.status != "reviewed" or not draft.reviewed_at or not draft.reviewed_by_id or draft.reviewed_digest != content_digest:
            raise ValueError("Review the exact current email before sending it.")
        if draft_blocked(draft):
            raise ValueError("This provider thread is paused for Jeremy's price review.")
        if not mail_readiness()["ready"]:
            raise ValueError("Reviewed email sending is disabled or needs server configuration.")
        try:
            validate_email(draft.recipient)
        except ValidationError:
            raise ValueError("The email recipient is invalid.") from None
        if any(c in draft.recipient + draft.subject for c in "\r\n") or not draft.body.strip():
            raise ValueError("The reviewed email has invalid headers or an empty body.")
        thread = validate_draft_thread(draft)
        in_reply_to, references = _headers_for_thread(thread)
        origin = draft.job.message if draft.job_id else case.messages.filter(role="staff", deleted_at__isnull=True).order_by("-pk").first()
        if origin:
            parent = CoordinateMailMessage.objects.select_related("thread__originating_message").filter(message_id=origin.pk).first()
            if parent:
                origin = parent.thread.originating_message
        if not origin:
            raise ValueError("The case needs visible conversation context before sending.")
        plan = CoordinatePlan.objects.filter(case=case).first()
        delivery_id = uuid4()
        delivery = CoordinateMailDelivery.objects.create(
            id=delivery_id, draft=draft, thread=thread, request_id=request_id, status="sending",
            sender_email=SENDER, recipient=draft.recipient, subject=draft.subject, body=draft.body,
            reviewed_digest=content_digest, requested_by=user,
            rfc_message_id=f"<coordinate-{delivery_id}@secondstate.art>",
            in_reply_to=in_reply_to, references=references,
            approval_snapshot={"reviewed_by_id": draft.reviewed_by_id, "reviewed_at": draft.reviewed_at.isoformat(),
                               "originating_message_id": origin.pk,
                               "destination": plan.destination if plan else "undecided",
                               "handling": plan.handling if plan else "", "quote_id": str(draft.quote_id or "")},
        )
        CoordinateActivity.objects.create(case=case, event="email_send_requested", details={
            "delivery_id": str(delivery.pk), "draft_id": str(draft.pk), "author_id": user.pk,
            "reviewed_digest": content_digest})
        invalidate_context(case)
        CoordinateCase.objects.filter(pk=case.pk).update(updated_at=timezone.now())
        return delivery, True


def send_snapshot(delivery):
    """One Gmail send call; OAuth scopes remain send-only. Never called by research."""
    from google.oauth2.credentials import Credentials
    from google_auth_httplib2 import AuthorizedHttp
    from googleapiclient.discovery import build
    import httplib2

    credentials = Credentials(token=None, refresh_token=settings.GOOGLE_GMAIL_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token", client_id=settings.GOOGLE_GMAIL_CLIENT_ID,
        client_secret=settings.GOOGLE_GMAIL_CLIENT_SECRET, scopes=[GMAIL_SEND_SCOPE])
    message = EmailMessage()
    message["From"], message["To"], message["Subject"] = delivery.sender_email, delivery.recipient, delivery.subject
    message["Date"] = format_datetime(delivery.requested_at)
    message["Message-ID"] = delivery.rfc_message_id
    if delivery.in_reply_to:
        message["In-Reply-To"], message["References"] = delivery.in_reply_to, delivery.references
    message.set_content(delivery.body, subtype="plain", charset="utf-8")
    payload = {"raw": base64.urlsafe_b64encode(message.as_bytes(policy=SMTP)).decode("ascii")}
    if delivery.thread_id:
        payload["threadId"] = delivery.thread.gmail_thread_id
    service = build("gmail", "v1", http=AuthorizedHttp(credentials, http=httplib2.Http(timeout=25)), cache_discovery=False)
    return service.users().messages().send(userId="me", body=payload).execute(num_retries=0)


def record_delivery_success(delivery_id, gmail_message_id, gmail_thread_id, *, require_visible=False):
    """Persist an observed provider receipt, including during exact reconciliation."""
    from .coordinate_views import _locked_case
    if not isinstance(gmail_message_id, str) or not ID_PATTERN.fullmatch(gmail_message_id) or not isinstance(gmail_thread_id, str) or not ID_PATTERN.fullmatch(gmail_thread_id):
        raise ValueError("Gmail did not return valid delivery identifiers.")
    identity = CoordinateMailDelivery.objects.select_related("draft").get(pk=delivery_id)
    with transaction.atomic():
        case = _locked_case(identity.draft.case_id)
        delivery = CoordinateMailDelivery.objects.select_for_update().select_related("draft", "thread").get(pk=delivery_id)
        if require_visible:
            require_draft_visible(delivery.draft)
            if delivery.thread_id and not thread_visible(delivery.thread):
                raise ValueError("This email thread is no longer visible for reconciliation.")
        if delivery.status == "sent":
            if delivery.gmail_message_id != gmail_message_id or delivery.gmail_thread_id != gmail_thread_id:
                raise ValueError("Delivery receipt conflicts with the saved receipt.")
            return delivery
        thread = delivery.thread
        if thread and thread.gmail_thread_id != gmail_thread_id:
            raise ValueError("Gmail returned a different thread for this reply.")
        if thread is None:
            thread, created = CoordinateMailThread.objects.get_or_create(gmail_thread_id=gmail_thread_id, defaults={
                "case": case, "originating_message_id": delivery.approval_snapshot["originating_message_id"],
                "provider_email": delivery.recipient, "sender_email": delivery.sender_email, "subject": delivery.subject})
            if not created and (thread.case_id != case.pk or thread.provider_email.casefold() != delivery.recipient.casefold()):
                raise ValueError("Gmail thread is already linked to a different case or recipient.")
        now = timezone.now()
        message = CoordinateMessage.objects.create(case=case, role="system",
            body=f"Email sent to {delivery.recipient}: {delivery.subject}",
            client_message_id=uuid5(NAMESPACE_URL, "coordinate-sent:" + str(delivery.pk)))
        CoordinateMailMessage.objects.create(thread=thread, message=message, direction="outbound",
            gmail_message_id=gmail_message_id, rfc_message_id=delivery.rfc_message_id,
            in_reply_to=delivery.in_reply_to, references=delivery.references, from_email=delivery.sender_email,
            to_emails=[delivery.recipient], subject=delivery.subject, body_text=delivery.body, received_at=now)
        delivery.thread, delivery.status, delivery.sent_at = thread, "sent", now
        delivery.gmail_message_id, delivery.gmail_thread_id, delivery.error_code = gmail_message_id, gmail_thread_id, ""
        delivery.save(update_fields=["thread", "status", "sent_at", "gmail_message_id", "gmail_thread_id", "error_code"])
        thread.save(update_fields=["updated_at"])
        CoordinateActivity.objects.create(case=case, event="email_sent", details={"delivery_id": str(delivery.pk),
            "draft_id": str(delivery.draft_id), "gmail_message_id": gmail_message_id, "thread_id": str(thread.pk)})
        invalidate_context(case)
        CoordinateCase.objects.filter(pk=case.pk).update(updated_at=now)
        return delivery


def mark_delivery_unknown(delivery_id):
    # Never store provider exception text: it may include tokens or message data.
    CoordinateMailDelivery.objects.filter(pk=delivery_id, status="sending").update(status="unknown", error_code="receipt_not_confirmed")


def draft_mail_state(draft):
    digest, delivery = draft_digest(draft), draft_delivery(draft)
    ready = mail_readiness()["ready"]
    status = delivery.status if delivery else draft.status
    current_approval = draft.status == "reviewed" and draft.reviewed_digest == digest and bool(draft.reviewed_by_id and draft.reviewed_at)
    try:
        require_draft_visible(draft)
        validate_draft_thread(draft)
        visible = True
    except ValueError:
        visible = False
    text = {"sending": "Send requested; waiting for Gmail confirmation.", "sent": "Sent through Gmail.",
            "unknown": "Delivery outcome is unknown. Check the linked mailbox before taking any further action.",
            "reviewed": "Wording reviewed." if current_approval else "Review the current wording again before sending.",
            "draft": "Review the wording before sending."}[status]
    return {"current_digest": digest, "reviewed_digest": draft.reviewed_digest, "thread_id": str(draft.mail_thread_id or ""),
            "send_url": reverse("coordinate_mail_send", args=[draft.case_id, draft.pk]),
            "send_request_id": str(uuid5(NAMESPACE_URL, "coordinate-send:" + str(draft.pk) + ":" + digest)),
            "send_status": status, "can_send": ready and current_approval and visible and not delivery and not draft_blocked(draft),
            "editable": not bool(delivery), "reviewed_at": draft.reviewed_at.isoformat() if draft.reviewed_at else "",
            "sent_at": delivery.sent_at.isoformat() if delivery and delivery.sent_at else "", "status_text": text}


def mail_state(case, max_message_id=None):
    readiness = mail_readiness()
    result = {**readiness, "last_checked_at": "", "threads": []}
    if not case or case.deleted_at:
        return result
    query = visible_threads(case)
    if max_message_id is not None:
        query = query.filter(originating_message_id__lte=max_message_id)
    remaining = 96000
    for thread in query[:8]:
        messages = thread.mail_messages.filter(message__deleted_at__isnull=True)
        if max_message_id is not None:
            messages = messages.filter(message_id__lte=max_message_id)
        observed = []
        for item in messages.order_by("-received_at", "-message_id")[:20]:
            body = item.body_text[:min(24000, remaining)] if max_message_id is None else ""
            remaining -= len(body)
            observed.append({"id": str(item.pk), "direction": item.direction, "sender": item.from_email,
                "message_id": item.message_id, "recipient": ", ".join(item.to_emails), "subject": item.subject, "body": body,
                "cc": item.cc_emails, "body_truncated": item.body_truncated or (max_message_id is None and len(body) < len(item.body_text)),
                "context_body_omitted": max_message_id is not None,
                "sent_at": item.received_at.isoformat(), "source_ref": "message:" + str(item.message_id),
                "source_url": "https://mail.google.com/mail/u/?authuser=" + SENDER + "#all/" + item.gmail_message_id})
        result["threads"].append({"id": str(thread.pk), "subject": thread.subject,
            "participants": [thread.sender_email, thread.provider_email], "provider_email": thread.provider_email,
            "url": "https://mail.google.com/mail/u/?authuser=" + SENDER + "#all/" + (thread.gmail_thread_id or ""),
            "last_synced_at": thread.sync_checked_at.isoformat() if thread.sync_checked_at else "", "messages": list(reversed(observed))})
        if thread.sync_checked_at and thread.sync_checked_at.isoformat() > result["last_checked_at"]:
            result["last_checked_at"] = thread.sync_checked_at.isoformat()
    return result
