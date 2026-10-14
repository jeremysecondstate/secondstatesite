"""Import posted Invaluable results from explicitly selected saved lot pages."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Iterable
from urllib.parse import urlsplit

from bs4 import BeautifulSoup, Comment

from catalogapp.bookmark_watchlist import BookmarkEntry, canonicalize_bookmark_url, source_for_url
from catalogapp.watchlist_adapters import InvaluableAdapter
from catalogapp.watchlist_cache import WatchlistCache
from catalogapp.watchlist_models import NormalizedLot
from catalogapp.watchlist_service import WatchlistMetrics, WatchlistResult, _agenda_sort_key


def _saved_lot_url(soup: BeautifulSoup) -> str:
    """Use page identity, excluding links and metadata for recommended lots."""

    def normalize(value: str) -> str:
        try:
            parts = urlsplit(value)
        except ValueError:
            return ""
        if parts.username or parts.password:
            return ""
        return canonicalize_bookmark_url(value)

    canonical = soup.find("link", rel="canonical")
    if canonical:
        return normalize(str(canonical.get("href", "")))
    social = soup.find("meta", attrs={"property": "og:url"})
    if social:
        return normalize(str(social.get("content", "")))
    # Chrome/Edge saved HTML can retain the origin in its Mark of the Web.
    for comment in soup.find_all(string=lambda value: isinstance(value, Comment)):
        match = re.match(r"\s*saved from url=\(\d+\)(https?://\S+)", str(comment), re.I)
        if match:
            return normalize(match[1])
    return ""


def _lot_ref(url: str) -> str:
    match = re.search(r"-c-([a-z0-9]+)(?:/|$)", urlsplit(url).path, re.I)
    return match[1].casefold() if match else ""


def _matches_lot(existing: NormalizedLot, detail: NormalizedLot, page_url: str) -> bool:
    if existing.lot_url == page_url:
        return True
    page_ref, existing_ref = _lot_ref(page_url), _lot_ref(existing.lot_url)
    if page_ref and existing_ref:
        # A title slug may change; Invaluable's source lot reference does not.
        return page_ref == existing_ref
    return bool(detail.source_lot_id and existing.source_lot_id == detail.source_lot_id)


def import_saved_sold_pages(
    paths: Iterable[str | Path],
    *,
    entries: Iterable[BookmarkEntry],
    cache: WatchlistCache,
    now: datetime | None = None,
) -> WatchlistResult:
    """Apply explicit sold prices to previously watched, selected cached lots.

    Files stay local. No browser session, URL fetch, AI enrichment, raw HTML, or
    companion asset is retained. Only the posted price and currency can change;
    cached identity, artist, estimate, bid, dates, and artwork remain intact.
    Invalid, gated, and unmatched pages leave their cached records unchanged.
    """

    chosen = [entry for entry in entries if entry.source == "Invaluable" and source_for_url(entry.url) == "Invaluable"]
    if not chosen:
        raise ValueError("Select at least one bookmarked Invaluable artist before importing sold results.")
    selected_paths = list(dict.fromkeys(Path(path) for path in paths))
    if not selected_paths:
        raise ValueError("Choose at least one saved Invaluable HTML lot page.")

    metrics = WatchlistMetrics(bookmark_urls=len(chosen), artists=len({entry.watch_label.casefold() for entry in chosen}))
    selected_lots: dict[str, NormalizedLot] = {}
    memberships: dict[str, set[str]] = {}
    for entry in chosen:
        for lot in cache.lots_for_watch_url(entry.url):
            if lot.source != "Invaluable":
                continue
            selected_lots[lot.cache_key] = lot
            memberships.setdefault(lot.cache_key, set()).add(entry.url)

    adapter = InvaluableAdapter()
    updates: dict[str, NormalizedLot] = {}
    notices: list[str] = []
    errors: list[str] = []
    for path in selected_paths:
        if path.suffix.casefold() not in {".html", ".htm"}:
            errors.append(f"{path.name}: choose an HTML file saved from an Invaluable lot page.")
            continue
        try:
            page = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            errors.append(f"{path.name}: the saved page could not be read.")
            continue
        soup = BeautifulSoup(page, "html.parser")
        page_url = _saved_lot_url(soup)
        parts = urlsplit(page_url)
        if (
            not page_url or parts.scheme not in {"http", "https"}
            or parts.username or parts.password or source_for_url(page_url) != "Invaluable"
            or not adapter._lot_href.search(parts.path)
        ):
            notices.append(f"{path.name}: no verified Invaluable lot-page address was found; no result was imported.")
            continue
        detail = adapter.parse_lot_detail(page, page_url, "")
        if detail is None or detail.sold_price is None:
            notices.append(
                f"{path.name}: no posted Sold price was visible. Save the lot page from your signed-in browser with its Sold amount visible."
            )
            continue
        matches = [lot for lot in selected_lots.values() if _matches_lot(lot, detail, page_url)]
        if len(matches) != 1:
            reason = "it does not match a previously watched lot for the selected artists" if not matches else "its watched lot identity is ambiguous"
            notices.append(f"{path.name}: {reason}; no result was imported.")
            continue
        existing = matches[0]
        if existing.cache_key in updates:
            previous = updates[existing.cache_key]
            if (previous.sold_price, previous.sold_currency) != (detail.sold_price, detail.sold_currency or existing.currency):
                errors.append(f"{path.name}: selected pages contain conflicting results for lot {existing.lot_number or existing.source_lot_id}; that lot was left unchanged.")
                updates.pop(existing.cache_key)
                selected_lots.pop(existing.cache_key)
            continue
        imported = NormalizedLot.from_dict(existing.to_dict())
        imported.sold_price = detail.sold_price
        imported.sold_currency = detail.sold_currency or existing.currency
        imported.content_hash = imported.calculate_content_hash()
        updates[imported.cache_key] = imported

    observed_at = now or datetime.now(timezone.utc)
    for lot in updates.values():
        lookup = cache.lookup(lot)
        # Each selected membership already exists. An import cannot attach a
        # saved page to a new artist bookmark or reactivate a sold lot.
        transitions = [
            cache.upsert(lot, watch_url=watch_url, search_hash=lookup.search_hash if lookup else "", observed_at=observed_at, active=False)
            for watch_url in sorted(memberships[lot.cache_key])
        ]
        if "changed" in transitions:
            metrics.changed_lots += 1
            lot.status = "changed"
            cache.update_payload(lot)
        else:
            metrics.unchanged_lots += 1
        metrics.cache_hits += 1
    lots = sorted(updates.values(), key=_agenda_sort_key)
    return WatchlistResult(lots=lots, metrics=metrics, errors=errors, notices=notices)
