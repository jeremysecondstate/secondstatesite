"""Private, case-scoped Gmail observations. This module never sends email."""
from datetime import timedelta
import json
import re
from uuid import UUID, uuid5, NAMESPACE_URL

from django.conf import settings
from django.core import signing
from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.http import JsonResponse
from django.utils import timezone

from scripts.coordinate_mail_sync import (
    ACCOUNT_EMAIL, GMAIL_LINK_ID, MAX_ATTACHMENTS, MAX_BODY, MAX_MESSAGES,
    MAX_THREADS, MAX_RECONCILE_CANDIDATES, SYNC_SECONDS, addresses, aware_time, gmail_id,
)
from .coordinate_mail import visible_threads, thread_visible, mail_readiness
from .coordinate_mail_models import CoordinateMailDelivery, CoordinateMailMessage, CoordinateMailThread
from .coordinate_views import _error, _locked_case, _worker_endpoint
from .models import CoordinateActivity, CoordinateCase, CoordinateJob, CoordinateMessage

SYNC_SALT = "coordinate-mail-observation-v1"
MAX_CONTEXT_BYTES = 240_000
STALE_SEND_SECONDS = 300  # Longer than the bounded 25-second Gmail send call.
RECONCILE_WINDOW_SECONDS = 60


def reconciliation_query(delivery):
    # Gmail search syntax is not email syntax. Exotic but valid addresses must
    # retain exact-ID/RFC reconciliation rather than becoming query operators.
    if not re.fullmatch(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+", delivery.recipient):
        return ""
    stamp = int(delivery.requested_at.timestamp())
    return (f"in:sent from:{ACCOUNT_EMAIL} to:{delivery.recipient} "
            f"after:{stamp - RECONCILE_WINDOW_SECONDS - 1} before:{stamp + RECONCILE_WINDOW_SECONDS + 1}")


def _sync_enabled():
    return bool(settings.COORDINATE_DRAFT_WORKFLOW_ENABLED and settings.COORDINATE_EMAIL_SYNC_ENABLED)


def mail_context(case, max_message_id=None):
    """Visible private email facts, with the same message cutoff as the job."""
    if not case or case.deleted_at:
        return []
    messages = CoordinateMailMessage.objects.filter(
        thread__in=visible_threads(case), message__deleted_at__isnull=True,
        received_at__lte=timezone.now(), message__created_at__lte=timezone.now(),
    ).select_related("thread", "message")
    if max_message_id is not None:
        messages = messages.filter(message_id__lte=max_message_id,
                                   thread__originating_message_id__lte=max_message_id)
    result, size = [], 0
    for item in messages.order_by("-message_id")[:40]:
        record = {"id": str(item.pk), "message_id": item.message_id,
            "source_ref": "message:" + str(item.message_id), "text": item.body_text,
            "from_address": item.from_email, "to_address": ", ".join(item.to_emails),
            "cc_addresses": getattr(item, "cc_emails", []), "direction": item.direction,
            "received_at": item.received_at.isoformat(), "thread_id": str(item.thread_id),
            "gmail_thread_id": item.thread.gmail_thread_id, "subject": item.subject,
            "attachments": item.attachments, "body_truncated": getattr(item, "body_truncated", False)}
        encoded_size = len(json.dumps(record, ensure_ascii=False).encode())
        if size + encoded_size > MAX_CONTEXT_BYTES:
            break
        result.append(record)
        size += encoded_size
    return list(reversed(result))


def _visible_reconciliation():
    # A stalled send is observed conservatively; a timeout never permits resend.
    from .coordinate_shipping import visible_artifacts
    from .models import CoordinateDraft
    return CoordinateMailDelivery.objects.filter(
        draft__in=visible_artifacts(CoordinateDraft.objects.all()),
        sender_email=ACCOUNT_EMAIL,
    ).filter(Q(status="unknown") | Q(status="sending", requested_at__lte=timezone.now() - timedelta(seconds=STALE_SEND_SECONDS))).select_related("draft__case")


@_worker_endpoint
def sync_manifest(request, data):
    now = timezone.now()
    if not _sync_enabled():
        return JsonResponse({"threads": [], "reconcile": [], "sync_enabled": False, "mail_readiness": mail_readiness()})
    threads = list(visible_threads().filter(sender_email=ACCOUNT_EMAIL,
        case__coordinator=data["worker_id"]).exclude(gmail_thread_id__isnull=True).exclude(gmail_thread_id="").order_by(
        F("sync_checked_at").asc(nulls_first=True), "created_at")[:MAX_THREADS])
    reconcile = list(_visible_reconciliation().filter(draft__case__coordinator=data["worker_id"]).order_by("requested_at")[:2])
    token = signing.dumps({"threads": [str(thread.pk) for thread in threads],
                           "deliveries": [str(item.pk) for item in reconcile], "account": ACCOUNT_EMAIL}, salt=SYNC_SALT)
    return JsonResponse({"sync_enabled": True, "mail_readiness": mail_readiness(), "account_email": ACCOUNT_EMAIL, "link_id": GMAIL_LINK_ID,
        "sync_token": token, "sync_deadline": (now + timedelta(seconds=SYNC_SECONDS)).isoformat(),
        "max_messages": MAX_MESSAGES,
        "threads": [{"id": str(thread.pk), "case_id": str(thread.case_id), "gmail_thread_id": thread.gmail_thread_id,
                     "provider_email": thread.provider_email, "sender_email": thread.sender_email,
                     "originating_message_id": thread.originating_message_id} for thread in threads],
        "reconcile": [{"delivery_id": str(item.pk), "rfc_message_id": item.rfc_message_id,
                       "gmail_message_id": item.gmail_message_id, "gmail_thread_id": item.gmail_thread_id,
                       "query": "in:sent rfc822msgid:" + item.rfc_message_id.strip("<>"),
                       "fallback_query": reconciliation_query(item), "max_candidates": MAX_RECONCILE_CANDIDATES,
                       "account_email": ACCOUNT_EMAIL} for item in reconcile]})


def _token(data):
    if data.get("account_email") != ACCOUNT_EMAIL:
        raise ValueError("Mail observations belong to the wrong account.")
    try:
        scope = signing.loads(data.get("sync_token", ""), salt=SYNC_SALT, max_age=300)
    except (signing.BadSignature, TypeError, ValueError):
        raise ValueError("Mail sync scope expired or is invalid; obtain a new manifest.") from None
    if not isinstance(scope, dict) or scope.get("account") != ACCOUNT_EMAIL:
        raise ValueError("Mail sync scope belongs to another account.")
    observed = aware_time(data.get("observed_at"))
    now = timezone.now()
    if not now - timedelta(minutes=5) <= observed <= now + timedelta(seconds=5):
        raise ValueError("Mail observations are stale or from the future.")
    return scope, observed


def _field(value, length, required=False):
    if not isinstance(value, str) or len(value) > length or "\x00" in value or (required and not value.strip()):
        raise ValueError("Invalid bounded mail field.")
    return value


def _participants(value):
    if not isinstance(value, list) or len(value) > 30:
        raise ValueError("Invalid mail recipients.")
    cleaned = []
    for item in value:
        parsed = addresses(_field(item, 254, True))
        if len(parsed) != 1 or parsed[0] != item.casefold():
            raise ValueError("Invalid normalized mail recipient.")
        cleaned.append(parsed[0])
    return list(dict.fromkeys(cleaned))


def _message(value, thread_id, observed):
    if not isinstance(value, dict) or value.get("gmail_thread_id") != thread_id:
        raise ValueError("Observed mail belongs to a different thread.")
    gmail_id(value.get("gmail_message_id"))
    sender = _participants([value.get("from_email")])[0]
    received = aware_time(value.get("received_at"))
    if received > min(observed, timezone.now()) + timedelta(seconds=5):
        raise ValueError("Future mail cannot enter a case.")
    attachments = value.get("attachments", [])
    if not isinstance(attachments, list) or len(attachments) > MAX_ATTACHMENTS:
        raise ValueError("Invalid attachment metadata.")
    cleaned_attachments = []
    for item in attachments:
        if not isinstance(item, dict) or set(item) != {"filename", "mime_type", "size"}:
            raise ValueError("Only attachment metadata may be imported.")
        size = item["size"]
        if not isinstance(size, int) or isinstance(size, bool) or not 0 <= size <= 10_000_000_000:
            raise ValueError("Invalid attachment size.")
        cleaned_attachments.append({"filename": _field(item["filename"], 200),
                                    "mime_type": _field(item["mime_type"], 100), "size": size})
    body = _field(value.get("body_text"), MAX_BODY)
    if not body.strip() and not attachments:
        raise ValueError("Mail has no readable body or attachment metadata.")
    if any(not isinstance(value.get(field, False), bool) for field in ("body_truncated", "sent_label", "has_bcc")):
        raise ValueError("Invalid mail observation flag.")
    return {"gmail_message_id": value["gmail_message_id"], "from_email": sender,
        "to_emails": _participants(value.get("to_emails", [])), "cc_emails": _participants(value.get("cc_emails", [])),
        "received_at": received, "subject": _field(value.get("subject", ""), 200), "body_text": body,
        "body_truncated": value.get("body_truncated", False), "attachments": cleaned_attachments,
        "rfc_message_id": _field(value.get("rfc_message_id", ""), 998),
        "in_reply_to": _field(value.get("in_reply_to", ""), 998),
        "references": _field(value.get("references", ""), 8000), "sent_label": value.get("sent_label", False),
        "has_bcc": value.get("has_bcc", False)}


def _import_thread(data, scope, observed):
    raw = data.get("thread")
    if not isinstance(raw, dict):
        raise ValueError("Expected one scoped Gmail thread.")
    identifier = gmail_id(raw.get("gmail_thread_id"))
    requested = CoordinateMailThread.objects.filter(pk__in=scope.get("threads", []), gmail_thread_id=identifier).first()
    if requested is None:
        raise ValueError("This Gmail thread was not requested by the sync manifest.")
    values = raw.get("messages")
    if not isinstance(values, list) or len(values) > MAX_MESSAGES:
        raise ValueError("Too many observed mail messages.")
    messages = [_message(value, identifier, observed) for value in values]
    if len({item["gmail_message_id"] for item in messages}) != len(messages):
        raise ValueError("Duplicate mail identifiers in an observation.")
    imported, duplicates, skipped = 0, 0, 0
    with transaction.atomic():
        case = _locked_case(requested.case_id)
        thread = CoordinateMailThread.objects.select_for_update().get(pk=requested.pk)
        if (not thread_visible(thread) or case.coordinator != data["worker_id"]
                or thread.sender_email.casefold() != ACCOUNT_EMAIL or thread.gmail_thread_id != identifier):
            raise ValueError("This case's email thread is no longer visible or current.")
        first_send = thread.deliveries.order_by("requested_at").values_list("requested_at", flat=True).first()
        floor = first_send if first_send is not None else thread.created_at - timedelta(minutes=1)
        for item in sorted(messages, key=lambda row: (row["received_at"], row["gmail_message_id"])):
            existing = CoordinateMailMessage.objects.filter(gmail_message_id=item["gmail_message_id"]).first()
            if existing is not None:
                if existing.thread_id != thread.pk:
                    raise ValueError("This Gmail message was already recorded on another case thread.")
                # Deletion hides an anchor, never deletes this identity tombstone.
                _refresh_outbound(existing, item, thread)
                duplicates += 1
                continue
            if item["from_email"] == ACCOUNT_EMAIL or item["sent_label"]:
                skipped += 1
                continue
            if item["from_email"] != thread.provider_email.casefold() or ACCOUNT_EMAIL not in item["to_emails"] + item["cc_emails"]:
                raise ValueError("Mail sender or recipients do not match the linked provider conversation.")
            if item["received_at"] < floor:
                skipped += 1
                continue
            item.pop("sent_label")
            item.pop("has_bcc")
            anchor = CoordinateMessage.objects.create(case=case, role="system",
                client_message_id=uuid5(NAMESPACE_URL, "coordinate:gmail:inbound:" + item["gmail_message_id"]),
                body="Email reply received from " + thread.provider_email + ". See the private correspondence view.")
            CoordinateMailMessage.objects.create(thread=thread, message=anchor, direction="inbound", **item)
            CoordinateJob.objects.create(message=anchor)
            imported += 1
        thread.sync_checked_at = timezone.now()
        thread.save(update_fields=["sync_checked_at"])
        if imported:
            case.updated_at = timezone.now()
            case.save(update_fields=["updated_at"])
            CoordinateActivity.objects.create(case=case, event="mail_replies_imported",
                details={"thread_id": str(thread.pk), "count": imported, "sent": False})
    return {"status": "imported", "thread_id": str(thread.pk), "imported": imported,
            "duplicates": duplicates, "skipped": skipped}


def _normalized_body(body):
    return body.replace("\r\n", "\n").strip()


def _snapshot_matches(delivery, item):
    return (item["sent_label"] and item["from_email"] == ACCOUNT_EMAIL
            and (not delivery.gmail_message_id or item["gmail_message_id"] == delivery.gmail_message_id)
            and item["to_emails"] == [delivery.recipient.casefold()] and not item["cc_emails"] and not item["has_bcc"]
            and item["subject"] == delivery.subject and not item["body_truncated"] and not item["attachments"]
            and _normalized_body(item["body_text"]) == _normalized_body(delivery.body)
            and abs((item["received_at"] - delivery.requested_at).total_seconds()) <= RECONCILE_WINDOW_SECONDS)


def _refresh_outbound(existing, item, thread):
    """Refresh actual reply headers only from the already-linked exact message."""
    from .coordinate_mail import RFC_ID_PATTERN
    if (existing.direction != "outbound" or existing.message.deleted_at
            or not item["sent_label"] or item["from_email"] != existing.from_email.casefold()
            or item["to_emails"] != [address.casefold() for address in existing.to_emails]
            or item["cc_emails"] or item["has_bcc"] or item["subject"] != existing.subject
            or item["body_truncated"] or item["attachments"]
            or _normalized_body(item["body_text"]) != _normalized_body(existing.body_text)
            or not RFC_ID_PATTERN.fullmatch(item["rfc_message_id"])):
        return
    # ID and thread equality were checked by the caller. No body, participant,
    # visibility or delivery snapshot is rewritten by this receipt observation.
    existing.rfc_message_id = item["rfc_message_id"]
    existing.received_at = item["received_at"]
    existing.save(update_fields=["rfc_message_id", "received_at"])
    CoordinateMailDelivery.objects.filter(gmail_message_id=existing.gmail_message_id,
        gmail_thread_id=thread.gmail_thread_id, status="sent").update(sent_at=item["received_at"])


def _reconcile(data, scope, observed):
    from .coordinate_mail import record_delivery_success, require_draft_visible
    raw = data.get("reconcile")
    if not isinstance(raw, dict) or raw.get("delivery_id") not in scope.get("deliveries", []):
        raise ValueError("Delivery reconciliation was not requested by the manifest.")
    delivery = CoordinateMailDelivery.objects.select_related("draft__case").get(pk=raw["delivery_id"])
    require_draft_visible(delivery.draft)
    if delivery.draft.case.coordinator != data["worker_id"]:
        raise ValueError("Delivery belongs to another coordinator.")
    values = raw.get("candidates", [raw["message"]] if "message" in raw else [])
    if not isinstance(values, list) or not 1 <= len(values) <= MAX_RECONCILE_CANDIDATES:
        raise ValueError("Reconciliation requires a bounded candidate collection.")
    candidates = []
    for value in values:
        identifier = gmail_id(value.get("gmail_thread_id")) if isinstance(value, dict) else ""
        item = _message(value, identifier, observed)
        item["gmail_thread_id"] = identifier
        candidates.append(item)
    if len({item["gmail_message_id"] for item in candidates}) != len(candidates):
        raise ValueError("Duplicate reconciliation candidates.")
    method = raw.get("match_method", "rfc822msgid")
    if method not in ("rfc822msgid", "snapshot", "receipt"):
        raise ValueError("Unsupported delivery reconciliation method.")
    fallback = method == "snapshot"
    if fallback and (not reconciliation_query(delivery) or raw.get("search_complete") is not True
                     or raw.get("query") != reconciliation_query(delivery)):
        raise ValueError("Fallback reconciliation needs the complete precisely scoped search observation.")
    matches = [item for item in candidates if _snapshot_matches(delivery, item)
               and (not delivery.gmail_thread_id or item["gmail_thread_id"] == delivery.gmail_thread_id)
               and (fallback or method == "receipt" and delivery.gmail_message_id == item["gmail_message_id"]
                    or item["rfc_message_id"] == delivery.rfc_message_id)]
    if len(matches) != 1:
        raise ValueError("Observed sent message does not match the exact reviewed delivery snapshot.")
    item = matches[0]
    if fallback:
        possible = CoordinateMailDelivery.objects.filter(sender_email=ACCOUNT_EMAIL,
            recipient__iexact=delivery.recipient, subject=delivery.subject,
            requested_at__gte=item["received_at"] - timedelta(seconds=RECONCILE_WINDOW_SECONDS),
            requested_at__lte=item["received_at"] + timedelta(seconds=RECONCILE_WINDOW_SECONDS))
        matching_ids = [candidate.pk for candidate in possible if _snapshot_matches(candidate, item)]
        if matching_ids != [delivery.pk]:
            raise ValueError("More than one saved delivery matches this observed message.")
    record_delivery_success(delivery.pk, item["gmail_message_id"], item["gmail_thread_id"], require_visible=True,
                            observed_rfc_message_id=item["rfc_message_id"], observed_received_at=item["received_at"])
    return {"status": "reconciled", "delivery_id": str(delivery.pk), "imported": 0, "duplicates": 0}


@_worker_endpoint
def import_mail(request, data):
    if not _sync_enabled():
        return _error("Case email sync is disabled.", 409)
    try:
        scope, observed = _token(data)
        result = _reconcile(data, scope, observed) if "reconcile" in data else _import_thread(data, scope, observed)
    except (ValueError, TypeError, CoordinateMailDelivery.DoesNotExist):
        return _error("Mail observation was rejected: scope, account, visibility, participants or evidence did not match.", 409)
    except IntegrityError:
        return _error("Mail import raced another change. Retry the identical observation.", 409)
    return JsonResponse(result)
