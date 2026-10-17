"""SQLite cache for incremental bookmark watchlist refreshes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import threading
from typing import Any, Iterable

from catalogapp.bookmark_watchlist import BookmarkEntry
from catalogapp.watchlist_coverage import WatchCoverage
from catalogapp.watchlist_models import NormalizedLot, lot_within_horizon, parse_lot_datetime


@dataclass(frozen=True, slots=True)
class CacheLookup:
    lot: NormalizedLot
    search_hash: str


class WatchlistCache:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._create_schema()

    def close(self) -> None:
        with self._lock:
            self.connection.close()

    def __enter__(self) -> "WatchlistCache":
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()

    def _create_schema(self) -> None:
        with self._lock, self.connection:
            self.connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS lots (
                    cache_key TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    source_lot_id TEXT NOT NULL,
                    canonical_url TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    search_hash TEXT NOT NULL DEFAULT '',
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1
                );
                CREATE INDEX IF NOT EXISTS lots_source_lot_id ON lots(source, source_lot_id);
                CREATE INDEX IF NOT EXISTS lots_canonical_url ON lots(source, canonical_url);
                CREATE TABLE IF NOT EXISTS watch_memberships (
                    watch_url TEXT NOT NULL,
                    cache_key TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY (watch_url, cache_key)
                );
                CREATE TABLE IF NOT EXISTS source_runs (
                    watch_url TEXT PRIMARY KEY,
                    last_success_at TEXT,
                    last_error_at TEXT,
                    last_error TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS watch_coverage (
                    watch_url TEXT PRIMARY KEY,
                    state TEXT NOT NULL DEFAULT 'pending',
                    last_attempt_at TEXT NOT NULL DEFAULT '',
                    detail TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS enrichments (
                    content_hash TEXT NOT NULL,
                    model TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (content_hash, model)
                );
                """
            )
            columns = {row["name"] for row in self.connection.execute("PRAGMA table_info(lots)")}
            if "search_hash" not in columns:
                self.connection.execute("ALTER TABLE lots ADD COLUMN search_hash TEXT NOT NULL DEFAULT ''")
            coverage_columns = {row["name"] for row in self.connection.execute("PRAGMA table_info(watch_coverage)")}
            if "covered_until" not in coverage_columns:
                self.connection.execute("ALTER TABLE watch_coverage ADD COLUMN covered_until TEXT NOT NULL DEFAULT ''")

    def lookup(self, lot: NormalizedLot) -> CacheLookup | None:
        with self._lock:
            row = self.connection.execute(
                "SELECT payload_json, search_hash FROM lots WHERE cache_key = ?",
                (lot.cache_key,),
            ).fetchone()
            if row is None and lot.lot_url:
                row = self.connection.execute(
                    "SELECT payload_json, search_hash FROM lots WHERE source = ? AND canonical_url = ?",
                    (lot.source, lot.lot_url),
                ).fetchone()
        if not row:
            return None
        return CacheLookup(NormalizedLot.from_dict(json.loads(row["payload_json"])), row["search_hash"])

    def get(self, cache_key: str) -> NormalizedLot | None:
        with self._lock:
            row = self.connection.execute(
                "SELECT payload_json FROM lots WHERE cache_key = ?", (cache_key,)
            ).fetchone()
        return NormalizedLot.from_dict(json.loads(row["payload_json"])) if row else None

    def active_lots_for_watch_url(self, watch_url: str) -> list[NormalizedLot]:
        """Return the last known active lots for a bookmark after a source outage."""

        with self._lock:
            rows = self.connection.execute(
                """
                SELECT lots.payload_json
                FROM watch_memberships
                JOIN lots ON lots.cache_key = watch_memberships.cache_key
                WHERE watch_memberships.watch_url = ?
                  AND watch_memberships.active = 1
                  AND lots.active = 1
                ORDER BY lots.last_seen_at, lots.cache_key
                """,
                (watch_url,),
            ).fetchall()
        return [NormalizedLot.from_dict(json.loads(row["payload_json"])) for row in rows]

    def lots_for_watch_url(self, watch_url: str) -> list[NormalizedLot]:
        """Include ended memberships so posted results can arrive after disappearance."""

        with self._lock:
            rows = self.connection.execute(
                """
                SELECT lots.payload_json FROM watch_memberships
                JOIN lots ON lots.cache_key = watch_memberships.cache_key
                WHERE watch_memberships.watch_url = ?
                ORDER BY lots.cache_key
                """,
                (watch_url,),
            ).fetchall()
        return [NormalizedLot.from_dict(json.loads(row["payload_json"])) for row in rows]

    def upsert(
        self,
        lot: NormalizedLot,
        *,
        watch_url: str,
        search_hash: str,
        observed_at: datetime | None = None,
        active: bool = True,
    ) -> str:
        now = _iso(observed_at)
        with self._lock, self.connection:
            existing = self.connection.execute(
                "SELECT content_hash, first_seen_at, payload_json FROM lots WHERE cache_key = ?", (lot.cache_key,)
            ).fetchone()
            if existing is None:
                transition = "new"
                lot.first_seen_at = now
            else:
                previous = NormalizedLot.from_dict(json.loads(existing["payload_json"]))
                if lot.sold_price is None and previous.sold_price is not None:
                    lot.sold_price = previous.sold_price
                    lot.sold_currency = previous.sold_currency or previous.currency
                    lot.content_hash = lot.calculate_content_hash()
                transition = "unchanged" if existing["content_hash"] == lot.content_hash else "changed"
                lot.first_seen_at = existing["first_seen_at"]
            lot.last_seen_at = now
            lot.status = transition
            active = active and lot.sold_price is None
            if not active and lot.sold_price is None:
                lot.status = "ended"
            self.connection.execute(
                """
                INSERT INTO lots (
                    cache_key, source, source_lot_id, canonical_url, payload_json, content_hash,
                    search_hash, first_seen_at, last_seen_at, status, active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    source=excluded.source,
                    source_lot_id=excluded.source_lot_id,
                    canonical_url=excluded.canonical_url,
                    payload_json=excluded.payload_json,
                    content_hash=excluded.content_hash,
                    search_hash=excluded.search_hash,
                    first_seen_at=excluded.first_seen_at,
                    last_seen_at=excluded.last_seen_at,
                    status=excluded.status,
                    active=excluded.active
                """,
                (
                    lot.cache_key,
                    lot.source,
                    lot.source_lot_id,
                    lot.lot_url,
                    json.dumps(lot.to_dict(), ensure_ascii=False, sort_keys=True),
                    lot.content_hash,
                    search_hash,
                    lot.first_seen_at,
                    lot.last_seen_at,
                    lot.status,
                    int(active),
                ),
            )
            self.connection.execute(
                """
                INSERT INTO watch_memberships (watch_url, cache_key, last_seen_at, active)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(watch_url, cache_key) DO UPDATE SET
                    last_seen_at=excluded.last_seen_at,
                    active=excluded.active
                """,
                (watch_url, lot.cache_key, now, int(active)),
            )
        return transition

    def mark_missing_ended(
        self,
        watch_url: str,
        observed_keys: Iterable[str],
        observed_at: datetime | None = None,
        *,
        covered_until: datetime | None = None,
    ) -> list[NormalizedLot]:
        seen = set(observed_keys)
        ended: list[NormalizedLot] = []
        now = _iso(observed_at)
        with self._lock, self.connection:
            rows = self.connection.execute(
                "SELECT cache_key FROM watch_memberships WHERE watch_url = ? AND active = 1",
                (watch_url,),
            ).fetchall()
            missing = [row["cache_key"] for row in rows if row["cache_key"] not in seen]
            for cache_key in missing:
                if covered_until is not None:
                    prior = self.get(cache_key)
                    when, _all_day = parse_lot_datetime(prior.relevant_at) if prior else (None, False)
                    # A narrower query says nothing about later or undated lots.
                    # The source predicate includes either normalized date, so
                    # this check also handles different auction/closing times.
                    if when is None or when > covered_until:
                        continue
                self.connection.execute(
                    "UPDATE watch_memberships SET active = 0, last_seen_at = ? WHERE watch_url = ? AND cache_key = ?",
                    (now, watch_url, cache_key),
                )
                active_count = self.connection.execute(
                    "SELECT COUNT(*) FROM watch_memberships WHERE cache_key = ? AND active = 1",
                    (cache_key,),
                ).fetchone()[0]
                if active_count:
                    continue
                row = self.connection.execute(
                    "SELECT payload_json FROM lots WHERE cache_key = ?", (cache_key,)
                ).fetchone()
                if not row:
                    continue
                lot = NormalizedLot.from_dict(json.loads(row["payload_json"]))
                if lot.sold_price is not None:
                    # A second bookmark disappearing cannot overwrite the
                    # explicit result transition recorded through the first.
                    continue
                lot.status = "ended"
                lot.last_seen_at = now
                self.connection.execute(
                    "UPDATE lots SET payload_json = ?, status = 'ended', active = 0 WHERE cache_key = ?",
                    (json.dumps(lot.to_dict(), ensure_ascii=False, sort_keys=True), cache_key),
                )
                ended.append(lot)
        return ended

    def import_shared_lot(self, lot: NormalizedLot, *, watch_urls: Iterable[str]) -> bool:
        """Restore Calendar data without recording a new auction-source observation.

        A download is not a source check. Preserve its original timestamps and
        never replace a newer local observation or retire lots absent remotely.
        """
        incoming = NormalizedLot.from_dict(lot.to_dict())
        urls = tuple(dict.fromkeys(url for url in watch_urls if url))
        if not urls:
            return False
        with self._lock, self.connection:
            existing = self.connection.execute(
                "SELECT payload_json, search_hash, active FROM lots WHERE cache_key = ?",
                (incoming.cache_key,),
            ).fetchone()
            chosen = incoming
            search_hash = ""
            changed = existing is None
            if existing is not None:
                previous = NormalizedLot.from_dict(json.loads(existing["payload_json"]))
                if not _newer(incoming.last_seen_at, previous.last_seen_at):
                    chosen = previous
                    search_hash = existing["search_hash"]
                else:
                    changed = True
                    if incoming.sold_price is None and previous.sold_price is not None:
                        chosen.sold_price = previous.sold_price
                        chosen.sold_currency = previous.sold_currency or previous.currency
                    if not incoming.saved_image_base64:
                        chosen.saved_image_base64 = previous.saved_image_base64
                first = [stamp for stamp in (incoming.first_seen_at, previous.first_seen_at) if stamp]
                if first:
                    chosen.first_seen_at = min(first, key=_timestamp)
            chosen.content_hash = chosen.calculate_content_hash()
            active = chosen.status != "ended" and chosen.sold_price is None
            if existing is not None and chosen is not incoming:
                active = bool(existing["active"])
            self.connection.execute(
                """
                INSERT INTO lots (
                    cache_key, source, source_lot_id, canonical_url, payload_json, content_hash,
                    search_hash, first_seen_at, last_seen_at, status, active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    payload_json=excluded.payload_json, content_hash=excluded.content_hash,
                    search_hash=excluded.search_hash, first_seen_at=excluded.first_seen_at,
                    last_seen_at=excluded.last_seen_at, status=excluded.status,
                    active=excluded.active, canonical_url=excluded.canonical_url
                """,
                (chosen.cache_key, chosen.source, chosen.source_lot_id, chosen.lot_url,
                 json.dumps(chosen.to_dict(), ensure_ascii=False, sort_keys=True), chosen.content_hash,
                 search_hash, chosen.first_seen_at, chosen.last_seen_at, chosen.status, int(active)),
            )
            for watch_url in urls:
                membership = self.connection.execute(
                    "SELECT last_seen_at FROM watch_memberships WHERE watch_url = ? AND cache_key = ?",
                    (watch_url, chosen.cache_key),
                ).fetchone()
                if membership is not None and not _newer(incoming.last_seen_at, membership["last_seen_at"]):
                    continue
                self.connection.execute(
                    """
                    INSERT INTO watch_memberships (watch_url, cache_key, last_seen_at, active)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(watch_url, cache_key) DO UPDATE SET
                        last_seen_at=excluded.last_seen_at, active=excluded.active
                    """,
                    (watch_url, chosen.cache_key, incoming.last_seen_at, int(active)),
                )
        return changed

    def import_shared_coverage(self, coverage: WatchCoverage) -> bool:
        """Merge dated source-check evidence; cached lots alone prove no coverage."""
        if coverage.state not in {"verified", "empty", "partial", "blocked", "pending"}:
            raise ValueError("Unknown watch coverage state")
        if coverage.state != "pending" and not parse_lot_datetime(coverage.checked_at)[0]:
            raise ValueError("Shared source coverage requires its original check time")
        with self._lock, self.connection:
            previous = self.connection.execute(
                "SELECT last_attempt_at FROM watch_coverage WHERE watch_url = ?", (coverage.watch_url,),
            ).fetchone()
            if previous is not None and not _newer(coverage.checked_at, previous["last_attempt_at"]):
                return False
            self.connection.execute(
                """
                INSERT INTO watch_coverage (watch_url, state, last_attempt_at, detail, covered_until)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(watch_url) DO UPDATE SET
                    state=excluded.state, last_attempt_at=excluded.last_attempt_at,
                    detail=excluded.detail, covered_until=excluded.covered_until
                """,
                (coverage.watch_url, coverage.state, coverage.checked_at,
                 " ".join(coverage.detail.split())[:500], coverage.covered_until),
            )
        return True

    def record_source_success(self, watch_url: str, observed_at: datetime | None = None) -> None:
        now = _iso(observed_at)
        with self._lock, self.connection:
            self.connection.execute(
                """
                INSERT INTO source_runs (watch_url, last_success_at, last_error_at, last_error)
                VALUES (?, ?, NULL, '')
                ON CONFLICT(watch_url) DO UPDATE SET
                    last_success_at=excluded.last_success_at,
                    last_error=''
                """,
                (watch_url, now),
            )

    def record_watch_coverage(
        self,
        watch_url: str,
        state: str,
        *,
        detail: str = "",
        observed_at: datetime | None = None,
        attempted: bool = True,
        covered_until: datetime | None = None,
    ) -> None:
        """Record catalog coverage without confusing failed optional details with it.

        A skipped watch is still unresolved, but does not move to the back of
        the recovery queue as if a request had actually been attempted.
        """
        if state not in {"verified", "empty", "partial", "blocked", "pending"}:
            raise ValueError("Unknown watch coverage state")
        checked_at = _iso(observed_at) if attempted else ""
        message = " ".join((detail or "").split())[:500]
        with self._lock, self.connection:
            self.connection.execute(
                """
                INSERT INTO watch_coverage (watch_url, state, last_attempt_at, detail, covered_until)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(watch_url) DO UPDATE SET
                    state=excluded.state,
                    last_attempt_at=CASE WHEN ? THEN excluded.last_attempt_at
                        ELSE watch_coverage.last_attempt_at END,
                    detail=excluded.detail,
                    covered_until=excluded.covered_until
                """,
                (watch_url, state, checked_at, message, _iso(covered_until) if covered_until else "", int(attempted)),
            )

    def coverage_for_entries(
        self, entries: Iterable[BookmarkEntry], *, observed_at: datetime | None = None,
        horizon_days: int | None = None,
    ) -> list[WatchCoverage]:
        """Read coverage after restart; older caches start honestly as pending.

        Lot counts do not imply coverage: a verified zero is different from an
        unread search, and cached lots alone never prove a complete catalog.
        """
        result: list[WatchCoverage] = []
        with self._lock:
            for entry in entries:
                row = self.connection.execute(
                    "SELECT state, last_attempt_at, detail, covered_until FROM watch_coverage WHERE watch_url = ?",
                    (entry.url,),
                ).fetchone()
                count = self.connection.execute(
                    """
                    SELECT COUNT(*) FROM watch_memberships
                    JOIN lots ON lots.cache_key = watch_memberships.cache_key
                    WHERE watch_memberships.watch_url = ?
                      AND watch_memberships.active = 1 AND lots.active = 1
                    """,
                    (entry.url,),
                ).fetchone()[0]
                state = row["state"] if row else "pending"
                detail = row["detail"] if row else "No complete source check recorded yet."
                covered_until = row["covered_until"] if row else ""
                if observed_at is not None:
                    now = observed_at if observed_at.tzinfo else observed_at.replace(tzinfo=timezone.utc)
                    now = now.astimezone(timezone.utc)
                    if horizon_days is not None:
                        count = sum(lot_within_horizon(lot, now, horizon_days)
                                    for lot in self.active_lots_for_watch_url(entry.url))
                    if state in {"verified", "empty"}:
                        checked, _ = parse_lot_datetime(row["last_attempt_at"])
                        end, _ = parse_lot_datetime(covered_until)
                        if checked is None or checked.astimezone(timezone.utc).date() != now.date():
                            state, detail = "pending", "A fresh source check is needed for today's calendar window."
                        elif (end is not None and horizon_days is not None
                              and end.date() < (now + timedelta(days=horizon_days)).date()):
                            state, detail = "pending", "The requested calendar window extends beyond the last complete check."
                        else:
                            state = "verified" if count else "empty"
                result.append(WatchCoverage(
                    artist=entry.watch_label, source=entry.source, watch_url=entry.url,
                    state=state, lot_count=count,
                    checked_at=row["last_attempt_at"] if row else "",
                    detail=detail, covered_until=covered_until,
                ))
        return result

    def record_source_error(self, watch_url: str, message: str, observed_at: datetime | None = None) -> None:
        now = _iso(observed_at)
        safe_message = " ".join((message or "Unknown source error").split())[:500]
        with self._lock, self.connection:
            self.connection.execute(
                """
                INSERT INTO source_runs (watch_url, last_success_at, last_error_at, last_error)
                VALUES (?, NULL, ?, ?)
                ON CONFLICT(watch_url) DO UPDATE SET
                    last_error_at=excluded.last_error_at,
                    last_error=excluded.last_error
                """,
                (watch_url, now, safe_message),
            )

    def get_enrichment(self, content_hash: str, model: str) -> dict[str, Any] | None:
        with self._lock:
            row = self.connection.execute(
                "SELECT payload_json FROM enrichments WHERE content_hash = ? AND model = ?",
                (content_hash, model),
            ).fetchone()
        return json.loads(row["payload_json"]) if row else None

    def put_enrichment(self, content_hash: str, model: str, payload: dict[str, Any]) -> None:
        with self._lock, self.connection:
            self.connection.execute(
                """
                INSERT INTO enrichments (content_hash, model, payload_json, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(content_hash, model) DO UPDATE SET
                    payload_json=excluded.payload_json,
                    created_at=excluded.created_at
                """,
                (
                    content_hash,
                    model,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    _iso(),
                ),
            )

    def update_payload(self, lot: NormalizedLot) -> None:
        """Persist local enrichment fields without changing the deterministic source hash."""

        with self._lock, self.connection:
            self.connection.execute(
                "UPDATE lots SET payload_json = ? WHERE cache_key = ?",
                (json.dumps(lot.to_dict(), ensure_ascii=False, sort_keys=True), lot.cache_key),
            )


def _iso(value: datetime | None = None) -> str:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.isoformat()


def _timestamp(value: str) -> datetime:
    parsed, _ = parse_lot_datetime(value)
    return parsed.astimezone(timezone.utc) if parsed else datetime.min.replace(tzinfo=timezone.utc)


def _newer(incoming: str, previous: str) -> bool:
    return _timestamp(incoming) > _timestamp(previous)
