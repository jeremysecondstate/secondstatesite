"""Upload normalized Artist Watchlist results to the private website calendar."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

import requests

from catalogapp.watchlist_models import NormalizedLot


class CalendarSyncError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CalendarSyncResult:
    received: int
    created: int
    updated: int
    ended: int
    reminder_status: str = ""
    reminder_summary: str = ""
    reminder_sent: int = 0
    reminder_skipped: int = 0
    reminder_failed: int = 0

    def summary(self) -> str:
        calendar_summary = (
            f"Website calendar synced: {self.received} lots "
            f"({self.created} new, {self.updated} updated, {self.ended} ended)."
        )
        return f"{calendar_summary} {self.reminder_summary}".strip()


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
    session=requests,
    timeout: tuple[int, int] = (10, 120),
) -> CalendarSyncResult:
    if not api_key:
        raise CalendarSyncError("CATALOG_API_KEY is required for website calendar sync.")
    endpoint = f"{_validated_base_url(base_url)}/calendar/sync/"
    try:
        response = session.post(
            endpoint,
            headers={"X-API-KEY": api_key, "Accept": "application/json"},
            json={"lots": [_calendar_payload(lot) for lot in lots]},
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
    reminder_payload = response_payload.get("reminders")
    if not isinstance(reminder_payload, dict):
        reminder_payload = {}
    return CalendarSyncResult(
        received=int(response_payload.get("received", 0)),
        created=int(response_payload.get("created", 0)),
        updated=int(response_payload.get("updated", 0)),
        ended=int(response_payload.get("ended", 0)),
        reminder_status=str(reminder_payload.get("status") or ""),
        reminder_summary=str(reminder_payload.get("summary") or ""),
        reminder_sent=int(reminder_payload.get("sent", 0)),
        reminder_skipped=int(reminder_payload.get("skipped", 0)),
        reminder_failed=int(reminder_payload.get("failed", 0)),
    )
