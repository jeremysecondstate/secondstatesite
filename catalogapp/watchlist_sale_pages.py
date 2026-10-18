"""Import saved Doyle and Phillips catalogs, including artists outside the watchlist."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from catalogapp.bookmark_watchlist import BookmarkEntry, source_for_url
from catalogapp.watchlist_adapters import adapter_for_url
from catalogapp.watchlist_cache import WatchlistCache
from catalogapp.watchlist_fetch import SourceAccessError
from catalogapp.watchlist_models import NormalizedLot, lot_within_horizon, parse_lot_datetime
from catalogapp.watchlist_service import WatchlistMetrics, WatchlistResult, _agenda_sort_key, _retain_missing_static_fields


def read_saved_sale_pages(
    paths: Iterable[str | Path], entry: BookmarkEntry,
) -> tuple[list[NormalizedLot], list[str]]:
    """Validate every selected file before returning public lots and sanitized images.

    A source timestamp (or file modification time) records snapshot observation;
    rereading an old saved page does not turn it into a fresh source check.
    """
    if entry.source not in {"Doyle", "Phillips"} or source_for_url(entry.url) != entry.source or not entry.is_sale:
        raise ValueError("Choose a bookmarked Doyle or Phillips sale before importing saved pages.")
    adapter = adapter_for_url(entry.url)
    if adapter is None:
        raise ValueError("The sale catalog adapter is unavailable.")
    from catalogapp.doyle import attach_saved_doyle_images
    from catalogapp.phillips import attach_saved_phillips_images

    attach_images = attach_saved_doyle_images if entry.source == "Doyle" else attach_saved_phillips_images
    selected = list(dict.fromkeys(Path(path) for path in paths))
    if not selected:
        raise ValueError("Choose at least one saved HTML catalog page.")
    observed: dict[str, NormalizedLot] = {}
    notices: list[str] = []
    totals: set[int] = set()
    for path in selected:
        if path.suffix.casefold() not in {".html", ".htm"} or path.stat().st_size > 32 * 1024 * 1024:
            raise ValueError(f"Choose saved HTML catalogs under 32 MiB: {path.name}")
        page = path.read_text(encoding="utf-8-sig", errors="replace")
        try:
            lots = adapter.parse_search_page(page, entry.url, "")
        except SourceAccessError as exc:
            raise ValueError(f"{path.name}: {exc}") from exc
        if not lots:
            raise ValueError(f"{path.name} contains no readable {entry.source} lots for the selected sale.")
        if any(lot.source != entry.source or not lot.relevant_at for lot in lots):
            raise ValueError(f"{path.name} contains a lot without a verified sale identity or date.")
        notices.extend(attach_images(page, path, lots))
        total = adapter.catalog_total(page)
        if total:
            totals.add(total)
        file_stamp = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        source_stamp = getattr(adapter, "snapshot_observed_at", lambda _page: None)(page)
        stamp = min(source_stamp, file_stamp).isoformat() if source_stamp else file_stamp.isoformat()
        for lot in lots:
            lot.first_seen_at = lot.last_seen_at = stamp
            lot.status = "unchanged"
            old = observed.get(lot.cache_key)
            if old is None or stamp >= old.last_seen_at:
                observed[lot.cache_key] = lot
    if totals and len(observed) < max(totals):
        notices.append(f"Imported {len(observed)} of {max(totals)} advertised {entry.source} lots; save the remaining catalog pages to include them.")
    notices.append("Saved catalogs retain their source timestamp or file modification time; missing lots are never marked ended.")
    return sorted(observed.values(), key=_agenda_sort_key), list(dict.fromkeys(notices))


def import_saved_sale_pages(
    paths: Iterable[str | Path], entry: BookmarkEntry, cache: WatchlistCache, *,
    now: datetime | None = None, horizon_days: int = 7, new_changed_only: bool = False,
) -> WatchlistResult:
    """Merge a validated snapshot into the existing local sale membership."""
    observed, notices = read_saved_sale_pages(paths, entry)
    current = now or datetime.now(timezone.utc)
    metrics = WatchlistMetrics(bookmark_urls=1, artists=len({lot.artist for lot in observed}))
    combined = {lot.cache_key: lot for lot in cache.active_lots_for_watch_url(entry.url)}
    fallback_keys = set(combined).difference(lot.cache_key for lot in observed)
    for key in fallback_keys:
        combined[key].status = "unchanged"
    metrics.cache_hits = len(fallback_keys)
    for lot in observed:
        previous = cache.lookup(lot)
        stamp, _ = parse_lot_datetime(lot.last_seen_at)
        if previous:
            previous_stamp, _ = parse_lot_datetime(previous.lot.last_seen_at)
            if previous_stamp and stamp and previous_stamp > stamp:
                combined[lot.cache_key] = previous.lot
                fallback_keys.add(lot.cache_key)
                metrics.cache_hits += 1
                continue
            _retain_missing_static_fields(lot, previous.lot)
        transition = cache.upsert(
            lot, watch_url=entry.url, search_hash=lot.calculate_content_hash(), observed_at=stamp,
        )
        setattr(metrics, f"{transition}_lots", getattr(metrics, f"{transition}_lots") + 1)
        combined[lot.cache_key] = lot
    lots = [lot for lot in combined.values() if lot_within_horizon(lot, current, horizon_days)]
    if new_changed_only:
        lots = [lot for lot in lots if lot.status in {"new", "changed"}]
    return WatchlistResult(
        lots=sorted(lots, key=_agenda_sort_key), metrics=metrics, notices=notices,
        fallback_lot_keys=fallback_keys,
    )
