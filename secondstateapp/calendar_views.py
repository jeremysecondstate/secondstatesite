from __future__ import annotations

import calendar as month_calendar
import hashlib
import json
import os
import re
import secrets
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone as datetime_timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST

from catalogapp.artprice_artist_links import artist_identity_key
from catalogapp.bookmark_watchlist import DEFAULT_ALLOWED_DOMAINS

from .artprice_max_bid import ArtpriceAnalysisError, analyze_artprice_comparables, analyze_artprice_html
from .auction_email import (
    AuctionEmailConfigurationError,
    compose_auction_email,
    configuration_warnings,
    recipient_choices,
    sanitize_delivery_failure,
    send_auction_email,
    validate_sending_configuration,
)
from .models import (
    AuctionEmailBatch,
    AuctionEmailBatchItem,
    AuctionMaxBidAnalysis,
    AuctionWatchArtist,
    AuctionWatchLot,
)


MAX_SYNC_LOTS = 1000
MAX_SYNC_BYTES = 2_000_000
MAX_ARTPRICE_HTML_BYTES = 5 * 1024 * 1024
ARTPRICE_PRELOADED_STATE_MARKER = "window.__PRELOADED_STATE__"


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


def _bid_label(lot: AuctionWatchLot) -> str:
    if lot.bid_count == 0:
        return "Current bid: No bids"
    if lot.current_bid is None:
        return "Current bid: N/A"
    currency = (lot.currency or "").upper()
    prefix = {"USD": "$", "GBP": "\u00a3", "EUR": "\u20ac"}.get(
        currency,
        f"{currency} " if currency else "",
    )
    label = f"Current bid: {prefix}{_money(lot.current_bid)}"
    if lot.bid_count is not None:
        noun = "bid" if lot.bid_count == 1 else "bids"
        label += f" \u00b7 {lot.bid_count} {noun}"
    return label


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


def _lot_json(lot: AuctionWatchLot, zone: ZoneInfo, selected_lot_ids: set[int] | None = None) -> dict:
    selected_lot_ids = selected_lot_ids or set()
    image_url = _calendar_image_url(lot.image_url)
    artist_artprice_url = ""
    if lot.watchlist_artist_id and lot.watchlist_artist.artprice_url:
        try:
            artist_artprice_url = _validated_artist_artprice_url(lot.watchlist_artist.artprice_url)
        except ValueError:
            pass
    return {
        "id": lot.pk,
        "artist": _artist_label(lot),
        "title": lot.title or "Untitled lot",
        "auction_house": lot.auction_house or lot.source or "Auction",
        "sale_title": lot.sale_title,
        "lot_number": lot.lot_number,
        "medium": lot.medium,
        "location": lot.location,
        "estimate": _estimate_label(lot),
        "bid": _bid_label(lot),
        "time": _time_label(lot, zone),
        "url": lot.lot_url or lot.sale_url,
        "images": [image_url] if image_url else [],
        "artist_artprice_url": artist_artprice_url,
        "artprice_url": lot.artprice_url,
        "artprice_update_url": reverse("auction_lot_artprice_link", args=(lot.pk,)),
        "artprice_analysis_url": reverse("auction_lot_artprice_analysis", args=(lot.pk,)),
        "email_tray_selected": lot.pk in selected_lot_ids,
        "email_tray_update_url": reverse("auction_email_lot_selection", args=(lot.pk,)),
        "ended": not lot.active,
    }


@staff_member_required
def auction_calendar(request):
    zone = _calendar_zone()
    now_local = timezone.localtime(timezone.now(), zone)
    selected_month = _month_start(request.GET.get("month"), now_local.date())
    following_month = _next_month(selected_month)
    range_start, range_end = _utc_bounds(selected_month, following_month, zone)

    active_email_batch = (
        AuctionEmailBatch.objects.filter(is_active=True)
        .prefetch_related("items")
        .first()
    )
    selected_lot_ids = {
        item.lot_id for item in active_email_batch.items.all()
    } if active_email_batch else set()

    month_lots = list(
        AuctionWatchLot.objects.filter(event_at__gte=range_start, event_at__lt=range_end)
        .select_related("watchlist_artist")
        .order_by("event_at", "auction_house", "artist", "id")
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
        day.isoformat(): [_lot_json(lot, zone, selected_lot_ids) for lot in lots]
        for day, lots in sorted(lots_by_day.items())
    }

    today_start, upcoming_end = _utc_bounds(now_local.date(), now_local.date() + timedelta(days=181), zone)
    upcoming_lots = list(
        AuctionWatchLot.objects.filter(active=True, event_at__gte=today_start, event_at__lt=upcoming_end)
        .select_related("watchlist_artist")
        .order_by("event_at", "auction_house", "artist", "id")[:1000]
    )
    upcoming_by_day_and_sale: dict[tuple[date, str], list[AuctionWatchLot]] = {}
    upcoming_by_day: dict[date, list[AuctionWatchLot]] = defaultdict(list)
    for lot in upcoming_lots:
        local_day = timezone.localtime(lot.event_at, zone).date()
        upcoming_by_day_and_sale.setdefault((local_day, _sale_identity(lot)), []).append(lot)
        upcoming_by_day[local_day].append(lot)

    for local_day, day_lots in upcoming_by_day.items():
        calendar_data.setdefault(
            local_day.isoformat(),
            [_lot_json(lot, zone, selected_lot_ids) for lot in day_lots],
        )

    upcoming_groups = []
    for (local_day, _identity), sale_lots in upcoming_by_day_and_sale.items():
        group = _group_lots(sale_lots, zone)[0]
        group["date_iso"] = local_day.isoformat()
        group["date_label"] = local_day.strftime("%a, %b %d").replace(" 0", " ")
        upcoming_groups.append(group)
    upcoming_groups.sort(key=lambda item: (item["date_iso"], item["sort_at"], item["auction_house"]))

    last_sent_batch = (
        AuctionEmailBatch.objects.filter(status=AuctionEmailBatch.Status.SENT, is_active=False)
        .select_related("requested_by")
        .order_by("-sent_at", "-id")
        .first()
    )
    email_recipients = recipient_choices()

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
        "email_batch": active_email_batch,
        "email_selected_count": len(selected_lot_ids),
        "email_recipient_names": ", ".join(choice["name"] for choice in email_recipients),
        "email_last_sent_batch": last_sent_batch,
        "email_configuration_warnings": configuration_warnings(),
    }
    return render(request, "calendar/calendar.html", context)


def _calendar_redirect(request):
    month_value = _month_start(request.POST.get("month"), _calendar_zone_today()).strftime("%Y-%m")
    return redirect(f"{reverse('auction_calendar')}?month={month_value}")


def _calendar_zone_today() -> date:
    return timezone.localtime(timezone.now(), _calendar_zone()).date()


def _validated_artprice_url(value: object) -> str:
    candidate = str(value or "").strip()
    if not candidate:
        return ""
    if len(candidate) > 2000:
        raise ValueError("The Artprice link is too long.")
    try:
        URLValidator(schemes=("https",))(candidate)
        parsed = urlparse(candidate)
        host = (parsed.hostname or "").lower().rstrip(".")
        port = parsed.port
    except (ValidationError, ValueError):
        raise ValueError("Enter a valid secure artprice.com link.") from None
    if (
        parsed.scheme.lower() != "https"
        or not (host == "artprice.com" or host.endswith(".artprice.com"))
        or parsed.username
        or parsed.password
        or port not in (None, 443)
    ):
        raise ValueError("Enter a valid secure artprice.com link.")
    return candidate


def _validated_artist_artprice_url(value: object) -> str:
    """Validate an imported Artprice artist URL without rewriting its query."""

    candidate = str(value or "").strip()
    if not candidate:
        return ""
    if len(candidate) > 2000:
        raise ValueError("The imported Artprice artist link is too long.")
    try:
        URLValidator(schemes=("http", "https"))(candidate)
        parsed = urlparse(candidate)
        host = (parsed.hostname or "").lower().rstrip(".")
        port = parsed.port
    except (ValidationError, ValueError):
        raise ValueError("Enter a valid Artprice artist link.") from None
    expected_ports = {None, 443} if parsed.scheme.lower() == "https" else {None, 80}
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or host not in {"artprice.com", "www.artprice.com"}
        or parsed.username
        or parsed.password
        or port not in expected_ports
        or not re.match(r"^/artist/\d+/[^/?#]+(?:/|$)", parsed.path or "", re.IGNORECASE)
    ):
        raise ValueError("Enter a valid Artprice artist link.")
    return candidate


def _active_email_batch_for_update(*, create: bool = False) -> AuctionEmailBatch | None:
    batch = AuctionEmailBatch.objects.select_for_update().filter(is_active=True).first()
    if batch is None and create:
        batch, _created = AuctionEmailBatch.objects.get_or_create(
            is_active=True,
            defaults={"status": AuctionEmailBatch.Status.DRAFT},
        )
        batch = AuctionEmailBatch.objects.select_for_update().get(pk=batch.pk)
    return batch


def _batch_selected_count(batch: AuctionEmailBatch | None) -> int:
    return batch.items.count() if batch else 0


@staff_member_required
@require_POST
def update_auction_lot_artprice_link(request, lot_id: int):
    try:
        artprice_url = _validated_artprice_url(request.POST.get("artprice_url"))
    except ValueError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)

    with transaction.atomic():
        lot = get_object_or_404(AuctionWatchLot.objects.select_for_update(), pk=lot_id)
        batch = _active_email_batch_for_update()
        selected_item = (
            batch.items.filter(lot=lot).first()
            if batch
            else None
        )
        if (
            selected_item
            and batch.status == AuctionEmailBatch.Status.SENDING
            and lot.artprice_url != artprice_url
        ):
            return JsonResponse(
                {"ok": False, "error": "This lot cannot be changed while its email batch is sending."},
                status=409,
            )
        if lot.artprice_url != artprice_url:
            lot.artprice_url = artprice_url
            lot.save(update_fields=("artprice_url",))
        if not artprice_url and selected_item:
            selected_item.delete()
        selected = bool(artprice_url and selected_item)
        selected_count = _batch_selected_count(batch)

    return JsonResponse(
        {
            "ok": True,
            "artprice_url": artprice_url,
            "email_tray_selected": selected,
            "selected_count": selected_count,
            "message": "Artprice link saved." if artprice_url else "Artprice link removed.",
        }
    )


@staff_member_required
@require_POST
def update_auction_email_selection(request, lot_id: int):
    submitted = str(request.POST.get("selected", "")).strip().casefold()
    if submitted not in {"true", "false", "1", "0", "on", "off"}:
        return JsonResponse({"ok": False, "error": "Choose whether to include this lot."}, status=400)
    selected = submitted in {"true", "1", "on"}

    with transaction.atomic():
        lot = get_object_or_404(AuctionWatchLot.objects.select_for_update(), pk=lot_id)
        batch = _active_email_batch_for_update(create=selected)
        if batch and batch.status == AuctionEmailBatch.Status.SENDING:
            return JsonResponse(
                {"ok": False, "error": "The Email Tray cannot be changed while it is sending."},
                status=409,
            )
        if selected:
            if not lot.artprice_url:
                return JsonResponse(
                    {"ok": False, "error": "Save an Artprice link before including this lot."},
                    status=400,
                )
            try:
                _validated_artprice_url(lot.artprice_url)
            except ValueError:
                return JsonResponse(
                    {"ok": False, "error": "This lot does not have a valid saved Artprice link."},
                    status=400,
                )
            AuctionEmailBatchItem.objects.get_or_create(
                batch=batch,
                lot=lot,
                defaults={"selected_by": request.user},
            )
        elif batch:
            batch.items.filter(lot=lot).delete()

        selected_count = _batch_selected_count(batch)

    return JsonResponse(
        {
            "ok": True,
            "selected": selected,
            "selected_count": selected_count,
            "message": "Lot added to the Email Tray." if selected else "Lot removed from the Email Tray.",
        }
    )


class _ArtpriceAnalysisRequestError(ValueError):
    def __init__(self, message: str, *, status: int = 400):
        super().__init__(message)
        self.status = status


def _analysis_options(post_data) -> dict:
    def submitted(name: str, default):
        value = post_data.get(name)
        if value is None:
            return default
        return value.strip() if isinstance(value, str) else value

    manual_resale_value = submitted("manual_resale_value", None)
    if manual_resale_value == "":
        manual_resale_value = None

    method = post_data.get("method")
    if method is None:
        method = post_data.get("resale_method")
    if method is None:
        method = "median"
    elif isinstance(method, str):
        method = method.strip()

    return {
        "method": method,
        "manual_resale_value": manual_resale_value,
        "recent_count": submitted("recent_count", 3),
        "inbound_shipping": submitted("inbound_shipping", 200),
        "target_profit": submitted("target_profit", 100),
        "seller_commission_pct": submitted("seller_commission_pct", 0),
        "outbound_shipping": submitted("outbound_shipping", 0),
        "other_resale_costs": submitted("other_resale_costs", 0),
        "premium_min": submitted("premium_min", 23),
        "premium_max": submitted("premium_max", 35),
    }


def _uploaded_artprice_html(request) -> tuple[str, str]:
    upload = request.FILES.get("artprice_html")
    if upload is None:
        raise _ArtpriceAnalysisRequestError("Choose a saved Artprice HTML file to analyze.")

    source_filename = Path(str(upload.name or "")).name
    if not source_filename or Path(source_filename).suffix.casefold() not in {".html", ".htm"}:
        raise _ArtpriceAnalysisRequestError("Upload a saved Artprice page with an .html or .htm extension.")
    if len(source_filename) > 255:
        source_filename = source_filename[-255:]

    try:
        raw_html = upload.read(MAX_ARTPRICE_HTML_BYTES + 1)
    except (OSError, ValueError):
        raise _ArtpriceAnalysisRequestError("The uploaded Artprice HTML file could not be read.") from None
    if len(raw_html) > MAX_ARTPRICE_HTML_BYTES:
        raise _ArtpriceAnalysisRequestError(
            "The Artprice HTML file must be 5 MB or smaller.",
            status=413,
        )

    html_text = raw_html.decode("utf-8", errors="replace")
    if ARTPRICE_PRELOADED_STATE_MARKER not in html_text:
        raise _ArtpriceAnalysisRequestError(
            "The file does not contain the Artprice preloaded results data. Save the Artprice results page and try again."
        )
    return source_filename, html_text


def _stored_decimal(value, *, nullable: bool = False) -> Decimal | None:
    if value is None and nullable:
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise _ArtpriceAnalysisRequestError("The Artprice analysis produced an invalid normalized result.") from None
    if not result.is_finite():
        raise _ArtpriceAnalysisRequestError("The Artprice analysis produced an invalid normalized result.")
    return result.quantize(Decimal("0.01"))


def _analysis_model_defaults(result: dict, *, source_filename: str, created_by) -> dict:
    assumptions = result.get("assumptions")
    comparables = result.get("comparables")
    bid_rows = result.get("bid_rows")
    if (
        not isinstance(assumptions, dict)
        or not isinstance(comparables, list)
        or not isinstance(bid_rows, list)
    ):
        raise _ArtpriceAnalysisRequestError("The Artprice analysis produced an invalid normalized result.")

    try:
        return {
            "source_filename": source_filename,
            "currency": str(result["currency"]),
            "resale_method": str(result["method"]),
            "manual_resale_value": _stored_decimal(
                assumptions.get("manual_resale_value"),
                nullable=True,
            ),
            "recent_count": int(assumptions["recent_count"]),
            "expected_resale_hammer": _stored_decimal(result["expected_resale_hammer"]),
            "net_resale_proceeds": _stored_decimal(result["net_resale_proceeds"]),
            "inbound_shipping": _stored_decimal(assumptions["inbound_shipping"]),
            "target_profit": _stored_decimal(assumptions["target_profit"]),
            "seller_commission_pct": _stored_decimal(assumptions["seller_commission_pct"]),
            "outbound_shipping": _stored_decimal(assumptions["outbound_shipping"]),
            "other_resale_costs": _stored_decimal(assumptions["other_resale_costs"]),
            "premium_min": int(assumptions["premium_min"]),
            "premium_max": int(assumptions["premium_max"]),
            "sold_records_count": int(result["sold_records_count"]),
            "comparables": comparables,
            "bid_rows": bid_rows,
            "created_by": created_by,
        }
    except (KeyError, TypeError, ValueError, OverflowError):
        raise _ArtpriceAnalysisRequestError("The Artprice analysis produced an invalid normalized result.") from None


def _replace_artprice_analysis(
    lot: AuctionWatchLot,
    result: dict,
    *,
    source_filename: str,
    created_by,
) -> AuctionMaxBidAnalysis:
    defaults = _analysis_model_defaults(
        result,
        source_filename=source_filename,
        created_by=created_by,
    )
    with transaction.atomic():
        analysis, _created = AuctionMaxBidAnalysis.objects.update_or_create(
            lot=lot,
            defaults=defaults,
        )
    return analysis


def _decimal_json(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return f"{value.quantize(Decimal('0.01')):.2f}"


def _analysis_json(analysis: AuctionMaxBidAnalysis) -> dict:
    updated_at = analysis.updated_at.isoformat()
    return {
        "source_filename": analysis.source_filename,
        "currency": analysis.currency,
        "sold_records_count": analysis.sold_records_count,
        "method": analysis.resale_method,
        "expected_resale_hammer": _decimal_json(analysis.expected_resale_hammer),
        "net_resale_proceeds": _decimal_json(analysis.net_resale_proceeds),
        "assumptions": {
            "manual_resale_value": _decimal_json(analysis.manual_resale_value),
            "recent_count": analysis.recent_count,
            "inbound_shipping": _decimal_json(analysis.inbound_shipping),
            "target_profit": _decimal_json(analysis.target_profit),
            "seller_commission_pct": _decimal_json(analysis.seller_commission_pct),
            "outbound_shipping": _decimal_json(analysis.outbound_shipping),
            "other_resale_costs": _decimal_json(analysis.other_resale_costs),
            "premium_min": analysis.premium_min,
            "premium_max": analysis.premium_max,
        },
        "comparables": analysis.comparables,
        "bid_rows": analysis.bid_rows,
        "created_at": analysis.created_at.isoformat(),
        "updated_at": updated_at,
        "last_analyzed_at": updated_at,
    }


@staff_member_required
@require_http_methods(["GET", "POST"])
def auction_lot_artprice_analysis(request, lot_id: int):
    lot = AuctionWatchLot.objects.filter(pk=lot_id).first()
    if lot is None:
        return JsonResponse({"ok": False, "error": "Auction lot not found."}, status=404)

    if request.method == "GET":
        analysis = AuctionMaxBidAnalysis.objects.filter(lot=lot).first()
        return JsonResponse(
            {
                "ok": True,
                "analysis": _analysis_json(analysis) if analysis is not None else None,
            }
        )

    action = str(request.POST.get("action") or "").strip().casefold()
    try:
        if action == "analyze":
            source_filename, html_text = _uploaded_artprice_html(request)
            result = analyze_artprice_html(html_text, **_analysis_options(request.POST))
            analysis = _replace_artprice_analysis(
                lot,
                result,
                source_filename=source_filename,
                created_by=request.user,
            )
            return JsonResponse(
                {
                    "ok": True,
                    "analysis": _analysis_json(analysis),
                    "message": "Artprice analysis saved.",
                }
            )

        if action == "recalculate":
            existing = AuctionMaxBidAnalysis.objects.filter(lot=lot).first()
            if existing is None:
                raise _ArtpriceAnalysisRequestError(
                    "Analyze a saved Artprice HTML page before recalculating."
                )
            result = analyze_artprice_comparables(
                existing.comparables,
                currency=existing.currency,
                **_analysis_options(request.POST),
            )
            analysis = _replace_artprice_analysis(
                lot,
                result,
                source_filename=existing.source_filename,
                created_by=request.user,
            )
            return JsonResponse(
                {
                    "ok": True,
                    "analysis": _analysis_json(analysis),
                    "message": "Artprice analysis recalculated.",
                }
            )

        if action == "delete":
            with transaction.atomic():
                AuctionMaxBidAnalysis.objects.filter(lot=lot).delete()
            return JsonResponse(
                {
                    "ok": True,
                    "analysis": None,
                    "message": "Artprice analysis removed.",
                }
            )

        raise _ArtpriceAnalysisRequestError("Choose a valid Artprice analysis action.")
    except _ArtpriceAnalysisRequestError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=exc.status)
    except ArtpriceAnalysisError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)


def _email_item_sort_key(item: AuctionEmailBatchItem) -> tuple:
    lot = item.lot
    return (
        lot.event_at is None,
        lot.event_at or datetime.max.replace(tzinfo=datetime_timezone.utc),
        (lot.auction_house or lot.source or "Auction").casefold(),
        (_artist_label(lot)).casefold(),
        (lot.lot_number or lot.source_lot_id or str(lot.pk)).casefold(),
        lot.pk,
    )


def _email_tray_redirect():
    return redirect(reverse("auction_email_tray"))


@staff_member_required
def review_auction_email_tray(request):
    batch = (
        AuctionEmailBatch.objects.filter(is_active=True)
        .select_related("requested_by")
        .prefetch_related("items__lot", "items__selected_by")
        .first()
    )
    items = sorted(list(batch.items.all()), key=_email_item_sort_key) if batch else []
    composition = compose_auction_email([item.lot for item in items]) if items else None
    checked_keys = set(batch.recipient_keys) if batch and batch.status == AuctionEmailBatch.Status.FAILED else set()
    if not checked_keys:
        checked_keys = {choice["key"] for choice in recipient_choices()}
    choices = [
        {**choice, "checked": choice["key"] in checked_keys}
        for choice in recipient_choices()
    ]
    return render(
        request,
        "calendar/email_tray.html",
        {
            "batch": batch,
            "items": items,
            "composition": composition,
            "recipient_choices": choices,
            "configuration_warnings": configuration_warnings(),
            "timezone_label": settings.CALENDAR_TIME_ZONE.replace("_", " "),
        },
    )


@staff_member_required
@require_POST
def remove_auction_email_lot(request, lot_id: int):
    with transaction.atomic():
        batch = _active_email_batch_for_update()
        if not batch:
            messages.info(request, "The Email Tray is already empty.")
            return _email_tray_redirect()
        if batch.status == AuctionEmailBatch.Status.SENDING:
            messages.error(request, "The Email Tray cannot be changed while it is sending.")
            return _email_tray_redirect()
        deleted, _details = batch.items.filter(lot_id=lot_id).delete()
    if deleted:
        messages.success(request, "Lot removed from the Email Tray.")
    else:
        messages.info(request, "That lot is not in the Email Tray.")
    return _email_tray_redirect()


@staff_member_required
@require_POST
def clear_auction_email_tray(request):
    with transaction.atomic():
        batch = _active_email_batch_for_update()
        if not batch:
            messages.info(request, "The Email Tray is already empty.")
            return _email_tray_redirect()
        if batch.status == AuctionEmailBatch.Status.SENDING:
            messages.error(request, "The Email Tray cannot be cleared while it is sending.")
            return _email_tray_redirect()
        batch.items.all().delete()
        if batch.status == AuctionEmailBatch.Status.FAILED:
            batch.status = AuctionEmailBatch.Status.DRAFT
            batch.recipient_keys = []
            batch.recipient_snapshot = []
            batch.subject_snapshot = ""
            batch.html_body_snapshot = ""
            batch.text_body_snapshot = ""
            batch.gmail_message_id = ""
            batch.failure_summary = ""
            batch.save(
                update_fields=(
                    "status",
                    "recipient_keys",
                    "recipient_snapshot",
                    "subject_snapshot",
                    "html_body_snapshot",
                    "text_body_snapshot",
                    "gmail_message_id",
                    "failure_summary",
                    "updated_at",
                )
            )
    messages.success(request, "Email Tray cleared.")
    return _email_tray_redirect()


def _prepare_auction_email_dispatch(request, *, retry: bool):
    submitted_keys = request.POST.getlist("recipients")
    with transaction.atomic():
        batch = _active_email_batch_for_update()
        if not batch or not batch.items.exists():
            messages.error(request, "The Email Tray is empty.")
            return None
        if batch.status == AuctionEmailBatch.Status.SENDING:
            messages.error(request, "This Email Tray batch is already sending.")
            return None
        if retry and batch.status != AuctionEmailBatch.Status.FAILED:
            messages.error(request, "Only a failed Email Tray batch can be retried.")
            return None
        if not retry and batch.status == AuctionEmailBatch.Status.FAILED:
            messages.error(request, "Use Retry Email to deliberately retry this failed batch.")
            return None
        if not retry and batch.status != AuctionEmailBatch.Status.DRAFT:
            messages.error(request, "This Email Tray batch cannot be sent from its current state.")
            return None

        try:
            recipients = validate_sending_configuration(submitted_keys)
        except AuctionEmailConfigurationError as exc:
            messages.error(request, str(exc))
            return None

        items = sorted(
            list(batch.items.select_related("lot", "selected_by")),
            key=_email_item_sort_key,
        )
        invalid_lots = []
        for item in items:
            try:
                valid_url = _validated_artprice_url(item.lot.artprice_url)
            except ValueError:
                valid_url = ""
            if not valid_url:
                invalid_lots.append(item.lot.lot_number or item.lot.source_lot_id or str(item.lot_id))
        if invalid_lots:
            messages.error(
                request,
                "Every selected lot must have a valid saved Artprice link. Remove or repair: "
                + ", ".join(invalid_lots[:5]),
            )
            return None

        composition = compose_auction_email([item.lot for item in items])
        for item in items:
            item.lot_snapshot = composition.lot_snapshots[item.lot_id]
        AuctionEmailBatchItem.objects.bulk_update(items, ("lot_snapshot",))

        now = timezone.now()
        batch.status = AuctionEmailBatch.Status.SENDING
        batch.requested_by = request.user
        batch.recipient_keys = [recipient.key for recipient in recipients]
        batch.recipient_snapshot = [
            {"key": recipient.key, "name": recipient.name, "address": recipient.address}
            for recipient in recipients
        ]
        batch.subject_snapshot = composition.subject
        batch.html_body_snapshot = composition.html_body
        batch.text_body_snapshot = composition.text_body
        batch.gmail_message_id = ""
        batch.attempt_count += 1
        batch.attempted_at = now
        batch.failure_summary = ""
        batch.save(
            update_fields=(
                "status",
                "requested_by",
                "recipient_keys",
                "recipient_snapshot",
                "subject_snapshot",
                "html_body_snapshot",
                "text_body_snapshot",
                "gmail_message_id",
                "attempt_count",
                "attempted_at",
                "failure_summary",
                "updated_at",
            )
        )
    return batch, recipients, composition


def _dispatch_auction_email(request, *, retry: bool):
    prepared = _prepare_auction_email_dispatch(request, retry=retry)
    if prepared is None:
        return _email_tray_redirect()
    batch, recipients, composition = prepared
    try:
        message_id = send_auction_email(
            subject=composition.subject,
            text_body=composition.text_body,
            html_body=composition.html_body,
            recipients=[recipient.address for recipient in recipients],
        )
    except Exception as exc:
        failure_summary = sanitize_delivery_failure(exc)
        AuctionEmailBatch.objects.filter(
            pk=batch.pk,
            is_active=True,
            status=AuctionEmailBatch.Status.SENDING,
        ).update(
            status=AuctionEmailBatch.Status.FAILED,
            failure_summary=failure_summary,
            updated_at=timezone.now(),
        )
        messages.error(request, f"Email delivery failed. The tray is ready to retry. {failure_summary}")
        return _email_tray_redirect()

    with transaction.atomic():
        sending_batch = AuctionEmailBatch.objects.select_for_update().get(pk=batch.pk)
        if sending_batch.status != AuctionEmailBatch.Status.SENDING or not sending_batch.is_active:
            messages.error(request, "Gmail returned success, but the batch state changed unexpectedly.")
            return _email_tray_redirect()
        sending_batch.status = AuctionEmailBatch.Status.SENT
        sending_batch.is_active = False
        sending_batch.gmail_message_id = message_id
        sending_batch.sent_at = timezone.now()
        sending_batch.failure_summary = ""
        sending_batch.save(
            update_fields=(
                "status",
                "is_active",
                "gmail_message_id",
                "sent_at",
                "failure_summary",
                "updated_at",
            )
        )

    recipient_names = ", ".join(recipient.name for recipient in recipients)
    messages.success(
        request,
        f"Sent {composition.lot_count} selected auction lot{'s' if composition.lot_count != 1 else ''} to {recipient_names}.",
    )
    return _calendar_redirect(request)


@staff_member_required
@require_POST
def send_auction_email_batch(request):
    return _dispatch_auction_email(request, retry=False)


@staff_member_required
@require_POST
def retry_auction_email_batch(request):
    return _dispatch_auction_email(request, retry=True)


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


def _calendar_image_url(value) -> str:
    """Allow automatic browser loads only from HTTPS watchlist-source hosts."""

    candidate = _url(value)
    parsed = urlparse(candidate)
    host = (parsed.hostname or "").casefold()
    if parsed.scheme != "https":
        return ""
    if any(host == domain or host.endswith(f".{domain}") for domain in DEFAULT_ALLOWED_DOMAINS):
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


def _nonnegative_integer(value) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise ValueError("must be a non-negative integer")
    try:
        result = int(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError("must be a non-negative integer") from exc
    if str(result) != str(value).strip() or result < 0 or result > 2_147_483_647:
        raise ValueError("must be a non-negative integer")
    return result


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
    raw_artist_links = payload.get("artist_links", [])
    if not isinstance(raw_artist_links, list):
        return JsonResponse({"ok": False, "error": "artist_links must be an array."}, status=400)
    if len(raw_artist_links) > MAX_SYNC_LOTS:
        return JsonResponse(
            {"ok": False, "error": f"At most {MAX_SYNC_LOTS} artist links may be synced at once."},
            status=400,
        )

    zone = _calendar_zone()
    prepared = []
    prepared_artist_links: dict[str, tuple[str, str]] = {}
    try:
        for index, record in enumerate(raw_artist_links):
            if not isinstance(record, dict):
                raise ValueError(f"artist_links[{index}] must be an object")
            name = _text(record.get("name"), 255)
            if not name:
                raise ValueError(f"artist_links[{index}].name is required")
            normalized_name = artist_identity_key(name)[:255]
            if not normalized_name:
                raise ValueError(f"artist_links[{index}].name is invalid")
            artprice_url = _validated_artist_artprice_url(record.get("artprice_url"))
            if not artprice_url:
                raise ValueError(f"artist_links[{index}].artprice_url is required")
            existing = prepared_artist_links.get(normalized_name)
            if existing and existing[1] != artprice_url:
                raise ValueError(f"artist_links[{index}] conflicts with another link for {name}")
            if existing is None or name.casefold() < existing[0].casefold():
                prepared_artist_links[normalized_name] = (name, artprice_url)

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
                "bid_count": _nonnegative_integer(record.get("bid_count")),
                "lot_url": _url(record.get("lot_url")),
                "sale_url": _url(record.get("sale_url")),
                "image_url": _calendar_image_url(record.get("image_url")),
                "source_status": source_status,
                "active": active,
                "source_first_seen_at": first_seen_at,
                "source_last_seen_at": last_seen_at,
            }
            artist_name = defaults["artist_watchlist_name"] or defaults["artist"]
            normalized_artist_name = artist_identity_key(artist_name)[:255]
            prepared.append((source, source_lot_id, defaults, artist_name, normalized_artist_name))
    except ValueError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)

    created_count = 0
    updated_count = 0
    ended_count = 0
    with transaction.atomic():
        artists_by_key: dict[str, AuctionWatchArtist] = {}
        for normalized_name, (name, artprice_url) in prepared_artist_links.items():
            artist, _created = AuctionWatchArtist.objects.update_or_create(
                normalized_name=normalized_name,
                defaults={"name": name, "artprice_url": artprice_url},
            )
            artists_by_key[normalized_name] = artist

        for source, source_lot_id, defaults, artist_name, normalized_artist_name in prepared:
            if normalized_artist_name:
                artist = artists_by_key.get(normalized_artist_name)
                if artist is None:
                    artist, _created = AuctionWatchArtist.objects.get_or_create(
                        normalized_name=normalized_artist_name,
                        defaults={"name": artist_name},
                    )
                    artists_by_key[normalized_artist_name] = artist
                defaults["watchlist_artist"] = artist
            _lot, created = AuctionWatchLot.objects.update_or_create(
                source=source,
                source_lot_id=source_lot_id,
                defaults=defaults,
            )
            created_count += int(created)
            updated_count += int(not created)
            ended_count += int(not defaults["active"])

    return JsonResponse(
        {
            "ok": True,
            "received": len(prepared),
            "created": created_count,
            "updated": updated_count,
            "ended": ended_count,
            "artist_links": len(prepared_artist_links),
        }
    )
