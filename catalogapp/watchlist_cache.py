"""SQLite cache for incremental bookmark watchlist refreshes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import threading
from typing import Any, Iterable

from catalogapp.watchlist_models import NormalizedLot


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

    def upsert(
        self,
        lot: NormalizedLot,
        *,
        watch_url: str,
        search_hash: str,
        observed_at: datetime | None = None,
    ) -> str:
        now = _iso(observed_at)
        with self._lock, self.connection:
            existing = self.connection.execute(
                "SELECT content_hash, first_seen_at FROM lots WHERE cache_key = ?", (lot.cache_key,)
            ).fetchone()
            if existing is None:
                transition = "new"
                lot.first_seen_at = now
            else:
                transition = "unchanged" if existing["content_hash"] == lot.content_hash else "changed"
                lot.first_seen_at = existing["first_seen_at"]
            lot.last_seen_at = now
            lot.status = transition
            self.connection.execute(
                """
                INSERT INTO lots (
                    cache_key, source, source_lot_id, canonical_url, payload_json, content_hash,
                    search_hash, first_seen_at, last_seen_at, status, active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
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
                    active=1
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
                    transition,
                ),
            )
            self.connection.execute(
                """
                INSERT INTO watch_memberships (watch_url, cache_key, last_seen_at, active)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(watch_url, cache_key) DO UPDATE SET
                    last_seen_at=excluded.last_seen_at,
                    active=1
                """,
                (watch_url, lot.cache_key, now),
            )
        return transition

    def mark_missing_ended(
        self,
        watch_url: str,
        observed_keys: Iterable[str],
        observed_at: datetime | None = None,
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
                lot.status = "ended"
                lot.last_seen_at = now
                self.connection.execute(
                    "UPDATE lots SET payload_json = ?, status = 'ended', active = 0 WHERE cache_key = ?",
                    (json.dumps(lot.to_dict(), ensure_ascii=False, sort_keys=True), cache_key),
                )
                ended.append(lot)
        return ended

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
