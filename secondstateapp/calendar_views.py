from __future__ import annotations

import calendar as month_calendar
import hashlib
import json
import logging
import os
import secrets
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone as datetime_timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .auction_reminders import (
    ReminderConfigurationError,
    build_due_digests,
    dispatch_active_auction_reminders,
    masked_reminder_recipients,
    validate_live_reminder_configuration,
)
from .models import AuctionReminderControl, AuctionWatchLot


MAX_SYNC_LOTS = 1000
MAX_SYNC_BYTES = 2_000_000
logger = logging.getLogger(__name__)


def _calendar_zone() -> ZoneInfo:
    return ZoneInfo(settings.CALENDAR_TIME_ZONE)


def _month_start(value: str | None, today: date) -> date:
    if value:
        try:
            parsed = date.fromisoformat(f"{value}-01")
            if 2000 <= parsed.year <= 2100:
                return parsed
        except (TypeError, ValueError):
            pass
    return today.replace(day=1)


def _next_month(value: date) -> date:
    return date(value.year + (value.month == 12), 1 if value.month == 12 else value.month + 1, 1)


def _previous_month(value: date) -> date:
    return date(value.year - (value.month == 1), 12 if value.month == 1 else value.month - 1, 1)


def _utc_bounds(start_date: date, end_date: date, zone: ZoneInfo) -> tuple[datetime, datetime]:
    start = datetime.combine(start_date, time.min, tzinfo=zone)
    end = datetime.combine(end_date, time.min, tzinfo=zone)
    return start.astimezone(datetime_timezone.utc), end.astimezone(datetime_timezone.utc)


def _artist_label(lot: AuctionWatchLot) -> str:
    return lot.artist_watchlist_name or lot.artist or "Unknown artist"


def _sale_identity(lot: AuctionWatchLot) -> str:
    if lot.sale_url:
        return f"sale:{lot.sale_url}"
    return "|".join(
        (
            lot.source,
            lot.auction_house,
            lot.sale_title,
            lot.event_at.isoformat() if lot.event_at else "",
        )
    )


def _money(value: Decimal | None) -> str:
    if value is None:
        return ""
    if value == value.to_integral_value():
        return f"{value:,.0f}"
    return f"{value:,.2f}"


def _estimate_label(lot: AuctionWatchLot) -> str:
    if lot.estimate_low is None and lot.estimate_high is None:
        return ""
    currency = (lot.currency or "").upper()
    prefix = {"USD": "$", "GBP": "£", "EUR": "€"}.get(currency, f"{currency} " if currency else "")
    if lot.estimate_low is not None and lot.estimate_high is not None:
        value = f"{_money(lot.estimate_low)}–{_money(lot.estimate_high)}"
    else:
        value = _money(lot.estimate_low if lot.estimate_low is not None else lot.estimate_high)
    return f"{prefix}{value} estimate"


def _time_label(lot: AuctionWatchLot, zone: ZoneInfo) -> str:
    if not lot.event_at or lot.is_all_day:
        return "Time TBA"
    return timezone.localtime(lot.event_at, zone).strftime("%-I:%M %p") if os.name != "nt" else timezone.localtime(
        lot.event_at, zone
    ).strftime("%I:%M %p").lstrip("0")


def _group_lots(lots: list[AuctionWatchLot], zone: ZoneInfo) -> list[dict]:
    grouped: dict[str, list[AuctionWatchLot]] = {}
    for lot in lots:
        grouped.setdefault(_sale_identity(lot), []).append(lot)

    groups = []
    for sale_lots in grouped.values():
        first = sale_lots[0]
        artists = sorted({_artist_label(lot) for lot in sale_lots}, key=str.casefold)
        groups.append(
            {
                "auction_house": first.auction_house or first.source or "Auction",
                "sale_title": first.sale_title,
                "lot_count": len(sale_lots),
                "artists": ", ".join(artists[:3]),
                "additional_artists": max(0, len(artists) - 3),
                "time_label": _time_label(first, zone),
                "url": first.sale_url or first.lot_url,
                "ended": all(not lot.active for lot in sale_lots),
                "sort_at": first.event_at,
            }
        )
    return sorted(groups, key=lambda item: (item["sort_at"], item["auction_house"]))


def _lot_json(lot: AuctionWatchLot, zone: ZoneInfo) -> dict:
    return {
        "artist": _artist_label(lot),
        "title": lot.title or "Untitled lot",
        "auction_house": lot.auction_house or lot.source or "Auction",
        "sale_title": lot.sale_title,
        "lot_number": lot.lot_number,
        "medium": lot.medium,
        "location": lot.location,
        "estimate": _estimate_label(lot),
        "time": _time_label(lot, zone),
        "url": lot.lot_url or lot.sale_url,
        "ended": not lot.active,
    }


@staff_member_required
def auction_calendar(request):
    zone = _calendar_zone()
    now_local = timezone.localtime(timezone.now(), zone)
    selected_month = _month_start(request.GET.get("month"), now_local.date())
    following_month = _next_month(selected_month)
    range_start, range_end = _utc_bounds(selected_month, following_month, zone)

    month_lots = list(
        AuctionWatchLot.objects.filter(event_at__gte=range_start, event_at__lt=range_end).order_by(
            "event_at", "auction_house", "artist", "id"
        )
    )
    lots_by_day: dict[date, list[AuctionWatchLot]] = defaultdict(list)
    for lot in month_lots:
        lots_by_day[timezone.localtime(lot.event_at, zone).date()].append(lot)

    weeks = []
    for week in month_calendar.Calendar(firstweekday=0).monthdatescalendar(selected_month.year, selected_month.month):
        week_items = []
        for day in week:
            day_lots = lots_by_day.get(day, [])
            event_groups = _group_lots(day_lots, zone)
            week_items.append(
                {
                    "date": day,
                    "iso": day.isoformat(),
                    "day_number": day.day,
                    "in_month": day.month == selected_month.month,
                    "is_today": day == now_local.date(),
                    "event_groups": event_groups[:3],
                    "more_count": max(0, len(event_groups) - 3),
                    "lot_count": len(day_lots),
                }
            )
        weeks.append(week_items)

    calendar_data = {
        day.isoformat(): [_lot_json(lot, zone) for lot in lots]
        for day, lots in sorted(lots_by_day.items())
    }

    today_start, upcoming_end = _utc_bounds(now_local.date(), now_local.date() + timedelta(days=181), zone)
    upcoming_lots = list(
        AuctionWatchLot.objects.filter(active=True, event_at__gte=today_start, event_at__lt=upcoming_end)
        .order_by("event_at", "auction_house", "artist", "id")[:1000]
    )
    upcoming_by_day_and_sale: dict[tuple[date, str], list[AuctionWatchLot]] = {}
    upcoming_by_day: dict[date, list[AuctionWatchLot]] = defaultdict(list)
    for lot in upcoming_lots:
        local_day = timezone.localtime(lot.event_at, zone).date()
        upcoming_by_day_and_sale.setdefault((local_day, _sale_identity(lot)), []).append(lot)
        upcoming_by_day[local_day].append(lot)

    for local_day, day_lots in upcoming_by_day.items():
        calendar_data.setdefault(local_day.isoformat(), [_lot_json(lot, zone) for lot in day_lots])

    upcoming_groups = []
    for (local_day, _identity), sale_lots in upcoming_by_day_and_sale.items():
        group = _group_lots(sale_lots, zone)[0]
        group["date_iso"] = local_day.isoformat()
        group["date_label"] = local_day.strftime("%a, %b %d").replace(" 0", " ")
        upcoming_groups.append(group)
    upcoming_groups.sort(key=lambda item: (item["date_iso"], item["sort_at"], item["auction_house"]))

    reminder_control = AuctionReminderControl.load()
    reminder_configuration_error = ""
    try:
        validate_live_reminder_configuration()
    except ReminderConfigurationError as exc:
        reminder_configuration_error = str(exc)
    if reminder_control.active and settings.TWILIO_SMS_ENABLED:
        reminder_status_label = "Active"
    elif reminder_control.active:
        reminder_status_label = "Safety lock on"
    else:
        reminder_status_label = "Paused"

    context = {
        "month_title": selected_month.strftime("%B %Y"),
        "month_value": selected_month.strftime("%Y-%m"),
        "previous_month": _previous_month(selected_month).strftime("%Y-%m"),
        "next_month": following_month.strftime("%Y-%m"),
        "weeks": weeks,
        "calendar_data": calendar_data,
        "initial_day": now_local.date().isoformat() if now_local.date() in lots_by_day else next(iter(calendar_data), ""),
        "upcoming_groups": upcoming_groups[:10],
        "timezone_label": settings.CALENDAR_TIME_ZONE.replace("_", " "),
        "synced_lot_count": AuctionWatchLot.objects.count(),
        "reminder_control": reminder_control,
        "reminder_status_label": reminder_status_label,
        "reminder_master_enabled": settings.TWILIO_SMS_ENABLED,
        "reminder_configuration_error": reminder_configuration_error,
        "reminder_can_start": bool(settings.TWILIO_SMS_ENABLED and not reminder_configuration_error),
        "reminder_recipients": masked_reminder_recipients(),
        "due_reminder_digests": build_due_digests(now_local.date()),
    }
    return render(request, "calendar/calendar.html", context)


def _calendar_redirect(request):
    month_value = _month_start(request.POST.get("month"), _calendar_zone_today()).strftime("%Y-%m")
    return redirect(f"{reverse('auction_calendar')}?month={month_value}")


def _calendar_zone_today() -> date:
    return timezone.localtime(timezone.now(), _calendar_zone()).date()


def _add_dispatch_message(request, outcome) -> None:
    if outcome.status in {"disabled", "failed", "partial_failure", "configuration_error"}:
        messages.error(request, outcome.summary)
    elif outcome.status in {"no_due", "paused", "up_to_date"}:
        messages.info(request, outcome.summary)
    else:
        messages.success(request, outcome.summary)


@staff_member_required
@require_POST
def manage_auction_reminders(request):
    action = request.POST.get("action", "").strip().lower()
    control = AuctionReminderControl.load()
    now = timezone.now()

    if action == "pause":
        control.active = False
        control.paused_at = now
        control.updated_by = request.user
        control.save(update_fields=("active", "paused_at", "updated_by", "updated_at"))
        messages.success(request, "Reminder texts are paused. Already queued Twilio messages cannot be recalled.")
        return _calendar_redirect(request)

    if action != "start":
        messages.error(request, "Unknown reminder control action.")
        return _calendar_redirect(request)
    if not settings.TWILIO_SMS_ENABLED:
        messages.error(request, "The Render SMS safety switch is off. Enable it only after Twilio approval.")
        return _calendar_redirect(request)
    try:
        validate_live_reminder_configuration()
    except ReminderConfigurationError as exc:
        messages.error(request, f"Reminder configuration error: {exc}")
        return _calendar_redirect(request)

    control.active = True
    control.started_at = now
    control.paused_at = None
    control.updated_by = request.user
    control.save(update_fields=("active", "started_at", "paused_at", "updated_by", "updated_at"))
    outcome = dispatch_active_auction_reminders(source="start")
    _add_dispatch_message(request, outcome)
    return _calendar_redirect(request)


@staff_member_required
@require_POST
def send_due_auction_reminders(request):
    control = AuctionReminderControl.load()
    if not control.active:
        messages.error(request, "Start reminder texts before using Send Due Now.")
        return _calendar_redirect(request)
    outcome = dispatch_active_auction_reminders(source="manual")
    _add_dispatch_message(request, outcome)
    return _calendar_redirect(request)


def _sync_authorized(request) -> bool:
    expected = os.environ.get("CATALOG_API_KEY", "").strip()
    provided = request.headers.get("X-API-KEY", "").strip()
    return bool(expected and provided and secrets.compare_digest(expected, provided))


def _text(value, max_length: int) -> str:
    if value is None:
        return ""
    return str(value).strip()[:max_length]


def _url(value) -> str:
    candidate = _text(value, 2000)
    parsed = urlparse(candidate)
    if parsed.scheme in {"http", "https"} and parsed.netloc and not parsed.username and not parsed.password:
        return candidate
    return ""


def _decimal(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("must be a number") from exc
    if not result.is_finite() or abs(result) >= Decimal("10000000000000"):
        raise ValueError("is outside the supported range")
    try:
        return result.quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise ValueError("must be a number with at most two decimal places") from exc


def _source_datetime(value, zone: ZoneInfo) -> tuple[datetime | None, bool]:
    if value in (None, ""):
        return None, False
    raw = str(value).strip()
    try:
        if len(raw) == 10:
            parsed_date = parse_date(raw)
            if parsed_date is not None:
                return datetime.combine(parsed_date, time.min, tzinfo=zone), True
        parsed_datetime = parse_datetime(raw)
        if parsed_datetime is not None:
            if timezone.is_naive(parsed_datetime):
                parsed_datetime = timezone.make_aware(parsed_datetime, zone)
            return parsed_datetime, False
        parsed_date = parse_date(raw)
        if parsed_date is not None:
            return datetime.combine(parsed_date, time.min, tzinfo=zone), True
    except (TypeError, ValueError):
        pass
    raise ValueError("must be an ISO-8601 date or datetime")


def _fallback_lot_id(record: dict) -> str:
    seed = record.get("lot_url") or "|".join(
        str(record.get(key) or "")
        for key in ("sale_url", "auction_house", "artist", "title", "lot_number", "end_at", "start_at")
    )
    return f"generated-{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:32]}"


@csrf_exempt
@require_POST
def sync_auction_calendar(request):
    if not os.environ.get("CATALOG_API_KEY", "").strip():
        return JsonResponse({"ok": False, "error": "Calendar sync is not configured."}, status=503)
    if not _sync_authorized(request):
        return JsonResponse({"ok": False, "error": "Unauthorized."}, status=401)
    if len(request.body) > MAX_SYNC_BYTES:
        return JsonResponse({"ok": False, "error": "Sync payload is too large."}, status=413)

    try:
        payload = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "Request body must be valid JSON."}, status=400)
    if not isinstance(payload, dict) or not isinstance(payload.get("lots"), list):
        return JsonResponse({"ok": False, "error": "Request must contain a lots array."}, status=400)
    if len(payload["lots"]) > MAX_SYNC_LOTS:
        return JsonResponse({"ok": False, "error": f"At most {MAX_SYNC_LOTS} lots may be synced at once."}, status=400)

    zone = _calendar_zone()
    prepared = []
    try:
        for index, record in enumerate(payload["lots"]):
            if not isinstance(record, dict):
                raise ValueError(f"lots[{index}] must be an object")
            source = _text(record.get("source"), 80)
            if not source:
                raise ValueError(f"lots[{index}].source is required")
            source_lot_id = _text(record.get("source_lot_id"), 255) or _fallback_lot_id(record)
            event_value = record.get("end_at") or record.get("start_at") or record.get("event_at")
            event_at, is_all_day = _source_datetime(event_value, zone)
            first_seen_at, _ = _source_datetime(record.get("first_seen_at"), zone)
            last_seen_at, _ = _source_datetime(record.get("last_seen_at"), zone)
            source_status = _text(record.get("status") or "unchanged", 24).lower()
            active = source_status != "ended" and record.get("active", True) is not False
            defaults = {
                "artist": _text(record.get("artist"), 255),
                "artist_watchlist_name": _text(record.get("artist_watchlist_name"), 255),
                "title": _text(record.get("title"), 500),
                "medium": _text(record.get("medium"), 500),
                "auction_house": _text(record.get("auction_house"), 255),
                "sale_title": _text(record.get("sale_title"), 500),
                "lot_number": _text(record.get("lot_number"), 80),
                "location": _text(record.get("location"), 255),
                "event_at": event_at,
                "is_all_day": bool(record.get("is_all_day", is_all_day)) or is_all_day,
                "estimate_low": _decimal(record.get("estimate_low")),
                "estimate_high": _decimal(record.get("estimate_high")),
                "currency": _text(record.get("currency"), 8).upper(),
                "current_bid": _decimal(record.get("current_bid")),
                "lot_url": _url(record.get("lot_url")),
                "sale_url": _url(record.get("sale_url")),
                "source_status": source_status,
                "active": active,
                "source_first_seen_at": first_seen_at,
                "source_last_seen_at": last_seen_at,
            }
            prepared.append((source, source_lot_id, defaults))
    except ValueError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)

    created_count = 0
    updated_count = 0
    ended_count = 0
    with transaction.atomic():
        for source, source_lot_id, defaults in prepared:
            _lot, created = AuctionWatchLot.objects.update_or_create(
                source=source,
                source_lot_id=source_lot_id,
                defaults=defaults,
            )
            created_count += int(created)
            updated_count += int(not created)
            ended_count += int(not defaults["active"])

    reminder_payload = {
        "status": "not_run",
        "summary": "No reminder catch-up was needed.",
        "active": False,
        "master_enabled": bool(settings.TWILIO_SMS_ENABLED),
        "attempted": False,
        "due_digests": 0,
        "sent": 0,
        "skipped": 0,
        "failed": 0,
    }
    if prepared:
        try:
            reminder_payload = dispatch_active_auction_reminders(source="sync").as_dict()
        except Exception:
            logger.exception("Auction reminder catch-up failed after calendar sync")
            reminder_payload.update(
                status="error",
                summary="Calendar data synced, but the reminder catch-up could not run.",
            )

    return JsonResponse(
        {
            "ok": True,
            "received": len(prepared),
            "created": created_count,
            "updated": updated_count,
            "ended": ended_count,
            "reminders": reminder_payload,
        }
    )
