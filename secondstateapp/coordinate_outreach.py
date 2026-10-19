"""Bounded initial quote requests. Test routing is enforced before transport."""
from datetime import timedelta
import hashlib
from uuid import UUID, uuid4

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from . import coordinate_mail as mail
from .coordinate_brief import brief_state
from .coordinate_shipping import enabled, invalidate_context, visible_artifacts
from .coordinate_views import _locked_case, _mail_visible, _worker_endpoint
from scripts.coordinate_brief_contract import _normalized
from .models import (CoordinateActivity, CoordinateCase, CoordinateDraft, CoordinateJob,
    CoordinateMailDelivery, CoordinateMailMessage, CoordinateOutreachPolicy, CoordinatePlan, CoordinateQuoteInquiry)

TEST_RECIPIENT = "jeremy@secondstate.art"
MAX_INITIAL_INQUIRIES = 3
MAX_PACKET_CHARS = 12000


def _policy_visible(policy, case, max_message_id=None):
    if not policy or case.deleted_at:
        return False
    query = CoordinateOutreachPolicy.objects.filter(pk=policy.pk, originating_message__case=case,
        originating_message__role="staff", originating_message__deleted_at__isnull=True,
        originating_message__worker_reply__deleted_at__isnull=True,
        originating_message__created_at__lte=timezone.now(), authorized_by__is_active=True, authorized_by__is_staff=True)
    if max_message_id is not None:
        query = query.filter(originating_message_id__lte=max_message_id)
    return query.exists()


def _existing_dispatch(worker_id, request_id):
    existing = CoordinateMailDelivery.objects.select_related("draft__case", "draft__job__message").filter(request_id=request_id).first()
    if existing:
        if (existing.draft.case.coordinator != worker_id
                or existing.approval_snapshot.get("authorization") not in ("initial_quote_test", "initial_quote_live")):
            raise ValueError("This dispatch identifier belongs to another operation.")
        mail.require_draft_visible(existing.draft)
        if not existing.draft.job_id or existing.draft.job.message.created_at > timezone.now():
            raise ValueError("This inquiry context is not currently visible.")
    return existing


def outreach_state(case, max_message_id=None):
    policy = CoordinateOutreachPolicy.objects.filter(case=case).first()
    result = {"mode": "off", "test_recipient": TEST_RECIPIENT,
              "settings_url": reverse("coordinate_outreach_settings", args=[case.pk])}
    if _policy_visible(policy, case, max_message_id):
        result.update(mode=policy.mode, destination=policy.destination,
                      destination_address=policy.destination_address, authorized_at=policy.authorized_at.isoformat())
    inquiries = CoordinateQuoteInquiry.objects.filter(case=case,
        draft__in=visible_artifacts(CoordinateDraft.objects.filter(job__message__created_at__lte=timezone.now())))
    if max_message_id is not None:
        inquiries = inquiries.filter(draft__job__message_id__lte=max_message_id)
    result["inquiries"] = [] if case.deleted_at else [{"provider": item.provider_name, "intended_recipient": item.provider_email,
        "mode": item.mode, "draft_id": str(item.draft_id)} for item in
        inquiries[:12]]
    return result


@never_cache
@staff_member_required
@require_http_methods(["GET", "POST"])
def configure(request, case_id):
    case = get_object_or_404(CoordinateCase, pk=case_id, deleted_at__isnull=True)
    error = ""
    if request.method == "POST":
        mode = request.POST.get("mode", "off")
        destination = request.POST.get("destination", "")
        address = request.POST.get("destination_address", "").strip()
        choices = dict(CoordinatePlan._meta.get_field("destination").choices)
        if mode not in ("off", "test", "live"):
            error = "Choose a valid inquiry mode."
        elif mode == "live" and not settings.COORDINATE_LIVE_QUOTE_OUTREACH_ENABLED:
            error = "Real provider outreach is not enabled. Finish the test and authorize rollout first."
        elif len(address) > 600 or "\x00" in address:
            error = "Provide the delivery address within 600 characters."
        elif mode != "off" and (destination not in choices or destination == "undecided" or not 10 <= len(address) <= 600):
            error = "Choose the destination and supply its complete delivery address."
        else:
            with transaction.atomic():
                case = _locked_case(case.pk)
                origin = case.messages.filter(role="staff", deleted_at__isnull=True,
                    worker_reply__deleted_at__isnull=True, created_at__lte=timezone.now()).order_by("-pk").first()
                if case.deleted_at or origin is None:
                    error = "Visible staff context is required."
                else:
                    policy, _ = CoordinateOutreachPolicy.objects.update_or_create(case=case, defaults={
                        "mode": mode, "destination": destination, "destination_address": address,
                        "authorized_by": request.user, "originating_message": origin})
                    CoordinateActivity.objects.create(case=case, event="quote_outreach_authorized", details={
                        "mode": mode, "destination": destination, "author_id": request.user.pk,
                        "test_recipient": TEST_RECIPIENT if mode == "test" else "",
                        "scope": "at most three initial non-binding quote inquiries; no booking, acceptance or payment"})
                    invalidate_context(case)
                    CoordinateCase.objects.filter(pk=case.pk).update(updated_at=timezone.now())
            if not error:
                if request.headers.get("Accept") == "application/json":
                    return JsonResponse(outreach_state(case))
                return redirect("coordinate_case", case_id=case.pk)
    return render(request, "coordinate/outreach_settings.html", {"case": case,
        "outreach": outreach_state(case), "error": error,
        "destinations": CoordinatePlan._meta.get_field("destination").choices,
        "live_enabled": settings.COORDINATE_LIVE_QUOTE_OUTREACH_ENABLED}, status=400 if error else 200)


def quote_packet(brief, provider, policy):
    """Build a narrow request from validated facts, never arbitrary action text."""
    lines = [f"hi {provider['name']}!", "", "we won the works below and would love a quote for collection, packing and shipping!",
        "", "destination: SecondState, " + policy.destination_address, ""]
    for lot in brief["lots"]:
        lines.append("lot " + (lot.get("lot_number") or "number unconfirmed") + ": " + (lot.get("artist") or "") + " — " + (lot.get("title") or lot["label"]))
        for key, label in (("auction_house", "auction house"), ("auction_date", "sale date"),
            ("medium", "medium"), ("edition", "edition"), ("dimensions", "artwork dimensions as listed"),
            ("framed_dimensions", "framed dimensions as listed"), ("framing", "listed framing/mounting"),
            ("condition", "seller-stated condition"), ("pickup_location", "collection location"),
            ("deadline_text", "published removal terms"), ("release_requirements", "published release requirements"),
            ("storage_terms", "published storage terms")):
            if lot.get(key):
                lines.append(label + ": " + lot[key])
        lines.extend(ref for ref in lot["source_refs"] if ref.startswith("https://"))
        lines.append("")
    currency = brief["shipping"]["working_currency"]
    if currency["code"]:
        lines.extend(["please quote in " + currency["code"] + (" (our working currency assumption; please correct us if needed)." if currency["basis"] == "inferred" else "."), ""])
    lines.extend([
        "could you itemize collection, packing, shipping and any coverage options, and let us know your availability?",
        "please quote shipping in the current frames, and, only if your handler is comfortable doing it safely, an alternative with the frames removed, original mats retained wherever possible, glassine protection and a rigid cardboard sandwich. please explain your experience with these prints and any handling constraints; do not detach a hinged print from its mat.",
        "please account for both artwork and framed dimensions above. please identify any measurements or glazing/mounting details that need confirmation and tell us what you would need before a final quote. any loose certificate or accompanying item should stay with its work.",
        "this is a non-binding quote request only. no pickup, packing, frame removal, booking, charges, payment, or quote acceptance is authorized. the invoice, payment clearance, release authorization and any agreed insurance value will be confirmed before collection.",
        "", "thanks!", "jeremy / secondstate"])
    subject = "collection & packing quote — " + (brief["lots"][0].get("auction_house") or "auction works")
    if policy.mode == "test":
        # All pilot messages share From/To. Distinct subjects keep provider mock
        # replies in separate Gmail conversations, even after title truncation.
        provider_key = hashlib.sha256(provider["email"].casefold().encode()).hexdigest()[:12]
        subject = f"[quote test {policy.case_id}:{provider_key}] {provider['name'][:40]} — " + subject
        lines = [f"test delivery to Jeremy; intended provider: {provider['name']} <{provider['email']}>. no provider has been contacted.", "", *lines]
    return subject[:200], "\n".join(lines)


def prepare_next(worker_id, request_id):
    """Case lock serializes workers; committed receipt uncertainty never resends."""
    if not enabled() or not mail.mail_readiness()["ready"]:
        return None
    existing = _existing_dispatch(worker_id, request_id)
    if existing:
        return existing, False
    for policy_id in CoordinateOutreachPolicy.objects.filter(mode__in=["test", "live"],
            case__deleted_at__isnull=True, case__coordinator=worker_id).values_list("pk", flat=True)[:20]:
        identity = CoordinateOutreachPolicy.objects.get(pk=policy_id)
        with transaction.atomic(durable=True):
            case = _locked_case(identity.case_id)
            existing = _existing_dispatch(worker_id, request_id)
            if existing:
                return existing, False
            policy = CoordinateOutreachPolicy.objects.select_for_update().select_related("originating_message").get(pk=policy_id)
            if (not _policy_visible(policy, case) or policy.mode not in ("test", "live")
                    or (policy.mode == "live" and not settings.COORDINATE_LIVE_QUOTE_OUTREACH_ENABLED)):
                continue
            # Let current research finish; never send from a stale brief while a new input is pending.
            if CoordinateJob.objects.filter(_mail_visible("message__"), message__case=case,
                    message__deleted_at__isnull=True).exclude(status__in=["completed", "cancelled"]).exists():
                continue
            plan = CoordinatePlan.objects.filter(case=case).first()
            if plan and plan.destination not in ("undecided", policy.destination):
                continue
            if plan and CoordinatePlan.canonical_stage(plan.stage) != "preparing":
                continue
            brief = brief_state(case)
            if not brief or not brief.get("shipping") or brief["shipping"]["quote_readiness"]["status"] != "conditional_ready":
                continue
            job = CoordinateJob.objects.select_related("message").get(pk=brief["job_id"])
            if job.message_id < policy.originating_message_id or job.status != "completed" or job.message.created_at > timezone.now():
                continue
            if case.messages.filter(role="staff", deleted_at__isnull=True, pk__gt=job.message_id).exists():
                continue
            # Public provider evidence must still be fresh and visible. Private staff/input is not a provider directory.
            fresh = visible_artifacts(case.research.filter(job__message_id__lte=job.message_id,
                fetched_at__gte=timezone.now() - timedelta(hours=24), fetched_at__lte=timezone.now(), error="",
                source_kind__in=["public_fetch", "public_browser"], identity_match__status__in=["exact", "context"]))
            inquiries = CoordinateQuoteInquiry.objects.filter(case=case, mode=policy.mode)
            if inquiries.count() >= MAX_INITIAL_INQUIRIES:
                continue
            for provider in brief["shipping"]["providers"]:
                recipient = provider["email"].casefold()
                if (not recipient or inquiries.filter(provider_email=recipient).exists()
                        or case.shipping_quotes.filter(provider_email__iexact=recipient).exists()
                        or case.mail_threads.filter(provider_email__iexact=recipient).exists()):
                    continue
                contact = _normalized(provider["contact_quote"])
                if not contact or not any(contact in _normalized(source.text) for source in
                        fresh.filter(final_url__in=provider["source_refs"], text__icontains=recipient)):
                    continue
                if not brief["lots"] or any(not lot.get("dimensions") and not lot.get("framed_dimensions") for lot in brief["lots"]):
                    continue
                subject, body = quote_packet(brief, provider, policy)
                if len(body) > MAX_PACKET_CHARS or any(char in subject + recipient for char in "\r\n\x00"):
                    continue
                origin = job.message
                source_mail = CoordinateMailMessage.objects.select_related("thread__originating_message").filter(message_id=origin.pk).first()
                if source_mail:
                    origin = source_mail.thread.originating_message
                draft = CoordinateDraft.objects.create(case=case, job=job, recipient=recipient,
                    subject=subject, body=body, purpose="Initial non-binding packing and shipping quote inquiry")
                CoordinateQuoteInquiry.objects.create(case=case, mode=policy.mode, provider_email=recipient,
                    provider_name=provider["name"], draft=draft)
                delivery_id = uuid4()
                delivery = CoordinateMailDelivery.objects.create(id=delivery_id, draft=draft, request_id=request_id,
                    status="sending", sender_email=mail.SENDER, recipient=TEST_RECIPIENT if policy.mode == "test" else recipient,
                    subject=subject, body=body, reviewed_digest=mail.draft_digest(draft), requested_by=policy.authorized_by,
                    rfc_message_id=f"<coordinate-{delivery_id}@secondstate.art>", approval_snapshot={
                        "authorization": "initial_quote_" + policy.mode, "intended_recipient": recipient,
                        "provider_name": provider["name"], "originating_message_id": origin.pk,
                        "destination": policy.destination, "destination_address": policy.destination_address,
                        "authorized_by_id": policy.authorized_by_id, "authorized_at": policy.authorized_at.isoformat(),
                        "source_refs": provider["source_refs"], "brief_id": brief["id"]})
                CoordinateActivity.objects.create(case=case, event="quote_inquiry_requested", details={
                    "delivery_id": str(delivery.pk), "mode": policy.mode, "intended_recipient": recipient,
                    "actual_recipient": delivery.recipient})
                invalidate_context(case)
                CoordinateCase.objects.filter(pk=case.pk).update(updated_at=timezone.now())
                return delivery, True
    return None


@transaction.non_atomic_requests
@_worker_endpoint
def dispatch(request, data):
    try:
        request_id = UUID(data.get("request_id", ""))
    except (ValueError, TypeError, AttributeError):
        return JsonResponse({"error": "A stable dispatch request_id is required."}, status=400)
    try:
        existing = _existing_dispatch(data["worker_id"], request_id)
        result = (existing, False) if existing else prepare_next(data["worker_id"], request_id)
    except (ValueError, IntegrityError):
        return JsonResponse({"error": "Inquiry dispatch conflicts with a saved operation or hidden context."}, status=409)
    if result is None:
        return JsonResponse({"status": "outreach_idle"})
    delivery, send = result
    if send:
        try:
            receipt = mail.send_snapshot(delivery)
            mail.record_provider_receipt(delivery.pk, receipt.get("id"), receipt.get("threadId"))
            delivery = mail.record_delivery_success(delivery.pk, receipt.get("id"), receipt.get("threadId"))
        except Exception as error:
            mail.mark_delivery_unknown(delivery.pk, error)
            delivery.refresh_from_db()
    return JsonResponse({"status": delivery.status, "case_id": str(delivery.draft.case_id),
        "delivery_id": str(delivery.pk), "mode": delivery.approval_snapshot["authorization"],
        "actual_recipient": delivery.recipient, "intended_recipient": delivery.approval_snapshot["intended_recipient"]})
