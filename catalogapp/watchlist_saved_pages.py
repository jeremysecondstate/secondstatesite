"""Import explicitly selected Heritage catalog snapshots without fetching URLs."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Iterable
from urllib.parse import parse_qsl, urlsplit

from bs4 import BeautifulSoup

from catalogapp.bookmark_watchlist import BookmarkEntry, source_for_url
from catalogapp.watchlist_adapters import adapter_for_url
from catalogapp.watchlist_cache import WatchlistCache
from catalogapp.watchlist_fetch import SourceAccessError
from catalogapp.watchlist_images import attach_saved_heritage_images
from catalogapp.watchlist_models import NormalizedLot, lot_within_horizon
from catalogapp.watchlist_service import WatchlistMetrics, WatchlistResult, _agenda_sort_key


def _sale_numbers(url: str) -> set[str]:
    parts = urlsplit(url)
    numbers = {
        value.strip()
        for key, value in parse_qsl(parts.query)
        if key.casefold() in {"auction_name", "saleno"} and value.strip()
    }
    match = re.search(r"/a/(\d+)-\d+(?:[./]|$)", parts.path, re.IGNORECASE)
    if match:
        numbers.add(match.group(1))
    return numbers


def import_saved_heritage_pages(
    paths: Iterable[str | Path],
    entry: BookmarkEntry,
    cache: WatchlistCache,
    *,
    now: datetime | None = None,
    horizon_days: int = 7,
    new_changed_only: bool = False,
) -> WatchlistResult:
    """Add saved catalog pages to a bookmarked sale's local cache and agenda.

    Every file is parsed and checked before any cache writes. A saved page is
    always a partial snapshot: it cannot end lots missing from that page. Only
    normalized lot records are retained; raw HTML is neither cached nor sent to
    a service. No fetcher, browser session, or AI enrichment is used.
    """

    if entry.source != "Heritage" or source_for_url(entry.url) != "Heritage":
        raise ValueError("Choose a bookmarked Heritage sale before importing saved pages.")
    sale_numbers = _sale_numbers(entry.url)
    if len(sale_numbers) != 1 or not next(iter(sale_numbers)).isdigit():
        raise ValueError("The Heritage bookmark must identify one sale with auction_name or saleNo.")
    sale_number = next(iter(sale_numbers))
    adapter = adapter_for_url(entry.url)
    if adapter is None or adapter.source != "Heritage":
        raise ValueError("The Heritage catalog adapter is unavailable.")

    selected_paths = list(dict.fromkeys(Path(path) for path in paths))
    if not selected_paths:
        raise ValueError("Choose at least one saved Heritage HTML catalog page.")

    observed: dict[str, NormalizedLot] = {}
    advertised_totals: set[int] = set()
    image_notices: list[str] = []
    for path in selected_paths:
        if path.suffix.casefold() not in {".html", ".htm"}:
            raise ValueError(f"Choose HTML files saved from the Heritage catalog: {path.name}")
        page = path.read_text(encoding="utf-8-sig", errors="replace")
        total_node = BeautifulSoup(page, "html.parser").select_one(".number-bid-buy-results")
        if total_node:
            total = total_node.get_text(strip=True).replace(",", "")
            if total.isdigit():
                advertised_totals.add(int(total))
        try:
            cards = adapter.parse_search_page(page, entry.url, entry.artist)
        except SourceAccessError as exc:
            raise ValueError(f"{path.name}: {exc}") from exc
        if not cards:
            raise ValueError(
                f"{path.name} contains no readable lots for Heritage sale {sale_number}. "
                "Save the selected sale's results page with its lot cards visible."
            )
        for card in cards:
            # Check normalized identities too before attaching records to this watch.
            card_sales = _sale_numbers(card.lot_url) | _sale_numbers(card.sale_url)
            if card.source != "Heritage" or card_sales != {sale_number}:
                raise ValueError(f"{path.name} contains a lot outside Heritage sale {sale_number}.")
        image_notices.extend(attach_saved_heritage_images(page, path, cards))
        for card in cards:
            observed[card.cache_key] = card

    observed_at = now or datetime.now(timezone.utc)
    metrics = WatchlistMetrics(bookmark_urls=1, artists=1)
    combined: dict[str, NormalizedLot] = {}
    for lot in cache.active_lots_for_watch_url(entry.url):
        if lot.cache_key not in observed:
            # Preserve the last observation time and active membership. A new
            # import must not present an unobserved cached lot as newly found.
            lot.status = "unchanged"
            combined[lot.cache_key] = lot
            metrics.cache_hits += 1

    for card in observed.values():
        cached = cache.lookup(card)
        if cached and not card.saved_image_base64 and cached.lot.saved_image_base64:
            # A later HTML-only save should not discard an earlier good image.
            card.saved_image_base64 = cached.lot.saved_image_base64
            card.content_hash = card.calculate_content_hash()
        search_hash = card.content_hash
        lot = card
        if cached and cached.search_hash == search_hash:
            # Retain any richer detail fields obtained by an earlier refresh.
            lot = cached.lot
            lot.artist_watchlist_name = card.artist_watchlist_name
            if card.saved_image_base64:
                lot.saved_image_base64 = card.saved_image_base64
                lot.content_hash = lot.calculate_content_hash()
            metrics.cache_hits += 1
        transition = cache.upsert(
            lot, watch_url=entry.url, search_hash=search_hash, observed_at=observed_at
        )
        if transition == "new":
            metrics.new_lots += 1
        elif transition == "changed":
            metrics.changed_lots += 1
        else:
            metrics.unchanged_lots += 1
        combined[lot.cache_key] = lot

    lots = [lot for lot in combined.values() if lot_within_horizon(lot, observed_at, horizon_days)]
    if new_changed_only:
        lots = [lot for lot in lots if lot.status in {"new", "changed"}]
    lots.sort(key=_agenda_sort_key)
    notices: list[str] = []
    if advertised_totals and len(observed) < max(advertised_totals):
        notices.append(
            f"The selected files contain {len(observed)} of {max(advertised_totals)} advertised Heritage lots. "
            "Those lots were imported. Save and import the remaining results pages to include the rest of the sale. "
            "Previously cached lots were retained."
        )
    undated = sum(not lot.relevant_at for lot in observed.values())
    if undated:
        notices.append(
            f"{undated} imported Heritage lots have no verified sale date and cannot appear on a dated calendar. "
            "Save the catalog with its sale heading and date visible."
        )
    notices.extend(dict.fromkeys(image_notices))
    return WatchlistResult(lots=lots, metrics=metrics, notices=notices)
