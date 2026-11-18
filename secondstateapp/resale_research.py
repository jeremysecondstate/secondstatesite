"""Staff venue research and the public-copy selections it contributes to each proposal."""

import json
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import RequestDataTooBig, ValidationError
from django.core.validators import URLValidator
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from .calendar_images import is_saved_calendar_image_url, prepare_saved_calendar_image, store_saved_calendar_image
from .models import AuctionWatchLot, HouseProposalEntry, LotResaleResearch


PUBLIC_TEXT_FIELDS = {
    "artist": 255, "title": 500, "year_text": 80, "medium": 500, "dimensions": 500,
    "edition": 500, "object_notes": 4000, "description": 8000, "provenance": 4000,
    "literature": 4000, "condition": 4000,
}
_web_url = URLValidator(schemes=["https", "http"])


class StaleReport(ValueError):
    pass


def _text(row, field, maximum, required=False):
    value = row.get(field, "")
    label = field.replace("_", " ").capitalize()
    if not isinstance(value, str) or len(value.strip()) > maximum:
        raise ValueError(f"{label} must be text up to {maximum} characters.")
    value = value.strip()
    if "\x00" in value or any("\ud800" <= ch <= "\udfff" for ch in value):
        raise ValueError(f"{label} contains an invalid text character.")
    if required and not value:
        raise ValueError(f"Enter {label.lower()}.")
    return value


def _objects(row, field, maximum):
    items = row.get(field, [])
    if not isinstance(items, list) or len(items) > maximum or any(not isinstance(item, dict) for item in items):
        raise ValueError(f"{field.capitalize()} must contain up to {maximum} entries.")
    return items


def _url(value, *, image=False):
    if image and (not value or is_saved_calendar_image_url(value)):
        return value
    try:
        _web_url(value)
        parsed = urlsplit(value)
        if parsed.username is not None or parsed.password is not None or (image and parsed.scheme != "https"):
            raise ValueError
    except (ValidationError, ValueError):
        label = "an HTTPS image URL or a saved Calendar image" if image else "a valid public source URL"
        raise ValueError(f"Enter {label}.") from None
    return value


def _amount(value):
    try:
        price = Decimal(str(value))
        if not price.is_finite() or not 0 < price < Decimal("1e13") or price != price.quantize(Decimal(".01")):
            raise ValueError
    except (ValueError, InvalidOperation):
        raise ValueError("Enter a positive USD amount with up to two decimal places.") from None
    return price.quantize(Decimal(".01"))


def _range(row, low_key, high_key, required):
    values = (row.get(low_key), row.get(high_key))
    if not required and all(v in (None, "") for v in values):
        return None, None
    low, high = map(_amount, values)
    if high < low:
        raise ValueError("The high end of a range must be at least its low end.")
    return low, high


def _house(row):
    name = _text(row, "house", 255, required=True)
    key = slugify(name, allow_unicode=True)
    if not key or len(key) > 255:
        raise ValueError("Enter the auction house's name.")
    return name, key


def _venue(row, ready):
    house, key = _house(row)
    low, high = _range(row, "low_usd", "high_usd", ready)
    sources = []
    for source in _objects(row, "sources", 25):
        sources.append({
            "label": _text(source, "label", 250, True),
            "url": _url(_text(source, "url", 2000, True)),
            "note": _text(source, "note", 1500, True),
        })
    if not sources:
        raise ValueError(f"Add a supporting record for {house}.")
    return {
        "house": house, "house_key": key, "department": _text(row, "department", 250, True),
        "low_usd": str(low) if low is not None else None,
        "high_usd": str(high) if high is not None else None, "fit": _text(row, "fit", 4000, True),
        "basis": _text(row, "basis", 4000, True), "sources": sources,
    }


def _integer(value, low, high, label):
    if not str(value).isascii() or not str(value).isdigit() or not low <= int(value) <= high:
        raise ValueError(f"Enter a {label} from {low} to {high}.")
    return int(value)


def _proposal_key(row):
    _, house_key = _house(row)
    season = row.get("season")
    if season not in ("spring", "fall"):
        raise ValueError("Select Spring or Fall for the proposal.")
    return {
        "house_key": house_key, "season": season, "year": _integer(row.get("year"), 1900, 2200, "sale year"),
        "work_key": _text(row, "work_key", 80) or "lot",
    }


def _proposal_fields(row, key, lot, ready):
    if row.get("estimate_currency", "USD") != "USD":
        raise ValueError("Enter the proposal estimate in USD.")
    low, high = _range(row, "estimate_low", "estimate_high", ready)
    fields = {field: _text(row, field, limit) for field, limit in PUBLIC_TEXT_FIELDS.items()}
    if key["work_key"] == "lot":
        for field in ("artist", "title", "medium"):
            if not fields[field]:
                fields[field] = getattr(lot, field)
    if not fields["artist"] or not fields["title"] or not fields["description"]:
        raise ValueError("Each proposal work needs an artist or attribution, an identifying title and house-specific catalog text.")
    fields.update(
        house=_text(row, "house", 255, True), estimate_low=low, estimate_high=high, estimate_currency="USD",
        sort_order=_integer(row.get("sort_order", 0), 0, 1000000, "display order"),
        image_url=_url(_text(row, "image_url", 2000), image=True),
    )
    image = prepare_saved_calendar_image(row["image_base64"]) if row.get("image_base64") else None
    return fields, image


def resale_summary(lot):
    if lot._state.adding:
        return None
    report = getattr(lot, "resale_research", None)
    if report is None:
        return None
    return {
        "status": report.status, "resale_unit": report.resale_unit,
        "venues": [{k: row[k] for k in ("house", "low_usd", "high_usd")} for row in report.venues],
        "report_url": reverse("auction_lot_resale_report", args=[lot.pk]),
    }


def _entry_payload(entry):
    keys = ["id", "house", "season", "year", "work_key", "sort_order", "image_url", "estimate_low", "estimate_high", *PUBLIC_TEXT_FIELDS]
    return {key: getattr(entry, key) for key in keys}


def _report_payload(lot, entries):
    record = getattr(lot, "resale_research", None)
    return {
        "version": record.version if record else 0,
        "status": record.status if record else "ready",
        "summary": record.summary if record else "",
        "resale_unit": record.resale_unit if record else "",
        "venues": record.venues if record else [], "proposals": [_entry_payload(e) for e in entries],
    }


@transaction.atomic
def save_report(lot_id, payload, user):
    if not isinstance(payload, dict):
        raise ValueError("The report must be an object.")
    # All writers lock the same lot, including when its research does not yet exist.
    lot = get_object_or_404(AuctionWatchLot.objects.select_for_update(), pk=lot_id)
    previous = getattr(lot, "resale_research", None)
    if previous:
        payload = {
            "status": previous.status, "summary": previous.summary, "resale_unit": previous.resale_unit,
            "venues": previous.venues, **payload,
        }
    version = _integer(payload.get("version", 0), 0, 2147483647, "report version")
    status = payload.get("status")
    if status not in ("ready", "limited"):
        raise ValueError("Choose Ready or Limited evidence.")
    ready = status == "ready"
    venues = [_venue(row, ready) for row in _objects(payload, "venues", 5)]
    house_keys = {v["house_key"] for v in venues}
    if len(house_keys) != len(venues):
        raise ValueError("Choose distinct resale houses.")
    if ready and len(venues) < 3:
        raise ValueError("A ready report requires three to five supported resale houses.")
    report_fields = {
        "status": status, "summary": _text(payload, "summary", 8000, True),
        "resale_unit": _text(payload, "resale_unit", 200, True), "venues": venues,
    }
    removing = payload.get("remove_proposal_ids", [])
    if not isinstance(removing, list) or len(removing) > 100:
        raise ValueError("Provide up to 100 proposal entry IDs to remove.")
    removing = {_integer(value, 1, 9223372036854775807, "proposal entry ID") for value in removing}
    entries = {entry.pk: entry for entry in lot.proposal_entries.all()}
    persisted = {(e.house_key, e.season, e.year, e.work_key): e for e in entries.values()}
    changed = not previous or any(getattr(previous, k) != v for k, v in report_fields.items())
    seen = set()
    writes = []
    for row in _objects(payload, "proposals", 100):
        by_id = None
        if row.get("id") is not None:
            by_id = entries.get(_integer(row["id"], 1, 9223372036854775807, "proposal entry ID"))
            if not by_id:
                raise ValueError("This proposal entry does not belong to the lot. To add a copy, omit its ID.")
            row = {**_entry_payload(by_id), **row}
        key = _proposal_key(row)
        identity = (key["house_key"], key["season"], key["year"], key["work_key"])
        existing = persisted.get(identity)
        if by_id and by_id != existing:
            raise ValueError("To copy to a different house, work or season, omit the original proposal entry ID.")
        if identity in seen or (existing and existing.pk in removing):
            raise ValueError("Each work can appear once per house and season. Review duplicate or removed entries.")
        if not existing and key["house_key"] not in house_keys:
            raise ValueError("Select a researched house for each new proposal entry.")
        seen.add(identity)
        if existing and not by_id:
            row = {**_entry_payload(existing), **row}
        # A historical draft retained from a limited report may still have no
        # estimate. A later ready report can preserve that selection verbatim.
        require_range = ready and (not existing or existing.estimate_low is not None)
        fields, image = _proposal_fields(row, key, lot, require_range)
        if image:
            # Calculate the content address before writing, for idempotent retries.
            fields["image_url"] = f"/media/calendar-lots/{sha256(image).hexdigest()}.jpg"
        if not existing or any(getattr(existing, k) != v for k, v in fields.items()):
            writes.append((key, fields, image))
    removing &= entries.keys()
    if previous and not changed and not writes and not removing:
        return previous
    if version != (previous.version if previous else 0):
        raise StaleReport("This report changed after it was opened. Reload the latest version before saving your edits.")
    for key, fields, image in writes:
        if image:
            fields["image_url"] = store_saved_calendar_image(image)
        HouseProposalEntry.objects.update_or_create(lot=lot, **key, defaults=fields)
    if removing:
        lot.proposal_entries.filter(pk__in=removing).delete()
    record, _ = LotResaleResearch.objects.update_or_create(
        lot=lot, defaults={**report_fields, "version": version + 1, "updated_by": user},
    )
    return record


@never_cache
@staff_member_required
@require_http_methods(["GET", "POST"])
def auction_lot_resale_report(request, lot_id):
    if request.method == "POST":
        if request.content_type != "application/json":
            return JsonResponse({"ok": False, "error": "Save the report as JSON."}, status=415)
        try:
            payload = json.loads(request.body, parse_constant=_invalid_constant)
            if request.GET.get("upload") == "image":
                get_object_or_404(AuctionWatchLot, pk=lot_id)
                if not isinstance(payload, dict):
                    raise ValueError("Provide an artwork image.")
                content = prepare_saved_calendar_image(payload.get("image_base64"))
                return JsonResponse({"ok": True, "image_url": store_saved_calendar_image(content)})
            record = save_report(lot_id, payload, request.user)
        except RequestDataTooBig:
            return JsonResponse({"ok": False, "error": "This request is too large. Save fewer images at once."}, status=413)
        except StaleReport as exc:
            return JsonResponse({"ok": False, "error": str(exc)}, status=409)
        except (ValueError, UnicodeDecodeError) as exc:
            return JsonResponse({"ok": False, "error": str(exc)}, status=400)
        return JsonResponse({"ok": True, "version": record.version, "report_url": request.path})
    lot = get_object_or_404(AuctionWatchLot.objects.select_related("resale_research", "superseded_by"), pk=lot_id)
    entries = list(lot.proposal_entries.all())
    report = _report_payload(lot, entries)
    if request.GET.get("format") == "json":
        return JsonResponse({"ok": True, "lot_id": lot.pk, "report": report})
    group_urls = {}
    for entry in entries:
        season = f"{entry.season}-{entry.year}"
        group = group_urls.setdefault(entry.house_key, {})
        if season not in group:
            query = urlencode({"season": season, "house": entry.house_key, "work": entry.pk})
            group[season] = {
                "url": reverse("calendar_consignment_proposals") + "?" + query,
                "house": entry.house, "season": f"{entry.season.title()} {entry.year}",
            }
    for venue in report["venues"]:
        if venue["low_usd"] is None:
            venue["display_range"] = "Estimate unavailable"
        else:
            bounds = [format(Decimal(venue[key]), ",.2f").removesuffix(".00") for key in ("low_usd", "high_usd")]
            venue["display_range"] = f"${bounds[0]}–${bounds[1]}"
        venue["links"] = list(group_urls.pop(venue["house_key"], {}).values())
    gallery_url = reverse("auction_calendar")
    display_lot = lot.superseded_by or lot
    if display_lot.event_at:
        day = timezone.localtime(display_lot.event_at, ZoneInfo(settings.CALENDAR_TIME_ZONE)).date()
        params = {"view": "research", "look": "dossier", "day": day.isoformat(), "lot": lot.pk}
        if request.GET.get("scope") == "oliver":
            params["scope"] = "oliver"
        gallery_url += "?" + urlencode(params)
    return render(request, "calendar/resale_report.html", {
        "lot": lot, "report": report, "gallery_url": gallery_url,
        "other_proposals": [link for group in group_urls.values() for link in group.values()],
    })


def _invalid_constant(value):
    raise ValueError(f"Invalid JSON number: {value}.")
