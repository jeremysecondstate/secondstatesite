"""Staff inventory messages and a claim-bound local workbook workflow."""
import hashlib
import json
import secrets
import uuid
from datetime import date, timedelta
from functools import wraps
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.db import IntegrityError, OperationalError, transaction
from django.db.models import Exists, F, OuterRef, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .models import AuctionWatchLot, InventoryCase, InventoryClaimRequest, InventoryJob, InventoryMessage, InventoryWorkerState

LEASE_SECONDS = 1800
MAX_BODY = 12000


def _error(message, status=400):
    return JsonResponse({"error": message}, status=status)


def _iso(value):
    return value.isoformat() if value else None


def _message(message):
    job = getattr(message, "job", None)
    return {
        "id": message.pk, "role": message.role, "body": message.body,
        "author": message.author.get_username() if message.author else "Codex",
        "created_at": _iso(message.created_at),
        "status": job.status if job else "completed", "error": job.last_error if job else "",
        "result": job.result if job else {},
        "retry_url": reverse("inventory_retry", args=[job.pk]) if job and job.status == "failed" else None,
    }


def _state(selected=None):
    statuses = {}
    for job in InventoryJob.objects.exclude(status="completed").select_related("message").order_by("message_id"):
        statuses.setdefault(job.message.case_id, job.status)
    cases = [{"id": str(case.pk), "title": case.title, "url": reverse("inventory_case", args=[case.pk]),
              "status": statuses.get(case.pk, "completed"), "updated_at": _iso(case.updated_at)}
             for case in InventoryCase.objects.all()[:200]]
    worker = InventoryWorkerState.objects.filter(pk=1).first()
    return {
        "cases": cases,
        "selected_case": {"id": str(selected.pk), "title": selected.title,
                          "url": reverse("inventory_case", args=[selected.pk])} if selected else None,
        "messages": [_message(m) for m in selected.messages.select_related("author", "job")] if selected else [],
        "worker": {"last_successful_check": _iso(worker.last_successful_check) if worker else None},
        "message_token": str(uuid.uuid4()),
    }


@never_cache
@staff_member_required
@require_GET
def inventory(request, case_id=None):
    case = get_object_or_404(InventoryCase, pk=case_id) if case_id else None
    if case is None and request.GET.get("new") != "1":
        case = InventoryCase.objects.first()
    return render(request, "inventory/index.html", _state(case))


@never_cache
@staff_member_required
@require_GET
def state(request):
    try:
        case_id = uuid.UUID(request.GET["case"]) if request.GET.get("case") else None
    except (TypeError, ValueError):
        return _error("Invalid request identifier.")
    return JsonResponse(_state(get_object_or_404(InventoryCase, pk=case_id) if case_id else None))


def _saved(request, case):
    if request.headers.get("Accept") == "application/json":
        return JsonResponse(_state(case))
    return redirect("inventory_case", case_id=case.pk)


def _submit(request, case=None):
    submitted_case_id = case.pk if case else None
    body = request.POST.get("body", "").strip()
    title = request.POST.get("title", "").strip() or body[:100]
    try:
        token = uuid.UUID(request.POST.get("client_message_id", ""))
    except (TypeError, ValueError, AttributeError):
        return _error("Reload this page before sending your message.")
    if not body or len(body) > MAX_BODY or len(title) > 160:
        return _error("Use a message of 1–12,000 characters and a title of at most 160 characters.")

    def duplicate():
        existing = InventoryMessage.objects.select_related("case").filter(client_message_id=token).first()
        if existing:
            if existing.author_id != request.user.pk or existing.body != body or (submitted_case_id and existing.case_id != submitted_case_id):
                return _error("This message identifier belongs to another submission.", 409)
            return _saved(request, existing.case)
        return None

    response = duplicate()
    if response is not None:
        return response
    try:
        with transaction.atomic():
            if case:
                case = InventoryCase.objects.select_for_update().get(pk=case.pk)
            else:
                case = InventoryCase.objects.create(title=title, created_by=request.user)
            message = InventoryMessage.objects.create(case=case, role="staff", body=body, author=request.user, client_message_id=token)
            InventoryJob.objects.create(message=message)
            InventoryCase.objects.filter(pk=case.pk).update(updated_at=timezone.now())
    except IntegrityError:
        response = duplicate()
        if response is not None:
            return response
        raise
    return _saved(request, case)


@staff_member_required
@require_POST
def create_case(request):
    return _submit(request)


@staff_member_required
@require_POST
def add_message(request, case_id):
    return _submit(request, get_object_or_404(InventoryCase, pk=case_id))


@staff_member_required
@require_POST
def retry_job(request, job_id):
    job = get_object_or_404(InventoryJob.objects.select_related("message__case"), pk=job_id)
    InventoryJob.objects.filter(pk=job.pk, status="failed").update(status="retry", available_at=timezone.now(), last_error="", claim_token=None)
    return _saved(request, job.message.case)


def _worker_endpoint(view):
    @csrf_exempt
    @never_cache
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        expected = getattr(settings, "INVENTORY_WORKER_TOKEN", "") or settings.COORDINATE_WORKER_TOKEN
        if not expected:
            return _error("Inventory worker authentication is not configured.", 503)
        if not secrets.compare_digest(request.headers.get("Authorization", "").encode(), ("Bearer " + expected).encode()):
            return _error("Worker authentication required.", 401)
        if request.method != "POST":
            return _error("POST required.", 405)
        if len(request.body) > 256000:
            return _error("Request is too large.", 413)
        try:
            data = json.loads(request.body)
        except (ValueError, UnicodeDecodeError):
            return _error("Expected a JSON object.")
        if not isinstance(data, dict) or data.get("worker_id") != "inventory-codex":
            return _error("The inventory-codex worker identifier is required.")
        try:
            return view(request, data, *args, **kwargs)
        except OperationalError as exc:
            if "locked" not in str(exc).lower() and "deadlock" not in str(exc).lower():
                raise
            response = _error("Database is busy; retry this request.", 503)
            response["Retry-After"] = "1"
            return response
    return wrapped


def _eligible(now):
    return (Q(status__in=["queued", "retry"], available_at__lte=now)
            | Q(status="processing", lease_expires_at__lte=now))


def _job_data(job):
    return {"id": str(job.pk), "case_id": str(job.message.case_id), "message_id": job.message_id,
            "claim_token": str(job.claim_token), "lease_expires_at": _iso(job.lease_expires_at),
            "attempt": job.attempts, "status": "expired" if job.status == "processing" and not _live(job) else job.status,
            "purchase_lot_ids": job.purchase_lot_ids}


@_worker_endpoint
def claim(request, data):
    try:
        request_id = uuid.UUID(data["request_id"]) if "request_id" in data else uuid.uuid4()
    except (TypeError, ValueError, AttributeError):
        return _error("A claim request_id must be a UUID.")
    with transaction.atomic():
        receipt, _ = InventoryClaimRequest.objects.get_or_create(pk=request_id)
        receipt = InventoryClaimRequest.objects.select_for_update().get(pk=receipt.pk)
        if receipt.response is not None:
            response = receipt.response
            if response.get("job"):
                current = InventoryJob.objects.get(pk=response["job"]["id"])
                response["job"]["status"] = (_job_data(current)["status"] if str(current.claim_token) == response["job"]["claim_token"] else "superseded")
                response["job"]["purchase_lot_ids"] = current.purchase_lot_ids
            InventoryWorkerState.objects.update_or_create(pk=1, defaults={"last_successful_check": timezone.now()})
            return JsonResponse(response)
        response = _claim_one(data)
        receipt.response = response
        receipt.save(update_fields=["response"])
        return JsonResponse(response)


def _claim_one(data):
    now = timezone.now()
    earlier = InventoryJob.objects.filter(message__case_id=OuterRef("message__case_id"), message_id__lt=OuterRef("message_id")).exclude(status="completed")
    candidates = InventoryJob.objects.filter(_eligible(now)).annotate(earlier_pending=Exists(earlier)).filter(earlier_pending=False).select_related("message").order_by("message_id")
    for candidate in candidates[:50]:
        with transaction.atomic():
            case = InventoryCase.objects.select_for_update().get(pk=candidate.message.case_id)
            if InventoryJob.objects.filter(message__case=case, message_id__lt=candidate.message_id).exclude(status="completed").exists():
                continue
            changed = InventoryJob.objects.filter(pk=candidate.pk, attempts=candidate.attempts).filter(_eligible(now)).update(
                status="processing", attempts=F("attempts") + 1, claim_token=uuid.uuid4(),
                lease_expires_at=now + timedelta(seconds=LEASE_SECONDS), worker_id=data["worker_id"], last_error="")
            if changed:
                job = InventoryJob.objects.select_related("message").get(pk=candidate.pk)
                history = case.messages.filter(Q(role="staff", pk__lt=job.message_id) | Q(role="assistant", in_reply_to_id__lt=job.message_id)).select_related("author", "job").order_by("-id")[:49]
                current = _message(job.message)
                current.pop("result")
                context, characters = [current], len(job.message.body)
                for message in history:
                    if characters + len(message.body) > 96000:
                        break
                    item = _message(message)
                    item.pop("result")
                    context.append(item)
                    characters += len(message.body)
                prior_results = []
                for previous in InventoryJob.objects.filter(message__case=case, status="completed", message_id__lt=job.message_id).order_by("-message_id")[:5]:
                    value = previous.result
                    prior_results.append({"message_id": previous.message_id, "purchase_lot_ids": previous.purchase_lot_ids,
                                          "result": {"workbook": value.get("workbook", {}), "summary": value.get("summary", "")[:3000],
                                                     "sources": value.get("sources", [])[:10], "pending_fields": value.get("pending_fields", [])[:20]}})
                InventoryWorkerState.objects.update_or_create(pk=1, defaults={"last_successful_check": now})
                return {"job": _job_data(job), "case": {"id": str(case.pk), "title": case.title},
                        "messages": sorted(context, key=lambda message: message["id"]), "prior_results": list(reversed(prior_results))}
    InventoryWorkerState.objects.update_or_create(pk=1, defaults={"last_successful_check": now})
    return {"job": None}


def _matches(job, data):
    return (job.claim_token is not None and str(job.claim_token) == data.get("claim_token")
            and str(job.message.case_id) == data.get("case_id") and job.message_id == data.get("message_id")
            and job.worker_id == data.get("worker_id"))


def _live(job):
    return job.status == "processing" and job.lease_expires_at and job.lease_expires_at > timezone.now()


def _sale_date(lot):
    if not lot.event_at:
        return None
    value = lot.event_at if lot.is_all_day else timezone.localtime(lot.event_at, ZoneInfo(settings.CALENDAR_TIME_ZONE))
    return value.date().isoformat()


def _lot(lot):
    return {"id": lot.pk, "source": lot.source, "source_lot_id": lot.source_lot_id, "lot_number": lot.lot_number,
            "auction_house": lot.auction_house, "auction_title": lot.sale_title, "lot_url": lot.lot_url,
            "sale_url": lot.sale_url, "artist": lot.artist, "title": lot.title, "medium": lot.medium,
            "event_at": _iso(lot.event_at), "sale_date": _sale_date(lot), "won_by_us": lot.won_by_us}


@_worker_endpoint
def lot_search(request, data):
    query, house, sale_date = data.get("query", ""), data.get("auction_house", ""), data.get("sale_date", "")
    numbers = data.get("lot_numbers", [])
    if (not isinstance(query, str) or len(query) > 200 or not isinstance(house, str) or len(house) > 200
            or not isinstance(numbers, list) or len(numbers) > 50 or any(not isinstance(x, str) or len(x) > 80 for x in numbers)):
        return _error("Invalid lot search.")
    lots = AuctionWatchLot.objects.filter(superseded_by__isnull=True)
    if query:
        lots = lots.filter(Q(artist__icontains=query) | Q(title__icontains=query) | Q(auction_house__icontains=query) | Q(sale_title__icontains=query))
    if house:
        lots = lots.filter(auction_house__icontains=house)
    if numbers:
        lots = lots.filter(lot_number__in=numbers)
    if sale_date:
        try:
            day = date.fromisoformat(sale_date)
        except (ValueError, TypeError):
            return _error("Use a sale date formatted YYYY-MM-DD.")
        lots = lots.filter(event_at__date__gte=day - timedelta(days=1), event_at__date__lte=day + timedelta(days=1))
    matches = []
    for lot in lots.order_by("-event_at", "pk")[:1000]:
        if not sale_date or _sale_date(lot) == sale_date:
            matches.append(_lot(lot))
        if len(matches) == 101:
            break
    return JsonResponse({"lots": matches[:100], "truncated": len(matches) > 100})


@_worker_endpoint
def purchases(request, data, job_id):
    items = data.get("lots")
    identity_fields = ("source_lot_id", "lot_number", "auction_house", "sale_date", "lot_url")
    if (not isinstance(items, list) or not 1 <= len(items) <= 50
            or any(not isinstance(item, dict) or type(item.get("id")) is not int
                   or any(not isinstance(item.get(field), str) or not item[field] for field in identity_fields) for item in items)):
        return _error("Provide lot IDs and complete exact sale identities.")
    ids = [item["id"] for item in items]
    if len(ids) != len(set(ids)):
        return _error("Duplicate lot identifiers.")
    with transaction.atomic():
        job = get_object_or_404(InventoryJob.objects.select_for_update().select_related("message"), pk=job_id)
        if not _matches(job, data) or not _live(job):
            return _error("A matching active claim is required.", 409)
        lots = {lot.pk: lot for lot in AuctionWatchLot.objects.select_for_update().filter(pk__in=ids, superseded_by__isnull=True)}
        for item in items:
            lot = lots.get(item["id"])
            if lot is None or any(_lot(lot)[field] != item[field] for field in identity_fields):
                return _error("A lot identity changed or does not match; no purchases were changed.", 409)
        AuctionWatchLot.objects.filter(pk__in=ids).update(won_by_us=True)
        job.purchase_lot_ids = sorted(set(job.purchase_lot_ids + ids))
        job.save(update_fields=["purchase_lot_ids"])
    return JsonResponse({"purchase_lot_ids": job.purchase_lot_ids})


def _result(value):
    if not isinstance(value, dict) or set(value) - {"workbook", "sources", "pending_fields", "summary"}:
        raise ValueError("Invalid inventory result fields.")
    if len(json.dumps(value, ensure_ascii=False)) > 100000:
        raise ValueError("Inventory result is too large.")
    workbook = value.get("workbook", {})
    if not isinstance(workbook, dict) or set(workbook) - {"path", "sheet", "rows", "backup_path", "sha256"}:
        raise ValueError("Invalid workbook receipt.")
    for key in ("path", "sheet", "backup_path", "sha256"):
        if key in workbook and (not isinstance(workbook[key], str) or len(workbook[key]) > 2000):
            raise ValueError("Invalid workbook receipt.")
    rows = workbook.get("rows", [])
    if not isinstance(rows, list) or len(rows) > 500 or any(type(row) is not int or row < 1 or row > 1048576 for row in rows):
        raise ValueError("Invalid workbook row numbers.")
    sources = value.get("sources", [])
    if not isinstance(sources, list) or len(sources) > 100:
        raise ValueError("Too many research sources.")
    for source in sources:
        if not isinstance(source, dict) or set(source) - {"url", "title"}:
            raise ValueError("Invalid research source.")
        url, title = source.get("url"), source.get("title", "")
        if not isinstance(url, str) or len(url) > 2048 or not isinstance(title, str) or len(title) > 500:
            raise ValueError("Invalid research source.")
        try:
            parts = urlsplit(url)
            if parts.scheme not in ("https", "http") or not parts.hostname or parts.username or parts.password:
                raise ValueError("Use public HTTP(S) source links without credentials.")
        except ValueError:
            raise ValueError("Use public HTTP(S) source links without credentials.")
    pending = value.get("pending_fields", [])
    if not isinstance(pending, list) or len(pending) > 100 or any(not isinstance(item, str) or len(item) > 1000 for item in pending):
        raise ValueError("Invalid pending fields.")
    if "summary" in value and (not isinstance(value["summary"], str) or len(value["summary"]) > MAX_BODY):
        raise ValueError("Invalid result summary.")
    return value


@_worker_endpoint
def job_status(request, data, job_id):
    job = get_object_or_404(InventoryJob.objects.select_related("message"), pk=job_id)
    if not _matches(job, data):
        # A transport retry can outlive its lease. Recognize only a recorded old
        # claim, and never reveal the token that replaced it.
        if (str(job.message.case_id) == data.get("case_id") and job.message_id == data.get("message_id")
                and isinstance(data.get("claim_token"), str)
                and InventoryClaimRequest.objects.filter(response__job__id=str(job.pk), response__job__claim_token=data["claim_token"]).exists()):
            stale = {"id": str(job.pk), "case_id": str(job.message.case_id), "message_id": job.message_id,
                     "claim_token": data["claim_token"], "status": "superseded", "lease_expires_at": None,
                     "purchase_lot_ids": job.purchase_lot_ids}
            return JsonResponse({"job": stale, "result": {}, "body": None})
        return _error("Claim does not match this request.", 409)
    reply = InventoryMessage.objects.filter(in_reply_to=job.message).first()
    return JsonResponse({"job": _job_data(job), "result": job.result, "body": reply.body if reply else None})


@_worker_endpoint
def complete(request, data, job_id):
    body = data.get("body")
    if not isinstance(body, str) or not body.strip() or len(body) > MAX_BODY:
        return _error("A reply of 1–12,000 characters is required.")
    try:
        result = _result(data.get("result", {}))
    except ValueError as exc:
        return _error(str(exc))
    digest = hashlib.sha256(json.dumps({"body": body, "result": result}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    with transaction.atomic():
        job = get_object_or_404(InventoryJob.objects.select_for_update().select_related("message"), pk=job_id)
        if not _matches(job, data):
            return _error("Claim does not match this request.", 409)
        if job.status == "completed":
            if job.completion_digest != digest:
                return _error("This request already completed with a different result.", 409)
            return JsonResponse({"already_completed": True, "reply_id": job.message.worker_reply.pk})
        if not _live(job):
            return _error("This claim has expired or is no longer active.", 409)
        reply = InventoryMessage.objects.create(case_id=job.message.case_id, role="assistant", body=body, in_reply_to=job.message)
        job.status, job.result, job.completion_digest, job.completed_at = "completed", result, digest, timezone.now()
        job.last_error = ""
        job.save(update_fields=["status", "result", "completion_digest", "completed_at", "last_error"])
        InventoryCase.objects.filter(pk=job.message.case_id).update(updated_at=timezone.now())
    return JsonResponse({"already_completed": False, "reply_id": reply.pk})


@_worker_endpoint
def fail(request, data, job_id):
    error = data.get("error", "Inventory could not finish. Review the request and retry.")
    retry = data.get("retry", False)
    if not isinstance(error, str) or not error.strip() or len(error) > 500 or type(retry) is not bool:
        return _error("Provide a concise error and a boolean retry flag.")
    with transaction.atomic():
        job = get_object_or_404(InventoryJob.objects.select_for_update().select_related("message"), pk=job_id)
        if not _matches(job, data) or not _live(job):
            return _error("A matching active claim is required.", 409)
        job.status, job.last_error = ("retry" if retry else "failed"), error
        job.available_at, job.lease_expires_at = timezone.now() + timedelta(minutes=10), None
        job.save(update_fields=["status", "last_error", "available_at", "lease_expires_at"])
        InventoryCase.objects.filter(pk=job.message.case_id).update(updated_at=timezone.now())
    return JsonResponse({"status": job.status})
