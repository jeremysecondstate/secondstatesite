"""Small, bounded server-side client for on-demand LiveArt auction research.

Only the endpoints needed by the private Calendar are exposed.  In particular,
there is no unbounded similar-artwork lookup or automatic background polling.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from typing import Any, Mapping

import requests


BASE_URL = "https://api.liveart.ai"
DEFAULT_TIMEOUT = (3.05, 10)
# One request at a time and just under 60/minute within this server process.
MIN_REQUEST_INTERVAL_SECONDS = 1.05
MAX_RETRY_AFTER_SECONDS = 5.0
MAX_PAGE_SIZE = 25

_REQUEST_LOCK = threading.Lock()
_NEXT_REQUEST_AT = 0.0

_SALE_FILTERS = frozenset(
    {
        "id",
        "number",
        "auction_house_id",
        "name__ilike",
        "status",
        "location",
        "start_datetime__gte",
        "start_datetime__lte",
        "end_datetime__gte",
        "end_datetime__lte",
        "sort",
    }
)
_ARTIST_FILTERS = frozenset({"q"})
_ARTWORK_FILTERS = frozenset(
    {
        "artist_id",
        "search",
        "category_id",
        "materials",
        "last_lot_status",
        "sort",
    }
)
_LOT_FILTERS = frozenset(
    {
        "id",
        "sale_id",
        "lot_num",
        "status",
        "auction_house_id",
        "sale_auction_house_id",
        "artist_id",
        "artwork_id",
        "category_id",
        "search",
        "sale_datetime__gte",
        "sale_datetime__lte",
        "hammer_price_usd__gte",
        "hammer_price_usd__lte",
        "sort",
    }
)


class LiveArtConfigurationError(RuntimeError):
    """The server has no usable LiveArt API key."""


class LiveArtAPIError(RuntimeError):
    """A LiveArt request failed without exposing credentials or response bodies."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


@dataclass(frozen=True)
class LiveArtPage:
    items: list[dict[str, Any]]
    has_more: bool
    total_count: int | None
    retrieved_at: str
    data_units: Decimal | None
    request_id: str | None
    remaining_data_units: Decimal | None
    limit: int
    offset: int


def has_api_key() -> bool:
    """Check configuration without logging or returning the key."""

    return bool(os.environ.get("LIVEART_API_KEY", "").strip())


def verify_sold_hammer_usd(lot: Mapping[str, Any]) -> Decimal | None:
    """Return only a positive, authenticated sold-lot USD hammer price.

    Premium, estimate and last-bid values are intentionally never substitutes.
    A public-response lot has no ``price`` object and returns ``None``.
    """

    if lot.get("status") != "sold":
        return None
    price = lot.get("price")
    if not isinstance(price, Mapping):
        return None
    raw = price.get("hammer_usd")
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not value.is_finite() or value <= 0 or value > Decimal("1000000000000"):
        return None
    return value


def _decimal_header(headers: Mapping[str, str], name: str) -> Decimal | None:
    try:
        value = Decimal(headers[name])
    except (KeyError, InvalidOperation, TypeError, ValueError):
        return None
    return value if value.is_finite() else None


def _retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        try:
            date = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        seconds = (date - datetime.now(timezone.utc)).total_seconds()
    if not 0 <= seconds < float("inf"):
        return None
    return seconds


def _pace_request(interval: float) -> None:
    """Call under ``_REQUEST_LOCK`` to pace across client instances."""

    global _NEXT_REQUEST_AT
    now = time.monotonic()
    if now < _NEXT_REQUEST_AT:
        time.sleep(_NEXT_REQUEST_AT - now)
    _NEXT_REQUEST_AT = time.monotonic() + interval


class LiveArtClient:
    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        api_key: str | None = None,
        timeout: tuple[float, float] = DEFAULT_TIMEOUT,
        _min_interval_seconds: float = MIN_REQUEST_INTERVAL_SECONDS,
    ) -> None:
        self._api_key = (api_key if api_key is not None else os.environ.get("LIVEART_API_KEY", "")).strip()
        if not self._api_key:
            raise LiveArtConfigurationError("LIVEART_API_KEY is not configured on the server.")
        self._session = session or requests.Session()
        self._timeout = timeout
        self._min_interval_seconds = _min_interval_seconds

    def get_usage(self) -> dict[str, Any]:
        """Return the authenticated, zero-DU account usage response."""

        payload, _, _ = self._get("/v1/usage")
        if not isinstance(payload, dict):
            raise LiveArtAPIError("LiveArt returned an invalid usage response.")
        return payload

    def list_sales(self, *, limit: int = 10, offset: int = 0, **filters: Any) -> LiveArtPage:
        return self._list("/v1/sales", filters, _SALE_FILTERS, limit=limit, offset=offset)

    def list_artists(self, *, q: str, limit: int = 3, offset: int = 0) -> LiveArtPage:
        """Look up a few artist identities by name or known synonym."""

        if not isinstance(q, str) or not q.strip():
            raise ValueError("An artist search name is required.")
        return self._list(
            "/v1/artists", {"q": q.strip()}, _ARTIST_FILTERS,
            limit=limit, offset=offset, items_key="artists", total_key="total",
        )

    def list_artworks(self, *, limit: int = 5, offset: int = 0, **filters: Any) -> LiveArtPage:
        """Search a small page of canonical artworks by artist and title."""

        return self._list("/v1/artworks", filters, _ARTWORK_FILTERS, limit=limit, offset=offset)

    def list_lots(self, *, limit: int = 20, offset: int = 0, **filters: Any) -> LiveArtPage:
        return self._list("/v1/lots", filters, _LOT_FILTERS, limit=limit, offset=offset)

    def _list(
        self,
        path: str,
        filters: dict[str, Any],
        allowed: frozenset[str],
        *,
        limit: int,
        offset: int,
        items_key: str = "items",
        total_key: str = "total_count",
    ) -> LiveArtPage:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_PAGE_SIZE:
            raise ValueError(f"LiveArt page limit must be between 1 and {MAX_PAGE_SIZE}.")
        if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= 100:
            raise ValueError("LiveArt offset must be between 0 and 100.")
        unknown = set(filters) - allowed
        if unknown:
            raise ValueError(f"Unsupported LiveArt filter: {', '.join(sorted(unknown))}.")
        params = {key: value for key, value in filters.items() if value is not None and value != ""}
        narrowing = set(params) - {"sort", "status"}
        if not narrowing:
            raise ValueError("A narrowing LiveArt filter is required to control Data Unit use.")
        params.update(limit=limit, offset=offset)
        payload, headers, retrieved_at = self._get(path, params=params)
        items = payload.get(items_key) if isinstance(payload, dict) else None
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise LiveArtAPIError("LiveArt returned an invalid list response.")
        total = payload.get(total_key)
        total_count = total if isinstance(total, int) and not isinstance(total, bool) else None
        has_more = payload.get("has_more")
        if not isinstance(has_more, bool):
            has_more = total_count is not None and offset + len(items) < total_count
        return LiveArtPage(
            items=items,
            has_more=has_more,
            total_count=total_count,
            retrieved_at=retrieved_at,
            data_units=_decimal_header(headers, "X-LiveArt-DataUnits"),
            request_id=headers.get("X-LiveArt-Request-Id") or payload.get("_request_id"),
            remaining_data_units=_decimal_header(headers, "X-LiveArt-DataUnits-Remaining"),
            limit=limit,
            offset=offset,
        )

    def _get(
        self, path: str, *, params: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any], Mapping[str, str], str]:
        headers = {"Authorization": f"Bearer {self._api_key}", "Accept": "application/json"}
        # Locking also avoids two simultaneous research clicks racing the trial's
        # single-concurrent-request limit within one application process.
        with _REQUEST_LOCK:
            for attempt in range(2):
                _pace_request(self._min_interval_seconds)
                try:
                    response = self._session.get(
                        f"{BASE_URL}{path}", headers=headers, params=params, timeout=self._timeout
                    )
                except requests.Timeout as exc:
                    raise LiveArtAPIError("LiveArt timed out; please try again.") from exc
                except requests.RequestException as exc:
                    raise LiveArtAPIError("LiveArt is unavailable; please try again.") from exc

                if response.status_code == 429:
                    retry_after = _retry_after_seconds(response.headers.get("Retry-After"))
                    if attempt == 0 and retry_after is not None and retry_after <= MAX_RETRY_AFTER_SECONDS:
                        time.sleep(retry_after)
                        continue
                    raise LiveArtAPIError(
                        "LiveArt rate limit reached; please try again later.",
                        status_code=429,
                        retry_after=retry_after,
                    )
                if response.status_code >= 400:
                    message = (
                        "LiveArt rejected the API key."
                        if response.status_code in (401, 403)
                        else f"LiveArt request failed (HTTP {response.status_code})."
                    )
                    raise LiveArtAPIError(message, status_code=response.status_code)
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise LiveArtAPIError("LiveArt returned invalid JSON.") from exc
                if not isinstance(payload, dict):
                    raise LiveArtAPIError("LiveArt returned an invalid response.")
                return payload, response.headers, datetime.now(timezone.utc).isoformat()
        raise AssertionError("LiveArt retry loop unexpectedly exhausted")
