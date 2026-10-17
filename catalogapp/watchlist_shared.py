"""Portable watchlist data shared through the authenticated Calendar service.

Only curated public links, normalized auction records and dated source-check
evidence cross machines. Browser profiles, credentials and local paths do not.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
from pathlib import Path
from typing import Iterable, Mapping
from urllib.parse import parse_qsl, urlsplit

import requests

from catalogapp.artprice_artist_links import artist_identity_key
from catalogapp.bookmark_watchlist import BookmarkEntry, canonicalize_bookmark_url, source_for_url
from catalogapp.watchlist_cache import WatchlistCache
from catalogapp.watchlist_coverage import WatchCoverage
from catalogapp.watchlist_models import NormalizedLot, parse_lot_datetime
from catalogapp.watchlist_registry import _entry, _normalize, save_watchlist
from catalogapp.watchlist_sync import CalendarSyncError, _validated_base_url


_PRIVATE_QUERY_KEYS = {
    "token", "access_token", "refresh_token", "api_key", "apikey", "authorization",
    "password", "session", "sessionid", "cookie", "email", "auth", "jwt",
}


def _public_watch(entry: BookmarkEntry) -> bool:
    return not any(key.casefold() in _PRIVATE_QUERY_KEYS
                   for key, _ in parse_qsl(urlsplit(entry.url).query, keep_blank_values=True))


@dataclass(slots=True)
class SharedWatchlistSnapshot:
    entries: list[BookmarkEntry] = field(default_factory=list)
    artist_artprice_links: dict[str, str] = field(default_factory=dict)
    coverage: list[WatchCoverage] = field(default_factory=list)
    lots: list[NormalizedLot] = field(default_factory=list)
    enabled_watch_urls: frozenset[str] = frozenset()
    calendar_lot_keys: frozenset[str] = frozenset()


def _date(value: object, *, required: bool = False) -> str:
    if not isinstance(value, str) or len(value) > 80:
        raise ValueError("Invalid observation date")
    if value:
        parsed, _ = parse_lot_datetime(value)
        if parsed is None:
            raise ValueError("Invalid observation date")
    elif required:
        raise ValueError("Missing observation date")
    return value


def _public_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        return bool(parsed.scheme in {"http", "https"} and parsed.hostname
                    and not parsed.username and not parsed.password
                    and parsed.port in {None, 80, 443}
                    and "\\" not in value and not any(ord(char) < 32 for char in value))
    except ValueError:
        return False


def _lot(record: object) -> NormalizedLot:
    if not isinstance(record, dict):
        raise ValueError("Invalid Calendar lot")
    string_fields = {
        "source", "source_lot_id", "artist", "artist_watchlist_name", "title", "medium", "auction_house",
        "sale_title", "lot_number", "start_at", "end_at", "location", "currency", "sold_currency",
        "lot_url", "sale_url", "image_url", "first_seen_at", "last_seen_at", "status",
    }
    values = {}
    for name in string_fields:
        value = record.get(name, "unchanged" if name == "status" else "")
        if not isinstance(value, str) or len(value) > 20000 or "\x00" in value:
            raise ValueError("Invalid Calendar lot field")
        values[name] = value
    if not values["source"] or not (values["source_lot_id"] or values["lot_url"]):
        raise ValueError("Missing Calendar lot identity")
    if values["status"] not in {"new", "changed", "unchanged", "ended"}:
        raise ValueError("Invalid Calendar lot state")
    for name in ("start_at", "end_at", "first_seen_at", "last_seen_at"):
        _date(values[name])
    if values["lot_url"] and (not _public_url(values["lot_url"])
                              or source_for_url(values["lot_url"]).casefold() != values["source"].casefold()):
        raise ValueError("Invalid auction lot URL")
    for name in ("sale_url", "image_url"):
        if values[name] and not _public_url(values[name]):
            raise ValueError("Invalid public auction URL")
    for name in ("estimate_low", "estimate_high", "current_bid", "sold_price"):
        value = record.get(name)
        if value is not None and (type(value) not in {int, float} or not math.isfinite(value) or value < 0):
            raise ValueError("Invalid Calendar amount")
        values[name] = value
    bids = record.get("bid_count")
    if bids is not None and (type(bids) is not int or bids < 0):
        raise ValueError("Invalid Calendar bid count")
    values["bid_count"] = bids
    # Ignore unknown and local-only fields, including hashes, cached pixels,
    # filesystem locations and enrichment metadata.
    return NormalizedLot(**values)


def _coverage(record: object, entries: Mapping[str, BookmarkEntry]) -> WatchCoverage:
    if not isinstance(record, dict) or not isinstance(record.get("watch_url"), str):
        raise ValueError("Invalid shared source check")
    url = canonicalize_bookmark_url(record["watch_url"])
    entry = entries.get(url)
    if entry is None:
        raise ValueError("Source check does not match a shared watch")
    state = record.get("state", "pending")
    if state not in {"verified", "empty", "partial", "blocked", "pending"}:
        raise ValueError("Invalid shared source-check state")
    checked = _date(record.get("checked_at", ""), required=state != "pending")
    until = _date(record.get("covered_until", ""))
    detail = record.get("detail", "")
    if not isinstance(detail, str) or len(detail) > 2000:
        raise ValueError("Invalid shared source-check detail")
    return WatchCoverage(entry.watch_label, entry.source, entry.url, state=state,
                         checked_at=checked, detail=detail, covered_until=until)


def _metadata(payload: object) -> SharedWatchlistSnapshot:
    if not isinstance(payload, dict) or payload.get("ok") is not True or payload.get("version") != 1:
        raise ValueError("Invalid shared watchlist response")
    records = payload.get("entries")
    if not isinstance(records, list) or len(records) > 10000:
        raise ValueError("Invalid shared entries")
    entries, enabled = {}, set()
    for record in records:
        entry = _entry(record)
        if (entry is None or not _public_watch(entry) or type(record.get("enabled", True)) is not bool
                or entry.url in entries):
            raise ValueError("Invalid shared entry")
        entries[entry.url] = entry
        if record.get("enabled", True):
            enabled.add(entry.url)
    raw_links = payload.get("artist_artprice_links", {})
    if not isinstance(raw_links, dict):
        raise ValueError("Invalid shared research links")
    _, links = _normalize(entries.values(), raw_links)
    if links != raw_links:
        raise ValueError("Invalid shared research link")
    checks = payload.get("coverage", [])
    if not isinstance(checks, list) or len(checks) > len(entries):
        raise ValueError("Invalid shared source checks")
    coverage = [_coverage(item, entries) for item in checks]
    if len({item.watch_url for item in coverage}) != len(coverage):
        raise ValueError("Duplicate shared source check")
    keys = payload.get("calendar_lot_keys")
    if not isinstance(keys, list) or len(keys) > 100000:
        raise ValueError("Missing Calendar lot identities")
    for key in keys:
        if (not isinstance(key, str) or len(key) > 10000 or "\x00" in key or ":" not in key
                or not key.split(":", 1)[0] or len(key.split(":", 1)[0]) > 80
                or key.split(":", 1)[0] != key.split(":", 1)[0].casefold()
                or not key.split(":", 1)[1]):
            raise ValueError("Invalid Calendar lot identity")
    if len(set(keys)) != len(keys):
        raise ValueError("Duplicate Calendar lot identity")
    return SharedWatchlistSnapshot(list(entries.values()), links, coverage,
                                   enabled_watch_urls=frozenset(enabled), calendar_lot_keys=frozenset(keys))


def fetch_shared_watchlist(
    *, base_url: str, api_key: str, horizon_days: int = 7,
    session=requests, timeout: tuple[int, int] = (10, 60),
) -> SharedWatchlistSnapshot:
    """Read shared artists and Calendar lots; never request auction-source pages."""
    if not api_key:
        raise CalendarSyncError("CATALOG_API_KEY is required to load your shared Calendar.")
    if horizon_days not in {3, 7}:
        raise CalendarSyncError("Shared Calendar supports a three- or seven-day window.")
    endpoint = f"{_validated_base_url(base_url)}/calendar/watchlist/"
    cursors, seen_lots = set(), set()
    cursor = None
    snapshot = None
    lots = []
    while True:
        try:
            response = session.get(endpoint, params={"cursor": cursor or "0", "page_size": 500, "horizon_days": horizon_days},
                                   headers={"X-API-KEY": api_key, "Accept": "application/json"},
                                   timeout=timeout, allow_redirects=False)
        except requests.RequestException as exc:
            raise CalendarSyncError("Could not load the shared Calendar. Your saved local data is still available.") from exc
        if response.status_code == 404:
            raise CalendarSyncError("Deploy the shared watchlist update to load Calendar data on this PC.")
        if response.status_code != 200:
            raise CalendarSyncError(f"Shared Calendar returned HTTP {response.status_code}.")
        try:
            payload = response.json()
            page = _metadata(payload)
            if snapshot is None:
                snapshot = page
            else:
                snapshot.calendar_lot_keys = snapshot.calendar_lot_keys | page.calendar_lot_keys
            records = payload.get("lots")
            if not isinstance(records, list) or len(records) > 500:
                raise ValueError("Invalid Calendar lot page")
            for record in records:
                lot = _lot(record)
                if lot.cache_key in seen_lots:
                    raise ValueError("Duplicate Calendar lot")
                seen_lots.add(lot.cache_key)
                lots.append(lot)
            if len(lots) > 100000:
                raise ValueError("Shared Calendar is too large")
            cursor = payload.get("next_cursor")
            if cursor is None:
                break
            if (not isinstance(cursor, str) or not cursor.isdecimal() or len(cursor) > 30
                    or cursor in cursors or not records):
                raise ValueError("Invalid Calendar page cursor")
            cursors.add(cursor)
        except (TypeError, ValueError, OverflowError) as exc:
            raise CalendarSyncError("The website returned invalid shared Calendar data. Local data was not changed.") from exc
    if not seen_lots.issubset(snapshot.calendar_lot_keys):
        raise CalendarSyncError("The website returned an incomplete Calendar lot inventory. Local data was not changed.")
    snapshot.lots = lots
    return snapshot


def publish_shared_watchlist(
    entries: Iterable[BookmarkEntry], *, base_url: str, api_key: str,
    artist_artprice_links: Mapping[str, str] | None = None,
    coverage: Iterable[WatchCoverage] = (), enabled_watch_urls: Iterable[str] | None = None,
    session=requests, timeout: tuple[int, int] = (10, 60),
) -> int:
    """Add curated watches and real source checks without removing other PCs' watches."""
    if not api_key:
        raise CalendarSyncError("CATALOG_API_KEY is required to share your artist watchlist.")
    normalized, links = _normalize(entries, dict(artist_artprice_links or {}))
    if any(not _public_watch(entry) for entry in normalized):
        raise CalendarSyncError("Only public artist bookmark URLs can be shared; remove private access parameters.")
    if len(normalized) > 10000:
        raise CalendarSyncError("Too many artists for one shared watchlist.")
    known = {entry.url: entry for entry in normalized}
    enabled = set(known) if enabled_watch_urls is None else set(enabled_watch_urls)
    records = [{**asdict(entry), "enabled": entry.url in enabled} for entry in normalized]
    # Pending entries with no source check are useful as configuration, but
    # cannot overwrite a successful check published by another machine.
    checks = []
    for check in coverage:
        if check.watch_url not in known or not check.checked_at:
            continue
        validated = _coverage(asdict(check), known)
        checks.append({name: getattr(validated, name) for name in (
            "artist", "source", "watch_url", "state", "checked_at", "covered_until",
        )})
    endpoint = f"{_validated_base_url(base_url)}/calendar/watchlist/"
    try:
        response = session.post(endpoint, headers={"X-API-KEY": api_key, "Accept": "application/json"},
                                json={"entries": records, "artist_artprice_links": links, "coverage": checks},
                                timeout=timeout, allow_redirects=False)
    except requests.RequestException as exc:
        raise CalendarSyncError("Could not share your artist watchlist. Your local artists remain saved.") from exc
    if response.status_code != 200:
        raise CalendarSyncError(f"Sharing the artist watchlist returned HTTP {response.status_code}.")
    try:
        payload = response.json()
        received = payload.get("entries_received")
        if payload.get("ok") is not True or type(received) is not int or received != len(normalized):
            raise ValueError("Incomplete shared watchlist confirmation")
    except (AttributeError, TypeError, ValueError) as exc:
        raise CalendarSyncError("The website did not confirm your shared artist watchlist.") from exc
    return received


def merge_shared_watchlist(
    snapshot: SharedWatchlistSnapshot, *, cache: WatchlistCache,
    entries: Iterable[BookmarkEntry] = (), artist_artprice_links: Mapping[str, str] | None = None,
    registry_path: str | Path | None = None,
) -> SharedWatchlistSnapshot:
    """Add shared records while keeping local watches and newer local observations."""
    local_entries, local_links = _normalize(entries, dict(artist_artprice_links or {}))
    merged = {entry.url: entry for entry in snapshot.entries}
    merged.update({entry.url: entry for entry in local_entries})
    links = {**snapshot.artist_artprice_links, **local_links}
    memberships: dict[tuple[str, str], list[str]] = {}
    sales = {}
    for entry in merged.values():
        if entry.is_sale:
            sales[entry.url] = entry
        else:
            memberships.setdefault((artist_identity_key(entry.artist or entry.title), entry.source.casefold()), []).append(entry.url)
    restored = []
    for lot in snapshot.lots:
        identity = (artist_identity_key(lot.artist_watchlist_name or lot.artist), lot.source.casefold())
        urls = list(memberships.get(identity, ()))
        sale_entry = sales.get(lot.sale_url)
        if sale_entry is not None and sale_entry.source.casefold() == lot.source.casefold():
            urls.append(sale_entry.url)
        if urls:
            cache.import_shared_lot(lot, watch_urls=urls)
            restored.append(cache.get(lot.cache_key))
    for check in snapshot.coverage:
        if check.watch_url in merged:
            cache.import_shared_coverage(check)
    if registry_path is not None:
        save_watchlist(registry_path, merged.values(), links)
    shared_urls = {entry.url for entry in snapshot.entries}
    enabled = snapshot.enabled_watch_urls | {entry.url for entry in local_entries if entry.url not in shared_urls}
    return SharedWatchlistSnapshot(list(merged.values()), links, snapshot.coverage, restored,
                                   frozenset(enabled), snapshot.calendar_lot_keys)
