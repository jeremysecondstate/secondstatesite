"""Staff conversations and an authenticated research/draft worker boundary."""

import json
import hashlib
import secrets
import uuid
from datetime import timedelta
from functools import wraps

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.db import IntegrityError, OperationalError, transaction
from django.db.models import Exists, F, OuterRef, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .models import CoordinateActivity, CoordinateCase, CoordinateJob, CoordinateMessage, CoordinateWorkerState
from .coordinate_shipping import coordination_state, enabled, enqueue_due_reviews, research_state, save_worker_artifacts, validate_worker_artifacts

MAX_MESSAGE_LENGTH = 12000
LEASE_SECONDS = 900
RETRY_SECONDS = 30


def _error(message, status=400):
    return JsonResponse({"error": message}, status=status)


def _iso(value):
    return value.isoformat() if value else None


def _job_status(job):
    if not job or job.status == "completed":
        return "replied"
    if job.status == "retry" or (job.status == "processing" and job.lease_expires_at and job.lease_expires_at <= timezone.now()):
        return "retrying"
    return "processing" if job.status == "processing" else "waiting"


def _message_json(message, case_deleted_at=None):
    deleted_at = message.deleted_at or case_deleted_at
    return {
        "id": message.pk,
        "role": message.role,
        "body": "" if deleted_at else message.body,
        "author": message.author.get_username() if message.author else ("Coordinate" if message.role == "system" else "Codex"),
        "created_at": _iso(message.created_at),
        "status": "deleted" if deleted_at else _job_status(getattr(message, "job", None)),
        "deleted": bool(deleted_at), "deleted_at": _iso(deleted_at),
        "individually_deleted": bool(message.deleted_at),
        "delete_url": reverse("coordinate_delete_message", args=[message.case_id, message.pk]),
        "restore_url": reverse("coordinate_restore_message", args=[message.case_id, message.pk]),
    }


def _state(selected=None):
    cases = []
    trash_cases = []
    # Fetch pending jobs together, rather than querying separately for every case.
    pending = CoordinateJob.objects.filter(message__deleted_at__isnull=True, message__case__deleted_at__isnull=True).exclude(status__in=["completed", "cancelled"]).select_related("message").order_by("message_id")
    statuses = {}
    for job in pending:
        statuses.setdefault(job.message.case_id, _job_status(job))
    for case in CoordinateCase.objects.all():
        item = {
            "id": str(case.pk), "title": case.title,
            "url": reverse("coordinate_case", args=[case.pk]),
            "status": "deleted" if case.deleted_at else statuses.get(case.pk, "replied"),
            "updated_at": _iso(case.updated_at), "coordinator": case.coordinator,
            "deleted": bool(case.deleted_at), "deleted_at": _iso(case.deleted_at),
            "delete_url": reverse("coordinate_delete_case", args=[case.pk]),
            "restore_url": reverse("coordinate_restore_case", args=[case.pk]),
        }
        (trash_cases if case.deleted_at else cases).append(item)
    worker = CoordinateWorkerState.objects.filter(pk=1).first()
    return {
        "cases": cases,
        "trash_cases": trash_cases,
        "selected_case": next((case for case in cases + trash_cases if selected and case["id"] == str(selected.pk)), None),
        "messages": [_message_json(message, selected.deleted_at) for message in selected.messages.select_related("author", "job").all()] if selected else [],
        "worker": {"last_successful_check": _iso(worker.last_successful_check) if worker else None, "test_mode": not enabled(), "draft_only": enabled()},
        "coordination": coordination_state(selected),
        "new_case_token": str(uuid.uuid4()), "message_token": str(uuid.uuid4()),
    }


@never_cache
@staff_member_required
@require_GET
def coordinate(request, case_id=None):
    case = get_object_or_404(CoordinateCase, pk=case_id) if case_id else None
    if case is None and request.GET.get("new") != "1":
        case = CoordinateCase.objects.filter(deleted_at__isnull=True).first()
    return render(request, "coordinate/index.html", _state(case))


@never_cache
@staff_member_required
@require_GET
def state(request):
    case_id = request.GET.get("case")
    try:
        case = get_object_or_404(CoordinateCase, pk=uuid.UUID(case_id)) if case_id else None
    except (ValueError, TypeError):
        return _error("Invalid case identifier.")
    return JsonResponse(_state(case))


def _submission(request):
    body = request.POST.get("body", "").strip()
    if not body or len(body) > MAX_MESSAGE_LENGTH:
        raise ValueError("Write a message between 1 and 12,000 characters.")
    try:
        token = uuid.UUID(request.POST.get("client_message_id", ""))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("A valid message identifier is required. Reload and try again.")
    return body, token


def _saved_response(request, message):
    if request.headers.get("Accept") == "application/json":
        return JsonResponse(_state(message.case))
    return redirect("coordinate_case", case_id=message.case_id)


def _form_error(request, message, case=None, status=400):
    if request.headers.get("Accept") == "application/json":
        return _error(message, status)
    context = _state(case)
    context.update(error=message, form_body=request.POST.get("body", ""), form_title=request.POST.get("title", ""))
    # Preserve a valid submission identifier, including when a client retries a POST.
    try:
        token = str(uuid.UUID(request.POST.get("client_message_id", "")))
        context["message_token" if case else "new_case_token"] = token
    except (ValueError, TypeError, AttributeError):
        pass
    return render(request, "coordinate/index.html", context, status=status)


def _duplicate(request, token, body, case_id=None):
    message = CoordinateMessage.objects.select_related("case").filter(client_message_id=token).first()
    if not message:
        return None
    if message.author_id != request.user.pk or message.body != body or (case_id and message.case_id != case_id):
        return _error("This message identifier was already used for a different submission.", 409)
    if message.deleted_at or message.case.deleted_at:
        return _error("This submission was deleted. Restore it before continuing.", 409)
    return _saved_response(request, message)


def _locked_case(case_id):
    """Call inside atomic(): serialize case/history/job writes on PostgreSQL and SQLite."""
    if not CoordinateCase.objects.filter(pk=case_id).update(updated_at=F("updated_at")):
        raise Http404("Case not found.")
    return CoordinateCase.objects.get(pk=case_id)


def _database_retry(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        try:
            return view(*args, **kwargs)
        except OperationalError as exc:
            if "locked" not in str(exc).lower() and "deadlock" not in str(exc).lower():
                raise
            response = _error("Database is busy; retry this request.", 503)
            response["Retry-After"] = "1"
            return response
    return wrapped


def _invalidate_processing(case, now):
    # A removed/restored historical message changes the context of later work too.
    return CoordinateJob.objects.filter(message__case=case, status="processing").update(
        status="retry", claim_token=None, lease_expires_at=None, available_at=now,
        last_error="Conversation changed; waiting for a fresh worker check.",
    )


def _case_response(request, case):
    if request.headers.get("Accept") == "application/json":
        return JsonResponse(_state(case))
    return redirect("coordinate_case", case_id=case.pk)


def _save_message(case, body, token, author):
    message = CoordinateMessage.objects.create(case=case, role="staff", body=body, client_message_id=token, author=author)
    job = CoordinateJob.objects.create(message=message)
    CoordinateCase.objects.filter(pk=case.pk).update(updated_at=timezone.now())
    CoordinateActivity.objects.create(case=case, job=job, event="message_saved", details={"message_id": message.pk, "author_id": author.pk})
    return message


@never_cache
@staff_member_required
@require_POST
def create_case(request):
    try:
        body, token = _submission(request)
    except ValueError as exc:
        return _form_error(request, str(exc))
    title = request.POST.get("title", "").strip() or body.splitlines()[0][:160]
    if len(title) > 160:
        return _form_error(request, "Case titles can contain at most 160 characters.")
    duplicate = _duplicate(request, token, body)
    if duplicate is not None:
        return duplicate
    try:
        with transaction.atomic():
            case = CoordinateCase.objects.create(title=title, created_by=request.user)
            message = _save_message(case, body, token, request.user)
    except IntegrityError:
        duplicate = _duplicate(request, token, body)
        if duplicate is not None:
            return duplicate
        raise
    return _saved_response(request, message)


@never_cache
@staff_member_required
@require_POST
@_database_retry
def add_message(request, case_id):
    case = get_object_or_404(CoordinateCase, pk=case_id)
    try:
        body, token = _submission(request)
    except ValueError as exc:
        return _form_error(request, str(exc), case)
    duplicate = _duplicate(request, token, body, case_id)
    if duplicate is not None:
        return duplicate
    try:
        with transaction.atomic():
            case = _locked_case(case_id)
            if case.deleted_at:
                return _error("Restore this case before adding messages.", 409)
            message = _save_message(case, body, token, request.user)
    except IntegrityError:
        duplicate = _duplicate(request, token, body, case_id)
        if duplicate is not None:
            return duplicate
        raise
    return _saved_response(request, message)


@never_cache
@staff_member_required
@require_POST
@_database_retry
def delete_message(request, case_id, message_id):
    with transaction.atomic():
        case = _locked_case(case_id)
        if case.deleted_at:
            return _error("Restore this case before changing messages.", 409)
        message = get_object_or_404(CoordinateMessage, case=case, pk=message_id)
        if message.deleted_at is None:
            now = timezone.now()
            CoordinateMessage.objects.filter(pk=message.pk).update(deleted_at=now, deleted_by=request.user)
            invalidated = _invalidate_processing(case, now)
            jobs = CoordinateJob.objects.filter(message=message)
            jobs.exclude(status="completed").update(status="cancelled")
            jobs.update(claim_token=None, lease_expires_at=None)
            if message.in_reply_to_id:
                CoordinateJob.objects.filter(message_id=message.in_reply_to_id).update(claim_token=None)
            details = {"message_id": message.pk, "actor_id": request.user.pk, "invalidated_jobs": invalidated}
            if message.role == "staff" and case.title == message.body.splitlines()[0][:160]:
                details["previous_title"] = case.title
                case.title = "Untitled case"
            case.updated_at = now
            case.save(update_fields=["title", "updated_at"])
            CoordinateActivity.objects.create(case=case, event="message_deleted", details=details)
    return _case_response(request, case)


@never_cache
@staff_member_required
@require_POST
@_database_retry
def restore_message(request, case_id, message_id):
    with transaction.atomic():
        case = _locked_case(case_id)
        if case.deleted_at:
            return _error("Restore this case before changing messages.", 409)
        message = get_object_or_404(CoordinateMessage, case=case, pk=message_id)
        if message.deleted_at is not None:
            now = timezone.now()
            CoordinateMessage.objects.filter(pk=message.pk).update(deleted_at=None, deleted_by=None)
            invalidated = _invalidate_processing(case, now)
            CoordinateJob.objects.filter(message=message).exclude(status="completed").update(
                status="queued", claim_token=None, lease_expires_at=None, available_at=now, last_error="",
            )
            deletion = case.activity.filter(event="message_deleted", details__message_id=message.pk).order_by("-id").first()
            if deletion and case.title == "Untitled case" and deletion.details.get("previous_title"):
                case.title = deletion.details["previous_title"]
            case.updated_at = now
            case.save(update_fields=["title", "updated_at"])
            CoordinateActivity.objects.create(case=case, event="message_restored", details={
                "message_id": message.pk, "actor_id": request.user.pk, "invalidated_jobs": invalidated,
            })
    return _case_response(request, case)


@never_cache
@staff_member_required
@require_POST
@_database_retry
def delete_case(request, case_id):
    with transaction.atomic():
        case = _locked_case(case_id)
        if case.deleted_at is None:
            now = timezone.now()
            case.deleted_at, case.deleted_by, case.updated_at = now, request.user, now
            case.save(update_fields=["deleted_at", "deleted_by", "updated_at"])
            jobs = CoordinateJob.objects.filter(message__case=case)
            cancelled = jobs.exclude(status="completed").update(status="cancelled")
            jobs.update(claim_token=None, lease_expires_at=None)
            CoordinateActivity.objects.create(case=case, event="case_deleted", details={
                "actor_id": request.user.pk, "cancelled_jobs": cancelled,
            })
    return _case_response(request, case)


@never_cache
@staff_member_required
@require_POST
@_database_retry
def restore_case(request, case_id):
    with transaction.atomic():
        case = _locked_case(case_id)
        if case.deleted_at is not None:
            now = timezone.now()
            case.deleted_at, case.deleted_by, case.updated_at = None, None, now
            case.save(update_fields=["deleted_at", "deleted_by", "updated_at"])
            requeued = CoordinateJob.objects.filter(message__case=case, message__deleted_at__isnull=True).exclude(status="completed").update(
                status="queued", claim_token=None, lease_expires_at=None, available_at=now, last_error="",
            )
            CoordinateActivity.objects.create(case=case, event="case_restored", details={
                "actor_id": request.user.pk, "requeued_jobs": requeued,
            })
    return _case_response(request, case)


def _worker_endpoint(view):
    @csrf_exempt
    @never_cache
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        expected = settings.COORDINATE_WORKER_TOKEN
        if not expected:
            return _error("Coordinate worker authentication is not configured.", 503)
        supplied = request.headers.get("Authorization", "")
        if not secrets.compare_digest(supplied.encode(), ("Bearer " + expected).encode()):
            return _error("Worker authentication required.", 401)
        if request.method != "POST":
            return _error("POST required.", 405)
        if len(request.body) > 128000:
            return _error("Request is too large.", 413)
        try:
            data = json.loads(request.body)
        except (ValueError, UnicodeDecodeError):
            return _error("Expected a JSON object.")
        if not isinstance(data, dict):
            return _error("Expected a JSON object.")
        worker_id = data.get("worker_id")
        if worker_id != "manual-codex":
            return _error("This milestone uses the designated manual-codex coordinator.")
        try:
            return view(request, data, *args, **kwargs)
        except OperationalError as exc:
            if "locked" not in str(exc).lower() and "deadlock" not in str(exc).lower():
                raise
            response = _error("Database is busy; retry this request.", 503)
            response["Retry-After"] = "1"
            return response
    return wrapped


def _playbook():
    return {
        "shipping": settings.COORDINATE_SHIPPING_PLAYBOOK or (settings.BASE_DIR / "docs" / "coordinate-playbook.md").read_text(encoding="utf-8"),
        "packing": settings.COORDINATE_PACKING_PLAYBOOK or (settings.BASE_DIR / "docs" / "cardboardsandwich.md").read_text(encoding="utf-8"),
    }


def _eligible(now):
    return Q(status__in=["queued", "retry"], available_at__lte=now) | Q(status="processing", lease_expires_at__lte=now)


@_worker_endpoint
def claim(request, data):
    try:
        playbook = _playbook()
    except (OSError, UnicodeError):
        return _error("The shipping playbook or original packing source is unavailable.", 503)
    enqueue_due_reviews()
    now = timezone.now()
    # Only the first unfinished message in each case can be claimed. The conditional
    # UPDATE below is the arbiter, on both PostgreSQL and SQLite (no lock assumptions).
    earlier = CoordinateJob.objects.filter(
        message__case_id=OuterRef("message__case_id"), message_id__lt=OuterRef("message_id"),
        message__deleted_at__isnull=True,
    ).exclude(status__in=["completed", "cancelled"])
    candidates = CoordinateJob.objects.filter(
        _eligible(now), message__case__coordinator=data["worker_id"],
        message__deleted_at__isnull=True, message__case__deleted_at__isnull=True,
    ).annotate(earlier_pending=Exists(earlier)).filter(earlier_pending=False).select_related("message").order_by("message_id")
    for candidate in candidates[:50]:
        token = uuid.uuid4()
        with transaction.atomic():
            case = _locked_case(candidate.message.case_id)
            if case.deleted_at or case.coordinator != data["worker_id"]:
                continue
            # A restored older message may have become pending since candidate selection.
            if CoordinateJob.objects.filter(message__case=case, message__deleted_at__isnull=True,
                                            message_id__lt=candidate.message_id).exclude(status__in=["completed", "cancelled"]).exists():
                continue
            updated = CoordinateJob.objects.filter(pk=candidate.pk, attempts=candidate.attempts).filter(_eligible(now)).update(
                status="processing", attempts=F("attempts") + 1, claim_token=token,
                lease_expires_at=now + timedelta(seconds=LEASE_SECONDS), worker_id=data["worker_id"], last_error="",
            )
            if updated:
                claimed = CoordinateJob.objects.select_related("message__case").get(pk=candidate.pk)
                CoordinateActivity.objects.create(case=claimed.message.case, job=claimed, event="job_claimed", details={"attempt": claimed.attempts})
                CoordinateWorkerState.objects.update_or_create(pk=1, defaults={"last_successful_check": now})
                # Materialize the context while holding the same case lock as deletions.
                history = case.messages.filter(
                    Q(role__in=["staff", "system"], pk__lte=claimed.message_id)
                    | Q(role="assistant", in_reply_to_id__lt=claimed.message_id, in_reply_to__deleted_at__isnull=True),
                    deleted_at__isnull=True,
                ).select_related("author", "job")
                return JsonResponse({
                    "job": {"id": str(claimed.pk), "case_id": str(case.pk), "message_id": claimed.message_id,
                            "claim_token": str(claimed.claim_token), "lease_expires_at": _iso(claimed.lease_expires_at), "attempt": claimed.attempts},
                    "case": {"id": str(case.pk), "title": case.title, "coordinator": case.coordinator},
                    "messages": [_message_json(message) for message in history],
                    "playbook": playbook, "test_mode": not enabled(), "draft_only": enabled(), "research_enabled": enabled(),
                    "coordination": coordination_state(case), "research": research_state(case) if enabled() else [],
                })
    CoordinateWorkerState.objects.update_or_create(pk=1, defaults={"last_successful_check": now})
    return JsonResponse({"job": None, "test_mode": not enabled(), "draft_only": enabled()})


def _claim_matches(job, data):
    return (
        str(job.claim_token) == data.get("claim_token")
        and str(job.message.case_id) == data.get("case_id")
        and job.message_id == data.get("message_id")
        and job.worker_id == data.get("worker_id")
    )


def _live_claim(job, now):
    return job.status == "processing" and job.lease_expires_at and job.lease_expires_at > now


@_worker_endpoint
def complete(request, data, job_id):
    body = data.get("body")
    if not isinstance(body, str) or not body.strip() or len(body) > MAX_MESSAGE_LENGTH:
        return _error("Reply must contain between 1 and 12,000 characters.")
    body = body.strip()
    try:
        artifacts = validate_worker_artifacts(data)
    except ValueError as exc:
        return _error(str(exc))
    digest = hashlib.sha256(json.dumps({"body": body, "artifacts": artifacts}, sort_keys=True, default=str).encode()).hexdigest()
    identity = get_object_or_404(CoordinateJob.objects.select_related("message"), pk=job_id)
    with transaction.atomic():
        case = _locked_case(identity.message.case_id)
        job = get_object_or_404(CoordinateJob.objects.select_related("message__case"), pk=job_id)
        if case.deleted_at or job.message.deleted_at:
            return _error("This case or message was deleted.", 409)
        if not _claim_matches(job, data):
            return _error("Claim does not match this case, message, or worker.", 409)
        if job.status == "completed":
            reply = CoordinateMessage.objects.get(in_reply_to=job.message)
            if reply.deleted_at:
                return _error("This reply was deleted; restore it through the case.", 409)
            digest_matches = not job.completion_digest or job.completion_digest == digest
            if (not digest_matches and artifacts[0]
                    and all("source_kind" not in item and "public_error" not in item for item in data.get("research", []))):
                # A pre-provenance completion may be replayed after deployment if
                # its response was lost. Only the original public payload shape
                # may use that older digest; explicit provenance remains binding.
                legacy_research = [
                    {key: value for key, value in item.items() if key not in ("source_kind", "public_error")}
                    for item in artifacts[0]
                ]
                legacy_digest = hashlib.sha256(json.dumps(
                    {"body": body, "artifacts": (legacy_research, artifacts[1])}, sort_keys=True, default=str,
                ).encode()).hexdigest()
                digest_matches = job.completion_digest == legacy_digest
            if reply.body != body or not digest_matches:
                return _error("This claim already completed with a different reply.", 409)
            return JsonResponse({"reply_id": reply.pk, "already_completed": True})
        now = timezone.now()
        if not _live_claim(job, now):
            return _error("Claim expired or is no longer active; retrieve pending work again.", 409)
        updated = CoordinateJob.objects.filter(pk=job.pk, status="processing", claim_token=job.claim_token, lease_expires_at__gt=now).update(
            status="completed", completed_at=now, last_error="", completion_digest=digest,
        )
        if not updated:
            return _error("Claim changed; retry this completion to check its result.", 409)
        try:
            save_worker_artifacts(job, artifacts)
        except ValueError as exc:
            transaction.set_rollback(True)
            return _error(str(exc))
        reply = CoordinateMessage.objects.create(case=job.message.case, role="assistant", body=body, in_reply_to=job.message)
        CoordinateCase.objects.filter(pk=job.message.case_id).update(updated_at=now)
        CoordinateActivity.objects.create(case=job.message.case, job=job, event="reply_saved", details={"reply_id": reply.pk, "message_id": job.message_id, "test_mode": not enabled(), "draft_only": enabled()})
    return JsonResponse({"reply_id": reply.pk, "already_completed": False})


@_worker_endpoint
def fail(request, data, job_id):
    identity = get_object_or_404(CoordinateJob.objects.select_related("message"), pk=job_id)
    with transaction.atomic():
        case = _locked_case(identity.message.case_id)
        job = get_object_or_404(CoordinateJob.objects.select_related("message__case"), pk=job_id)
        if case.deleted_at or job.message.deleted_at:
            return _error("This case or message was deleted.", 409)
        if not _claim_matches(job, data):
            return _error("Claim does not match this case, message, or worker.", 409)
        if job.status == "retry":
            return JsonResponse({"status": "retrying"})
        now = timezone.now()
        if not _live_claim(job, now):
            return _error("Claim expired or is no longer active.", 409)
        # Do not persist raw exception/CLI output, which can contain credentials or context.
        updated = CoordinateJob.objects.filter(pk=job.pk, status="processing", claim_token=job.claim_token, lease_expires_at__gt=now).update(
            status="retry", available_at=now + timedelta(seconds=RETRY_SECONDS),
            lease_expires_at=None, last_error="Worker could not complete; pending a manual retry.",
        )
        if not updated:
            return _error("Claim changed; retry to check its result.", 409)
        CoordinateActivity.objects.create(case=job.message.case, job=job, event="job_retry", details={"attempt": job.attempts})
    return JsonResponse({"status": "retrying"})
