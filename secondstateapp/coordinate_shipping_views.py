"""Staff-only plan, quote and draft controls. Reviewing a draft never sends it."""
from decimal import Decimal, InvalidOperation
from functools import wraps
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
import uuid

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from .coordinate_shipping import draft_blocked, enabled, invalidate_context, quote_paused
from .coordinate_mail import draft_digest, require_current_digest, require_draft_editable, validate_draft_thread
from .coordinate_mail_models import CoordinateMailThread
from .models import CoordinateActivity, CoordinateCase, CoordinateDraft, CoordinatePlan, CoordinateQuote


def staff_action(event):
    def decorate(view):
        @never_cache
        @staff_member_required
        @require_POST
        @wraps(view)
        def wrapped(request, case_id, **kwargs):
            from .coordinate_views import _form_error, _locked_case, _state
            case = get_object_or_404(CoordinateCase, pk=case_id)
            if not enabled():
                return JsonResponse({"error": "Shipping workspace is not enabled."}, status=503)
            try:
                with transaction.atomic():
                    case = _locked_case(case_id)
                    if case.deleted_at:
                        return JsonResponse({"error": "Restore this case before editing its shipping records."}, status=409)
                    details = view(request, case, **kwargs) or {}
                    invalidate_context(case)
                    CoordinateCase.objects.filter(pk=case.pk).update(updated_at=timezone.now())
                    CoordinateActivity.objects.create(case=case, event=event, details={"author_id": request.user.pk, **details})
            except ValueError as exc:
                return _form_error(request, str(exc), case)
            if request.headers.get("Accept") == "application/json":
                case.refresh_from_db()
                return JsonResponse(_state(case))
            return redirect("coordinate_case", case_id=case.pk)
        return wrapped
    return decorate


def field(request, name, maximum, required=False):
    value = request.POST.get(name, "").strip()
    if len(value) > maximum or (required and not value):
        raise ValueError(f"Provide {name.replace('_', ' ')} within {maximum:,} characters.")
    return value


def email(value):
    try:
        validate_email(value)
    except ValidationError:
        raise ValueError("Provide one valid recipient email address.")
    if "\n" in value or "\r" in value:
        raise ValueError("Provide one valid recipient email address.")
    return value


def money(value):
    try:
        amount = Decimal(value)
        if not amount.is_finite() or amount < 0 or amount > Decimal("99999999.99") or amount != amount.quantize(Decimal("0.01")):
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        raise ValueError("Enter a non-negative USD amount with at most two decimal places.")
    return amount


@staff_action("shipping_plan_updated")
def update_plan(request, case):
    stage = CoordinatePlan.canonical_stage(field(request, "stage", 20, True))
    destination = field(request, "destination", 20, True)
    if stage not in dict(CoordinatePlan._meta.get_field("stage").choices) or destination not in dict(CoordinatePlan._meta.get_field("destination").choices):
        raise ValueError("Choose a valid stage and destination.")
    deadline_value = field(request, "pickup_deadline", 64)
    deadline = parse_datetime(deadline_value) if deadline_value else None
    if deadline_value and not deadline:
        raise ValueError("Provide a valid pickup deadline.")
    if deadline and timezone.is_naive(deadline):
        deadline = timezone.make_aware(deadline, ZoneInfo("America/New_York"))
    tracking_url = field(request, "tracking_url", 2048)
    try:
        parsed = urlsplit(tracking_url)
        if tracking_url and (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password):
            raise ValueError
    except ValueError:
        raise ValueError("Tracking links must use HTTPS and contain no login credentials.")
    plan, _ = CoordinatePlan.objects.get_or_create(case=case)
    handling = field(request, "handling", 2000)
    if plan.destination != destination or plan.handling != handling:
        case.shipping_quotes.filter(accepted=True).update(accepted=False)
        case.email_drafts.filter(status="reviewed", mail_delivery__isnull=True).update(status="draft", reviewed_at=None, reviewed_by=None, reviewed_digest="")
    if plan.pickup_deadline != deadline:
        plan.deadline_reminded_at = None
    plan.stage, plan.destination, plan.handling = stage, destination, handling
    plan.pickup_deadline, plan.tracking_url = deadline, tracking_url
    plan.tracking_number = field(request, "tracking_number", 200)
    plan.notes = field(request, "notes", 6000)
    plan.save()
    return {"stage": stage, "destination": destination}


@staff_action("shipping_quote_added")
def add_quote(request, case):
    currency = field(request, "currency", 3) or "USD"
    if currency != "USD":
        raise ValueError("Quote approval currently supports USD only. Record other currencies in case notes for review.")
    amount = money(field(request, "amount", 40, True))
    quote = CoordinateQuote.objects.create(case=case, provider_name=field(request, "provider_name", 200, True),
                                           provider_email=email(field(request, "provider_email", 254, True)),
                                           amount=amount, latest_amount=amount, currency=currency)
    return {"quote_id": str(quote.pk)}


@staff_action("shipping_quote_total_updated")
def update_quote(request, case, quote_id):
    quote = get_object_or_404(CoordinateQuote, pk=quote_id, case=case)
    quote.latest_amount = money(field(request, "latest_amount", 40, True))
    quote.save(update_fields=["latest_amount"])
    if quote_paused(quote):
        case.email_drafts.filter(recipient__iexact=quote.provider_email, mail_delivery__isnull=True).update(status="draft", reviewed_at=None, reviewed_by=None, reviewed_digest="")
        CoordinateActivity.objects.create(case=case, event="provider_thread_paused", details={
            "quote_id": str(quote.pk), "accepted_baseline": str(quote.accepted_amount),
            "latest_amount": str(quote.latest_amount), "notify": "Jeremy", "payment_authorized": False,
        })
    return {"quote_id": str(quote.pk), "latest_amount": str(quote.latest_amount), "paused": quote_paused(quote)}


@staff_action("shipping_quote_selected")
def accept_quote(request, case, quote_id):
    quote = get_object_or_404(CoordinateQuote, pk=quote_id, case=case)
    plan = CoordinatePlan.objects.filter(case=case).first()
    if not plan or plan.destination == "undecided" or not plan.handling.strip():
        raise ValueError("Choose the destination and handling method in the shipping plan before selecting a quote.")
    case.shipping_quotes.exclude(pk=quote.pk).filter(accepted=True).update(accepted=False)
    quote.accepted = True
    # Preserve the first accepted provider baseline, even across provider reselection.
    if quote.accepted_amount is None:
        quote.accepted_amount = quote.latest_amount
    quote.accepted_at, quote.accepted_by = timezone.now(), request.user
    quote.accepted_destination, quote.accepted_handling = plan.destination, plan.handling
    quote.save()
    return {"quote_id": str(quote.pk), "accepted_baseline": str(quote.accepted_amount), "payment_authorized": False}


@staff_action("provider_increase_reviewed")
def resolve_quote(request, case, quote_id):
    reviewer = settings.COORDINATE_PRICE_REVIEWER_USERNAME
    if not reviewer or request.user.get_username() != reviewer:
        raise ValueError("Jeremy must review this increase before replies on this provider thread resume.")
    quote = get_object_or_404(CoordinateQuote, pk=quote_id, case=case)
    note = field(request, "note", 2000, True)
    if not quote_paused(quote):
        raise ValueError("This quote has no unreviewed price increase requiring a pause.")
    quote.increase_reviewed_amount, quote.increase_review_note = quote.latest_amount, note
    quote.save(update_fields=["increase_reviewed_amount", "increase_review_note"])
    return {"quote_id": str(quote.pk), "reviewed_total": str(quote.latest_amount), "payment_authorized": False}


def draft_fields(request, case):
    recipient = email(field(request, "recipient", 254, True))
    subject = field(request, "subject", 200, True)
    if "\n" in subject or "\r" in subject:
        raise ValueError("The subject must fit on one line.")
    quote_id = field(request, "quote_id", 36)
    if quote_id:
        try:
            uuid.UUID(quote_id)
        except ValueError:
            raise ValueError("Choose a valid provider quote.")
    quote = get_object_or_404(CoordinateQuote, pk=quote_id, case=case) if quote_id else None
    thread_id = field(request, "thread_id", 36)
    try:
        thread = CoordinateMailThread.objects.get(pk=uuid.UUID(thread_id), case=case) if thread_id else None
    except (ValueError, CoordinateMailThread.DoesNotExist):
        raise ValueError("Choose a valid email thread from this case.") from None
    candidate = CoordinateDraft(case=case, recipient=recipient, subject=subject, mail_thread=thread)
    validate_draft_thread(candidate)
    return {"recipient": recipient, "subject": subject, "body": field(request, "body", 12000, True),
            "purpose": field(request, "purpose", 300), "quote": quote, "mail_thread": thread}


@staff_action("email_draft_added")
def add_draft(request, case):
    draft = CoordinateDraft.objects.create(case=case, **draft_fields(request, case))
    return {"draft_id": str(draft.pk), "sent": False}


@staff_action("email_draft_edited")
def update_draft(request, case, draft_id):
    draft = get_object_or_404(CoordinateDraft, pk=draft_id, case=case)
    require_draft_editable(draft)
    require_current_digest(draft, request.POST.get("content_digest"))
    for name, value in draft_fields(request, case).items():
        setattr(draft, name, value)
    draft.status, draft.reviewed_at, draft.reviewed_by, draft.reviewed_digest = "draft", None, None, ""
    draft.save()
    return {"draft_id": str(draft.pk), "sent": False}


@staff_action("email_draft_reviewed")
def review_draft(request, case, draft_id):
    draft = get_object_or_404(CoordinateDraft, pk=draft_id, case=case)
    require_draft_editable(draft)
    require_current_digest(draft, request.POST.get("content_digest"))
    validate_draft_thread(draft)
    if draft_blocked(draft):
        raise ValueError("This provider thread is paused for Jeremy's price review. Even acknowledgment must wait.")
    draft.status, draft.reviewed_at, draft.reviewed_by = "reviewed", timezone.now(), request.user
    draft.reviewed_digest = draft_digest(draft)
    draft.save(update_fields=["status", "reviewed_at", "reviewed_by", "reviewed_digest"])
    return {"draft_id": str(draft.pk), "sent": False}
