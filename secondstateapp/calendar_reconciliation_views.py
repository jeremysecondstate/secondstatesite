"""Authenticated public lot readback and explicitly reviewed duplicate plans.

Candidate generation never authorizes a suppression. POST requires reviewed
identities and the same optimistic fingerprints as the management command.
"""

from datetime import datetime, time, timedelta
from hashlib import sha256
import json
import re

from django.conf import settings
from django.core.exceptions import RequestDataTooBig
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .calendar_duplicates import PUBLIC_FIELDS, apply_pairs, audit_lots, fingerprint, snapshot
from .calendar_views import _calendar_zone, _sync_authorized
from .models import AuctionLotReconciliation, AuctionLotSupersessionReceipt, AuctionWatchLot


MAX_BYTES = 1_000_000
MAX_PAIRS = 200
MAX_PAGE = 500
EXTRA_FIELDS = ("current_bid", "bid_count", "sold_price", "sold_currency", "location",
                "source_first_seen_at", "source_last_seen_at", "source_status")


def _projection(lot):
    row = snapshot(lot)
    row.update({name: getattr(lot, name) for name in EXTRA_FIELDS})
    row["fingerprint"] = fingerprint(lot)
    return row


def _query(request):
    rows = AuctionWatchLot.objects.filter(Q(source__iexact="Invaluable") | Q(source__iexact="Drouot"))
    bounds = {}
    for name in ("start", "end"):
        raw = request.GET.get(name)
        if raw is not None:
            try:
                value = parse_date(raw)
            except ValueError:
                value = None
            if value is None or value.isoformat() != raw:
                raise ValueError("start and end must be ISO calendar dates.")
            bounds[name] = value
    if "start" in bounds and "end" in bounds and bounds["end"] < bounds["start"]:
        raise ValueError("end must not precede start.")
    zone = _calendar_zone()
    if "start" in bounds:
        rows = rows.filter(event_at__gte=datetime.combine(bounds["start"], time.min, tzinfo=zone))
    if "end" in bounds:
        rows = rows.filter(event_at__lt=datetime.combine(bounds["end"] + timedelta(days=1), time.min, tzinfo=zone))
    ids = request.GET.get("ids")
    if ids is not None:
        values = ids.split(",")
        if not 1 <= len(values) <= MAX_PAGE or any(not re.fullmatch(r"[1-9][0-9]{0,18}", value) for value in values):
            raise ValueError("ids must contain at most 500 positive Calendar IDs.")
        numbers = [int(value) for value in values]
        if any(value > 2**63 - 1 for value in numbers):
            raise ValueError("Calendar ID is out of range.")
        rows = rows.filter(pk__in=numbers)
    return rows, bounds, ids


def _read(request):
    operation = request.GET.get("operation")
    if operation is not None:
        record = AuctionLotReconciliation.objects.filter(operation=operation).first()
        if record is None:
            return JsonResponse({"ok": False, "error": "Operation not found."}, status=404)
        return JsonResponse({"ok": True, "version": 1, "operation": record.operation,
                             "request_hash": record.request_hash, "receipt": record.receipt,
                             "created_at": record.created_at})
    rows, bounds, ids = _query(request)
    mode = request.GET.get("mode", "lots")
    if mode == "audit":
        if ids is None and (len(bounds) != 2 or (bounds["end"] - bounds["start"]).days >= 90):
            raise ValueError("An audit needs ids or an inclusive date window of at most 90 days.")
        lots = list(rows.only(*PUBLIC_FIELDS).order_by("pk")[:10001])
        if len(lots) > 10000:
            raise ValueError("Audit window exceeds 10000 records; use smaller date windows.")
        return JsonResponse({"ok": True, "version": 1, "observed_at": timezone.now(),
                             "audit": audit_lots(lots, timezone_name=settings.CALENDAR_TIME_ZONE)})
    if mode != "lots":
        raise ValueError("mode must be lots or audit.")
    try:
        cursor = int(request.GET.get("cursor", "0"))
        page_size = int(request.GET.get("page_size", str(MAX_PAGE)))
    except ValueError:
        raise ValueError("Invalid cursor or page_size.") from None
    if not 0 <= cursor <= 2**63 - 1 or not 1 <= page_size <= MAX_PAGE:
        raise ValueError("Invalid cursor or page_size.")
    lots = list(rows.filter(pk__gt=cursor).only(*PUBLIC_FIELDS, *EXTRA_FIELDS).order_by("pk")[:page_size + 1])
    return JsonResponse({"ok": True, "version": 1, "observed_at": timezone.now(),
                         "lots": [_projection(lot) for lot in lots[:page_size]],
                         "next_cursor": str(lots[page_size - 1].pk) if len(lots) > page_size else None})


def _plan(payload):
    if not isinstance(payload, dict) or set(payload) - {"version", "operation", "reviewed", "pairs"}:
        raise ValueError("Request must contain only version, operation, reviewed and pairs.")
    if type(payload.get("version")) is not int or payload.get("version") != 1 or payload.get("reviewed") is not True:
        raise ValueError("A version 1 explicitly reviewed plan is required.")
    operation = payload.get("operation")
    if not isinstance(operation, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,75}", operation):
        raise ValueError("operation must be a unique run identifier of at most 76 characters.")
    pairs = payload.get("pairs")
    if not isinstance(pairs, list) or not 1 <= len(pairs) <= MAX_PAIRS:
        raise ValueError(f"pairs must contain 1 to {MAX_PAIRS} reviewed pairs.")
    keys = {"keep_id", "remove_id", "keep_fingerprint", "remove_fingerprint", "reason"}
    normalized = []
    for pair in pairs:
        if not isinstance(pair, dict) or set(pair) != keys:
            raise ValueError("Each pair needs keep/remove IDs, fingerprints and a supporting reason.")
        for field in ("keep_id", "remove_id"):
            if type(pair[field]) is not int or not 0 < pair[field] <= 2**63 - 1:
                raise ValueError("Pair IDs must be positive Calendar IDs.")
        for field in ("keep_fingerprint", "remove_fingerprint"):
            if not isinstance(pair[field], str) or not re.fullmatch(r"[0-9a-f]{64}", pair[field]):
                raise ValueError("A current fingerprint is required for each lot.")
        if not isinstance(pair["reason"], str) or not pair["reason"].strip() or len(pair["reason"]) > 4000:
            raise ValueError("Each pair requires a supporting reason of at most 4000 characters.")
        normalized.append({**pair, "reason": pair["reason"].strip()})
    normalized.sort(key=lambda pair: (pair["remove_id"], pair["keep_id"]))
    digest = sha256(json.dumps(normalized, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return operation, normalized, digest


def _apply(operation, pairs, digest):
    with transaction.atomic():
        record, created = AuctionLotReconciliation.objects.get_or_create(
            operation=operation, defaults={"request_hash": digest, "receipt": {}},
        )
        record = AuctionLotReconciliation.objects.select_for_update().get(pk=record.pk)
        if not created:
            if record.request_hash != digest:
                raise ValueError("This operation identifier already belongs to a different plan.")
            return record.receipt, True
        ids = {pair[key] for pair in pairs for key in ("keep_id", "remove_id")}
        rows = {lot.pk: lot for lot in AuctionWatchLot.objects.select_for_update().filter(pk__in=ids).order_by("pk")}
        for pair in pairs:
            keep, old = rows.get(pair["keep_id"]), rows.get(pair["remove_id"])
            if keep is None or old is None or keep.source.casefold() != "invaluable" or old.source.casefold() != "drouot":
                raise ValueError("This endpoint only supersedes a reviewed Drouot lot with Invaluable.")
        receipt = apply_pairs(pairs)
        receipt["operation"] = operation
        receipt["request_hash"] = digest
        for change in receipt["changes"]:
            AuctionLotSupersessionReceipt.objects.create(
                operation=f"api:{operation}", lot_id=change["remove_id"],
                replacement_id=change["keep_id"], active_before=change["active_before"],
            )
        record.receipt = receipt
        record.save(update_fields=["receipt"])
        return receipt, False


@csrf_exempt
@never_cache
@require_http_methods(["GET", "POST"])
def calendar_reconciliation(request):
    if not _sync_authorized(request):
        return JsonResponse({"ok": False, "error": "Unauthorized."}, status=401)
    if request.method == "GET":
        try:
            return _read(request)
        except (ValueError, OverflowError) as exc:
            return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    try:
        body = request.body
    except RequestDataTooBig:
        return JsonResponse({"ok": False, "error": "Plan is too large."}, status=413)
    if len(body) > MAX_BYTES:
        return JsonResponse({"ok": False, "error": "Plan is too large."}, status=413)
    try:
        operation, pairs, digest = _plan(json.loads(body))
    except (ValueError, UnicodeDecodeError) as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    try:
        receipt, replayed = _apply(operation, pairs, digest)
    except ValueError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=409)
    return JsonResponse({"ok": True, "version": 1, "replayed": replayed, "receipt": receipt})
