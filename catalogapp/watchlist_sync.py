"""Upload normalized Artist Watchlist results to the private website calendar."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urlparse

import requests

from catalogapp.artprice_artist_links import artist_identity_key
from catalogapp.watchlist_models import NormalizedLot


class CalendarSyncError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CalendarSyncResult:
    received: int
    created: int
    updated: int
    ended: int

    def summary(self) -> str:
        return (
            f"Website calendar synced: {self.received} lots "
            f"({self.created} new, {self.updated} updated, {self.ended} ended)."
        )


def _calendar_payload(lot: NormalizedLot) -> dict:
    """Return only normalized public auction fields; never local bookmark or cache data."""

    return {
        "source": lot.source,
        "source_lot_id": lot.source_lot_id,
        "artist": lot.artist,
        "artist_watchlist_name": lot.artist_watchlist_name,
        "title": lot.title,
        "medium": lot.medium,
        "auction_house": lot.auction_house,
        "sale_title": lot.sale_title,
        "lot_number": lot.lot_number,
        "start_at": lot.start_at,
        "end_at": lot.end_at,
        "location": lot.location,
        "estimate_low": lot.estimate_low,
        "estimate_high": lot.estimate_high,
        "currency": lot.currency,
        "current_bid": lot.current_bid,
        "bid_count": lot.bid_count,
        "lot_url": lot.lot_url,
        "sale_url": lot.sale_url,
        "first_seen_at": lot.first_seen_at,
        "last_seen_at": lot.last_seen_at,
        "status": lot.status,
    }


def _validated_base_url(base_url: str) -> str:
    normalized = (base_url or "").strip().rstrip("/")
    parsed = urlparse(normalized)
    local_host = (parsed.hostname or "").casefold() in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and not (parsed.scheme == "http" and local_host):
        raise CalendarSyncError("Calendar sync requires HTTPS (HTTP is allowed only for localhost testing).")
    if not parsed.netloc or parsed.username or parsed.password:
        raise CalendarSyncError("Calendar sync website URL is invalid.")
    return normalized


def sync_watchlist_lots(
    lots: list[NormalizedLot],
    *,
    base_url: str,
    api_key: str,
    artist_artprice_links: Mapping[str, str] | None = None,
    session=requests,
    timeout: tuple[int, int] = (10, 120),
) -> CalendarSyncResult:
    if not api_key:
        raise CalendarSyncError("CATALOG_API_KEY is required for website calendar sync.")
    endpoint = f"{_validated_base_url(base_url)}/calendar/sync/"
    artist_links: dict[str, tuple[str, str]] = {}
    for name, url in (artist_artprice_links or {}).items():
        key = artist_identity_key(name)
        if not key or not str(url or "").strip():
            continue
        value = (str(name).strip(), str(url).strip())
        existing = artist_links.get(key)
        if existing is not None and existing[1] != value[1]:
            raise CalendarSyncError(f"Conflicting Artprice links were matched to {value[0]}.")
        artist_links[key] = min(existing, value, key=lambda item: item[0].casefold()) if existing else value
    try:
        response = session.post(
            endpoint,
            headers={"X-API-KEY": api_key, "Accept": "application/json"},
            json={
                "lots": [_calendar_payload(lot) for lot in lots],
                "artist_links": [
                    {"name": name, "artprice_url": url}
                    for name, url in sorted(artist_links.values(), key=lambda item: item[0].casefold())
                ],
            },
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise CalendarSyncError(f"Could not reach the website calendar: {exc}") from exc

    try:
        response_payload = response.json()
    except (TypeError, ValueError):
        response_payload = {}
    if response.status_code >= 400:
        message = response_payload.get("error") if isinstance(response_payload, dict) else ""
        raise CalendarSyncError(message or f"Website calendar returned HTTP {response.status_code}.")
    if not isinstance(response_payload, dict) or not response_payload.get("ok"):
        raise CalendarSyncError("Website calendar returned an unexpected response.")
    return CalendarSyncResult(
        received=int(response_payload.get("received", 0)),
        created=int(response_payload.get("created", 0)),
        updated=int(response_payload.get("updated", 0)),
        ended=int(response_payload.get("ended", 0)),
    )
