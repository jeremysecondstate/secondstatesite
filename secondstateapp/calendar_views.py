from __future__ import annotations

import calendar as month_calendar
import hashlib
import json
import math
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
from django.core.exceptions import RequestDataTooBig, ValidationError
from django.core.validators import URLValidator
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from catalogapp.artprice_artist_links import artist_identity_key
from catalogapp.bookmark_watchlist import DEFAULT_ALLOWED_DOMAINS

from .artprice_max_bid import ArtpriceAnalysisError, _artprice_lot_url, analyze_artprice_comparables, analyze_artprice_html, artprice_sale_identity, merge_artprice_sources
from .auction_email import (
    AuctionEmailConfigurationError,
    compose_auction_email,
    configuration_warnings,
    recipient_choices,
    sanitize_delivery_failure,
    send_auction_email,
    validate_sending_configuration,
)
from .calendar_images import (
    is_saved_calendar_image_url,
    prepare_saved_calendar_image,
    store_saved_calendar_image,
)
from .liveart_artist import liveart_artist_names_match, liveart_artist_search_name
from .liveart_client import LiveArtAPIError, LiveArtClient, LiveArtConfigurationError
from .liveart_resale import artwork_matches, artwork_search_title, build_scenarios_with_sources, is_prints_and_multiples, normalize_candidate, safe_artwork_reference
from .liveart_search import PRINTS_AND_MULTIPLES_CATEGORY_ID, PRINTS_AND_MULTIPLES_LABEL, merge_search_lots, parse_search_terms, search_query_limits
from .models import (
    AuctionEmailBatch,
    AuctionEmailBatchItem,
    AuctionMaxBidAnalysis,
    AuctionWatchArtist,
    AuctionWatchLot,
    LiveArtResaleAnalysis,
)


MAX_SYNC_LOTS = 1000
MAX_SYNC_BYTES = 2_000_000
MAX_ARTPRICE_HTML_BYTES = 5 * 1024 * 1024
MAX_ARTPRICE_SOURCES = 10
MAX_ARTPRICE_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_SELECTED_RESALE_COMPS = 25
ARTPRICE_PRELOADED_STATE_MARKER = "window.__PRELOADED_STATE__"
ARTPRICE_REACT_STORE_MARKER = 'data-js-react-on-rails-store="artpriceStore"'
LIVEART_ARTIST_YEAR_MARKER = re.compile(
    r"\(\s*(?:c\.?\s*)?\d{4}(?:\s*[-\u2013\u2014]\s*\d{0,4})?\s*\)", re.IGNORECASE
)
# Heritage serves lot photographs separately from its bookmarked auction pages.
CALENDAR_IMAGE_DOMAINS = (*DEFAULT_ALLOWED_DOMAINS, "heritagestatic.com")


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
        auction_house = next((lot.auction_house for lot in sale_lots if lot.auction_house), first.source or "Auction")
        sale_title = next((lot.sale_title for lot in sale_lots if lot.sale_title), "")
        artists = sorted({_artist_label(lot) for lot in sale_lots}, key=str.casefold)
        groups.append(
            {
                "auction_house": auction_house,
                "sale_title": sale_title,
                "lot_count": len(sale_lots),
                "artists": ", ".join(artists[:3]),
                "additional_artists": max(0, len(artists) - 3),
                "time_label": _time_label(first, zone),
                "url": first.sale_url or first.lot_url,
                "sale_url": first.sale_url,
                "ended": all(not lot.active for lot in sale_lots),
                "sort_at": first.event_at,
            }
        )
    return sorted(groups, key=lambda item: (item["sort_at"], item["auction_house"]))


def _sale_json(group: dict) -> dict:
    return {
        "auction_house": group["auction_house"],
        "sale_title": group["sale_title"],
        "lot_count": group["lot_count"],
        "time_label": group["time_label"],
        "sale_url": group["sale_url"],
    }


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
        "lot_url": lot.lot_url,
        "sale_url": lot.sale_url,
        "images": [image_url] if image_url else [],
        "image_urls": [image_url] if image_url else [],
        "currency": lot.currency,
        "current_bid": _decimal_json(lot.current_bid),
        "bid_count": lot.bid_count,
        "artist_artprice_url": artist_artprice_url,
        "artprice_url": lot.artprice_url,
        "artprice_update_url": reverse("auction_lot_artprice_link", args=(lot.pk,)),
        "artprice_analysis_url": reverse("auction_lot_artprice_analysis", args=(lot.pk,)),
        "liveart_research_url": reverse("auction_lot_liveart_research", args=(lot.pk,)),
        "liveart_analysis_url": reverse("auction_lot_liveart_analysis", args=(lot.pk,)),
        "bid_board_url": reverse("auction_lot_bid_board", args=(lot.pk,)),
        "email_tray_selected": lot.pk in selected_lot_ids,
        "email_tray_update_url": reverse("auction_email_lot_selection", args=(lot.pk,)),
        "ended": not lot.active,
    }


@never_cache
@staff_member_required
def auction_calendar(request):
    zone = _calendar_zone()
    now_local = timezone.localtime(timezone.now(), zone)
    # A shared research link can name its day without a separate month parameter.
    selected_month = _month_start(
        request.GET.get("month") or (request.GET.get("day") or "")[:7],
        now_local.date(),
    )
    following_month = _next_month(selected_month)
    month_weeks = month_calendar.Calendar(firstweekday=0).monthdatescalendar(selected_month.year, selected_month.month)
    range_start, range_end = _utc_bounds(month_weeks[0][0], month_weeks[-1][-1] + timedelta(days=1), zone)

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
    for week in month_weeks:
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
                    "sale_count": len(event_groups),
                    "lot_count": len(day_lots),
                }
            )
        weeks.append(week_items)

    calendar_data = {
        day.isoformat(): [_lot_json(lot, zone, selected_lot_ids) for lot in lots]
        for day, lots in sorted(lots_by_day.items())
    }
    calendar_sales_data = {
        day.isoformat(): [_sale_json(group) for group in _group_lots(lots, zone)]
        for day, lots in sorted(lots_by_day.items())
    }

    today_start, upcoming_end = _utc_bounds(now_local.date(), now_local.date() + timedelta(days=181), zone)
    upcoming_lots = list(
        AuctionWatchLot.objects.filter(active=True, event_at__gte=today_start, event_at__lt=upcoming_end)
        .select_related("watchlist_artist")
        .order_by("event_at", "auction_house", "artist", "id")[:1000]
    )
    upcoming_by_day_and_sale: dict[tuple[date, str], list[AuctionWatchLot]] = {}
    for lot in upcoming_lots:
        local_day = timezone.localtime(lot.event_at, zone).date()
        upcoming_by_day_and_sale.setdefault((local_day, _sale_identity(lot)), []).append(lot)

    upcoming_groups = []
    for (local_day, _identity), sale_lots in upcoming_by_day_and_sale.items():
        group = _group_lots(sale_lots, zone)[0]
        group["date_iso"] = local_day.isoformat()
        group["date_label"] = local_day.strftime("%a, %b %d").replace(" 0", " ")
        upcoming_groups.append(group)
    upcoming_groups.sort(key=lambda item: (item["date_iso"], item["sort_at"], item["auction_house"]))
    visible_upcoming_groups = upcoming_groups[:10]

    # The upcoming list is capped for display, but each date it can select must
    # include every lot even when the initial upcoming query stops at 1,000.
    for day_iso in sorted({group["date_iso"] for group in visible_upcoming_groups}):
        if day_iso in calendar_data:
            continue
        local_day = date.fromisoformat(day_iso)
        day_start, day_end = _utc_bounds(local_day, local_day + timedelta(days=1), zone)
        day_lots = list(
            AuctionWatchLot.objects.filter(event_at__gte=day_start, event_at__lt=day_end)
            .select_related("watchlist_artist")
            .order_by("event_at", "auction_house", "artist", "id")
        )
        calendar_data[day_iso] = [_lot_json(lot, zone, selected_lot_ids) for lot in day_lots]
        calendar_sales_data[day_iso] = [_sale_json(group) for group in _group_lots(day_lots, zone)]

    in_month_days = sorted(day for day in lots_by_day if selected_month <= day < following_month)
    if now_local.date() in in_month_days:
        initial_day = now_local.date().isoformat()
    elif in_month_days:
        initial_day = in_month_days[0].isoformat()
    elif visible_upcoming_groups:
        initial_day = visible_upcoming_groups[0]["date_iso"]
    else:
        initial_day = next(iter(calendar_data), "")

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
        "calendar_sales_data": calendar_sales_data,
        "initial_day": initial_day,
        "upcoming_groups": visible_upcoming_groups,
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

    filename, html_text, _size = _read_artprice_upload(upload)
    return filename, html_text


def _read_artprice_upload(upload) -> tuple[str, str, int]:
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
    if not any(marker in html_text for marker in (ARTPRICE_PRELOADED_STATE_MARKER, ARTPRICE_REACT_STORE_MARKER)):
        raise _ArtpriceAnalysisRequestError(
            "The file does not contain Artprice preloaded or saved results data. Save the Artprice results page and try again."
        )
    return source_filename, html_text, len(raw_html)


def _uploaded_artprice_sources(request) -> list[dict]:
    uploads = request.FILES.getlist("artprice_html")
    if not uploads:
        raise _ArtpriceAnalysisRequestError("Choose saved Artprice HTML files to analyze.")
    if len(uploads) > MAX_ARTPRICE_SOURCES:
        raise _ArtpriceAnalysisRequestError("Save up to 10 Artprice HTML files per lot.")
    total_bytes = 0
    sources = []
    for upload in uploads:
        filename, html_text, byte_count = _read_artprice_upload(upload)
        total_bytes += byte_count
        if total_bytes > MAX_ARTPRICE_UPLOAD_BYTES:
            raise _ArtpriceAnalysisRequestError("Upload at most 25 MB of Artprice HTML at a time.", status=413)
        try:
            result = analyze_artprice_html(html_text, inbound_shipping=0, target_profit=0)
        except ArtpriceAnalysisError as exc:
            raise _ArtpriceAnalysisRequestError(f"{filename}: {exc}") from None
        sources.append({
            "id": hashlib.sha256(html_text.encode("utf-8")).hexdigest(),
            "filename": filename,
            "currency": result["currency"],
            "comparables": result["comparables"],
            "uploaded_at": timezone.now().isoformat(),
        })
    return sources


def _stored_artprice_sources(analysis: AuctionMaxBidAnalysis) -> list[dict]:
    if analysis.sources:
        return analysis.sources
    return [{
        "id": f"legacy-{analysis.pk}",
        "filename": analysis.source_filename,
        "currency": analysis.currency,
        "comparables": analysis.comparables,
        "uploaded_at": analysis.updated_at.isoformat(),
    }]


def _source_descriptions(analysis: AuctionMaxBidAnalysis) -> list[dict]:
    return [{
        "id": source["id"], "filename": source["filename"],
        "currency": source["currency"], "sold_records_count": len(source["comparables"]),
        "uploaded_at": source["uploaded_at"],
    } for source in _stored_artprice_sources(analysis)]


def _saved_artprice_options(analysis: AuctionMaxBidAnalysis) -> dict:
    return {
        "method": analysis.resale_method,
        **{field: getattr(analysis, field) for field in (
            "manual_resale_value", "recent_count", "inbound_shipping", "target_profit",
            "seller_commission_pct", "outbound_shipping", "other_resale_costs", "premium_min", "premium_max",
        )},
    }


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
    sources: list[dict] | None = None,
) -> AuctionMaxBidAnalysis:
    defaults = _analysis_model_defaults(
        result,
        source_filename=source_filename,
        created_by=created_by,
    )
    if sources is not None:
        defaults["sources"] = sources
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
    sources = _source_descriptions(analysis)
    raw_count = sum(source["sold_records_count"] for source in sources)
    return {
        "source_filename": analysis.source_filename,
        "sources": sources,
        # The merged estimate fills missing descriptions from overlapping files.
        # Keep the ledger faithful to what each individual file actually said.
        "source_ledger": [
            {**description, "comparables": source["comparables"]}
            for description, source in zip(sources, _stored_artprice_sources(analysis))
        ],
        "source_count": len(sources),
        "raw_sold_records_count": raw_count,
        "duplicate_records_count": max(0, raw_count - analysis.sold_records_count),
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
        "no_positive_bid": not bool(analysis.bid_rows),
        "created_at": analysis.created_at.isoformat(),
        "updated_at": updated_at,
        "last_analyzed_at": updated_at,
    }


def _artprice_candidates(lot: AuctionWatchLot) -> list[dict]:
    """Adapt the saved, normalized Artprice hammers for the resale comp review.

    The upload is already tied to this private Calendar lot.  Historical saved
    comparables have fewer descriptive fields than newer Artprice pages, so
    missing attributes stay visible. Selection is resolved against saved choices.
    """

    analysis = AuctionMaxBidAnalysis.objects.filter(lot=lot).first()
    if analysis is None:
        return []
    currency = str(analysis.currency or "").strip().upper()
    legacy_source = _stored_artprice_sources(analysis)[0]
    candidates = []
    seen_ids = set()
    for comparable in analysis.comparables if isinstance(analysis.comparables, list) else []:
        if not isinstance(comparable, dict):
            continue
        provider_id = str(comparable.get("provider_id") or "").strip() or None
        identity = provider_id or hashlib.sha256(
            json.dumps(
                [comparable.get(key) for key in ("sale_date", "auction_house", "lot_number", "title", "hammer_price")],
                sort_keys=True,
                default=str,
            ).encode("utf-8")
        ).hexdigest()[:20]
        candidate_id = f"artprice:{identity}"
        if candidate_id in seen_ids:
            continue
        seen_ids.add(candidate_id)

        raw_hammer = comparable.get("hammer_price")
        try:
            hammer = Decimal(str(raw_hammer))
        except (InvalidOperation, TypeError, ValueError):
            hammer = None
        valid_hammer = bool(hammer is not None and hammer.is_finite() and 0 < hammer <= Decimal("1000000000000"))
        artist = str(comparable.get("artist") or "").strip() or None
        calendar_artist = (lot.artist or lot.artist_watchlist_name or "").strip()
        artist_conflict = bool(
            artist and calendar_artist and artist_identity_key(artist) != artist_identity_key(calendar_artist)
        )
        credible = bool(currency == "USD" and valid_hammer and not artist_conflict)
        source_url = _artprice_lot_url(comparable.get("provider_url"))

        medium = str(comparable.get("medium") or "").strip() or None
        edition = str(comparable.get("edition") or "").strip() or None
        size = str(comparable.get("size") or "").strip() or None
        signature = str(comparable.get("signature") or "").strip() or None
        condition = str(comparable.get("condition") or "").strip() or None
        location = str(comparable.get("location") or "").strip() or None
        differences = {}
        for field, subject, comp in (
            ("medium", lot.medium, medium),
            ("edition", None, edition),
            ("signature", None, signature),
            ("size", None, size),
            ("condition", None, condition),
        ):
            subject = str(subject or "").strip() or None
            differences[field] = {
                "subject": subject,
                "comp": comp,
                "status": (
                    "unknown" if not subject or not comp else
                    "same" if subject.casefold() == comp.casefold() else "different"
                ),
            }
        missing = [
            field for field, value in (
                ("provider_id", provider_id), ("provider_url", source_url),
                ("artist", artist), ("title", comparable.get("title")),
                ("auction_house", comparable.get("auction_house")),
                ("lot_number", comparable.get("lot_number")),
                ("sale_date", comparable.get("sale_date")),
                ("medium", medium), ("edition", edition),
                ("signature", signature), ("size", size), ("condition", condition),
                ("location", location),
            ) if not value
        ]
        if not valid_hammer:
            missing.append("verified_hammer")
        notes = []
        if currency != "USD":
            notes.append("Original currency is not USD; no verified USD hammer conversion is available")
        if not valid_hammer:
            notes.append("No positive numeric hammer price")
        if artist_conflict:
            notes.append("Artprice artist differs from this Calendar artist")
        if artist is None:
            notes.append("Artist is not recorded in this saved Artprice result; verify before selecting")
        candidates.append({
            "id": candidate_id,
            "sale_identity": json.dumps(artprice_sale_identity(comparable), separators=(",", ":")),
            "provider": "Artprice",
            "provider_id": provider_id,
            "provider_url": source_url,
            "source_id": provider_id,
            "source_url": source_url,
            "source_filename": (comparable.get("source_filenames") or [analysis.source_filename])[0],
            "source_filenames": comparable.get("source_filenames") or [analysis.source_filename],
            "source_ids": comparable.get("source_ids") or [legacy_source["id"]],
            "match_type": "artprice_html",
            "status": "sold",
            "sale_date": str(comparable.get("sale_date") or ""),
            "auction_house": str(comparable.get("auction_house") or ""),
            "lot_number": str(comparable.get("lot_number") or ""),
            "artist": artist,
            "title": str(comparable.get("title") or ""),
            "hammer_usd": f"{hammer:.2f}" if credible else None,
            "original_hammer": f"{hammer:.2f}" if valid_hammer else None,
            "original_currency": currency or None,
            "medium": medium,
            "edition": edition,
            "signature": signature,
            "size": size,
            "condition": condition,
            "location": location,
            "differences": differences,
            "missing_data": missing,
            "credible": credible,
            "selected": False,
            "exclusion_reasons": notes,
            "match_notes": notes,
            "retrieved_at": analysis.updated_at.isoformat(),
        })
    return candidates


def _merged_resale_candidates(lot: AuctionWatchLot, candidates: object) -> list[dict]:
    liveart = [item for item in candidates if isinstance(item, dict) and item.get("provider") != "Artprice"] if isinstance(candidates, list) else []
    return liveart + _artprice_candidates(lot)


def _selected_resale_ids(
    candidates: list[dict],
    selected_ids: list[str | int],
    *,
    previous_candidates: list[dict] | None = None,
    initialize_artprice: bool = False,
) -> list[str]:
    """Include eligible new Artprice sales while retaining explicit later choices."""

    allowed = {str(item.get("id")) for item in candidates if item.get("credible") and item.get("status") == "sold"}
    requested = {str(item) for item in selected_ids}
    previous_artprice_by_sale = {
        artprice_sale_identity({**item, "hammer_price": item.get("hammer_usd")}): str(item.get("id"))
        for item in previous_candidates or [] if item.get("provider") == "Artprice"
    }
    carried_ids = []
    retained_artprice_ids = set()
    for item in candidates:
        if item.get("provider") != "Artprice":
            continue
        previous_id = previous_artprice_by_sale.get(artprice_sale_identity({**item, "hammer_price": item.get("hammer_usd")}))
        if previous_id is not None:
            retained_artprice_ids.add(str(item.get("id")))
            if previous_id in requested:
                carried_ids.append(str(item.get("id")))
    selected = list(dict.fromkeys(str(item) for item in [*selected_ids, *carried_ids] if str(item) in allowed))[:MAX_SELECTED_RESALE_COMPS]
    previous_artprice_ids = {
        str(item.get("id")) for item in previous_candidates or [] if item.get("provider") == "Artprice"
    } | retained_artprice_ids
    for candidate in candidates:
        identifier = str(candidate.get("id"))
        if (
            candidate.get("provider") == "Artprice"
            and identifier in allowed
            and bool(str(candidate.get("artist") or "").strip())
            and identifier not in selected
            and (initialize_artprice or identifier not in previous_artprice_ids)
            and len(selected) < MAX_SELECTED_RESALE_COMPS
        ):
            selected.append(identifier)
    return selected


def _candidates_with_selection(candidates: list[dict], selected_ids: list[str]) -> list[dict]:
    selected = set(selected_ids)
    return [{**candidate, "selected": str(candidate.get("id")) in selected} for candidate in candidates]


def _initialize_legacy_artprice(saved: LiveArtResaleAnalysis | None) -> bool:
    if saved is None:
        return True
    return not saved.source_summary and not any(
        str(item).startswith("artprice:") for item in saved.selected_ids
    )


def _lot_resale_scenarios(
    lot: AuctionWatchLot, candidates: list[dict], selected_ids: list[str], assumptions: dict,
    *, allow_unestimable: bool = False,
) -> tuple[dict, list[dict], dict]:
    artprice = AuctionMaxBidAnalysis.objects.filter(lot=lot).first()
    return build_scenarios_with_sources(
        candidates,
        selected_ids,
        assumptions,
        artprice_sold_count=artprice.sold_records_count if artprice is not None else 0,
        artprice_source_filename=artprice.source_filename if artprice is not None else None,
        artprice_sources=_source_descriptions(artprice) if artprice is not None else [],
        artprice_analysis_updated_at=artprice.updated_at.isoformat() if artprice is not None else None,
        allow_unestimable=allow_unestimable,
    )


def _refresh_saved_resale_from_artprice(
    lot: AuctionWatchLot, *, allow_unestimable: bool = False,
) -> LiveArtResaleAnalysis | None:
    """Persist source-aware bids whenever the saved Artprice history changes."""

    saved = LiveArtResaleAnalysis.objects.filter(lot=lot).first()
    if saved is None:
        return None
    candidates = _merged_resale_candidates(lot, saved.candidates)
    selected_ids = _selected_resale_ids(
        candidates, saved.selected_ids,
        previous_candidates=saved.candidates,
        initialize_artprice=_initialize_legacy_artprice(saved),
    )
    candidates = _candidates_with_selection(candidates, selected_ids)
    assumptions, scenarios, source_summary = _lot_resale_scenarios(
        lot, candidates, selected_ids, saved.assumptions, allow_unestimable=allow_unestimable,
    )
    if (
        saved.candidates != candidates or saved.selected_ids != selected_ids
        or saved.assumptions != assumptions or saved.scenarios != scenarios
        or saved.source_summary != source_summary
    ):
        saved.candidates = candidates
        saved.selected_ids = selected_ids
        saved.assumptions = assumptions
        saved.scenarios = scenarios
        saved.source_summary = source_summary
        saved.save(update_fields=("candidates", "selected_ids", "assumptions", "scenarios", "source_summary", "updated_at"))
    return saved


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
        if action in {"analyze", "add_sources"}:
            uploaded_sources = _uploaded_artprice_sources(request)
            with transaction.atomic():
                # Serialize edits of this lot so simultaneous additions cannot lose a file.
                AuctionWatchLot.objects.select_for_update().get(pk=lot.pk)
                existing = AuctionMaxBidAnalysis.objects.filter(lot=lot).first()
                sources = _stored_artprice_sources(existing) if action == "add_sources" and existing else []
                existing_ids = {source["id"] for source in sources}
                sources = list(sources)
                for source in uploaded_sources:
                    if source["id"] not in existing_ids:
                        sources.append(source)
                        existing_ids.add(source["id"])
                if len(sources) > MAX_ARTPRICE_SOURCES:
                    raise _ArtpriceAnalysisRequestError("Save up to 10 Artprice HTML files per lot. Remove a saved file before adding more.")
                result = analyze_artprice_comparables(
                    merge_artprice_sources(sources), currency="USD", **_analysis_options(request.POST),
                )
                analysis = _replace_artprice_analysis(
                    lot,
                    result,
                    source_filename=sources[0]["filename"],
                    created_by=request.user,
                    sources=sources,
                )
                _refresh_saved_resale_from_artprice(lot)
            return JsonResponse(
                {
                    "ok": True,
                    "analysis": _analysis_json(analysis),
                    "message": "Artprice analysis saved.",
                }
            )

        if action == "recalculate":
            with transaction.atomic():
                AuctionWatchLot.objects.select_for_update().get(pk=lot.pk)
                existing = AuctionMaxBidAnalysis.objects.filter(lot=lot).first()
                if existing is None:
                    raise _ArtpriceAnalysisRequestError(
                        "Analyze a saved Artprice HTML page before recalculating."
                    )
                sources = _stored_artprice_sources(existing)
                result = analyze_artprice_comparables(
                    merge_artprice_sources(sources),
                    currency=existing.currency,
                    **_analysis_options(request.POST),
                )
                analysis = _replace_artprice_analysis(
                    lot,
                    result,
                    source_filename=existing.source_filename,
                    created_by=request.user,
                    sources=sources,
                )
                _refresh_saved_resale_from_artprice(lot)
            return JsonResponse(
                {
                    "ok": True,
                    "analysis": _analysis_json(analysis),
                    "message": "Artprice analysis recalculated.",
                }
            )

        if action == "remove_source":
            source_id = str(request.POST.get("source_id") or "")
            with transaction.atomic():
                AuctionWatchLot.objects.select_for_update().get(pk=lot.pk)
                existing = AuctionMaxBidAnalysis.objects.filter(lot=lot).first()
                if existing is None:
                    raise _ArtpriceAnalysisRequestError("The saved Artprice file was not found.", status=404)
                sources = _stored_artprice_sources(existing)
                remaining = [source for source in sources if source["id"] != source_id]
                if len(remaining) == len(sources):
                    raise _ArtpriceAnalysisRequestError("The saved Artprice file was not found.", status=404)
                if remaining:
                    result = analyze_artprice_comparables(
                        merge_artprice_sources(remaining), currency=existing.currency,
                        allow_no_bid=True,
                        **_saved_artprice_options(existing),
                    )
                    analysis = _replace_artprice_analysis(
                        lot, result, source_filename=remaining[0]["filename"],
                        sources=remaining, created_by=request.user,
                    )
                else:
                    existing.delete()
                    analysis = None
                _refresh_saved_resale_from_artprice(lot)
            return JsonResponse({
                "ok": True, "analysis": _analysis_json(analysis) if analysis else None,
                "message": "Artprice HTML file removed.",
            })

        if action == "delete":
            with transaction.atomic():
                AuctionWatchLot.objects.select_for_update().get(pk=lot.pk)
                AuctionMaxBidAnalysis.objects.filter(lot=lot).delete()
                _refresh_saved_resale_from_artprice(lot)
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


def _liveart_search_context(research: dict) -> dict:
    return {key: research[key] for key in (
        "search_terms_used", "search_summary", "search_title_used", "search_category", "excluded_category_count",
    ) if key in research}


def _liveart_analysis_json(analysis: LiveArtResaleAnalysis) -> dict:
    analysis = _refresh_saved_resale_from_artprice(analysis.lot, allow_unestimable=True) or analysis
    return {
        "provider": "Resale",
        "saved": True,
        "subject_match": safe_artwork_reference(analysis.subject_match) if analysis.subject_match else None,
        "subject_matches": [safe_artwork_reference(item) for item in analysis.subject_matches if isinstance(item, dict)],
        "candidates": analysis.candidates,
        "selected_ids": analysis.selected_ids,
        "assumptions": analysis.assumptions,
        "scenarios": analysis.scenarios,
        "source_summary": analysis.source_summary,
        "no_credible_comps": not bool(analysis.scenarios),
        "retrieved_at": analysis.retrieved_at.isoformat(),
        "data_units_spent": float(analysis.data_units_spent) if analysis.data_units_spent is not None else None,
        "created_at": analysis.created_at.isoformat(),
        "updated_at": analysis.updated_at.isoformat(),
        "estimate_notice": "Resale values and maximum hammer bids are estimates, not guaranteed profit.",
        **_liveart_search_context(analysis.search_context or {}),
    }


def _artprice_resale_preview(lot: AuctionWatchLot) -> dict | None:
    candidates = _artprice_candidates(lot)
    if not candidates:
        return None
    selected_ids = _selected_resale_ids(candidates, [], initialize_artprice=True)
    candidates = _candidates_with_selection(candidates, selected_ids)
    assumptions, scenarios, source_summary = _lot_resale_scenarios(
        lot, candidates, selected_ids, {}, allow_unestimable=True,
    )
    source = AuctionMaxBidAnalysis.objects.get(lot=lot)
    return {
        "provider": "Resale",
        "saved": False,
        "subject_match": None,
        "subject_matches": [],
        "candidates": candidates,
        "selected_ids": selected_ids,
        "assumptions": assumptions,
        "scenarios": scenarios,
        "source_summary": source_summary,
        "no_credible_comps": not bool(scenarios),
        "retrieved_at": source.updated_at.isoformat(),
        "data_units_spent": None,
        "created_at": None,
        "updated_at": None,
        "estimate_notice": "Resale values and maximum hammer bids are estimates, not guaranteed profit.",
    }


def _liveart_du(page) -> float | None:
    """Keep the metered response's half-unit precision when it is provided."""

    value = getattr(page, "data_units", None)
    return float(value) if value is not None and value >= 0 else None


def _add_liveart_du(total: float | None, page) -> float | None:
    cost = _liveart_du(page)
    return total + cost if total is not None and cost is not None else None


def _research_liveart_terms(lot, client, *, artist_id, terms: tuple[str, ...], units: float | None) -> dict:
    raw_comps = []
    summary = []
    excluded_count = 0
    for term, limit in zip(terms, search_query_limits(len(terms))):
        page = client.list_lots(
            artist_id=artist_id, status="sold", search=term, sort="SALE_DATE_DESC", limit=limit,
            category_id=PRINTS_AND_MULTIPLES_CATEGORY_ID,
        )
        units = _add_liveart_du(units, page)
        returned_rows = page.items[:limit]
        rows = [item for item in returned_rows if is_prints_and_multiples(item)]
        excluded = len(returned_rows) - len(rows)
        excluded_count += excluded
        raw_comps.extend({**item, "_retrieved_at": page.retrieved_at, "_search_terms": [term]} for item in rows)
        result = {
            "term": term, "returned_count": len(rows),
            "has_more": bool(page.has_more or len(page.items) > limit),
        }
        if page.total_count is not None:
            result["total_count"] = page.total_count
        if excluded:
            result["excluded_count"] = excluded
        summary.append(result)
    candidates = []
    for raw in merge_search_lots(raw_comps):
        candidate = normalize_candidate(raw, None, lot)
        # A query discovers candidate sales, not verified artwork identities.
        # Every result needs an explicit selection even if its title matches.
        candidate["selected"] = False
        candidate["match_type"] = "related_work"
        candidate["search_terms"] = raw["_search_terms"]
        candidate["match_notes"] = [
            *(candidate.get("match_notes") or []),
            "Found by a search term; review the work before selecting this sale",
        ]
        candidates.append(candidate)
    candidates.sort(key=lambda item: str(item.get("sale_date") or ""), reverse=True)
    return {
        "subject_matches": [], "subject_match": None, "candidates": candidates,
        "selected_ids": [], "retrieved_at": timezone.now().isoformat(),
        "data_units_spent": units, "requires_subject_choice": False,
        "search_terms_used": list(terms), "search_summary": summary,
        "excluded_category_count": excluded_count,
        "message": (
            f"Found {len(candidates)} distinct Prints & Multiples sold results across {len(terms)} search terms; review and select sales to use."
            if candidates else "No confirmed Prints & Multiples sold results were returned for these search terms and this artist."
        ),
    }


def _research_liveart_lot(
    lot: AuctionWatchLot, *, subject_id: str = "", search_title: str = "", search_terms: tuple[str, ...] = (),
) -> dict:
    artist_name = (lot.artist or lot.artist_watchlist_name or "").strip()
    if not artist_name or not lot.title.strip():
        raise ValueError("This Calendar lot needs an artist and title for LiveArt research.")

    client = LiveArtClient()
    artist_query = " ".join(LIVEART_ARTIST_YEAR_MARKER.sub(" ", artist_name).split()) or artist_name
    artwork_title = artwork_search_title(lot.title, artist_name)
    title_query = search_title or artwork_title
    artist_page = client.list_artists(q=liveart_artist_search_name(artist_query)[:200], limit=3)
    units = _liveart_du(artist_page)
    artist = next(
        (
            item for item in artist_page.items
            if liveart_artist_names_match(artist_name, str(item.get("name") or ""))
            and item.get("id") is not None
        ),
        None,
    )
    retrieved_at = timezone.now().isoformat()
    if artist is None:
        return {
            "subject_matches": [],
            "subject_match": None,
            "candidates": [],
            "selected_ids": [],
            "retrieved_at": retrieved_at,
            "data_units_spent": units,
            "requires_subject_choice": False,
            "message": "No LiveArt artist matched this Calendar artist. No sold prices were used.",
            **({"search_terms_used": list(search_terms), "search_summary": []} if search_terms else {}),
        }

    artist_id = artist["id"]
    if search_terms:
        return _research_liveart_terms(lot, client, artist_id=artist_id, terms=search_terms, units=units)
    artwork_page = client.list_artworks(
        artist_id=artist_id, search=title_query[:200], limit=5, category_id=PRINTS_AND_MULTIPLES_CATEGORY_ID,
    )
    units = _add_liveart_du(units, artwork_page)
    print_artworks = [item for item in artwork_page.items if is_prints_and_multiples(item)]
    excluded_count = len(artwork_page.items) - len(print_artworks)
    matches = artwork_matches(
        lot, print_artworks, artist_id=artist_id, artist_name=str(artist.get("name") or artist_name),
        title_aliases=(search_title,) if search_title else (),
    )
    verified = [item for item in matches if item.get("verified")]
    selectable = [item for item in matches if item.get("can_choose")]
    chosen = None
    if subject_id:
        chosen = next((item for item in selectable if str(item.get("id")) == subject_id), None)
        if chosen is None:
            raise ValueError("The selected LiveArt artwork does not match this artist and searched title.")
        if not chosen.get("verified"):
            chosen = {**chosen, "chosen_manually": True}
    elif len(verified) == 1:
        chosen = verified[0]

    raw_comps: list[dict] = []
    if chosen is not None:
        history_page = client.list_lots(
            artwork_id=chosen["artwork_id"], status="sold", limit=10, category_id=PRINTS_AND_MULTIPLES_CATEGORY_ID,
        )
        units = _add_liveart_du(units, history_page)
        raw_comps.extend({**item, "_retrieved_at": history_page.retrieved_at} for item in history_page.items)

    # All fallback and related-work searches stay within Prints & Multiples,
    # including when no artwork reference was found.
    related_filters = {
        "artist_id": artist_id, "status": "sold", "sort": "SALE_DATE_DESC", "limit": 10,
        "category_id": PRINTS_AND_MULTIPLES_CATEGORY_ID,
    }
    related_page = client.list_lots(**related_filters)
    units = _add_liveart_du(units, related_page)
    raw_comps.extend({**item, "_retrieved_at": related_page.retrieved_at} for item in related_page.items)

    candidates = []
    seen_ids = set()
    seen_sales = set()
    for raw in raw_comps:
        if not is_prints_and_multiples(raw):
            excluded_count += 1
            continue
        candidate_id = str(raw.get("id") or "")
        if not candidate_id or candidate_id in seen_ids:
            continue
        sale_key = (str(raw.get("sale_id") or ""), str(raw.get("lot_num") or ""))
        if all(sale_key) and sale_key in seen_sales:
            continue
        seen_ids.add(candidate_id)
        if all(sale_key):
            seen_sales.add(sale_key)
        candidate = normalize_candidate(raw, chosen, lot)
        if chosen is not None and chosen.get("chosen_manually"):
            candidate["selected"] = False
            candidate["match_notes"] = [
                *(candidate.get("match_notes") or []),
                "Artwork title differs from the Calendar title; review this sale before selecting it",
            ]
        candidate["retrieved_at"] = raw.get("_retrieved_at") or timezone.now().isoformat()
        candidates.append(candidate)
    candidates.sort(key=lambda item: str(item.get("sale_date") or ""), reverse=True)
    candidates.sort(key=lambda item: item.get("match_type") != "exact_work")
    selected_ids = [str(item["id"]) for item in candidates if item.get("selected") and item.get("credible")]
    requires_choice = chosen is None and (len(verified) > 1 or bool(selectable and not verified))
    if requires_choice and verified:
        message = "Multiple LiveArt artwork references match. Choose one to search its sale history."
    elif requires_choice:
        message = "An artwork matched the supplied title variant, but its title differs from the Calendar title. Review and choose it to search its sale history."
    elif candidates:
        message = f"Found {len(candidates)} Prints & Multiples sold results for this work and related works; review each before saving."
    else:
        message = "No suitable Prints & Multiples sold results were returned for this artist and artwork search."
    return {
        "subject_matches": matches,
        "subject_match": chosen,
        "candidates": candidates,
        "selected_ids": selected_ids,
        "retrieved_at": timezone.now().isoformat(),
        "data_units_spent": units,
        "requires_subject_choice": requires_choice,
        "search_title_used": title_query,
        "excluded_category_count": excluded_count,
        "message": message,
    }


@never_cache
@staff_member_required
@require_POST
def auction_lot_liveart_research(request, lot_id: int):
    lot = AuctionWatchLot.objects.filter(pk=lot_id).first()
    if lot is None:
        return JsonResponse({"ok": False, "error": "Auction lot not found."}, status=404)
    if len(request.body) > 2_000:
        return JsonResponse({"ok": False, "error": "Research request is too large."}, status=413)
    try:
        payload = json.loads(request.body or b"{}")
        if not isinstance(payload, dict):
            raise ValueError("Research request must be a JSON object.")
        subject_id = str(payload.get("subject_id") or "").strip()
        if len(subject_id) > 80:
            raise ValueError("Invalid LiveArt artwork ID.")
        raw_search_title = payload.get("search_title") or ""
        if not isinstance(raw_search_title, str) or len(raw_search_title.strip()) > 200:
            raise ValueError("Invalid LiveArt title variant.")
        search_title = raw_search_title.strip()
        search_terms = parse_search_terms(payload.get("search_terms", ""))
        if search_terms and subject_id:
            raise ValueError("Select sales directly from term search results; an artwork reference cannot be chosen for this search.")
        research = _research_liveart_lot(lot, subject_id=subject_id, search_title=search_title, search_terms=search_terms)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "Research request must be valid JSON."}, status=400)
    except LiveArtConfigurationError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=503)
    except LiveArtAPIError as exc:
        response = JsonResponse(
            {"ok": False, "error": str(exc)},
            status=exc.status_code if exc.status_code == 429 else 503,
        )
        if exc.status_code == 429 and exc.retry_after is not None:
            response["Retry-After"] = str(math.ceil(exc.retry_after))
        return response
    except ValueError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)

    research["search_category"] = {"id": PRINTS_AND_MULTIPLES_CATEGORY_ID, "label": PRINTS_AND_MULTIPLES_LABEL}
    research.setdefault("excluded_category_count", 0)
    research["research_id"] = secrets.token_hex(16)
    request.session[f"liveart_research_{lot.pk}"] = research
    existing = LiveArtResaleAnalysis.objects.filter(lot=lot).first()
    candidates = _merged_resale_candidates(lot, research.get("candidates"))
    selected_ids = list(research.get("selected_ids") or [])
    if existing is not None:
        selected_ids.extend(
            str(item) for item in existing.selected_ids if str(item).startswith("artprice:")
        )
    selected_ids = _selected_resale_ids(
        candidates, selected_ids,
        previous_candidates=existing.candidates if existing is not None else None,
        initialize_artprice=_initialize_legacy_artprice(existing),
    )
    response_research = {
        **research,
        "candidates": _candidates_with_selection(candidates, selected_ids),
        "selected_ids": selected_ids,
    }
    return JsonResponse({"ok": True, **response_research})


@never_cache
@staff_member_required
@require_http_methods(["GET", "POST"])
def auction_lot_liveart_analysis(request, lot_id: int):
    lot = AuctionWatchLot.objects.filter(pk=lot_id).first()
    if lot is None:
        return JsonResponse({"ok": False, "error": "Auction lot not found."}, status=404)
    existing = LiveArtResaleAnalysis.objects.filter(lot=lot).first()
    if request.method == "GET":
        return JsonResponse(
            {"ok": True, "analysis": _liveart_analysis_json(existing) if existing else _artprice_resale_preview(lot)}
        )
    if len(request.body) > 20_000:
        return JsonResponse({"ok": False, "error": "Analysis request is too large."}, status=413)
    try:
        payload = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "Analysis request must be valid JSON."}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({"ok": False, "error": "Analysis request must be a JSON object."}, status=400)
    action = str(payload.get("action") or "save").strip().casefold()
    if action == "delete":
        if existing:
            existing.delete()
        request.session.pop(f"liveart_research_{lot.pk}", None)
        return JsonResponse({"ok": True, "analysis": _artprice_resale_preview(lot), "message": "Resale bid analysis removed."})
    if action != "save":
        return JsonResponse({"ok": False, "error": "Choose a valid resale analysis action."}, status=400)
    research_id = str(payload.get("research_id") or "")
    research = request.session.get(f"liveart_research_{lot.pk}")
    if research_id and (not isinstance(research, dict) or research.get("research_id") != research_id):
        return JsonResponse(
            {"ok": False, "error": "This research was replaced in another tab. Find LiveArt comps again."}, status=409
        )
    if not research_id and existing is not None:
        research = {
            "subject_match": existing.subject_match or None,
            "subject_matches": existing.subject_matches,
            "candidates": existing.candidates,
            "retrieved_at": existing.retrieved_at.isoformat(),
            "data_units_spent": existing.data_units_spent,
            **_liveart_search_context(existing.search_context or {}),
        }
    if not research_id and not isinstance(research, dict) and AuctionMaxBidAnalysis.objects.filter(lot=lot).exists():
        research = {
            "subject_match": None,
            "subject_matches": [],
            "candidates": [],
            "retrieved_at": timezone.now().isoformat(),
            "data_units_spent": None,
        }
    if not isinstance(research, dict):
        return JsonResponse(
            {"ok": False, "error": "Find LiveArt comps or upload Artprice HTML before saving an analysis."}, status=400
        )
    candidates = _merged_resale_candidates(lot, research.get("candidates"))
    selected_ids = payload.get("selected_ids", [])
    assumptions = payload.get("assumptions", {})
    if not isinstance(candidates, list) or not isinstance(selected_ids, list) or not isinstance(assumptions, dict):
        return JsonResponse({"ok": False, "error": "Invalid resale analysis selections."}, status=400)
    if len(selected_ids) > MAX_SELECTED_RESALE_COMPS or any(not isinstance(item, (str, int)) for item in selected_ids):
        return JsonResponse({"ok": False, "error": "Invalid resale comp selection."}, status=400)
    selected_ids = list(dict.fromkeys(str(item) for item in selected_ids))
    allowed = {str(item.get("id")) for item in candidates if isinstance(item, dict) and item.get("credible")}
    if any(item not in allowed for item in selected_ids):
        return JsonResponse({"ok": False, "error": "Select only eligible sold USD hammer comps."}, status=400)
    candidates = _candidates_with_selection(candidates, selected_ids)
    try:
        normalized_assumptions, scenarios, source_summary = _lot_resale_scenarios(
            lot, candidates, selected_ids, assumptions
        )
    except ValueError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    retrieved_at = parse_datetime(str(research.get("retrieved_at") or "")) or timezone.now()
    if timezone.is_naive(retrieved_at):
        retrieved_at = timezone.make_aware(retrieved_at, datetime_timezone.utc)
    defaults = {
        "subject_match": research.get("subject_match") or {},
        "subject_matches": research.get("subject_matches") or [],
        "candidates": candidates,
        "selected_ids": selected_ids,
        "assumptions": normalized_assumptions,
        "scenarios": scenarios,
        "source_summary": source_summary,
        "search_context": _liveart_search_context(research),
        "retrieved_at": retrieved_at,
        "data_units_spent": research.get("data_units_spent"),
        "created_by": request.user,
    }
    analysis, _created = LiveArtResaleAnalysis.objects.update_or_create(lot=lot, defaults=defaults)
    request.session.pop(f"liveart_research_{lot.pk}", None)
    return JsonResponse(
        {"ok": True, "analysis": _liveart_analysis_json(analysis), "message": "Resale bid analysis saved."}
    )


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
    if any(ord(char) < 32 for char in candidate) or "\\" in candidate:
        return ""
    try:
        parsed = urlparse(candidate)
        if parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username and not parsed.password and parsed.port in (None, 80, 443):
            return candidate
    except ValueError:
        pass
    return ""


def _calendar_image_url(value) -> str:
    """Allow saved artwork or HTTPS auction hosts and their CDNs."""

    if is_saved_calendar_image_url(value):
        return value
    candidate = _url(value)
    parsed = urlparse(candidate)
    host = (parsed.hostname or "").casefold()
    if parsed.scheme != "https":
        return ""
    if any(host == domain or host.endswith(f".{domain}") for domain in CALENDAR_IMAGE_DOMAINS):
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
    try:
        body = request.body
    except RequestDataTooBig:
        return JsonResponse({"ok": False, "error": "Sync payload is too large."}, status=413)
    if len(body) > MAX_SYNC_BYTES:
        return JsonResponse({"ok": False, "error": "Sync payload is too large."}, status=413)

    try:
        payload = json.loads(body or b"{}")
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
    prepared_images = []
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
            saved_image = None
            if "saved_image_base64" in record:
                try:
                    saved_image = prepare_saved_calendar_image(record["saved_image_base64"])
                except ValueError as exc:
                    raise ValueError(f"lots[{index}].{exc}") from exc
            prepared_images.append(saved_image)
            prepared.append((source, source_lot_id, defaults, artist_name, normalized_artist_name))
    except ValueError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)

    created_count = 0
    updated_count = 0
    ended_count = 0
    # Every record has passed validation before either files or database rows change.
    try:
        for prepared_lot, saved_image in zip(prepared, prepared_images):
            if saved_image is not None:
                prepared_lot[2]["image_url"] = store_saved_calendar_image(saved_image)
    except OSError:
        return JsonResponse({"ok": False, "error": "Calendar image storage is unavailable. Please retry."}, status=503)
    with transaction.atomic():
        artists_by_key: dict[str, AuctionWatchArtist] = {}
        for normalized_name, (name, artprice_url) in prepared_artist_links.items():
            artist, _created = AuctionWatchArtist.objects.update_or_create(
                normalized_name=normalized_name,
                defaults={"name": name, "artprice_url": artprice_url},
            )
            artists_by_key[normalized_name] = artist

        for (source, source_lot_id, defaults, artist_name, normalized_artist_name), saved_image in zip(prepared, prepared_images):
            if normalized_artist_name:
                artist = artists_by_key.get(normalized_artist_name)
                if artist is None:
                    artist, _created = AuctionWatchArtist.objects.get_or_create(
                        normalized_name=normalized_artist_name,
                        defaults={"name": artist_name},
                    )
                    artists_by_key[normalized_artist_name] = artist
                defaults["watchlist_artist"] = artist
            if saved_image is None:
                existing_image = AuctionWatchLot.objects.select_for_update().filter(
                    source=source, source_lot_id=source_lot_id,
                ).values_list("image_url", flat=True).first()
                if is_saved_calendar_image_url(existing_image):
                    defaults.pop("image_url", None)
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
            "images_received": sum(image is not None for image in prepared_images),
        }
    )
