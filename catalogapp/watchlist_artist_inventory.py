"""Reconcile bookmark artists with local lots and the website's inventory.

This module only combines supplied data. Scanning a bookmark file is separate
from requesting an artist's auction results or uploading lots to the Calendar.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone

from catalogapp.artprice_artist_links import artist_identity_key
from catalogapp.bookmark_watchlist import BookmarkEntry, canonicalize_bookmark_url
from catalogapp.watchlist_coverage import WatchCoverage
from catalogapp.watchlist_models import NormalizedLot


@dataclass(frozen=True, slots=True)
class ArtistInventoryRow:
    artist: str
    source: str
    local_count: int
    # Calendar counts cover all stored records, not the desktop look-ahead.
    # None means the Calendar inventory has not been successfully read.
    calendar_count: int | None
    upcoming_count: int | None
    status: str
    syncable: bool
    watch_urls: tuple[str, ...] = ()
    last_synced_at: str = ""


def _value(record: object, name: str, default=""):
    return record.get(name, default) if isinstance(record, Mapping) else getattr(record, name, default)


def _identity(artist: str, source: str) -> tuple[str, str]:
    return artist_identity_key(artist), source.strip().casefold()


def _when(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=timezone.utc)


def artist_inventory_rows(
    entries: Iterable[BookmarkEntry],
    current_lots: Iterable[NormalizedLot],
    coverage: Iterable[WatchCoverage],
    calendar_inventory: Iterable[object] | None = None,
) -> list[ArtistInventoryRow]:
    """Build one row per exact normalized artist and source, including new artists.

    Pass only the bookmark folders the user wants to scan. Artist labels come
    from parsed bookmark URLs, so a misspelling in a bookmark title cannot create
    a second artist. Name matching is deterministic, never fuzzy. Calendar-only
    rows have no source search URL and cannot be synced until one is supplied.

    An unavailable Calendar inventory is ``None``; an empty successful inventory
    is ``[]``. Local lots count only the supplied local view, while Calendar
    counts retain the server's full stored-record and upcoming-record totals.
    """
    groups: dict[tuple[str, str], dict] = {}
    for entry in entries:
        artist = entry.watch_label.strip()
        key = _identity(artist, entry.source)
        if not key[0]:
            continue
        group = groups.setdefault(key, {
            "artist": artist, "source": entry.source.strip(), "urls": set(),
        })
        url = canonicalize_bookmark_url(entry.url)
        if url:
            group["urls"].add(url)

    calendar_totals: dict[tuple[str, str], dict] = {}
    seen_inventory: set[tuple] = set()
    for record in calendar_inventory if calendar_inventory is not None else ():
        artist = str(_value(record, "name") or _value(record, "normalized_name")).strip()
        source = str(_value(record, "source")).strip()
        key = _identity(artist, source)
        if not key[0]:
            continue
        count = int(_value(record, "lot_count", 0))
        upcoming = int(_value(record, "upcoming_count", 0))
        synced = str(_value(record, "last_synced_at") or "")
        fingerprint = (artist, source.casefold(), count, upcoming, synced)
        if fingerprint in seen_inventory:
            continue
        seen_inventory.add(fingerprint)
        total = calendar_totals.setdefault(key, {
            "artist": artist, "source": source, "count": 0, "upcoming": 0, "synced": "",
        })
        total["count"] += count
        total["upcoming"] += upcoming
        if _when(synced) > _when(total["synced"]):
            total["synced"] = synced

    sourced_artists = {key[0] for key in (*groups, *calendar_totals) if key[1]}
    for key, total in calendar_totals.items():
        # Stored artist links can exist before their first lot. They do not add
        # an extra blank-source row beside an artist's actual auction sources.
        if not key[1] and not total["count"] and key[0] in sourced_artists:
            continue
        groups.setdefault(key, {"artist": total["artist"], "source": total["source"], "urls": set()})

    local_keys: dict[tuple[str, str], set[str]] = {}
    for lot in current_lots:
        key = _identity(lot.artist_watchlist_name or lot.artist, lot.source)
        local_keys.setdefault(key, set()).add(lot.cache_key)

    # Keep the most recent check for each catalog URL. A recent successful check
    # of one URL does not erase a blocked or unchecked second URL for the artist.
    latest_checks: dict[tuple[tuple[str, str], str], tuple[datetime, int, str]] = {}
    for index, check in enumerate(coverage):
        key = _identity(check.artist, check.source)
        url = canonicalize_bookmark_url(check.watch_url) or check.watch_url
        state = check.state if check.state in {"verified", "empty", "partial", "blocked", "pending"} else "pending"
        candidate = (_when(check.checked_at), index, state)
        previous = latest_checks.get((key, url))
        if previous is None or candidate[:2] > previous[:2]:
            latest_checks[(key, url)] = candidate

    rows = []
    for key, group in groups.items():
        urls = tuple(sorted(group["urls"]))
        if urls:
            states = [latest_checks.get((key, url), (None, 0, "pending"))[2] for url in urls]
            status = next((state for state in ("blocked", "partial", "pending") if state in states), "")
            if not status:
                status = "empty" if all(state == "empty" for state in states) else "verified"
        else:
            status = "calendar_only"
        total = calendar_totals.get(key)
        rows.append(ArtistInventoryRow(
            artist=group["artist"], source=group["source"], local_count=len(local_keys.get(key, ())),
            calendar_count=(total["count"] if total else 0) if calendar_inventory is not None else None,
            upcoming_count=(total["upcoming"] if total else 0) if calendar_inventory is not None else None,
            status=status, syncable=bool(urls), watch_urls=urls,
            last_synced_at=total["synced"] if total else "",
        ))
    return sorted(rows, key=lambda row: (
        not (row.syncable and row.status == "pending" and not row.local_count and row.calendar_count in (None, 0)),
        row.artist.casefold(), row.source.casefold(),
    ))
