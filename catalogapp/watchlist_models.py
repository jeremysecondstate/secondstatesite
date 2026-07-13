"""Stable local lot schema shared by adapters, cache, UI, and exports."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import re
from typing import Any, Iterable

from catalogapp.bookmark_watchlist import canonicalize_bookmark_url


@dataclass(slots=True)
class NormalizedLot:
    source: str
    source_lot_id: str
    artist: str
    artist_watchlist_name: str
    title: str
    medium: str = ""
    auction_house: str = ""
    sale_title: str = ""
    lot_number: str = ""
    start_at: str = ""
    end_at: str = ""
    location: str = ""
    estimate_low: float | None = None
    estimate_high: float | None = None
    currency: str = ""
    current_bid: float | None = None
    lot_url: str = ""
    sale_url: str = ""
    image_url: str = ""
    first_seen_at: str = ""
    last_seen_at: str = ""
    content_hash: str = ""
    status: str = "unchanged"
    ambiguities: list[str] = field(default_factory=list)
    duplicate_of: str = ""

    def __post_init__(self) -> None:
        self.lot_url = canonicalize_bookmark_url(self.lot_url) or self.lot_url
        self.sale_url = canonicalize_bookmark_url(self.sale_url) or self.sale_url
        if not self.content_hash:
            self.content_hash = self.calculate_content_hash()

    @property
    def cache_key(self) -> str:
        identity = self.source_lot_id.strip() or self.lot_url.strip()
        return f"{self.source.casefold()}:{identity}"

    @property
    def relevant_at(self) -> str:
        return self.end_at or self.start_at

    def visible_content(self) -> dict[str, Any]:
        ignored = {
            "artist_watchlist_name",
            "first_seen_at",
            "last_seen_at",
            "content_hash",
            "status",
            "ambiguities",
            "duplicate_of",
        }
        return {key: value for key, value in asdict(self).items() if key not in ignored}

    def calculate_content_hash(self) -> str:
        payload = json.dumps(self.visible_content(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "NormalizedLot":
        names = {item.name for item in fields(cls)}
        return cls(**{key: value for key, value in payload.items() if key in names})

    def apply_enrichment(self, payload: dict[str, Any]) -> None:
        mapping = {
            "normalized_artist": "artist",
            "medium": "medium",
            "end_at": "end_at",
            "duplicate_group": "duplicate_of",
        }
        for source_key, target_key in mapping.items():
            value = payload.get(source_key)
            if value not in (None, ""):
                setattr(self, target_key, value)
        self.ambiguities = []


def parse_lot_datetime(value: str) -> tuple[datetime | None, bool]:
    raw = (value or "").strip()
    if not raw:
        return None, False
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        parsed_date = date.fromisoformat(raw)
        return datetime.combine(parsed_date, time.min, tzinfo=timezone.utc), True
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None, False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed, False


def lot_within_horizon(lot: NormalizedLot, now: datetime, horizon_days: int) -> bool:
    parsed, _all_day = parse_lot_datetime(lot.relevant_at)
    if parsed is None:
        return True
    aware_now = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    return aware_now - timedelta(days=1) <= parsed <= aware_now + timedelta(days=horizon_days + 1)


def _duplicate_signature(lot: NormalizedLot) -> tuple[str, ...]:
    def normalized(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", (value or "").casefold()).strip()

    when, _all_day = parse_lot_datetime(lot.relevant_at)
    day = when.date().isoformat() if when else ""
    return (
        normalized(lot.artist or lot.artist_watchlist_name),
        normalized(lot.title),
        normalized(lot.auction_house),
        normalized(lot.lot_number),
        day,
    )


def mark_cross_source_duplicates(lots: Iterable[NormalizedLot]) -> list[NormalizedLot]:
    """Mark deterministic likely duplicates without hiding any source record."""

    result = list(lots)
    seen: dict[tuple[str, ...], NormalizedLot] = {}
    for lot in result:
        signature = _duplicate_signature(lot)
        if not signature[0] or not signature[1] or not signature[4]:
            continue
        original = seen.get(signature)
        if original and original.source.casefold() != lot.source.casefold():
            lot.duplicate_of = original.cache_key
        else:
            seen[signature] = lot
    return result
