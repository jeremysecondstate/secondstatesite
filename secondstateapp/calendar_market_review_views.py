"""Review current and future Calendar lots in auction order."""

from collections import Counter
from datetime import datetime, time, timedelta
from itertools import islice
import json
import re
from urllib.parse import urlsplit

from django.core.exceptions import RequestDataTooBig, ValidationError
from django.core.validators import URLValidator
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .calendar_market_review import (
    CATALOG_FIELDS, FIRST_REVIEW_DAY, RECHECK_START_DAY, has_artist_signature,
    review_fingerprint, review_is_current, signature_required,
)
from .calendar_views import _artist_label, _attach_superseded_attribution, _calendar_zone, _sync_authorized
from .lot_presentation import artist_attribution_label
from .models import AuctionLotMarketReview, AuctionWatchLot
from .sale_geography import sale_geography


MAX_BATCH = 200
MAX_BYTES = 1_000_000
RETRY_UNCERTAIN = timedelta(days=7)
validate_web_url = URLValidator(schemes=["http", "https"])


def _review_start(recheck_from=None):
    zone = _calendar_zone()
    if recheck_from is not None:
        if recheck_from != RECHECK_START_DAY.isoformat():
            raise ValueError(f"The full Calendar recheck starts on {RECHECK_START_DAY}.")
        return datetime.combine(RECHECK_START_DAY, time.min, tzinfo=zone)
    first_day = max(FIRST_REVIEW_DAY, timezone.localdate(timezone=zone))
    return datetime.combine(first_day, time.min, tzinfo=zone)


def _eligible_lots(recheck_from=None):
    return AuctionWatchLot.objects.filter(superseded_by__isnull=True, event_at__gte=_review_start(recheck_from))


def _census(params):
    start = params.get("start", RECHECK_START_DAY.isoformat())
    cursor = int(params.get("cursor", "0"))
    size = int(params.get("page_size", "500"))
    if not 0 <= cursor <= 2**63 - 1 or not 1 <= size <= 500:
        raise ValueError("Invalid census cursor or page size.")
    lots = list(_eligible_lots(start).filter(pk__gt=cursor).order_by("pk").values("id", "event_at")[:size + 1])
    return {"lots": lots[:size], "next_cursor": str(lots[size - 1]["id"]) if len(lots) > size else None}


def _projections(lots):
    rows = []
    for lot in lots:
        row = {name: getattr(lot, name) for name in CATALOG_FIELDS}
        artist = _artist_label(lot)
        geography = sale_geography(lot)
        row.update(
            artist_source=artist, attribution_label=artist_attribution_label(lot.artist, artist, title=lot.title),
            sale_country=geography["country_code"], sale_region=geography["region"],
            active=lot.active, sold_price=lot.sold_price, sold_currency=lot.sold_currency,
        )
        rows.append(row)
    _attach_superseded_attribution({"lots": rows})
    for lot, row in zip(lots, rows):
        row["fingerprint"] = review_fingerprint(lot, row["attribution_label"], row["sale_country"], row["sale_region"])
    return rows


def _ids(raw):
    values = raw.split(",")
    if (not 1 <= len(values) <= MAX_BATCH
            or any(not re.fullmatch(r"[1-9][0-9]{0,18}", item) for item in values)):
        raise ValueError(f"ids must contain 1 to {MAX_BATCH} positive Calendar IDs.")
    result = [int(item) for item in values]
    if max(result) > 2**63 - 1 or len(set(result)) != len(result):
        raise ValueError("Invalid or repeated Calendar ID.")
    return result


def _inspect(raw_ids, recheck_from=None):
    lots = list(AuctionWatchLot.objects.select_related("market_review").filter(pk__in=_ids(raw_ids)).order_by("pk"))
    rows = _projections(lots)
    start = _review_start(recheck_from)
    for lot, row in zip(lots, rows):
        review = getattr(lot, "market_review", None)
        row.update(
            eligible=bool(lot.superseded_by_id is None and lot.event_at and lot.event_at >= start),
            revision=review.revision if review else 0, review=None,
        )
        if review:
            row["review"] = {
                "current": review_is_current(lot, review, row["fingerprint"]), "status": review.status,
                "reason": review.reason, "sale_market": review.sale_market, "stronger_market": review.stronger_market,
                "sources": review.sources, "reviewed_at": review.reviewed_at,
            }
    return {"lots": rows}


def _pending(raw_limit):
    limit = int(raw_limit)
    if not 1 <= limit <= MAX_BATCH:
        raise ValueError(f"limit must be between 1 and {MAX_BATCH}.")
    zone = _calendar_zone()
    retry_before = timezone.now() - RETRY_UNCERTAIN
    ordered = _eligible_lots().order_by("event_at", "pk")
    unreviewed = ordered.filter(market_review__isnull=True)
    pending_count = eligible_count = unreviewed.count()
    pending = _projections(list(unreviewed[:limit]))
    for row in pending:
        row["revision"] = 0
    # Re-evaluate fingerprints on reviewed rows, even if other, unrelated source
    # observations have changed. Legacy flags also need signature evidence.
    reviewed = ordered.filter(market_review__isnull=False).select_related("market_review").only(
        *CATALOG_FIELDS, "active", "sold_price", "sold_currency",
        "market_review__fingerprint", "market_review__status", "market_review__reviewed_at", "market_review__revision",
        "market_review__sources",
    ).iterator(chunk_size=500)
    due = []
    due_by_day = Counter()
    while batch := list(islice(reviewed, 500)):
        eligible_count += len(batch)
        for lot, row in zip(batch, _projections(batch)):
            review = lot.market_review
            if (review_is_current(lot, review, row["fingerprint"])
                    and (review.status != AuctionLotMarketReview.Status.UNCERTAIN or review.reviewed_at > retry_before)):
                continue
            pending_count += 1
            due_by_day[row["event_at"].astimezone(zone).date()] += 1
            if len(due) < limit:
                row["revision"] = review.revision
                due.append(row)
    pending.extend(due)
    pending.sort(key=lambda row: (row["event_at"], row["id"]))
    first_day = None
    first_day_count = 0
    if pending:
        first_day = pending[0]["event_at"].astimezone(zone).date()
        start = datetime.combine(first_day, time.min, tzinfo=zone)
        first_day_count = due_by_day[first_day] + unreviewed.filter(
            event_at__gte=start, event_at__lt=start + timedelta(days=1),
        ).count()
    return {
        "lots": pending[:limit], "pending_count": pending_count, "eligible_count": eligible_count,
        "oldest_pending_day": first_day, "oldest_pending_day_count": first_day_count,
        "upcoming_pending_count": pending_count, "archive_pending_count": 0,
    }


def _string(value, field, max_length, required=True):
    if not isinstance(value, str) or len(value) > max_length or (required and not value.strip()):
        raise ValueError(f"Invalid {field} (up to {max_length} characters).")
    return value.strip()


def _sources(entries):
    if not isinstance(entries, list) or len(entries) > 10:
        raise ValueError("Provide up to 10 source links.")
    sources, urls = [], set()
    for source in entries:
        if (not isinstance(source, dict) or not {"label", "url"} <= set(source)
                or set(source) - {"label", "url", "artist_signature"}):
            raise ValueError("Every source needs a label and a web URL.")
        label = _string(source["label"], "source label", 300)
        url = _string(source["url"], "source URL", 2000)
        try:
            validate_web_url(url)
            parsed = urlsplit(url)
        except (ValidationError, ValueError):
            raise ValueError("Invalid source URL.") from None
        identity = (parsed.hostname, parsed.port, parsed.path.rstrip("/"), parsed.query)
        if parsed.username is not None or parsed.password is not None or identity in urls:
            raise ValueError("Source URLs must be distinct web links without credentials.")
        item = {"label": label, "url": url}
        if "artist_signature" in source:
            signature = source["artist_signature"]
            if not isinstance(signature, dict) or set(signature) != {"artist", "observation"}:
                raise ValueError("Signature evidence needs the artist and the observation on this lot.")
            item["artist_signature"] = {
                "artist": _string(signature["artist"], "signing artist", 250),
                "observation": _string(signature["observation"], "artist hand-signature observation", 1000),
            }
        sources.append(item)
        urls.add(identity)
    return sources


def _plan(payload):
    if not isinstance(payload, dict) or set(payload) != {"reviews"}:
        raise ValueError("Provide a reviews array.")
    reviews = payload["reviews"]
    if not isinstance(reviews, list) or not 1 <= len(reviews) <= MAX_BATCH:
        raise ValueError(f"Provide between 1 and {MAX_BATCH} reviews.")
    normalized = {}
    fields = {"id", "revision", "fingerprint", "status", "reason", "sale_market", "stronger_market", "sources"}
    for review in reviews:
        if not isinstance(review, dict) or set(review) - fields:
            raise ValueError("Unexpected review fields.")
        lot_id, revision = review.get("id"), review.get("revision")
        if type(lot_id) is not int or not 1 <= lot_id <= 2**63 - 1 or lot_id in normalized:
            raise ValueError("Provide a unique positive Calendar ID for each review.")
        if type(revision) is not int or not 0 <= revision <= 2**31 - 1:
            raise ValueError("Provide the current numeric review revision.")
        fingerprint = review.get("fingerprint")
        if not isinstance(fingerprint, str) or not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
            raise ValueError("Provide the current catalog fingerprint.")
        status = review.get("status")
        if status not in AuctionLotMarketReview.Status.values:
            raise ValueError("Choose mismatch, clear, or uncertain.")
        flagged = status == AuctionLotMarketReview.Status.MISMATCH
        evidence = {
            "fingerprint": fingerprint, "status": status, "reason": _string(review.get("reason"), "reason", 4000),
            "sale_market": _string(review.get("sale_market", ""), "sale market", 200, flagged),
            "stronger_market": _string(review.get("stronger_market", ""), "stronger market", 200, flagged),
            "sources": _sources(review.get("sources", [])),
        }
        if flagged and len(evidence["sources"]) < 2:
            raise ValueError("A mismatch requires evidence links for the sale and the stronger market.")
        normalized[lot_id] = (revision, evidence)
    return normalized


@transaction.atomic
def _apply(plan, recheck_from=None):
    # Lock canonical lot rows in consistent order before reading or creating the review.
    # An outer join to the optional review cannot be locked on PostgreSQL.
    lots = list(_eligible_lots(recheck_from).select_for_update().filter(pk__in=plan).order_by("pk"))
    if len(lots) != len(plan):
        raise ValueError("One or more lots fall outside the current Calendar review window. Read the lots again.")
    saved = AuctionLotMarketReview.objects.in_bulk(plan, field_name="lot_id")
    results = []
    for lot, row in zip(lots, _projections(lots)):
        expected_revision, evidence = plan[lot.pk]
        if (evidence["status"] == AuctionLotMarketReview.Status.MISMATCH and signature_required(lot)
                and not has_artist_signature(evidence["sources"])):
            raise ValueError(f"Lot {lot.pk} requires cited evidence of the artist’s hand signature on the offered object.")
        if row["fingerprint"] != evidence["fingerprint"]:
            raise ValueError(f"Lot {lot.pk} catalog facts changed. Read the lot again.")
        record = saved.get(lot.pk)
        revision = record.revision if record else 0
        if revision != expected_revision:
            if not (revision == expected_revision + 1 and all(getattr(record, k) == v for k, v in evidence.items())):
                raise ValueError(f"Lot {lot.pk} has a newer review. Read the lot again.")
            # Identical retry after an ambiguous response preserves the original review date.
        else:
            revision += 1
            AuctionLotMarketReview.objects.update_or_create(lot=lot, defaults={**evidence, "revision": revision})
        results.append({"id": lot.pk, "status": evidence["status"], "revision": revision})
    return {"reviews": results}


@csrf_exempt
@never_cache
@require_http_methods(["GET", "POST"])
def calendar_market_review(request):
    if not _sync_authorized(request):
        return JsonResponse({"ok": False, "error": "Unauthorized."}, status=401)
    if request.method == "GET":
        try:
            if request.GET.get("mode") == "census":
                result = _census(request.GET)
            elif "ids" in request.GET:
                result = _inspect(request.GET["ids"], request.GET.get("recheck_from"))
            else:
                result = _pending(request.GET.get("limit", 50))
        except ValueError as exc:
            return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    else:
        try:
            body = request.body
        except RequestDataTooBig:
            return JsonResponse({"ok": False, "error": "Review batch is too large."}, status=413)
        if len(body) > MAX_BYTES:
            return JsonResponse({"ok": False, "error": "Review batch is too large."}, status=413)
        try:
            plan = _plan(json.loads(body))
        except (ValueError, UnicodeDecodeError) as exc:
            return JsonResponse({"ok": False, "error": str(exc)}, status=400)
        try:
            result = _apply(plan, request.GET.get("recheck_from"))
        except ValueError as exc:
            return JsonResponse({"ok": False, "error": str(exc)}, status=409)
    return JsonResponse({"ok": True, "version": 1, **result})
