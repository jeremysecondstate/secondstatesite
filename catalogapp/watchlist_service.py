"""Incremental watchlist orchestration over curated bookmark URLs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import threading
from typing import Callable, Iterable

from catalogapp.bookmark_watchlist import BookmarkEntry
from catalogapp.watchlist_adapters import BatchedSearchPage, BookmarkSourceAdapter, adapter_for_url
from catalogapp.watchlist_cache import WatchlistCache
from catalogapp.watchlist_enrichment import OpenAIEnricher
from catalogapp.watchlist_fetch import SourceAccessBlocked, SourceAccessError, WatchlistStopped, page_fetcher_from_environment
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
    notices: list[str] = field(default_factory=list)
    # View-only provenance: the source failed and these lots were not observed
    # in this refresh. Do not overwrite their stored transition or timestamp.
    fallback_lot_keys: set[str] = field(default_factory=set)


@dataclass(slots=True)
class _PostedResultChecks:
    details: dict[str, NormalizedLot | None] = field(default_factory=dict)
    access_blocked: bool = False


_SOLD_LOGIN_NOTICE = (
    "Invaluable requires sign-in to view these sold prices, so they are unavailable to this sync. "
    "Existing estimates and results have been retained."
)


class WatchlistService:
    def __init__(
        self,
        cache: WatchlistCache,
        *,
        fetcher=None,
        invaluable_fetcher=None,
        enricher: OpenAIEnricher | None = None,
        now: Callable[[], datetime] | None = None,
        max_pages_per_bookmark: int = 10,
    ) -> None:
        self.cache = cache
        self.fetcher = fetcher
        self.invaluable_fetcher = invaluable_fetcher
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
        invaluable_fetcher = self.invaluable_fetcher if self.invaluable_fetcher is not None else fetcher
        fetchers = {id(item): item for item in (fetcher, invaluable_fetcher)}
        started_pages = {key: int(getattr(item, "pages_fetched", 0)) for key, item in fetchers.items()}

        def source_fetcher(adapter: BookmarkSourceAdapter):
            return invaluable_fetcher if adapter.source == "Invaluable" else fetcher

        def fetched_pages() -> int:
            return sum(max(0, int(getattr(item, "pages_fetched", 0)) - started_pages[key]) for key, item in fetchers.items())

        selected = {artist.casefold() for artist in selected_artists}
        chosen = [entry for entry in entries if entry.watch_label.casefold() in selected]
        metrics = WatchlistMetrics(
            bookmark_urls=len(chosen),
            artists=len({entry.watch_label.casefold() for entry in chosen}),
        )
        errors: list[str] = []
        notices: list[str] = []
        if not zero_ai and not self.enricher.enabled:
            errors.append(
                "AI enrichment was requested but is not enabled. Set OPENAI_WATCHLIST_ENRICHMENT_ENABLED=1 "
                "and configure OPENAI_API_KEY, or keep Zero-AI mode selected."
            )
        refreshed_lots: list[NormalizedLot] = []
        fallback_lot_keys: set[str] = set()
        observed_lot_keys: set[str] = set()
        result_checks = _PostedResultChecks()
        stopped = False
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
                        source_fetcher(adapter),
                        max_pages=self.max_pages_per_bookmark,
                    )
                )
            except WatchlistStopped:
                stopped = True
                break
            except Exception as exc:
                if adapter.source == "Invaluable" and isinstance(exc, SourceAccessBlocked):
                    result_checks.access_blocked = True
                message = " ".join(str(exc).split())[:500]
                cached_count = 0
                uncached_watches: list[str] = []
                for entry in adapter_entries:
                    batch_failed_urls.add(entry.url)
                    cached = self._cached_lots_for_entry(entry)
                    if not cached:
                        uncached_watches.append(entry.watch_label)
                    cached_count += len(cached)
                    refreshed_lots.extend(cached)
                    fallback_lot_keys.update(lot.cache_key for lot in cached)
                    metrics.cache_hits += len(cached)
                    self.cache.record_source_error(entry.url, message, observed_at)
                suffix = _cached_fallback_message(cached_count, new_changed_only)
                errors.append(
                    f"{adapter.source} ({len(adapter_entries)} artists): {message}{suffix}"
                )
                if uncached_watches:
                    errors.append(_uncached_watches_message(uncached_watches))

        if stopped:
            metrics.pages_fetched = fetched_pages()
            return WatchlistResult(lots=[], metrics=metrics, errors=errors, stopped=True, notices=notices)

        for entry in chosen:
            if stop.is_set():
                stopped = True
                break
            adapter = adapter_for_url(entry.url)
            if adapter is None:
                errors.append(f"{entry.source or 'Unsupported source'} adapter is not available yet: {entry.watch_label}")
                continue
            if entry.url in batch_failed_urls:
                if adapter.source == "Invaluable":
                    try:
                        refreshed_lots.extend(self._refresh_posted_results(
                            entry, adapter, source_fetcher(adapter), stop, metrics, observed_at, [],
                            result_checks, errors, observed_lot_keys, notices, ended_only=True,
                        ))
                    except WatchlistStopped:
                        stopped = True
                        break
                continue
            if progress:
                progress(f"Fetching {entry.watch_label} from {entry.source}…")
            try:
                lots, ended, complete = self._refresh_entry(
                    entry,
                    adapter,
                    source_fetcher(adapter),
                    stop,
                    metrics,
                    observed_at,
                    preloaded_search=batched_pages.get(entry.url),
                    observed_lot_keys=observed_lot_keys,
                    result_checks=result_checks,
                    errors=errors,
                    notices=notices,
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
                if adapter.source == "Invaluable" and isinstance(exc, SourceAccessBlocked):
                    result_checks.access_blocked = True
                message = " ".join(str(exc).split())[:500]
                cached = self._cached_lots_for_entry(entry)
                refreshed_lots.extend(cached)
                fallback_lot_keys.update(lot.cache_key for lot in cached)
                metrics.cache_hits += len(cached)
                suffix = _cached_fallback_message(
                    sum(lot.cache_key not in observed_lot_keys for lot in cached), new_changed_only
                )
                errors.append(f"{entry.watch_label} ({entry.source}): {message}{suffix}")
                if not cached:
                    errors.append(_uncached_watches_message([entry.watch_label]))
                self.cache.record_source_error(entry.url, message, observed_at)
                if adapter.source == "Invaluable":
                    try:
                        refreshed_lots.extend(self._refresh_posted_results(
                            entry, adapter, source_fetcher(adapter), stop, metrics, observed_at, [],
                            result_checks, errors, observed_lot_keys, notices, ended_only=True,
                        ))
                    except WatchlistStopped:
                        stopped = True
                        break

        metrics.pages_fetched = fetched_pages()
        fallback_lot_keys.difference_update(observed_lot_keys)
        freshly_observed_lots = [lot for lot in refreshed_lots if lot.cache_key not in fallback_lot_keys]
        enrichment = self.enricher.enrich(freshly_observed_lots, zero_ai=zero_ai)
        metrics.ai_enriched_records = enrichment.records_enriched
        metrics.ai_cache_hits = enrichment.cache_hits
        metrics.cache_hits += enrichment.cache_hits
        metrics.input_tokens = enrichment.input_tokens
        metrics.output_tokens = enrichment.output_tokens
        metrics.total_tokens = enrichment.total_tokens
        deduplicated: dict[str, NormalizedLot] = {}
        priority = {"new": 3, "changed": 2, "ended": 1, "unchanged": 0}
        for lot in mark_cross_source_duplicates(refreshed_lots):
            previous = deduplicated.get(lot.cache_key)
            if previous is None or not (previous.sold_price is not None and lot.sold_price is None):
                if previous is not None and priority.get(previous.status, 0) > priority.get(lot.status, 0):
                    lot.status = previous.status
                deduplicated[lot.cache_key] = lot
        lots = list(deduplicated.values())
        for lot in lots:
            if lot.cache_key not in fallback_lot_keys:
                self.cache.update_payload(lot)
        lots = [lot for lot in lots if lot.status == "ended" or lot.sold_price is not None
                or lot_within_horizon(lot, observed_at, horizon_days)]
        if new_changed_only:
            lots = [
                lot for lot in lots
                if lot.cache_key not in fallback_lot_keys and (
                    lot.status in {"new", "changed"}
                    or (lot.status == "ended" and lot.cache_key in observed_lot_keys)
                )
            ]
        lots.sort(key=_agenda_sort_key)
        if progress:
            progress(metrics.summary())
        return WatchlistResult(
            lots=lots, metrics=metrics, errors=errors, stopped=stopped,
            notices=notices,
            fallback_lot_keys=fallback_lot_keys.intersection(lot.cache_key for lot in lots),
        )

    def _refresh_entry(
        self,
        entry: BookmarkEntry,
        adapter: BookmarkSourceAdapter,
        fetcher,
        stop: threading.Event,
        metrics: WatchlistMetrics,
        observed_at: datetime,
        preloaded_search: BatchedSearchPage | None = None,
        observed_lot_keys: set[str] | None = None,
        result_checks: _PostedResultChecks | None = None,
        errors: list[str] | None = None,
        notices: list[str] | None = None,
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
            if stop.is_set():
                raise WatchlistStopped("Watchlist refresh stopped by the user.")
            cards = adapter.parse_search_page(page, page_url, entry.artist)
            if len(visited_pages) > 1 and cards and all(card.cache_key in observed_keys for card in cards):
                raise SourceAccessError(
                    "The source repeated an earlier catalog page; existing lots have been retained."
                )
            for card in cards:
                if card.cache_key in observed_keys:
                    continue
                observed_keys.add(card.cache_key)
                search_hash = card.content_hash
                cached = self.cache.lookup(card)
                if cached and cached.search_hash == search_hash and not adapter.needs_detail(cached.lot):
                    lot = cached.lot
                    lot.artist_watchlist_name = entry.artist or lot.artist
                    metrics.cache_hits += 1
                else:
                    lot = card
                    if adapter.needs_detail(lot) and lot.lot_url and not (
                        adapter.source == "Invaluable" and result_checks is not None and result_checks.access_blocked
                    ):
                        try:
                            detail_page = adapter.fetch_lot_detail(lot.lot_url, fetcher)
                        except SourceAccessError as exc:
                            if adapter.source == "Invaluable" and result_checks is not None:
                                result_checks.details[lot.cache_key] = None
                                if isinstance(exc, SourceAccessBlocked):
                                    result_checks.access_blocked = True
                            raise
                        metrics.detail_pages_fetched += 1
                        detail = adapter.parse_lot_detail(detail_page, lot.lot_url, entry.artist)
                        if detail is None:
                            if adapter.source == "Invaluable" and result_checks is not None:
                                result_checks.details[lot.cache_key] = None
                            raise SourceAccessError("The lot page did not contain recognizable auction details.")
                        if result_checks is not None:
                            result_checks.details[lot.cache_key] = detail
                            self._note_sold_access(detail, result_checks, notices if notices is not None else [])
                        if detail:
                            lot = adapter.merge_detail(lot, detail)
                transition = self.cache.upsert(
                    lot,
                    watch_url=entry.url,
                    search_hash=search_hash,
                    observed_at=observed_at,
                )
                if observed_lot_keys is not None:
                    observed_lot_keys.add(lot.cache_key)
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
        if complete and adapter.source == "Invaluable":
            lots = self._refresh_posted_results(
                entry, adapter, fetcher, stop, metrics, observed_at, lots,
                result_checks if result_checks is not None else _PostedResultChecks(),
                errors if errors is not None else [], observed_lot_keys,
                notices if notices is not None else [],
            )
        ended = self.cache.mark_missing_ended(entry.url, observed_keys, observed_at) if complete else []
        if observed_lot_keys is not None:
            observed_lot_keys.update(lot.cache_key for lot in ended)
        return lots, ended, complete

    def _refresh_posted_results(
        self,
        entry: BookmarkEntry,
        adapter: BookmarkSourceAdapter,
        fetcher,
        stop: threading.Event,
        metrics: WatchlistMetrics,
        observed_at: datetime,
        lots: list[NormalizedLot],
        result_checks: _PostedResultChecks,
        errors: list[str],
        observed_lot_keys: set[str] | None,
        notices: list[str],
        *,
        ended_only: bool = False,
    ) -> list[NormalizedLot]:
        """Revisit watched details for 30 days, even after upcoming searches drop them."""

        current = {lot.cache_key: lot for lot in lots}
        now = observed_at if observed_at.tzinfo else observed_at.replace(tzinfo=timezone.utc)
        for cached in self.cache.lots_for_watch_url(entry.url):
            if stop.is_set():
                raise WatchlistStopped("Watchlist refresh stopped by the user.")
            if cached.sold_price is not None:
                # A confirmed result is still included for reliable sync retries.
                if cached.cache_key not in current:
                    if not ended_only:
                        cached.status = "unchanged"
                    current[cached.cache_key] = cached
                    metrics.cache_hits += 1
                continue
            # Already ended records remain visible even if a catalog cannot be
            # read, or their result is older than the automatic recheck window.
            if cached.status == "ended" and cached.cache_key not in current:
                current[cached.cache_key] = cached
            if ended_only and cached.status != "ended":
                continue
            when, _all_day = parse_lot_datetime(cached.relevant_at)
            if when is None or not now - timedelta(days=30) <= when <= now:
                continue
            if not cached.lot_url:
                continue
            if cached.cache_key not in result_checks.details:
                if result_checks.access_blocked:
                    continue
                try:
                    page = adapter.fetch_lot_detail(cached.lot_url, fetcher)
                    if stop.is_set():
                        raise WatchlistStopped("Watchlist refresh stopped by the user.")
                    metrics.detail_pages_fetched += 1
                    detail = adapter.parse_lot_detail(page, cached.lot_url, entry.artist)
                    if detail is None:
                        raise SourceAccessError("The lot page did not contain recognizable auction details.")
                    result_checks.details[cached.cache_key] = detail
                    self._note_sold_access(detail, result_checks, notices)
                except WatchlistStopped:
                    raise
                except Exception as exc:
                    result_checks.details[cached.cache_key] = None
                    if isinstance(exc, SourceAccessBlocked):
                        result_checks.access_blocked = True
                    message = " ".join(str(exc).split())[:300]
                    errors.append(
                        f"{entry.watch_label} (Invaluable), lot {cached.lot_number or cached.source_lot_id}: "
                        f"sold result could not be checked: {message}. The last known data was retained."
                    )
            detail = result_checks.details[cached.cache_key]
            if detail is not None and detail.sold_price is not None:
                lot = adapter.merge_detail(cached, detail)
                lookup = self.cache.lookup(cached)
                transition = self.cache.upsert(
                    lot, watch_url=entry.url,
                    search_hash=lookup.search_hash if lookup else "",
                    observed_at=observed_at, active=False,
                )
                prior = current.get(lot.cache_key)
                if prior is not None and prior.status in {"new", "changed"}:
                    lot.status = prior.status
                elif transition == "changed":
                    metrics.changed_lots += 1
                if observed_lot_keys is not None:
                    observed_lot_keys.add(lot.cache_key)
                current[lot.cache_key] = lot
            elif cached.status == "ended" and cached.cache_key not in current:
                current[cached.cache_key] = cached
        return list(current.values())

    @staticmethod
    def _note_sold_access(detail: NormalizedLot | None, checks: _PostedResultChecks, notices: list[str]) -> None:
        if detail is not None and "sold_price_login" in detail.ambiguities and detail.sold_price is None:
            checks.access_blocked = True
            if _SOLD_LOGIN_NOTICE not in notices:
                notices.append(_SOLD_LOGIN_NOTICE)

    def _cached_lots_for_entry(self, entry: BookmarkEntry) -> list[NormalizedLot]:
        lots = self.cache.active_lots_for_watch_url(entry.url)
        known_keys = {lot.cache_key for lot in lots}
        lots.extend(
            lot for lot in self.cache.lots_for_watch_url(entry.url)
            if lot.cache_key not in known_keys and (lot.status == "ended" or lot.sold_price is not None)
        )
        for lot in lots:
            lot.artist_watchlist_name = entry.artist or lot.artist
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


def _cached_fallback_message(count: int, new_changed_only: bool) -> str:
    if not count:
        return ""
    noun = "lot" if count == 1 else "lots"
    visibility = " Hidden by New/changed only." if new_changed_only else " Displayed as Cached."
    return f" Retained {count} cached {noun}; live data was not verified.{visibility}"


def _uncached_watches_message(watch_labels: Iterable[str]) -> str:
    labels = list(dict.fromkeys(" ".join(label.split()) for label in watch_labels))
    displayed = [label if len(label) <= 80 else label[:77] + "..." for label in labels[:8]]
    if len(labels) > len(displayed):
        displayed.append(f"and {len(labels) - len(displayed)} more")
    return (
        f"No cached lots are available for calendar sync for: {', '.join(displayed)}. "
        "Once source access is restored, click Sync to Calendar to fetch and upload new lots."
    )
