"""Incremental watchlist orchestration over curated bookmark URLs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import re
import threading
from typing import Callable, Iterable
from urllib.parse import urlsplit

from catalogapp.bookmark_watchlist import BookmarkEntry
from catalogapp.watchlist_adapters import BatchedSearchPage, BookmarkSourceAdapter, adapter_for_url
from catalogapp.watchlist_cache import CacheLookup, WatchlistCache
from catalogapp.watchlist_coverage import WatchCoverage
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
    coverage: list[WatchCoverage] = field(default_factory=list)


@dataclass(slots=True)
class _PostedResultChecks:
    details: dict[str, NormalizedLot | None] = field(default_factory=dict)
    access_blocked: bool = False
    catalog_access_blocked: bool = False
    blocked_detail_sources: set[str] = field(default_factory=set)
    detail_errors_by_watch: dict[str, str] = field(default_factory=dict)


_SOLD_LOGIN_NOTICE = (
    "Invaluable requires sign-in to view these sold prices, so they are unavailable to this sync. "
    "Existing estimates and results have been retained."
)


class _CatalogAccessBlocked(SourceAccessBlocked):
    """Distinguish a search failure from an optional or required detail denial."""


def _invaluable_lot_reference(url: str) -> str:
    match = re.search(r"-c-([a-z0-9]+)(?:/|$)", urlsplit(url).path, re.I)
    return match[1].casefold() if match else ""


def _retain_missing_static_fields(card: NormalizedLot, previous: NormalizedLot) -> None:
    """Preserve richer cached description fields without carrying old bids."""
    if card.source == "Doyle" and card.title == f"Lot {card.lot_number}" and previous.title:
        card.title = previous.title
    if not card.saved_image_base64 and (not card.image_url or card.image_url == previous.image_url):
        card.saved_image_base64 = previous.saved_image_base64
    for field in ("title", "medium", "auction_house", "sale_title", "lot_number", "location", "sale_url", "image_url"):
        if not getattr(card, field):
            setattr(card, field, getattr(previous, field))
    if card.medium.casefold() == "print" and previous.medium:
        card.medium = previous.medium
    card.content_hash = card.calculate_content_hash()


def _has_usable_search_data(lot: NormalizedLot) -> bool:
    """A failed optional detail request must not admit an undated calendar lot."""
    try:
        when, _all_day = parse_lot_datetime(lot.relevant_at)
    except ValueError:
        return False
    return bool(lot.title.strip() and when is not None)


class WatchlistService:
    def __init__(
        self,
        cache: WatchlistCache,
        *,
        fetcher=None,
        invaluable_fetcher=None,
        invaluable_recovery_factory: Callable[[], object] | None = None,
        enricher: OpenAIEnricher | None = None,
        now: Callable[[], datetime] | None = None,
        max_pages_per_bookmark: int = 10,
    ) -> None:
        self.cache = cache
        self.fetcher = fetcher
        self.invaluable_fetcher = invaluable_fetcher
        self.invaluable_recovery_factory = invaluable_recovery_factory
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
        pending_only: bool = False,
    ) -> WatchlistResult:
        stop = stop_event or threading.Event()
        fetcher = self.fetcher or page_fetcher_from_environment(stop)
        invaluable_fetcher = self.invaluable_fetcher if self.invaluable_fetcher is not None else fetcher
        fetchers = {id(item): item for item in (fetcher, invaluable_fetcher)}
        started_pages = {key: int(getattr(item, "pages_fetched", 0)) for key, item in fetchers.items()}
        recovery_fetcher = None
        recovery_started = False
        recovery_error: Exception | None = None
        recovery_checks = _PostedResultChecks()

        def can_recover(message: object, *, blocked: bool) -> bool:
            # A 202 JavaScript access page can be loaded in the visible browser.
            # Authentication denials and rate limits must not start this fallback.
            return bool(
                self.invaluable_recovery_factory is not None
                and getattr(invaluable_fetcher, "uses_natural_catalog_requests", False) is not True
                and blocked and re.search(r"\bHTTP\s+202\b", str(message), re.I)
                and not re.search(r"\bHTTP\s+(?:401|403|429)\b", str(message), re.I)
            )

        def browser_recovery():
            nonlocal recovery_fetcher, recovery_started, recovery_error
            if stop.is_set():
                raise WatchlistStopped("Watchlist refresh stopped by the user.")
            if not recovery_started:
                recovery_started = True
                if progress:
                    progress("Invaluable needs its browser page. Opening browser recovery for unfinished artists…")
                try:
                    recovery_fetcher = self.invaluable_recovery_factory()
                    if getattr(recovery_fetcher, "uses_natural_catalog_requests", False) is not True:
                        raise SourceAccessError("Recovery requires the public search browser.")
                    key = id(recovery_fetcher)
                    fetchers[key] = recovery_fetcher
                    started_pages[key] = int(getattr(recovery_fetcher, "pages_fetched", 0))
                except WatchlistStopped:
                    raise
                except Exception as exc:
                    recovery_error = SourceAccessBlocked(
                        "Invaluable browser recovery could not start: " + " ".join(str(exc).split())[:300]
                    )
            if recovery_error is not None:
                raise recovery_error
            return recovery_fetcher

        def source_fetcher(adapter: BookmarkSourceAdapter):
            return invaluable_fetcher if adapter.source == "Invaluable" else fetcher

        def fetched_pages() -> int:
            return sum(max(0, int(getattr(item, "pages_fetched", 0)) - started_pages[key]) for key, item in fetchers.items())

        observed_at = self.now()
        observed_at = observed_at if observed_at.tzinfo else observed_at.replace(tzinfo=timezone.utc)
        horizon_days = max(1, int(horizon_days))
        catalog_end = observed_at + timedelta(days=horizon_days)
        scoped_adapters: dict[int, BookmarkSourceAdapter] = {}

        def configured_adapter(url: str) -> BookmarkSourceAdapter | None:
            adapter = adapter_for_url(url)
            if adapter is None:
                return None
            if id(adapter) not in scoped_adapters:
                scope = getattr(adapter, "with_catalog_end", None)
                scoped_adapters[id(adapter)] = scope(catalog_end) if callable(scope) else adapter
            return scoped_adapters[id(adapter)]

        def coverage():
            return self.cache.coverage_for_entries(
                all_chosen, observed_at=observed_at, horizon_days=horizon_days,
            )

        selected = {artist.casefold() for artist in selected_artists}
        all_chosen = [entry for entry in entries if entry.watch_label.casefold() in selected]
        previous_coverage = {item.watch_url: item for item in coverage()}
        chosen = all_chosen
        if pending_only:
            chosen = sorted(
                (entry for entry in all_chosen if previous_coverage[entry.url].needs_recovery),
                key=lambda entry: (bool(self._cached_lots_for_entry(entry)), previous_coverage[entry.url].checked_at),
            )
        metrics = WatchlistMetrics(
            bookmark_urls=len(all_chosen),
            artists=len({entry.watch_label.casefold() for entry in all_chosen}),
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
        if pending_only:
            requested_urls = {entry.url for entry in chosen}
            for entry in all_chosen:
                if entry.url in requested_urls:
                    continue
                cached = self._cached_lots_for_entry(entry)
                refreshed_lots.extend(cached)
                fallback_lot_keys.update(lot.cache_key for lot in cached)
                metrics.cache_hits += len(cached)
            notices.append(
                f"Recovering {len(chosen)} pending watches individually. Previously verified searches "
                "are retained from cache; use Update Calendar to check every watch again."
            )
        profile_directory = getattr(fetcher, "profile_directory", None)
        if profile_directory and progress:
            progress(f"Using the explicitly selected browser profile: {profile_directory}")

        batched_pages: dict[str, BatchedSearchPage] = {}
        batch_failed_urls: set[str] = set()
        batch_error_entries: dict[int, list[BookmarkEntry]] = {}
        recovery_urls: set[str] = set()
        incomplete_uncached_watches: list[str] = []
        entries_by_adapter: dict[BookmarkSourceAdapter, list[BookmarkEntry]] = {}
        for entry in chosen:
            adapter = configured_adapter(entry.url)
            if adapter is not None:
                entries_by_adapter.setdefault(adapter, []).append(entry)
        for adapter, adapter_entries in entries_by_adapter.items():
            batcher = getattr(adapter, "fetch_search_batch", None)
            if pending_only or len(adapter_entries) < 2 or not callable(batcher):
                continue
            if progress:
                progress(
                    f"Fetching {len(adapter_entries)} {adapter.source} artists in small groups…"
                )
            batch_entries = adapter_entries
            if adapter.source == "Invaluable":
                # Give newly added watches a chance before a later source block
                # can leave them perpetually absent from the calendar.
                batch_entries = sorted(adapter_entries, key=lambda entry: (
                    not previous_coverage[entry.url].needs_recovery,
                    bool(self._cached_lots_for_entry(entry)),
                    previous_coverage[entry.url].checked_at,
                ))
            try:
                fetched = batcher(
                    [(entry.url, entry.artist) for entry in batch_entries],
                    source_fetcher(adapter),
                    max_pages=self.max_pages_per_bookmark,
                )
                batched_pages.update(fetched)
                failures: dict[str, list[BookmarkEntry]] = {}
                for entry in adapter_entries:
                    page = fetched.get(entry.url)
                    if page is None:
                        continue
                    if page.access_blocked and adapter.source == "Invaluable":
                        result_checks.access_blocked = True
                        result_checks.catalog_access_blocked = True
                    if page.error:
                        if adapter.source == "Invaluable" and can_recover(page.error, blocked=page.access_blocked):
                            recovery_urls.add(entry.url)
                        else:
                            failures.setdefault(page.error, []).append(entry)
                for message, affected_entries in failures.items():
                    batch_error_entries[len(errors)] = affected_entries
                    errors.append(f"{adapter.source} ({len(affected_entries)} artists): {message}")
            except WatchlistStopped:
                stopped = True
                break
            except Exception as exc:
                if adapter.source == "Invaluable" and isinstance(exc, SourceAccessBlocked):
                    result_checks.access_blocked = True
                    result_checks.catalog_access_blocked = True
                message = " ".join(str(exc).split())[:500]
                if adapter.source == "Invaluable" and can_recover(exc, blocked=isinstance(exc, SourceAccessBlocked)):
                    recovery_urls.update(entry.url for entry in adapter_entries)
                    continue
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
                    self.cache.record_watch_coverage(
                        entry.url, "blocked" if isinstance(exc, SourceAccessBlocked) else "pending",
                        detail=message, observed_at=observed_at,
                    )
                suffix = _cached_fallback_message(cached_count, new_changed_only)
                errors.append(
                    f"{adapter.source} ({len(adapter_entries)} artists): {message}{suffix}"
                )
                if uncached_watches:
                    errors.append(_uncached_watches_message(uncached_watches))

        if stopped:
            metrics.pages_fetched = fetched_pages()
            return WatchlistResult(
                lots=[], metrics=metrics, errors=errors, stopped=True, notices=notices,
                coverage=coverage(),
            )

        for entry in chosen:
            if stop.is_set():
                stopped = True
                break
            adapter = configured_adapter(entry.url)
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
            attempted = True
            entry_fetcher = source_fetcher(adapter)
            entry_checks = result_checks
            preloaded = batched_pages.get(entry.url)
            prior_observations: dict[str, str] = {}
            recovery_observations: list[NormalizedLot] = []

            def use_recovery():
                nonlocal entry_fetcher, entry_checks, preloaded, prior_observations, recovery_observations
                # The first HTTP pages may already have updated the cache before
                # a later page failed. Retain their transitions and provenance.
                fresh = [lot for lot in self._cached_lots_for_entry(entry) if lot.cache_key in observed_lot_keys]
                recovery_observations = fresh
                prior_observations = {lot.cache_key: lot.status for lot in fresh}
                entry_checks = recovery_checks
                preloaded = None
                entry_fetcher = browser_recovery()

            try:
                if adapter.source == "Invaluable" and (
                    entry.url in recovery_urls or (recovery_started and preloaded is None)
                ):
                    if preloaded is not None:
                        # Incomplete HTTP pages are useful even if the browser
                        # later fails. They cannot end absent lots.
                        self._refresh_entry(
                            entry, adapter, entry_fetcher, stop, metrics, observed_at,
                            preloaded_search=preloaded, observed_lot_keys=observed_lot_keys,
                            result_checks=result_checks, errors=errors, notices=notices,
                            catalog_only=True,
                        )
                    use_recovery()
                # Previously received pages remain usable after a later source
                # block, but no further catalog or lot requests may be made.
                if adapter.source == "Invaluable" and entry_checks.catalog_access_blocked and preloaded is None:
                    attempted = False
                    raise SourceAccessBlocked(
                        "Further Invaluable requests were skipped because source access is unavailable."
                    )
                try:
                    lots, ended, complete = self._refresh_entry(
                        entry, adapter, entry_fetcher, stop, metrics, observed_at,
                        preloaded_search=preloaded, observed_lot_keys=observed_lot_keys,
                        result_checks=entry_checks, errors=errors, notices=notices,
                        prior_observations=prior_observations,
                    )
                except SourceAccessBlocked as exc:
                    if (adapter.source != "Invaluable" or entry_checks is recovery_checks
                            or not isinstance(exc, _CatalogAccessBlocked) or not can_recover(exc, blocked=True)):
                        raise
                    result_checks.access_blocked = True
                    result_checks.catalog_access_blocked = True
                    use_recovery()
                    lots, ended, complete = self._refresh_entry(
                        entry, adapter, entry_fetcher, stop, metrics, observed_at,
                        observed_lot_keys=observed_lot_keys, result_checks=entry_checks,
                        errors=errors, notices=notices, prior_observations=prior_observations,
                    )
                if not complete:
                    refreshed_lots.extend(recovery_observations)
                refreshed_lots.extend(lots)
                if complete:
                    refreshed_lots.extend(ended)
                    metrics.ended_lots += len(ended)
                if not complete:
                    message = preloaded.error if preloaded is not None else ""
                    if not message:
                        message = (
                            "The catalog refresh reached its page limit before all lots could be checked. "
                            "Existing cached lots were retained; live data was not verified for them."
                        )
                        errors.append(f"{entry.watch_label} ({entry.source}): {message}")
                    cached = [
                        lot for lot in self._cached_lots_for_entry(entry)
                        if lot.cache_key not in observed_lot_keys
                    ]
                    refreshed_lots.extend(cached)
                    fallback_lot_keys.update(lot.cache_key for lot in cached)
                    metrics.cache_hits += len(cached)
                    if not lots and not cached:
                        incomplete_uncached_watches.append(entry.watch_label)
                    self.cache.record_source_error(entry.url, message, observed_at)
                    self.cache.record_watch_coverage(
                        entry.url, "blocked" if preloaded is not None and preloaded.access_blocked else "partial",
                        detail=message, observed_at=observed_at,
                    )
                elif entry.url in entry_checks.detail_errors_by_watch:
                    self.cache.record_source_error(entry.url, entry_checks.detail_errors_by_watch[entry.url], observed_at)
                else:
                    self.cache.record_source_success(entry.url, observed_at)
                if complete:
                    source_end = getattr(adapter, "catalog_end", None)
                    active = self.cache.active_lots_for_watch_url(entry.url)
                    visible = [lot for lot in active if lot_within_horizon(lot, observed_at, horizon_days)]
                    self.cache.record_watch_coverage(
                        entry.url, "verified" if visible else "empty",
                        observed_at=observed_at,
                        covered_until=source_end,
                        detail=(f"Complete catalog check for the next {horizon_days} days, through "
                                f"{source_end.astimezone(timezone.utc):%Y-%m-%d %H:%M} UTC.") if source_end else "",
                    )
            except WatchlistStopped:
                stopped = True
                break
            except Exception as exc:
                if adapter.source == "Invaluable" and (
                    isinstance(exc, SourceAccessBlocked)
                    or (entry_checks is recovery_checks and not getattr(entry_fetcher, "pages_fetched", 0))
                ):
                    # A lazy browser startup failure must not launch once per
                    # artist. Later ordinary page failures retain their scope.
                    entry_checks.access_blocked = True
                    entry_checks.catalog_access_blocked = True
                message = " ".join(str(exc).split())[:500]
                refreshed_lots.extend(recovery_observations)
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
                self.cache.record_watch_coverage(
                    entry.url, "blocked" if isinstance(exc, SourceAccessBlocked) else "partial" if any(
                        lot.cache_key in observed_lot_keys for lot in cached
                    ) else "pending",
                    detail=message, observed_at=observed_at, attempted=attempted,
                )
                if adapter.source == "Invaluable":
                    try:
                        refreshed_lots.extend(self._refresh_posted_results(
                            entry, adapter, entry_fetcher, stop, metrics, observed_at, [],
                            entry_checks, errors, observed_lot_keys, notices, ended_only=True,
                        ))
                    except WatchlistStopped:
                        stopped = True
                        break

        if incomplete_uncached_watches:
            errors.append(_uncached_watches_message(incomplete_uncached_watches))
        metrics.pages_fetched = fetched_pages()
        fallback_lot_keys.difference_update(observed_lot_keys)
        for error_index, affected_entries in batch_error_entries.items():
            retained_keys = {
                lot.cache_key
                for entry in affected_entries
                for lot in self._cached_lots_for_entry(entry)
                if lot.cache_key in fallback_lot_keys
            }
            errors[error_index] += _cached_fallback_message(len(retained_keys), new_changed_only)
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
            coverage=coverage(),
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
        catalog_only: bool = False,
        prior_observations: dict[str, str] | None = None,
    ) -> tuple[list[NormalizedLot], list[NormalizedLot], bool]:
        result_checks = result_checks if result_checks is not None else _PostedResultChecks()
        errors = errors if errors is not None else []
        notices = notices if notices is not None else []
        public_browser = adapter.source == "Invaluable" and getattr(fetcher, "uses_natural_catalog_requests", False) is True
        page_url = entry.url
        visited_pages: set[str] = set()
        observed_keys: set[str] = set()
        lots: list[NormalizedLot] = []
        complete = True
        use_preloaded_search = preloaded_search is not None
        # Saved HTML identifies Invaluable lots by the stable URL reference;
        # its live feed can identify the same lot by a numeric objectID.
        watched_lots = self.cache.lots_for_watch_url(entry.url) if adapter.source == "Invaluable" else []
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
                try:
                    page = adapter.fetch_search_page(page_url, fetcher)
                except SourceAccessBlocked as exc:
                    raise _CatalogAccessBlocked(str(exc)) from exc
            if stop.is_set():
                raise WatchlistStopped("Watchlist refresh stopped by the user.")
            cards = [(card, self._reconcile_search_identity(card, watched_lots))
                     for card in adapter.parse_search_page(page, page_url, entry.artist)]
            catalog_reader = getattr(adapter, "_catalog_result", None)
            catalog_result = catalog_reader(page) if adapter.source == "Invaluable" and callable(catalog_reader) else None
            if catalog_result is not None and catalog_result["hits"] and not cards:
                raise SourceAccessError(
                    "Invaluable returned lots that could not be read as this artist's calendar records; "
                    "the search has not been verified as empty."
                )
            if len(visited_pages) > 1 and cards and all(card.cache_key in observed_keys for card, _cached in cards):
                raise SourceAccessError(
                    "The source repeated an earlier catalog page; existing lots have been retained."
                )
            for card, cached in cards:
                if stop.is_set():
                    raise WatchlistStopped("Watchlist refresh stopped by the user.")
                if catalog_only and not _has_usable_search_data(card):
                    # This is a partial HTTP snapshot awaiting browser recovery.
                    # Keep only dated cards; the browser can retrieve missing dates.
                    continue
                if card.cache_key in observed_keys:
                    continue
                observed_keys.add(card.cache_key)
                search_hash = card.content_hash
                if cached and cached.search_hash == search_hash and not adapter.needs_detail(cached.lot):
                    lot = cached.lot
                    lot.artist_watchlist_name = entry.artist or lot.artist
                    metrics.cache_hits += 1
                else:
                    lot = card
                    if cached:
                        _retain_missing_static_fields(lot, cached.lot)
                    if (adapter.needs_detail(lot) and lot.lot_url
                            and not ((catalog_only or public_browser) and _has_usable_search_data(lot))):
                        detail_blocked = adapter.source in result_checks.blocked_detail_sources or (
                            adapter.source == "Invaluable" and result_checks.access_blocked
                        )
                        if detail_blocked:
                            if not _has_usable_search_data(lot):
                                raise SourceAccessError(
                                    "A search result has no usable title or auction date, and lot-page access is unavailable."
                                )
                            notice = (
                                f"Further {adapter.source} lot-page requests were skipped while access is unavailable. "
                                "Dated search results were retained for calendar sync; their lot-page details remain unverified."
                            )
                            if notice not in notices:
                                notices.append(notice)
                            result_checks.detail_errors_by_watch.setdefault(entry.url, notice)
                        else:
                            try:
                                detail_page = adapter.fetch_lot_detail(lot.lot_url, fetcher)
                                if stop.is_set():
                                    raise WatchlistStopped("Watchlist refresh stopped by the user.")
                                metrics.detail_pages_fetched += 1
                                detail = adapter.parse_lot_detail(detail_page, lot.lot_url, entry.artist)
                                if detail is None:
                                    raise SourceAccessError("The lot page did not contain recognizable auction details.")
                            except WatchlistStopped:
                                raise
                            except Exception as exc:
                                if stop.is_set():
                                    raise WatchlistStopped("Watchlist refresh stopped by the user.") from exc
                                result_checks.details[lot.cache_key] = None
                                if isinstance(exc, SourceAccessBlocked):
                                    result_checks.blocked_detail_sources.add(adapter.source)
                                    if adapter.source == "Invaluable":
                                        result_checks.access_blocked = True
                                if not _has_usable_search_data(lot):
                                    raise
                                message = " ".join(str(exc).split())[:300]
                                detail_error = (
                                    f"{entry.watch_label} ({adapter.source}), lot {lot.lot_number or lot.source_lot_id}: "
                                    f"lot-page details could not be verified: {message}. "
                                    "The dated search result was retained for calendar sync."
                                )
                                result_checks.detail_errors_by_watch[entry.url] = detail_error
                                errors.append(detail_error)
                            else:
                                result_checks.details[lot.cache_key] = detail
                                self._note_sold_access(detail, result_checks, notices)
                                lot = adapter.merge_detail(lot, detail)
                if stop.is_set():
                    raise WatchlistStopped("Watchlist refresh stopped by the user.")
                transition = self.cache.upsert(
                    lot,
                    watch_url=entry.url,
                    search_hash=search_hash,
                    observed_at=observed_at,
                )
                if observed_lot_keys is not None:
                    observed_lot_keys.add(lot.cache_key)
                previous_transition = (prior_observations or {}).get(lot.cache_key)
                if previous_transition in {"new", "changed", "unchanged"}:
                    # Re-reading a partial HTTP card in browser recovery is one
                    # observation for change counts, preserving the first new lot.
                    priority = {"new": 2, "changed": 1, "unchanged": 0}
                    if priority[previous_transition] >= priority[transition]:
                        lot.status = previous_transition
                        lots.append(lot)
                        continue
                    field = "unchanged_lots" if previous_transition == "unchanged" else previous_transition + "_lots"
                    setattr(metrics, field, max(0, getattr(metrics, field) - 1))
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
        if stop.is_set():
            raise WatchlistStopped("Watchlist refresh stopped by the user.")
        if complete and adapter.source == "Invaluable":
            lots = self._refresh_posted_results(
                entry, adapter, fetcher, stop, metrics, observed_at, lots,
                result_checks, errors, observed_lot_keys, notices,
            )
        if stop.is_set():
            raise WatchlistStopped("Watchlist refresh stopped by the user.")
        ended = self.cache.mark_missing_ended(
            entry.url, observed_keys, observed_at, covered_until=getattr(adapter, "catalog_end", None),
        ) if complete else []
        if observed_lot_keys is not None:
            observed_lot_keys.update(lot.cache_key for lot in ended)
        return lots, ended, complete

    def _reconcile_search_identity(self, card: NormalizedLot, watched_lots: list[NormalizedLot]) -> CacheLookup | None:
        cached = self.cache.lookup(card)
        if card.source == "Invaluable":
            reference = _invaluable_lot_reference(card.lot_url)
            if cached and reference and _invaluable_lot_reference(cached.lot.lot_url) not in {"", reference}:
                raise SourceAccessError("Invaluable returned conflicting lot identities; existing lots were retained.")
            if cached is None and reference:
                matches = [lot for lot in watched_lots
                           if lot.source == card.source and _invaluable_lot_reference(lot.lot_url) == reference]
                if len(matches) > 1:
                    raise SourceAccessError("An Invaluable lot matches multiple cached identities; existing lots were retained.")
                if matches:
                    cached = self.cache.lookup(matches[0])
        if cached:
            card.source_lot_id = cached.lot.source_lot_id
            card.lot_url = cached.lot.lot_url or card.lot_url
            card.content_hash = card.calculate_content_hash()
        return cached

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
            if getattr(fetcher, "uses_natural_catalog_requests", False) is True:
                # Browser recovery is for the upcoming calendar. Retain sold
                # history, but avoid optional detail pages that can block it.
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
