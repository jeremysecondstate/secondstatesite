"""Incremental watchlist orchestration over curated bookmark URLs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import threading
from typing import Callable, Iterable

from catalogapp.bookmark_watchlist import BookmarkEntry
from catalogapp.watchlist_adapters import BatchedSearchPage, BookmarkSourceAdapter, adapter_for_url
from catalogapp.watchlist_cache import WatchlistCache
from catalogapp.watchlist_enrichment import OpenAIEnricher
from catalogapp.watchlist_fetch import WatchlistStopped, page_fetcher_from_environment
from catalogapp.watchlist_models import (
    NormalizedLot,
    lot_within_horizon,
    mark_cross_source_duplicates,
    parse_lot_datetime,
)


@dataclass(slots=True)
class WatchlistMetrics:
    bookmark_urls: int = 0
    artists: int = 0
    pages_fetched: int = 0
    detail_pages_fetched: int = 0
    cache_hits: int = 0
    new_lots: int = 0
    changed_lots: int = 0
    unchanged_lots: int = 0
    ended_lots: int = 0
    ai_enriched_records: int = 0
    ai_cache_hits: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    def summary(self) -> str:
        return (
            f"Pages fetched: {self.pages_fetched} · Cache hits: {self.cache_hits} · "
            f"New: {self.new_lots} · Changed: {self.changed_lots} · Ended: {self.ended_lots} · "
            f"AI-enriched: {self.ai_enriched_records} · Tokens: {self.total_tokens}"
        )


@dataclass(slots=True)
class WatchlistResult:
    lots: list[NormalizedLot]
    metrics: WatchlistMetrics
    errors: list[str] = field(default_factory=list)
    stopped: bool = False


class WatchlistService:
    def __init__(
        self,
        cache: WatchlistCache,
        *,
        fetcher=None,
        enricher: OpenAIEnricher | None = None,
        now: Callable[[], datetime] | None = None,
        max_pages_per_bookmark: int = 10,
    ) -> None:
        self.cache = cache
        self.fetcher = fetcher
        self.enricher = enricher or OpenAIEnricher.from_environment(cache)
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.max_pages_per_bookmark = max(1, min(int(max_pages_per_bookmark), 25))

    def refresh(
        self,
        entries: Iterable[BookmarkEntry],
        *,
        selected_artists: Iterable[str],
        horizon_days: int = 7,
        zero_ai: bool = True,
        new_changed_only: bool = False,
        stop_event: threading.Event | None = None,
        progress: Callable[[str], None] | None = None,
    ) -> WatchlistResult:
        stop = stop_event or threading.Event()
        fetcher = self.fetcher or page_fetcher_from_environment(stop)
        selected = {artist.casefold() for artist in selected_artists}
        chosen = [entry for entry in entries if entry.artist.casefold() in selected]
        metrics = WatchlistMetrics(
            bookmark_urls=len(chosen),
            artists=len({entry.artist.casefold() for entry in chosen}),
        )
        errors: list[str] = []
        if not zero_ai and not self.enricher.enabled:
            errors.append(
                "AI enrichment was requested but is not enabled. Set OPENAI_WATCHLIST_ENRICHMENT_ENABLED=1 "
                "and configure OPENAI_API_KEY, or keep Zero-AI mode selected."
            )
        refreshed_lots: list[NormalizedLot] = []
        stopped = False
        started_pages = int(getattr(fetcher, "pages_fetched", 0))
        observed_at = self.now()
        profile_directory = getattr(fetcher, "profile_directory", None)
        if profile_directory and progress:
            progress(f"Using the explicitly selected browser profile: {profile_directory}")

        batched_pages: dict[str, BatchedSearchPage] = {}
        batch_failed_urls: set[str] = set()
        entries_by_adapter: dict[BookmarkSourceAdapter, list[BookmarkEntry]] = {}
        for entry in chosen:
            adapter = adapter_for_url(entry.url)
            if adapter is not None:
                entries_by_adapter.setdefault(adapter, []).append(entry)
        for adapter, adapter_entries in entries_by_adapter.items():
            batcher = getattr(adapter, "fetch_search_batch", None)
            if len(adapter_entries) < 2 or not callable(batcher):
                continue
            if progress:
                progress(
                    f"Fetching {len(adapter_entries)} {adapter.source} artists in a rate-safe batchâ€¦"
                )
            try:
                batched_pages.update(
                    batcher(
                        [(entry.url, entry.artist) for entry in adapter_entries],
                        fetcher,
                        max_pages=self.max_pages_per_bookmark,
                    )
                )
            except WatchlistStopped:
                stopped = True
                break
            except Exception as exc:
                message = " ".join(str(exc).split())[:500]
                cached_count = 0
                for entry in adapter_entries:
                    batch_failed_urls.add(entry.url)
                    cached = self._cached_lots_for_entry(entry)
                    cached_count += len(cached)
                    refreshed_lots.extend(cached)
                    metrics.cache_hits += len(cached)
                    self.cache.record_source_error(entry.url, message, observed_at)
                suffix = f" Showing {cached_count} cached lots." if cached_count else ""
                errors.append(
                    f"{adapter.source} ({len(adapter_entries)} artists): {message}{suffix}"
                )

        if stopped:
            metrics.pages_fetched = max(0, int(getattr(fetcher, "pages_fetched", 0)) - started_pages)
            return WatchlistResult(lots=[], metrics=metrics, errors=errors, stopped=True)

        for entry in chosen:
            if stop.is_set():
                stopped = True
                break
            if entry.url in batch_failed_urls:
                continue
            adapter = adapter_for_url(entry.url)
            if adapter is None:
                errors.append(f"{entry.source or 'Unsupported source'} adapter is not available yet: {entry.artist}")
                continue
            if progress:
                progress(f"Fetching {entry.artist} from {entry.source}…")
            try:
                lots, ended, complete = self._refresh_entry(
                    entry,
                    adapter,
                    fetcher,
                    stop,
                    metrics,
                    observed_at,
                    preloaded_search=batched_pages.get(entry.url),
                )
                refreshed_lots.extend(lots)
                if complete:
                    refreshed_lots.extend(ended)
                    metrics.ended_lots += len(ended)
                self.cache.record_source_success(entry.url, observed_at)
            except WatchlistStopped:
                stopped = True
                break
            except Exception as exc:
                message = " ".join(str(exc).split())[:500]
                cached = self._cached_lots_for_entry(entry)
                refreshed_lots.extend(cached)
                metrics.cache_hits += len(cached)
                suffix = f" Showing {len(cached)} cached lots." if cached else ""
                errors.append(f"{entry.artist} ({entry.source}): {message}{suffix}")
                self.cache.record_source_error(entry.url, message, observed_at)

        metrics.pages_fetched = max(0, int(getattr(fetcher, "pages_fetched", 0)) - started_pages)
        enrichment = self.enricher.enrich(refreshed_lots, zero_ai=zero_ai)
        metrics.ai_enriched_records = enrichment.records_enriched
        metrics.ai_cache_hits = enrichment.cache_hits
        metrics.cache_hits += enrichment.cache_hits
        metrics.input_tokens = enrichment.input_tokens
        metrics.output_tokens = enrichment.output_tokens
        metrics.total_tokens = enrichment.total_tokens
        for lot in refreshed_lots:
            self.cache.update_payload(lot)

        deduplicated: dict[str, NormalizedLot] = {}
        for lot in mark_cross_source_duplicates(refreshed_lots):
            deduplicated[lot.cache_key] = lot
        lots = list(deduplicated.values())
        lots = [lot for lot in lots if lot.status == "ended" or lot_within_horizon(lot, observed_at, horizon_days)]
        if new_changed_only:
            lots = [lot for lot in lots if lot.status in {"new", "changed", "ended"}]
        lots.sort(key=_agenda_sort_key)
        if progress:
            progress(metrics.summary())
        return WatchlistResult(lots=lots, metrics=metrics, errors=errors, stopped=stopped)

    def _refresh_entry(
        self,
        entry: BookmarkEntry,
        adapter: BookmarkSourceAdapter,
        fetcher,
        stop: threading.Event,
        metrics: WatchlistMetrics,
        observed_at: datetime,
        preloaded_search: BatchedSearchPage | None = None,
    ) -> tuple[list[NormalizedLot], list[NormalizedLot], bool]:
        page_url = entry.url
        visited_pages: set[str] = set()
        observed_keys: set[str] = set()
        lots: list[NormalizedLot] = []
        complete = True
        use_preloaded_search = preloaded_search is not None
        while page_url and page_url not in visited_pages:
            if len(visited_pages) >= self.max_pages_per_bookmark:
                complete = False
                break
            if stop.is_set():
                raise WatchlistStopped("Watchlist refresh stopped by the user.")
            visited_pages.add(page_url)
            if use_preloaded_search:
                page = preloaded_search.page
                complete = complete and preloaded_search.complete
                use_preloaded_search = False
            else:
                page = adapter.fetch_search_page(page_url, fetcher)
            cards = adapter.parse_search_page(page, page_url, entry.artist)
            for card in cards:
                if card.cache_key in observed_keys:
                    continue
                observed_keys.add(card.cache_key)
                search_hash = card.content_hash
                cached = self.cache.lookup(card)
                if cached and cached.search_hash == search_hash and not adapter.needs_detail(cached.lot):
                    lot = cached.lot
                    lot.artist_watchlist_name = entry.artist
                    metrics.cache_hits += 1
                else:
                    lot = card
                    if adapter.needs_detail(lot) and lot.lot_url:
                        detail_page = adapter.fetch_lot_detail(lot.lot_url, fetcher)
                        metrics.detail_pages_fetched += 1
                        detail = adapter.parse_lot_detail(detail_page, lot.lot_url, entry.artist)
                        if detail:
                            lot = adapter.merge_detail(lot, detail)
                transition = self.cache.upsert(
                    lot,
                    watch_url=entry.url,
                    search_hash=search_hash,
                    observed_at=observed_at,
                )
                if transition == "new":
                    metrics.new_lots += 1
                elif transition == "changed":
                    metrics.changed_lots += 1
                else:
                    metrics.unchanged_lots += 1
                lots.append(lot)
            next_url = adapter.extract_next_page_url(page, page_url)
            if next_url in visited_pages:
                next_url = ""
            page_url = next_url
        ended = self.cache.mark_missing_ended(entry.url, observed_keys, observed_at) if complete else []
        return lots, ended, complete

    def _cached_lots_for_entry(self, entry: BookmarkEntry) -> list[NormalizedLot]:
        lots = self.cache.active_lots_for_watch_url(entry.url)
        for lot in lots:
            lot.artist_watchlist_name = entry.artist
        return lots


def _agenda_sort_key(lot: NormalizedLot) -> tuple[str, str, str, str]:
    parsed, _all_day = parse_lot_datetime(lot.relevant_at)
    when = parsed.isoformat() if parsed else "9999-12-31T23:59:59+00:00"
    return (
        when,
        (lot.artist_watchlist_name or lot.artist).casefold(),
        lot.auction_house.casefold(),
        lot.lot_number.casefold(),
    )
