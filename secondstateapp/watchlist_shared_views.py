"""Authenticated, source-free transfer of public watchlist state between PCs."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, time, timedelta
import json
from urllib.parse import parse_qsl, urlsplit

from django.core.exceptions import RequestDataTooBig
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from catalogapp.artprice_artist_links import artist_identity_key
from catalogapp.bookmark_watchlist import canonicalize_bookmark_url
from catalogapp.watchlist_models import NormalizedLot
from catalogapp.watchlist_registry import _entry

from .calendar_views import _calendar_zone, _sync_authorized, _validated_artist_artprice_url
from .models import AuctionWatchArtist, AuctionWatchLot, SharedArtistWatchlist


MAX_SHARED_BYTES = 2_000_000
MAX_SHARED_ENTRIES = 2000
PAGE_SIZE = 500
_PRIVATE_QUERY_KEYS = {
    "token", "access_token", "refresh_token", "api_key", "apikey", "authorization",
    "password", "session", "sessionid", "cookie", "email", "auth", "jwt",
}


def _public_url(value: str) -> bool:
    return not any(
        key.casefold() in _PRIVATE_QUERY_KEYS
        for key, _value in parse_qsl(urlsplit(value).query, keep_blank_values=True)
    )


def _timestamp(value, field: str, *, optional: bool = False) -> str:
    if optional and value in (None, ""):
        return ""
    parsed = parse_datetime(value) if isinstance(value, str) else None
    if parsed is None or timezone.is_naive(parsed):
        raise ValueError(f"{field} must be an ISO timestamp with a time zone.")
    return parsed.isoformat()


def _prepare(payload: object) -> tuple[list[dict], dict[str, str], list[dict]]:
    if not isinstance(payload, dict) or payload.get("version", 1) != 1:
        raise ValueError("Request must be a version 1 watchlist object.")
    raw_entries = payload.get("entries", [])
    raw_links = payload.get("artist_artprice_links", {})
    raw_coverage = payload.get("coverage", [])
    if not isinstance(raw_entries, list) or len(raw_entries) > MAX_SHARED_ENTRIES:
        raise ValueError(f"entries must be an array of at most {MAX_SHARED_ENTRIES} public bookmarks.")
    if not isinstance(raw_links, dict) or len(raw_links) > MAX_SHARED_ENTRIES:
        raise ValueError("artist_artprice_links must be an object of public artist links.")
    if not isinstance(raw_coverage, list) or len(raw_coverage) > MAX_SHARED_ENTRIES:
        raise ValueError("coverage must be an array of watch results.")
    entries = []
    for index, raw in enumerate(raw_entries):
        entry = _entry(raw)
        if entry is None or not _public_url(entry.url):
            raise ValueError(f"entries[{index}] must be a public auction bookmark.")
        enabled = raw.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError(f"entries[{index}].enabled must be a boolean.")
        # Only the curated BookmarkEntry schema is persisted, never browser or file settings.
        entries.append({**asdict(entry), "folder_path": list(entry.folder_path), "enabled": enabled})
    links = {}
    for name, value in raw_links.items():
        if not isinstance(name, str) or not name.strip() or len(name) > 255 or not isinstance(value, str):
            raise ValueError("Artist links must map artist names to public Artprice URLs.")
        url = _validated_artist_artprice_url(value)
        if not url or not _public_url(url):
            raise ValueError("Artist links must use public Artprice URLs.")
        links[name.strip()] = url
    coverage = []
    for index, row in enumerate(raw_coverage):
        if not isinstance(row, dict):
            raise ValueError(f"coverage[{index}] must be an object.")
        raw_url = row.get("watch_url")
        entry = _entry({"url": raw_url})
        if entry is None or not _public_url(entry.url):
            raise ValueError(f"coverage[{index}].watch_url must be a public auction bookmark.")
        state = row.get("state")
        if state not in {"verified", "empty", "partial", "blocked", "pending"}:
            raise ValueError(f"coverage[{index}].state is invalid.")
        # An unattempted local default must not erase another PC's actual check.
        checked_at = _timestamp(row.get("checked_at"), "checked_at", optional=True)
        covered_until = _timestamp(row.get("covered_until"), "covered_until", optional=True)
        if not checked_at:
            continue
        coverage.append({
            "watch_url": entry.url, "state": state,
            "checked_at": checked_at, "covered_until": covered_until,
        })
    return entries, links, coverage


def _calendar_lot_keys() -> list[str]:
    """Recognize the same published lot even when a fallback source ID changes."""
    keys = {}
    records = AuctionWatchLot.objects.filter(superseded_by__isnull=True).order_by("pk").values_list(
        "source", "source_lot_id", "lot_url",
    )
    for source, source_lot_id, lot_url in records:
        identities = [source_lot_id.strip()]
        try:
            identities.append(canonicalize_bookmark_url(lot_url))
        except ValueError:
            pass
        for identity in identities:
            if identity:
                keys.setdefault(f"{source.casefold()}:{identity}", None)
    return list(keys)


def _metadata(state: SharedArtistWatchlist | None) -> dict:
    entries = state.entries if state else []
    links = dict(state.artist_artprice_links) if state else {}
    # Website-edited artist links remain authoritative over stale desktop copies.
    names = {artist_identity_key(entry["artist"]): entry["artist"] for entry in entries if entry.get("artist")}
    for artist in AuctionWatchArtist.objects.filter(normalized_name__in=names).exclude(artprice_url=""):
        try:
            link = _validated_artist_artprice_url(artist.artprice_url)
        except ValueError:
            continue
        if _public_url(link):
            links[names[artist.normalized_name]] = link
    return {
        "ok": True, "version": 1, "entries": entries, "artist_artprice_links": links,
        "coverage": state.coverage if state else [],
        "calendar_lot_keys": _calendar_lot_keys(),
        "updated_at": state.updated_at.isoformat() if state else "",
    }


def _normalized_lot(lot: AuctionWatchLot, request) -> dict:
    event = ""
    if lot.event_at:
        event = (timezone.localtime(lot.event_at, _calendar_zone()).date().isoformat()
                 if lot.is_all_day else lot.event_at.isoformat())
    values = {
        name: getattr(lot, name)
        for name in (
            "source", "source_lot_id", "artist", "artist_watchlist_name", "title", "medium",
            "auction_house", "sale_title", "lot_number", "location", "currency", "bid_count",
            "sold_currency", "lot_url", "sale_url", "image_url",
        )
    }
    for name in ("estimate_low", "estimate_high", "current_bid", "sold_price"):
        value = getattr(lot, name)
        values[name] = float(value) if value is not None else None
    if values["image_url"].startswith("/"):
        values["image_url"] = request.build_absolute_uri(values["image_url"])
    values["title"] = values["title"] or "Untitled lot"
    status = lot.source_status if lot.source_status in {"new", "changed", "unchanged", "ended"} else "unchanged"
    values.update(
        end_at=event, status=status if lot.active else "ended",
        first_seen_at=lot.source_first_seen_at.isoformat() if lot.source_first_seen_at else "",
        last_seen_at=lot.source_last_seen_at.isoformat() if lot.source_last_seen_at else "",
    )
    return NormalizedLot(**values).to_dict()


@csrf_exempt
@never_cache
@require_http_methods(["GET", "POST"])
def shared_artist_watchlist(request):
    if not _sync_authorized(request):
        return JsonResponse({"ok": False, "error": "Unauthorized."}, status=401)
    if request.method == "GET":
        try:
            cursor = int(request.GET.get("cursor") or "0")
            page_size = int(request.GET.get("page_size", str(PAGE_SIZE)))
            horizon_days = int(request.GET.get("horizon_days", "7"))
            if (cursor < 0 or cursor > 2**63 - 1 or not 1 <= page_size <= PAGE_SIZE
                    or horizon_days not in {3, 7}):
                raise ValueError
        except ValueError:
            return JsonResponse({"ok": False, "error": "Invalid Calendar page cursor or page size."}, status=400)
        state = SharedArtistWatchlist.objects.filter(pk=1).first()
        zone = _calendar_zone()
        today = timezone.localdate(timezone=zone)
        start = datetime.combine(today - timedelta(days=7), time.min, tzinfo=zone)
        end = datetime.combine(today + timedelta(days=horizon_days + 1), time.min, tzinfo=zone)
        lots = list(AuctionWatchLot.objects.filter(superseded_by__isnull=True, pk__gt=cursor)
                    .filter(Q(event_at__isnull=True) | Q(event_at__gte=start, event_at__lt=end))
                    .order_by("pk")[:page_size + 1])
        result = _metadata(state)
        result["lots"] = [_normalized_lot(lot, request) for lot in lots[:page_size]]
        result["next_cursor"] = str(lots[page_size - 1].pk) if len(lots) > page_size else None
        return JsonResponse(result)
    try:
        body = request.body
    except RequestDataTooBig:
        return JsonResponse({"ok": False, "error": "Watchlist payload is too large."}, status=413)
    if len(body) > MAX_SHARED_BYTES:
        return JsonResponse({"ok": False, "error": "Watchlist payload is too large."}, status=413)
    try:
        entries, links, coverage = _prepare(json.loads(body or b"{}"))
    except (ValueError, UnicodeDecodeError) as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    with transaction.atomic():
        SharedArtistWatchlist.objects.get_or_create(pk=1)
        state = SharedArtistWatchlist.objects.select_for_update().get(pk=1)
        merged = {entry["url"]: entry for entry in state.entries}
        for entry in entries:
            # A stale or smaller PC can add bookmarks, but never erase or disable another's.
            merged.setdefault(entry["url"], entry)
        if len(merged) > MAX_SHARED_ENTRIES:
            return JsonResponse({"ok": False, "error": "The shared watchlist is full."}, status=400)
        names = {entry["artist"] for entry in merged.values() if entry.get("artist")}
        merged_links = dict(state.artist_artprice_links)
        for name, url in links.items():
            if name in names:
                merged_links.setdefault(name, url)
        merged_coverage = {row["watch_url"]: row for row in state.coverage}
        for row in coverage:
            entry = merged.get(row["watch_url"])
            if entry is None:
                continue
            current = merged_coverage.get(row["watch_url"])
            if current and parse_datetime(current["checked_at"]) >= parse_datetime(row["checked_at"]):
                continue
            merged_coverage[row["watch_url"]] = {
                **row, "artist": entry.get("artist", ""), "source": entry["source"],
            }
        state.entries = list(merged.values())
        state.artist_artprice_links = merged_links
        state.coverage = list(merged_coverage.values())
        state.save()
    return JsonResponse({**_metadata(state), "entries_received": len(entries), "lots": [], "next_cursor": None})
