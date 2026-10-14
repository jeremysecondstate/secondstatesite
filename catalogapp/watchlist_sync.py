"""Upload normalized Artist Watchlist results to the private website calendar."""

from __future__ import annotations

from dataclasses import dataclass
import json
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
    images_received: int = 0
    sold_prices_received: int = 0

    def summary(self) -> str:
        message = (
            f"Website calendar synced: {self.received} lots "
            f"({self.created} new, {self.updated} updated, {self.ended} ended)."
        )
        if self.images_received:
            message += f" {self.images_received} saved artwork images synced."
        if self.sold_prices_received:
            noun = "price" if self.sold_prices_received == 1 else "prices"
            message += f" {self.sold_prices_received} sold {noun} synced."
        return message


def _calendar_payload(lot: NormalizedLot) -> dict:
    """Return only normalized public auction fields; never local bookmark or cache data."""

    payload = {
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
        "sold_price": lot.sold_price,
        "sold_currency": lot.sold_currency,
        "lot_url": lot.lot_url,
        "sale_url": lot.sale_url,
        "image_url": lot.image_url,
        "first_seen_at": lot.first_seen_at,
        "last_seen_at": lot.last_seen_at,
        "status": lot.status,
    }
    if lot.saved_image_base64:
        payload["saved_image_base64"] = lot.saved_image_base64
    return payload


def _sync_batches(lots: list[NormalizedLot], artist_links: list[dict]) -> list[dict]:
    """Keep each JSON request under the website's 2 MB limit, including images."""

    limit = 1_800_000
    batch = {"lots": [], "artist_links": artist_links}
    size = len(json.dumps(batch).encode("utf-8"))
    if size > limit or len(artist_links) > 1000:
        raise CalendarSyncError("Too many artist links for one calendar sync.")
    batches = []
    for lot in lots:
        record = _calendar_payload(lot)
        record_size = len(json.dumps(record).encode("utf-8")) + 2
        if record_size > limit - 100:
            raise CalendarSyncError("A saved artwork image is too large to sync. Import the saved catalog again.")
        if size + record_size > limit or len(batch["lots"]) >= 1000:
            batches.append(batch)
            batch = {"lots": [], "artist_links": []}
            size = len(json.dumps(batch).encode("utf-8"))
        batch["lots"].append(record)
        size += record_size
    batches.append(batch)
    return batches


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
    batches = _sync_batches(lots, [
        {"name": name, "artprice_url": url}
        for name, url in sorted(artist_links.values(), key=lambda item: item[0].casefold())
    ])
    totals = dict(received=0, created=0, updated=0, ended=0, images_received=0, sold_prices_received=0)
    for batch in batches:
        try:
            response = session.post(
                endpoint,
                headers={"X-API-KEY": api_key, "Accept": "application/json"},
                json=batch,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            raise CalendarSyncError(
                "Could not reach the website calendar. Retry Sync Website Calendar; "
                "any completed batches will be updated without duplicates."
            ) from exc

        try:
            response_payload = response.json()
        except (TypeError, ValueError):
            response_payload = {}
        if response.status_code >= 400:
            message = response_payload.get("error") if isinstance(response_payload, dict) else ""
            raise CalendarSyncError(message or f"Website calendar returned HTTP {response.status_code}.")
        if not isinstance(response_payload, dict) or not response_payload.get("ok"):
            raise CalendarSyncError("Website calendar returned an unexpected response.")
        expected_images = sum(bool(record.get("saved_image_base64")) for record in batch["lots"])
        expected_sold_prices = sum(record.get("sold_price") is not None for record in batch["lots"])
        try:
            counts = {key: int(response_payload.get(key, 0)) for key in totals}
        except (TypeError, ValueError) as exc:
            raise CalendarSyncError("Website calendar returned invalid sync counts.") from exc
        if counts["received"] != len(batch["lots"]):
            raise CalendarSyncError("The website did not confirm every lot. Retry Sync Website Calendar.")
        if counts["images_received"] != expected_images:
            raise CalendarSyncError(
                "Lot details reached the website, but saved artwork images were not confirmed. "
                "Deploy the website's saved-image update, then click Sync Website Calendar again."
            )
        if counts["sold_prices_received"] != expected_sold_prices:
            raise CalendarSyncError(
                "Lot details reached the website, but sold prices were not confirmed. "
                "Deploy the website's sold-price update and migration, then click Sync Website Calendar again."
            )
        for key in totals:
            totals[key] += counts[key]
    return CalendarSyncResult(**totals)
