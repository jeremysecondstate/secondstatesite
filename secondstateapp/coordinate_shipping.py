"""Shipping context, draft persistence and deadline checks. No sending capability."""
from collections import Counter
from datetime import timedelta
from decimal import Decimal
import re
import uuid
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from scripts.coordinate_evidence import (
    NEW_SOURCE_KINDS, PROVENANCE_FIELDS, research_identity_key,
    validate_evidence_provenance, validate_research_bounds,
)

from .models import (
    CoordinateActivity, CoordinateCase, CoordinateDraft, CoordinateJob,
    CoordinateMessage, CoordinatePlan, CoordinateQuote, CoordinateResearch,
)

EMAIL_PATTERN = re.compile(r"[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9](?:[A-Z0-9.-]*[A-Z0-9])?\.[A-Z]{2,}", re.I)


def enabled():
    return settings.COORDINATE_DRAFT_WORKFLOW_ENABLED


def quote_paused(quote):
    return bool(quote.accepted_amount is not None
                and quote.latest_amount - quote.accepted_amount >= Decimal("50")
                and (quote.increase_reviewed_amount is None or quote.latest_amount > quote.increase_reviewed_amount))


def draft_blocked(draft, quotes=None):
    quotes = quotes if quotes is not None else draft.case.shipping_quotes.all()
    return any(quote_paused(quote) and (draft.quote_id == quote.pk or draft.recipient.casefold() == quote.provider_email.casefold()) for quote in quotes)


def visible_artifacts(query):
    # Deleted conversation inputs must not re-enter the model through derived artifacts.
    return query.filter(Q(job__isnull=True) | Q(job__message__deleted_at__isnull=True, job__message__worker_reply__deleted_at__isnull=True))


def research_state(case, max_message_id=None):
    result, seen, per_source = [], set(), Counter()
    query = case.research.all()
    if max_message_id is not None:
        query = query.filter(job__message_id__lte=max_message_id)
    for item in visible_artifacts(query)[:120]:
        key = (item.source_url, item.final_url, item.source_kind)
        if key in seen or per_source[item.source_url] >= 6:
            continue
        seen.add(key)
        per_source[item.source_url] += 1
        result.append({"source_url": item.source_url, "final_url": item.final_url, "title": item.title,
                       "text": item.text, "fetched_at": item.fetched_at.isoformat(), "error": item.error,
                       "source_kind": item.source_kind, "public_error": item.public_error,
                       **({field: getattr(item, field) for field in PROVENANCE_FIELDS}
                          if item.source_kind in NEW_SOURCE_KINDS else {})})
        if len(result) == 24:
            break
    return result


def coordination_state(case, max_message_id=None):
    if not case or case.deleted_at or not enabled():
        return None
    plan = CoordinatePlan.objects.filter(case=case).first() or CoordinatePlan(case=case)
    quotes = list(case.shipping_quotes.all())
    draft_query = case.email_drafts.select_related("quote")
    if max_message_id is not None:
        draft_query = draft_query.filter(Q(job__isnull=True) | Q(job__message_id__lte=max_message_id))
    drafts = list(visible_artifacts(draft_query))
    from .coordinate_brief import brief_state
    from .coordinate_intake import intake_state
    return {
        "draft_only": True,
        "brief": brief_state(case, max_message_id=max_message_id),
        **({"intake": intake_state(case)} if max_message_id is None else {}),
        "plan": {"stage": plan.stage, "destination": plan.destination, "handling": plan.handling,
                 "pickup_deadline": plan.pickup_deadline.astimezone(ZoneInfo("America/New_York")).isoformat() if plan.pickup_deadline else "",
                 "notes": plan.notes, "tracking_number": plan.tracking_number, "tracking_url": plan.tracking_url,
                 "update_url": reverse("coordinate_plan", args=[case.pk])},
        "quotes": [{"id": str(q.pk), "provider_name": q.provider_name, "provider_email": q.provider_email,
                    "amount": str(q.amount), "currency": q.currency, "latest_amount": str(q.latest_amount),
                    "accepted": q.accepted, "accepted_amount": str(q.accepted_amount) if q.accepted_amount is not None else None,
                    "accepted_destination": q.accepted_destination, "accepted_handling": q.accepted_handling,
                    "increase_reviewed_amount": str(q.increase_reviewed_amount) if q.increase_reviewed_amount is not None else None,
                    "increase_review_note": q.increase_review_note,
                    "paused": quote_paused(q), "change_amount": str(q.latest_amount - q.accepted_amount) if q.accepted_amount is not None else "0.00",
                    "update_url": reverse("coordinate_quote_update", args=[case.pk, q.pk]),
                    "accept_url": reverse("coordinate_quote_accept", args=[case.pk, q.pk]),
                    "resolve_url": reverse("coordinate_quote_resolve", args=[case.pk, q.pk])} for q in quotes],
        "drafts": [{"id": str(d.pk), "recipient": d.recipient, "subject": d.subject, "body": d.body,
                    "purpose": d.purpose, "status": d.status, "blocked": draft_blocked(d, quotes),
                    "quote_id": str(d.quote_id) if d.quote_id else "",
                    "save_url": reverse("coordinate_draft_update", args=[case.pk, d.pk]),
                    "review_url": reverse("coordinate_draft_review", args=[case.pk, d.pk])} for d in drafts],
        "research": research_state(case, max_message_id=max_message_id),
        "urls": {"add_quote": reverse("coordinate_quote_add", args=[case.pk]),
                 "add_draft": reverse("coordinate_draft_add", args=[case.pk])},
    }


def _bounded_string(value, maximum, required=False):
    if not isinstance(value, str) or len(value) > maximum or (required and not value.strip()):
        raise ValueError("Invalid worker artifact text.")
    return value.strip()


def _research_url(value, required=True, allow_http=False):
    value = _bounded_string(value, 2048, required)
    if not value and not required:
        return value
    try:
        parsed = urlsplit(value)
        allowed_ports = {"https": 443, **({"http": 80} if allow_http else {})}
        if (parsed.scheme not in allowed_ports or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.port not in (None, allowed_ports[parsed.scheme])):
            raise ValueError
    except ValueError:
        raise ValueError("Research URLs must use HTTPS, or standard HTTP for a failed fetch, without credentials.")
    return value


def validate_worker_artifacts(data):
    research, drafts = data.get("research", []), data.get("drafts", [])
    if not isinstance(research, list) or len(research) > 24 or not isinstance(drafts, list) or len(drafts) > 3:
        raise ValueError("Too many worker artifacts.")
    if len(research) > 8 and all(isinstance(item, dict) and item.get("source_kind", "public") not in NEW_SOURCE_KINDS for item in research):
        raise ValueError("Too many legacy research records.")
    cleaned_research, cleaned_drafts = [], []
    seen = set()
    for item in research:
        if not isinstance(item, dict):
            raise ValueError("Invalid research record.")
        source_kind = item.get("source_kind", "public")
        if source_kind not in ("public", "browser", *NEW_SOURCE_KINDS):
            raise ValueError("Invalid research source kind.")
        if source_kind not in NEW_SOURCE_KINDS and any(field in item for field in PROVENANCE_FIELDS):
            raise ValueError("Discovery provenance requires an explicit research observation kind.")
        error = _bounded_string(item.get("error", ""), 200)
        public_error = _bounded_string(item.get("public_error", ""), 200)
        browser_source = source_kind in ("browser", "public_browser", "authenticated_browser")
        source_url = _research_url(item.get("source_url"), allow_http=bool(error) or browser_source or source_kind == "search_only")
        final_url = _research_url(item.get("final_url", ""), False, allow_http=bool(error) and not browser_source)
        title = _bounded_string(item.get("title", ""), 300)
        text = _bounded_string(item.get("text", ""), 6000)
        provenance = {}
        if source_kind in NEW_SOURCE_KINDS:
            provenance = validate_evidence_provenance(item)
        elif browser_source:
            if not public_error:
                raise ValueError("Browser sources must preserve the public fetch failure.")
            if any(character.isspace() or ord(character) < 32 or character == "\\" for character in source_url + final_url):
                raise ValueError("Invalid browser source URL.")
            if source_url != item.get("source_url") or final_url != item.get("final_url", ""):
                raise ValueError("Browser source URLs must match the observed URLs exactly.")
            if final_url:
                source_host = urlsplit(source_url).hostname.lower().removeprefix("www.")
                final_host = urlsplit(final_url).hostname.lower().removeprefix("www.")
                if final_host not in (source_host, "invaluable.com"):
                    raise ValueError("Browser sources must remain on the source site or Invaluable.")
            if error and (text or title):
                raise ValueError("Failed browser sources cannot contain source evidence.")
            if not error and (not text or not final_url):
                raise ValueError("Successful browser sources require observed text and a final URL.")
        elif public_error:
            raise ValueError("Only browser sources may include a prior public fetch failure.")
        key = research_identity_key({**item, "source_url": source_url, "final_url": final_url})
        if key in seen:
            raise ValueError("Duplicate research source.")
        seen.add(key)
        fetched = parse_datetime(_bounded_string(item.get("fetched_at"), 64, True))
        if not fetched or timezone.is_naive(fetched) or fetched > timezone.now() + timedelta(minutes=5):
            raise ValueError("Invalid research timestamp.")
        cleaned_research.append({"source_url": source_url, "final_url": final_url, "title": title, "text": text,
                                 "error": error, "fetched_at": fetched, "source_kind": source_kind,
                                 "public_error": public_error, **provenance})
    validate_research_bounds(cleaned_research)
    for item in drafts:
        if not isinstance(item, dict):
            raise ValueError("Invalid draft record.")
        recipient = _bounded_string(item.get("recipient"), 254, True)
        subject = _bounded_string(item.get("subject"), 200, True)
        try:
            validate_email(recipient)
        except ValidationError:
            raise ValueError("Invalid draft recipient.")
        if any(c in recipient + subject for c in "\r\n"):
            raise ValueError("Invalid draft header.")
        cleaned_drafts.append({"recipient": recipient, "subject": subject,
                               "body": _bounded_string(item.get("body"), 12000, True),
                               "purpose": _bounded_string(item.get("purpose", ""), 300)})
    if not enabled() and (cleaned_research or cleaned_drafts):
        raise ValueError("Shipping research and drafts are not enabled.")
    return cleaned_research, cleaned_drafts


def save_worker_artifacts(job, artifacts):
    research, drafts = artifacts
    case = job.message.case
    # Recipients must have been provided in case context or successful source evidence.
    quotes = list(case.shipping_quotes.order_by("-accepted", "created_at"))
    known = {quote.provider_email.casefold() for quote in quotes}
    staff_messages = list(case.messages.filter(role="staff", deleted_at__isnull=True,
                                               pk__lte=job.message_id).values("role", "body"))
    staff_text = "\n".join(message["body"] for message in staff_messages)
    from scripts.coordinate_sources import public_identity, staff_urls
    requested_urls = set(staff_urls(staff_messages))
    expected_identities = {}
    for item in research:
        if (not item["error"] and item["source_kind"] in ("public", "public_fetch")
                and item.get("discovery_method", "direct") == "direct"):
            expected_identities[item["source_url"]] = public_identity(item)
    for item in research:
        if item["source_kind"] in NEW_SOURCE_KINDS:
            if item["source_url"] not in requested_urls:
                raise ValueError("Research must retain an original visible submitted URL from this job's context.")
            if item["fetched_at"] < timezone.now() - timedelta(hours=24):
                raise ValueError("New research observations must be fresh within 24 hours.")
            validate_evidence_provenance(item, expected_identity=expected_identities.get(item["source_url"]))
    plan_notes = CoordinatePlan.objects.filter(case=case).values_list("notes", flat=True).first() or ""
    successful_sources = [r["text"] for r in [*research, *research_state(case, job.message_id)]
                          if not r["error"] and r.get("source_kind") != "search_only"
                          and r.get("identity_match", {}).get("status") not in ("historical", "unverified")]
    from .coordinate_intake import intake_context
    successful_sources.extend(item.get("text", "") for item in intake_context(case, job.message_id))
    for source in [staff_text, plan_notes, *successful_sources]:
        known.update(match.casefold() for match in EMAIL_PATTERN.findall(source))
    for draft in drafts:
        if draft["recipient"].casefold() not in known:
            raise ValueError("Draft recipient has no supporting case evidence.")
    for item in research:
        CoordinateResearch.objects.create(case=case, job=job, **item)
    saved_drafts = 0
    for item in drafts:
        provider_quotes = [quote for quote in quotes if quote.provider_email.casefold() == item["recipient"].casefold()]
        # A paused provider thread must receive no newly prepared response.
        if any(quote_paused(quote) for quote in provider_quotes):
            continue
        quote = provider_quotes[0] if provider_quotes else None
        CoordinateDraft.objects.create(case=case, job=job, quote=quote, **item)
        saved_drafts += 1
    if research or drafts:
        CoordinateActivity.objects.create(case=case, job=job, event="research_and_drafts_saved",
                                          details={"research_count": len(research), "draft_count": saved_drafts, "sent": False})


def invalidate_context(case):
    """A saved staff decision invalidates work generated from its earlier version."""
    CoordinateJob.objects.filter(message__case=case, status="processing").update(
        status="retry", claim_token=None, lease_expires_at=None, available_at=timezone.now(),
        last_error="Case details changed; pending a fresh worker check.")


def enqueue_due_reviews():
    """One durable reminder per recorded pickup deadline, even without new messages."""
    if not enabled():
        return
    from .coordinate_views import _locked_case
    now = timezone.now()
    due = CoordinatePlan.objects.filter(
        case__deleted_at__isnull=True, pickup_deadline__lte=now + timedelta(hours=48),
        deadline_reminded_at__isnull=True, stage__in=["gathering", "quotes", "ready"],
    ).values_list("case_id", flat=True)[:20]
    for case_id in list(due):
        with transaction.atomic():
            case = _locked_case(case_id)
            if case.deleted_at:
                continue
            plan = CoordinatePlan.objects.get(case=case)
            if plan.deadline_reminded_at or plan.stage not in ("gathering", "quotes", "ready") or not plan.pickup_deadline or plan.pickup_deadline > now + timedelta(hours=48):
                continue
            plan.deadline_reminded_at = now
            plan.save(update_fields=["deadline_reminded_at"])
            message = CoordinateMessage.objects.create(
                case=case, role="system", client_message_id=uuid.uuid4(),
                body=f"Pickup deadline check: the recorded deadline is {plan.pickup_deadline.isoformat()}. Review the saved case plan and identify any decision or missing information needed. No external action is authorized.",
            )
            job = CoordinateJob.objects.create(message=message)
            CoordinateCase.objects.filter(pk=case.pk).update(updated_at=now)
            CoordinateActivity.objects.create(case=case, job=job, event="pickup_deadline_review_queued",
                                              details={"deadline": plan.pickup_deadline.isoformat()})
