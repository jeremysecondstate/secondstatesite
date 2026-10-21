"""Authenticated, snapshot-bound approval of the email bundle shown beside chat."""
import json
import re
from uuid import uuid5

from django.core import signing
from django.db import transaction
from django.utils import timezone

from . import coordinate_mail as mail
from .coordinate_shipping import draft_blocked, enabled, visible_artifacts
from .models import CoordinateActivity, CoordinateCase, CoordinateDraft, CoordinateMessage

SALT = "coordinate.chat-send.v1"
_PRAISE = r"(?:dude|yes|yep|yeah|ok|okay|perfect|great|excellent|awesome|thanks|thank you|(?:i )?love (?:it|them)|(?:this|that|these|it|they) (?:is|are|looks?|sounds?) (?:perfect|great|excellent|good|ready)|(?:looks?|sounds?) (?:perfect|great|excellent|good)|approved)"
_SEND = re.compile(
    rf"^(?:{_PRAISE}[\s,.!;:—-]+)*(?:please\s+)?"
    r"(?:(?P<request>can|could)\s+you\s+(?:please\s+)?|(?:go ahead(?:\s+and)?|let['’]s)\s+)?"
    r"send\s+(?:it|them|(?:the|these|those) emails?|(?:the|these|those) drafts?|all three|all 3|them all)"
    r"(?:\s+out)?(?:\s+(?:now|please))?(?P<question>\?)?"
    r"(?:[\s.!]+(?:thanks|thank you))?[\s.!]*(?:[👍💪]\ufe0f?[\U0001f3fb-\U0001f3ff]?[\s.!]*)*$", re.I,
)


def explicit_send(body):
    """Accept direct requests; advice/status questions, conditions and edits do not dispatch."""
    match = _SEND.fullmatch(body.strip()) if isinstance(body, str) else None
    return bool(match and (not match.group("question") or match.group("request")))


def _snapshot(case):
    from .coordinate_views import _conversation_visible
    if case:
        case = CoordinateCase.objects.get(pk=case.pk)
    if not case or case.deleted_at or case.purged_at or not enabled():
        return None
    messages = case.messages.filter(_conversation_visible(), deleted_at__isnull=True)
    reply = messages.filter(role="assistant", in_reply_to__job__email_drafts__isnull=False).order_by("-pk").first()
    if not reply:
        return None
    drafts = list(visible_artifacts(case.email_drafts.filter(job__message_id=reply.in_reply_to_id)))
    if not drafts or len(drafts) > 3:
        return None
    return {
        "case_id": str(case.pk), "case_version": case.updated_at.isoformat(),
        "reply_id": reply.pk, "last_message_id": messages.order_by("-pk").values_list("pk", flat=True).first(),
        "drafts": [{"id": str(d.pk), "content_digest": mail.draft_digest(d)} for d in drafts],
    }


def chat_send_state(case, displayed_drafts=None):
    snapshot = _snapshot(case)
    if snapshot is None:
        return None
    consistent = True
    if displayed_drafts is not None:
        displayed = {item["id"]: item.get("current_digest") for item in displayed_drafts}
        consistent = all(displayed.get(item["id"]) == item["content_digest"] for item in snapshot["drafts"])
    return {key: snapshot[key] for key in ("reply_id", "last_message_id", "drafts")} | {
        # A concurrent edit between rendering drafts and building the manifest
        # must never authorize text that the browser did not receive.
        "token": signing.dumps(snapshot, salt=SALT, compress=True) if consistent else None,
    }


def _validate_context(case, raw):
    message = "The displayed emails or case changed. Review the current emails, then ask me to send them again, or use Send reviewed email."
    try:
        if not isinstance(raw, str) or len(raw) > 8192:
            raise ValueError
        supplied = json.loads(raw)
        if not isinstance(supplied, dict) or set(supplied) != {"reply_id", "last_message_id", "drafts", "token"}:
            raise ValueError
        if not isinstance(supplied["token"], str):
            raise ValueError
        signed = signing.loads(supplied["token"], salt=SALT, max_age=86400)
        snapshot = _snapshot(case)
        if snapshot is None or signed != snapshot:
            raise ValueError
        if any(supplied[key] != snapshot[key] for key in ("reply_id", "last_message_id", "drafts")):
            raise ValueError
    except (ValueError, TypeError, KeyError, signing.BadSignature):
        raise ValueError(message) from None
    return snapshot


def send_from_chat(case_id, user, body, token, raw_context):
    """Save the human request and all immutable deliveries before any network I/O."""
    from .coordinate_views import _locked_case
    if not user.is_active or not user.is_staff or not explicit_send(body):
        raise ValueError("An explicit send instruction from signed-in staff is required.")
    deliveries = []
    with transaction.atomic(durable=True):
        case = _locked_case(case_id)
        if case.deleted_at or case.purged_at:
            raise ValueError("Restore this case before sending email.")
        previous = CoordinateMessage.objects.filter(client_message_id=token).first()
        if previous:
            if previous.case_id != case.pk or previous.author_id != user.pk or previous.body != body or previous.deleted_at:
                raise ValueError("This message identifier already belongs to another submission.")
            return previous
        error = ""
        try:
            snapshot = _validate_context(case, raw_context)
        except ValueError as exc:
            error = str(exc)
        message = CoordinateMessage.objects.create(case=case, role="staff", body=body, author=user, client_message_id=token)
        if not error:
            try:
                # Reserve the whole bundle or none. A stale/paused later item must
                # not leave an earlier item approved or queued for delivery.
                with transaction.atomic():
                    targets = []
                    for item in snapshot["drafts"]:
                        draft = CoordinateDraft.objects.select_related("case", "job__message", "mail_thread").get(pk=item["id"], case=case)
                        mail.require_draft_visible(draft)
                        mail.require_current_digest(draft, item["content_digest"])
                        delivery = mail.draft_delivery(draft)
                        if delivery:
                            if delivery.status != "sent":
                                raise ValueError("An email in this bundle has a pending or unknown delivery outcome. Check its delivery status before sending more; it will not be resent.")
                            continue
                        if draft_blocked(draft):
                            raise ValueError("A provider thread is paused for Jeremy's price review. Resolve that review before sending these emails.")
                        mail.validate_draft_thread(draft)
                        targets.append((draft, item["content_digest"]))
                    if not targets:
                        raise ValueError("These emails have already been sent. Their delivery receipts are shown below; no duplicates were sent.")
                    for draft, digest in targets:
                        draft.status, draft.reviewed_at, draft.reviewed_by = "reviewed", timezone.now(), user
                        draft.reviewed_digest = digest
                        draft.save(update_fields=["status", "reviewed_at", "reviewed_by", "reviewed_digest"])
                        CoordinateActivity.objects.create(case=case, event="email_draft_reviewed", details={
                            "draft_id": str(draft.pk), "author_id": user.pk, "message_id": message.pk,
                            "reviewed_digest": digest, "approval_method": "staff_chat",
                        })
                        delivery, dispatch = mail.prepare_delivery_locked(case, draft.pk, user, digest, uuid5(token, str(draft.pk)))
                        if dispatch:
                            delivery.approval_snapshot.update(approval_method="staff_chat", approval_message_id=message.pk,
                                                              approval_reply_id=snapshot["reply_id"])
                            delivery.save(update_fields=["approval_snapshot"])
                            deliveries.append(delivery)
            except (ValueError, CoordinateDraft.DoesNotExist) as exc:
                deliveries = []
                error = str(exc) if isinstance(exc, ValueError) else "The displayed emails changed. Review the current emails and ask me to send again."
        reply = CoordinateMessage.objects.create(case=case, role="assistant", in_reply_to=message,
            body=error or f"Sending the {len(deliveries)} saved email{'s' if len(deliveries) != 1 else ''} you approved. Check the delivery status below.")
        CoordinateActivity.objects.create(case=case, event="chat_send_rejected" if error else "chat_send_requested", details={
            "message_id": message.pk, "reply_id": reply.pk, "author_id": user.pk,
            "delivery_ids": [str(d.pk) for d in deliveries],
        })
        CoordinateCase.objects.filter(pk=case.pk).update(updated_at=timezone.now())
    if not deliveries:
        return message
    outcomes = [mail.dispatch_delivery(delivery) for delivery in deliveries]
    sent = sum(delivery.status == "sent" for delivery in outcomes)
    unknown = len(outcomes) - sent
    result = f"Sent {sent} email{'s' if sent != 1 else ''}." if sent else "Sending was attempted."
    if unknown:
        result += f" Delivery is unconfirmed for {unknown}; check the delivery status below. I will not resend them."
    else:
        result += " The delivery receipts are shown below."
    with transaction.atomic():
        case = _locked_case(case_id)
        CoordinateMessage.objects.filter(pk=reply.pk).update(body=result)
        CoordinateCase.objects.filter(pk=case.pk).update(updated_at=timezone.now())
    return message
