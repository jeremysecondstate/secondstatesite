"""Parse saved Artprice results and calculate maximum auction bids.

The functions in this module operate entirely on text and normalized values.
They do not read uploaded files, write source HTML, or contact Artprice.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import (
    Decimal,
    InvalidOperation,
    ROUND_HALF_EVEN,
    localcontext,
)
from typing import Any
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit


PRELOADED_STATE_MARKER = "window.__PRELOADED_STATE__"
REACT_STORE_NAME = "artpriceStore"
SUPPORTED_METHODS = frozenset({"median", "mean", "recent", "max", "min", "manual"})
DEFAULT_CURRENCY = "USD"
MAX_MONEY_AMOUNT = Decimal("1000000000000")
MAX_RECENT_COUNT = 10_000
MAX_PREMIUM_PCT = 100
MAX_PREMIUM_ROWS = 101
MONEY_QUANTUM = Decimal("0.01")
PERCENT_QUANTUM = Decimal("0.01")
_MONEY_CLEAN_RE = re.compile(r"[^\d.\-]")


class ArtpriceAnalysisError(ValueError):
    """A validation or parsing error that is safe to show to a staff user."""


@dataclass(frozen=True)
class AuctionResult:
    """One normalized sold auction result."""

    title: str
    hammer_price: Decimal
    sale_date: str
    auction_house: str
    lot_number: str
    estimate_low: Decimal | None
    estimate_high: Decimal | None
    provider_id: str | None = None
    provider_url: str | None = None
    image_url: str | None = None
    artist: str | None = None
    category: str | None = None
    medium: str | None = None
    edition: str | None = None
    size: str | None = None
    signature: str | None = None
    condition: str | None = None
    location: str | None = None
    source_ids: tuple[str, ...] = ()
    source_filenames: tuple[str, ...] = ()


def money_to_decimal(value: Any) -> Decimal | None:
    """Convert a displayed money value such as ``$ 1,266`` to a Decimal.

    Unavailable, non-finite, malformed, and unreasonably large values return
    ``None``. Artprice's textual "not sold" values are also unavailable.
    """

    if value is None or isinstance(value, bool):
        return None

    if isinstance(value, Decimal):
        amount = value
    elif isinstance(value, (int, float)):
        try:
            amount = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
    else:
        text = str(value).strip()
        if not text or "not sold" in text.lower() or len(text) > 128:
            return None

        cleaned = _MONEY_CLEAN_RE.sub("", text.replace(",", ""))
        if not cleaned or cleaned in {"-", ".", "-."}:
            return None
        try:
            amount = Decimal(cleaned)
        except InvalidOperation:
            return None

    if (
        not amount.is_finite()
        or len(amount.as_tuple().digits) > 128
        or amount.copy_abs() > MAX_MONEY_AMOUNT
    ):
        return None
    return amount


def _reject_json_constant(_value: str) -> None:
    raise ArtpriceAnalysisError("The embedded Artprice data contains an invalid number.")


class _ReactStoreParser(HTMLParser):
    """Extract Artprice JSON data without executing saved page scripts."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self._capturing: str | None = None
        self._chunks: list[str] = []
        self.stores: list[str] = []
        self.searchbars: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "script":
            return
        attributes = dict(attrs)
        if (attributes.get("type") or "").casefold() != "application/json":
            return
        if attributes.get("data-js-react-on-rails-store") == REACT_STORE_NAME:
            self._capturing = "store"
        elif (attributes.get("data-component-name") or "").startswith("Lots::Searchbars::"):
            self._capturing = "searchbar"
        if self._capturing:
            self._chunks = []

    def handle_data(self, data: str) -> None:
        if self._capturing:
            self._chunks.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._capturing:
            if self._capturing == "store":
                self.stores.append("".join(self._chunks))
            else:
                self.searchbars.append("".join(self._chunks))
            self._capturing = None
            self._chunks = []


def _react_page_data(html_text: str) -> tuple[dict[str, Any] | None, list[str] | None]:
    parser = _ReactStoreParser()
    parser.feed(html_text)
    parser.close()
    if not parser.stores:
        return None, None
    if len(parser.stores) != 1:
        raise ArtpriceAnalysisError("The saved Artprice page contains ambiguous results data.")
    try:
        state = json.loads(
            parser.stores[0], parse_float=Decimal, parse_constant=_reject_json_constant,
        )
    except ArtpriceAnalysisError:
        raise
    except (json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise ArtpriceAnalysisError("Could not decode the embedded Artprice data.") from exc
    if not isinstance(state, dict):
        raise ArtpriceAnalysisError("The embedded Artprice data is not a JSON object.")

    active_ids: list[str] | None = None
    for raw_searchbar in parser.searchbars:
        try:
            searchbar = json.loads(raw_searchbar, parse_constant=_reject_json_constant)
        except ArtpriceAnalysisError:
            raise
        except (json.JSONDecodeError, RecursionError, ValueError) as exc:
            raise ArtpriceAnalysisError("Could not decode the active Artprice search data.") from exc
        if not isinstance(searchbar, dict) or "lotIds" not in searchbar:
            continue
        raw_ids = searchbar["lotIds"]
        if (
            not isinstance(raw_ids, list)
            or any(
                isinstance(raw_id, bool)
                or not isinstance(raw_id, (int, str))
                or not str(raw_id).isdecimal()
                for raw_id in raw_ids
            )
        ):
            raise ArtpriceAnalysisError("The active Artprice search lot IDs are invalid.")
        found_ids = [str(raw_id) for raw_id in raw_ids]
        if active_ids is not None and active_ids != found_ids:
            raise ArtpriceAnalysisError("The saved Artprice page contains ambiguous search results.")
        active_ids = found_ids
    return state, active_ids


def extract_preloaded_state(html_text: str) -> dict[str, Any]:
    """Decode either supported embedded Artprice results format.

    ``raw_decode`` permits normal JavaScript trailing text such as a semicolon
    without relying on the saved page's line structure.
    """

    if not isinstance(html_text, str):
        raise ArtpriceAnalysisError("The uploaded Artprice page could not be read as text.")

    marker_index = html_text.find(PRELOADED_STATE_MARKER)
    if marker_index == -1:
        state, _active_ids = _react_page_data(html_text)
        if state is not None:
            return state
        raise ArtpriceAnalysisError(
            "Could not find Artprice preloaded results data in the uploaded page."
        )

    equals_index = html_text.find("=", marker_index + len(PRELOADED_STATE_MARKER))
    if equals_index == -1:
        raise ArtpriceAnalysisError(
            "The Artprice preloaded-state assignment is incomplete."
        )

    start = html_text.find("{", equals_index + 1)
    if start == -1:
        raise ArtpriceAnalysisError(
            "Could not find the Artprice preloaded-state JSON object."
        )

    decoder = json.JSONDecoder(
        parse_float=Decimal,
        parse_constant=_reject_json_constant,
    )
    try:
        state, _end = decoder.raw_decode(html_text[start:])
    except ArtpriceAnalysisError:
        raise
    except (json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise ArtpriceAnalysisError(
            "Could not decode the embedded Artprice data."
        ) from exc

    if not isinstance(state, dict):
        raise ArtpriceAnalysisError(
            "The embedded Artprice preloaded state is not a JSON object."
        )
    return state


def _looks_like_lot(value: Mapping[str, Any]) -> bool:
    return (
        "price" in value
        and ("saleDtStart" in value or "auctioneerName" in value)
        and ("title" in value or "id" in value)
    )


def find_lot_dicts(
    node: Any, *, active_lot_ids: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """Find the largest coherent group of auction lots in a state tree.

    Artprice has moved the results container between releases, so traversal is
    iterative and structure-agnostic. Selecting one sibling group avoids
    mixing the search results with lot-shaped records from unrelated
    cached/account branches. React pages may also provide explicit current
    search lot IDs; those take precedence over cached entities.
    """

    active_ids = set(active_lot_ids) if active_lot_ids is not None else None

    def included(lot: Mapping[str, Any]) -> bool:
        return active_ids is None or str(lot.get("id")) in active_ids

    candidates: list[list[dict[str, Any]]] = []
    standalone_lots: list[dict[str, Any]] = []

    stack = [node]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            if _looks_like_lot(value) and included(value):
                standalone_lots.append(value)

            children = list(value.values())
            dict_lots = [
                child
                for child in children
                if isinstance(child, dict) and _looks_like_lot(child) and included(child)
            ]
            if dict_lots:
                candidates.append(dict_lots)
            stack.extend(reversed(children))
        elif isinstance(value, list):
            list_lots = [
                child
                for child in value
                if isinstance(child, dict) and _looks_like_lot(child) and included(child)
            ]
            if list_lots:
                candidates.append(list_lots)
            stack.extend(reversed(value))

    if candidates:
        return max(candidates, key=len)
    if standalone_lots:
        return standalone_lots
    if active_ids is not None:
        raise ArtpriceAnalysisError(
            "No active search lot records were found in the saved Artprice page."
        )
    raise ArtpriceAnalysisError("No auction lot records were found in the embedded Artprice data.")


def _react_lot_dicts(
    state: Mapping[str, Any], active_lot_ids: list[str] | None,
) -> list[dict[str, Any]]:
    """Use the React store's lot entities, not other cached state branches."""

    entities = state.get("dbEntities")
    if not isinstance(entities, Mapping):
        raise ArtpriceAnalysisError("No Artprice lot entities were found in the saved page.")
    lots = entities.get("lots")
    if not isinstance(lots, (dict, list)):
        raise ArtpriceAnalysisError("No Artprice lot entities were found in the saved page.")
    if isinstance(lots, dict) and isinstance(lots.get("data"), (dict, list)):
        lots = lots["data"]
    return find_lot_dicts(lots, active_lot_ids=active_lot_ids)


def _currency_value(value: Any) -> str | None:
    current = value
    while isinstance(current, Mapping):
        nested_value = None
        for key in ("code", "value", "id", "name"):
            if key in current:
                nested_value = current[key]
                break
        if nested_value is None or nested_value is current:
            return None
        current = nested_value

    if current is None:
        return None
    text = str(current).strip()
    if not text:
        return None
    normalized = re.sub(r"[\s_-]+", "", text).upper()
    if normalized in {"$", "USD", "USDOLLAR", "USDOLLARS"}:
        return DEFAULT_CURRENCY
    return text.upper()


def _extract_currency(state: Mapping[str, Any]) -> str | None:
    preferences = state.get("preferences")
    if isinstance(preferences, Mapping) and "currency" in preferences:
        return _currency_value(preferences.get("currency"))

    stack: list[Any] = [state]
    while stack:
        value = stack.pop()
        if isinstance(value, Mapping):
            nested_preferences = value.get("preferences")
            if isinstance(nested_preferences, Mapping) and "currency" in nested_preferences:
                found = _currency_value(nested_preferences.get("currency"))
                if found is not None:
                    return found
            stack.extend(reversed(list(value.values())))
        elif isinstance(value, list):
            stack.extend(reversed(value))
    return None


def _require_usd(currency: Any) -> str:
    normalized = _currency_value(currency) if currency is not None else DEFAULT_CURRENCY
    if normalized is None:
        normalized = DEFAULT_CURRENCY
    if normalized != DEFAULT_CURRENCY:
        raise ArtpriceAnalysisError(
            "This Artprice page is not set to USD. Save the results page again "
            "with the Artprice currency set to USD."
        )
    return DEFAULT_CURRENCY


def _is_not_sold_status(value: Any) -> bool:
    if isinstance(value, bool) or value is None:
        return False
    try:
        return Decimal(str(value).strip()) == Decimal("3")
    except (InvalidOperation, ValueError):
        return False


def _sale_date_key(result: AuctionResult) -> datetime:
    try:
        return datetime.strptime(result.sale_date, "%d %b %Y")
    except (TypeError, ValueError):
        return datetime.min


def _rounded_money(value: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = 50
        rounded = value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_EVEN)
    if rounded == 0:
        return Decimal("0.00")
    return rounded


def _optional_lot_text(value: Any) -> str | None:
    if value is None or isinstance(value, (dict, list, bool)):
        return None
    text = str(value).strip()
    return text[:500] if text else None


def _artprice_lot_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate or len(candidate) > 2000 or any(ord(char) < 32 for char in candidate) or "\\" in candidate:
        return None
    try:
        parsed = urlsplit(candidate)
        if parsed.scheme or parsed.netloc:
            if (
                parsed.scheme != "https"
                or parsed.hostname not in {"artprice.com", "www.artprice.com"}
                or parsed.username
                or parsed.password
                or parsed.port not in (None, 443)
            ):
                return None
        elif not candidate.startswith("/") or candidate.startswith("//"):
            return None
        if not re.match(r"^/artist/\d+/", parsed.path):
            return None
    except ValueError:
        return None
    return candidate if parsed.scheme else f"https://www.artprice.com{candidate}"


def _lot_location(lot: Mapping[str, Any]) -> str | None:
    """Keep the source's explicit location; never infer it from the house."""
    direct = _optional_lot_text(lot.get("location"))
    if direct:
        return direct
    return ", ".join(dict.fromkeys(
        value for key in ("saleCity", "saleCountry")
        if (value := _optional_lot_text(lot.get(key)))
    )) or None


def _artprice_image_url(value: Any) -> str | None:
    """Allow only explicit Artprice artwork-image URLs, never local saved-page paths."""
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if (
        not candidate or len(candidate) > 2000
        or any(char.isspace() or ord(char) < 32 for char in candidate)
        or "\\" in candidate
    ):
        return None
    try:
        parsed = urlsplit(candidate)
        decoded_path = unquote(parsed.path)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in {"imgprivate2.artprice.com", "imgpublic.artprice.com"}
            or parsed.username or parsed.password
            or parsed.port not in (None, 443)
            or not parsed.path.startswith("/lots/")
            or parsed.path == "/lots/"
            or any(part in {".", ".."} for part in decoded_path.split("/"))
            or "\\" in decoded_path
            or parsed.fragment
        ):
            return None
    except ValueError:
        return None
    return candidate


def _lot_image_url(lot: Mapping[str, Any]) -> str | None:
    """Keep the first valid image attached to this lot's own embedded record."""
    image_urls = lot.get("imageUrls")
    if isinstance(image_urls, list):
        for value in image_urls:
            if image_url := _artprice_image_url(value):
                return image_url
    return _artprice_image_url(lot.get("imageUrl"))


def _require_two_decimal_places(value: Decimal, *, label: str) -> Decimal:
    rounded = _rounded_money(value)
    if value != rounded:
        raise ArtpriceAnalysisError(f"{label} must have at most two decimal places.")
    return rounded


def _normalize_results(lots: Iterable[Mapping[str, Any]]) -> list[AuctionResult]:
    results: list[AuctionResult] = []
    seen: set[tuple] = set()

    for lot in lots:
        hammer = money_to_decimal(lot.get("price"))
        if hammer is None or _is_not_sold_status(lot.get("lotstatus")):
            continue
        hammer = _rounded_money(hammer)

        estimation = lot.get("estimation")
        if not isinstance(estimation, Mapping):
            estimation = {}
        estimate_low = money_to_decimal(estimation.get("low"))
        estimate_high = money_to_decimal(estimation.get("high"))
        raw_id = _optional_lot_text(lot.get("id"))
        provider_id = raw_id if raw_id and raw_id.isdecimal() else None

        result = AuctionResult(
            title=str(lot.get("title") or "Untitled"),
            hammer_price=hammer,
            sale_date=str(lot.get("saleDtStart") or ""),
            auction_house=str(lot.get("auctioneerName") or ""),
            lot_number=str(lot.get("number") or ""),
            estimate_low=(
                _rounded_money(estimate_low) if estimate_low is not None else None
            ),
            estimate_high=(
                _rounded_money(estimate_high) if estimate_high is not None else None
            ),
            provider_id=provider_id,
            provider_url=_artprice_lot_url(lot.get("url")),
            image_url=_lot_image_url(lot),
            artist=_optional_lot_text(lot.get("artistOrAssociation")),
            category=_optional_lot_text(lot.get("category")),
            medium=_optional_lot_text(lot.get("technique")),
            edition=_optional_lot_text(lot.get("numberAndEdition")),
            size=_optional_lot_text(lot.get("dimension")),
            signature=_optional_lot_text(lot.get("signature")),
            condition=_optional_lot_text(lot.get("condition")),
            location=_lot_location(lot),
            source_ids=tuple(lot.get("_source_ids") or ()),
            source_filenames=tuple(lot.get("_source_filenames") or ()),
        )
        dedupe_key = ("provider", provider_id) if provider_id else (
            result.title, result.sale_date, result.hammer_price,
            result.auction_house, result.lot_number, result.artist,
        )
        if dedupe_key not in seen:
            seen.add(dedupe_key)
            results.append(result)

    if not results:
        raise ArtpriceAnalysisError(
            "The Artprice page contained no sold lots with numeric hammer prices."
        )
    return sorted(results, key=_sale_date_key, reverse=True)


def parse_auction_results(html_text: str) -> list[AuctionResult]:
    """Extract normalized, deduplicated sold results from saved HTML text."""

    state = extract_preloaded_state(html_text)
    if PRELOADED_STATE_MARKER not in html_text:
        active_ids = _react_page_data(html_text)[1]
        return _normalize_results(_react_lot_dicts(state, active_ids))
    return _normalize_results(find_lot_dicts(state))


def _coerce_decimal(
    value: Any,
    *,
    label: str,
    allow_none: bool = False,
) -> Decimal | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        if allow_none:
            return None
        raise ArtpriceAnalysisError(f"{label} is required.")
    if isinstance(value, bool):
        raise ArtpriceAnalysisError(f"{label} must be a valid number.")

    text = str(value).strip()
    if len(text) > 128:
        raise ArtpriceAnalysisError(f"{label} is too large.")
    try:
        number = value if isinstance(value, Decimal) else Decimal(text)
    except (InvalidOperation, ValueError):
        raise ArtpriceAnalysisError(f"{label} must be a valid number.") from None

    if not number.is_finite():
        raise ArtpriceAnalysisError(f"{label} must be a finite number.")
    if number.copy_abs() > MAX_MONEY_AMOUNT:
        raise ArtpriceAnalysisError(f"{label} is too large.")
    return number


def _coerce_nonnegative_money(value: Any, *, label: str) -> Decimal:
    number = _coerce_decimal(value, label=label)
    assert number is not None
    if number < 0:
        raise ArtpriceAnalysisError(f"{label} cannot be negative.")
    return _require_two_decimal_places(number, label=label)


def _coerce_integer(value: Any, *, label: str) -> int:
    number = _coerce_decimal(value, label=label)
    assert number is not None
    integral = number.to_integral_value()
    if number != integral:
        raise ArtpriceAnalysisError(f"{label} must be a whole number.")
    return int(integral)


def _normalize_method(method: Any) -> str:
    normalized = str(method or "").strip().lower()
    if normalized not in SUPPORTED_METHODS:
        raise ArtpriceAnalysisError("Select a supported resale valuation method.")
    return normalized


def choose_resale_value(
    prices: Iterable[Decimal | int | float | str],
    method: str,
    manual_value: Decimal | int | float | str | None = None,
    recent_count: int = 3,
) -> Decimal:
    """Choose an expected resale hammer from newest-first sold prices."""

    values: list[Decimal] = []
    for price in prices:
        value = _coerce_decimal(price, label="Sold hammer price")
        assert value is not None
        values.append(value)
    if not values:
        raise ArtpriceAnalysisError("No sold hammer prices are available.")

    normalized_method = _normalize_method(method)
    normalized_recent_count = _coerce_integer(recent_count, label="Recent record count")
    if normalized_recent_count < 1:
        raise ArtpriceAnalysisError("Recent record count must be at least 1.")
    if normalized_recent_count > MAX_RECENT_COUNT:
        raise ArtpriceAnalysisError("Recent record count is too large.")

    normalized_manual = _coerce_decimal(
        manual_value,
        label="Manual resale value",
        allow_none=True,
    )
    if normalized_manual is not None and normalized_manual <= 0:
        raise ArtpriceAnalysisError("Manual resale value must be greater than zero.")

    if normalized_method == "manual":
        if normalized_manual is None:
            raise ArtpriceAnalysisError(
                "Manual resale value must be greater than zero when using "
                "the manual method."
            )
        return normalized_manual

    if normalized_method == "max":
        return max(values)
    if normalized_method == "min":
        return min(values)

    selected = values
    if normalized_method == "recent":
        selected = values[: min(normalized_recent_count, len(values))]

    ordered = sorted(selected)
    midpoint = len(ordered) // 2
    if normalized_method == "mean":
        return sum(values, Decimal("0")) / Decimal(len(values))
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / Decimal("2")


def _validate_premium_range(premium_min: Any, premium_max: Any) -> tuple[int, int]:
    minimum = _coerce_integer(premium_min, label="Minimum buyer premium")
    maximum = _coerce_integer(premium_max, label="Maximum buyer premium")
    if minimum < 0 or maximum < minimum:
        raise ArtpriceAnalysisError("Buyer-premium range is invalid.")
    if maximum > MAX_PREMIUM_PCT:
        raise ArtpriceAnalysisError(
            f"Buyer-premium percentages cannot exceed {MAX_PREMIUM_PCT}%."
        )
    if maximum - minimum + 1 > MAX_PREMIUM_ROWS:
        raise ArtpriceAnalysisError("Buyer-premium range would create too many rows.")
    return minimum, maximum


def calculate_bid_rows(
    expected_resale_hammer: Decimal | int | float | str,
    premium_min: int,
    premium_max: int,
    inbound_shipping: Decimal | int | float | str,
    target_profit: Decimal | int | float | str,
    seller_commission_pct: Decimal | int | float | str,
    outbound_shipping: Decimal | int | float | str,
    other_resale_costs: Decimal | int | float | str,
) -> tuple[Decimal, list[dict[str, Decimal | int]]]:
    """Calculate net proceeds and inclusive integer premium rows."""

    expected = _coerce_decimal(
        expected_resale_hammer,
        label="Expected resale hammer",
    )
    assert expected is not None
    shipping = _coerce_nonnegative_money(inbound_shipping, label="Inbound shipping")
    profit = _coerce_nonnegative_money(target_profit, label="Target profit")
    outbound = _coerce_nonnegative_money(
        outbound_shipping,
        label="Outbound shipping",
    )
    other_costs = _coerce_nonnegative_money(
        other_resale_costs,
        label="Other resale costs",
    )
    commission = _coerce_decimal(
        seller_commission_pct,
        label="Seller commission",
    )
    assert commission is not None
    if commission < 0 or commission >= 100:
        raise ArtpriceAnalysisError(
            "Seller commission must be at least 0% and less than 100%."
        )
    commission = _require_two_decimal_places(
        commission,
        label="Seller commission",
    )
    minimum, maximum = _validate_premium_range(premium_min, premium_max)

    with localcontext() as context:
        context.prec = 50
        seller_rate = commission / Decimal("100")
        net_resale_proceeds = (
            expected * (Decimal("1") - seller_rate) - outbound - other_costs
        )
        available = net_resale_proceeds - profit - shipping
        if available <= 0:
            raise ArtpriceAnalysisError(
                "No positive bid is possible with these assumptions. Increase "
                "the expected resale value or reduce costs or the profit target."
            )

        rows: list[dict[str, Decimal | int]] = []
        for premium_pct in range(minimum, maximum + 1):
            premium_rate = Decimal(premium_pct) / Decimal("100")
            max_bid = available / (Decimal("1") + premium_rate)
            buyers_premium = max_bid * premium_rate
            all_in_acquisition = max_bid + buyers_premium + shipping
            projected_profit = net_resale_proceeds - all_in_acquisition
            rows.append(
                {
                    "premium_pct": premium_pct,
                    "max_bid": max_bid,
                    "buyers_premium": buyers_premium,
                    "shipping": shipping,
                    "all_in_acquisition": all_in_acquisition,
                    "projected_profit": projected_profit,
                }
            )

    return net_resale_proceeds, rows


def _two_decimal_string(value: Decimal) -> str:
    rounded = _rounded_money(value)
    return format(rounded, ".2f")


def _result_to_json(result: AuctionResult) -> dict[str, Any]:
    normalized = {
        "sale_date": result.sale_date,
        "hammer_price": _two_decimal_string(result.hammer_price),
        "currency": DEFAULT_CURRENCY,
        "auction_house": result.auction_house,
        "title": result.title,
        "lot_number": result.lot_number,
        "estimate_low": (
            _two_decimal_string(result.estimate_low)
            if result.estimate_low is not None
            else None
        ),
        "estimate_high": (
            _two_decimal_string(result.estimate_high)
            if result.estimate_high is not None
            else None
        ),
    }
    for key in ("provider_id", "provider_url", "image_url", "artist", "category", "medium", "edition", "size", "signature", "condition", "location"):
        value = getattr(result, key)
        if value is not None:
            normalized[key] = value
    if result.source_ids:
        normalized["source_ids"] = list(result.source_ids)
        normalized["source_filenames"] = list(result.source_filenames)
    return normalized


def _results_from_comparables(
    comparables: Iterable[Mapping[str, Any]],
) -> list[AuctionResult]:
    lots: list[dict[str, Any]] = []
    try:
        iterator = iter(comparables)
    except TypeError as exc:
        raise ArtpriceAnalysisError("Saved sold comparables are invalid.") from exc

    for comparable in iterator:
        if not isinstance(comparable, Mapping):
            raise ArtpriceAnalysisError("Saved sold comparables are invalid.")
        lots.append(
            {
                "price": comparable.get("hammer_price"),
                "saleDtStart": comparable.get("sale_date"),
                "auctioneerName": comparable.get("auction_house"),
                "title": comparable.get("title"),
                "number": comparable.get("lot_number"),
                "estimation": {
                    "low": comparable.get("estimate_low"),
                    "high": comparable.get("estimate_high"),
                },
                "id": comparable.get("provider_id"),
                "url": comparable.get("provider_url"),
                "imageUrl": comparable.get("image_url"),
                "artistOrAssociation": comparable.get("artist"),
                "category": comparable.get("category"),
                "technique": comparable.get("medium"),
                "numberAndEdition": comparable.get("edition"),
                "dimension": comparable.get("size"),
                "signature": comparable.get("signature"),
                "condition": comparable.get("condition"),
                "location": comparable.get("location"),
                "_source_ids": comparable.get("source_ids"),
                "_source_filenames": comparable.get("source_filenames"),
            }
        )
    return _normalize_results(lots)


def artprice_sale_identity(comparable: Mapping[str, Any]) -> tuple:
    def clean(key):
        return " ".join(str(comparable.get(key) or "").casefold().split())

    sale_date = clean("sale_date")
    for pattern in ("%d %b %Y", "%d %B %Y", "%Y-%m-%d"):
        try:
            sale_date = datetime.strptime(sale_date[:10] if pattern == "%Y-%m-%d" else sale_date, pattern).date().isoformat()
            break
        except ValueError:
            continue
    house, lot = clean("auction_house"), clean("lot_number")
    if sale_date and house and lot:
        return ("sale", sale_date, house, lot)
    return ("detail", sale_date, house, lot, clean("title"), clean("hammer_price"), clean("artist"))


def merge_artprice_sources(sources: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Combine normalized saved searches, retaining every file for each sale."""

    merged: list[dict[str, Any]] = []
    by_provider: dict[str, dict] = {}
    by_sale: dict[tuple, dict] = {}
    for source in sources:
        _require_usd(source.get("currency"))
        for comparable in source.get("comparables", []):
            comparable = dict(comparable)
            image_url = _artprice_image_url(comparable.get("image_url"))
            if image_url:
                comparable["image_url"] = image_url
            else:
                comparable.pop("image_url", None)
            provider_id = str(comparable.get("provider_id") or "")
            sale_key = artprice_sale_identity(comparable)
            existing = by_provider.get(provider_id) if provider_id else None
            existing = existing or by_sale.get(sale_key)
            if existing is None:
                existing = {**comparable, "source_ids": [], "source_filenames": []}
                merged.append(existing)
            else:
                # Fill absent descriptions without replacing the first observed price.
                for key, value in comparable.items():
                    if key not in {"source_ids", "source_filenames"} and not existing.get(key) and value:
                        existing[key] = value
            if provider_id:
                by_provider[provider_id] = existing
            by_sale[sale_key] = existing
            if source["id"] not in existing["source_ids"]:
                existing["source_ids"].append(source["id"])
                existing["source_filenames"].append(source["filename"])
    return merged


def _build_analysis(
    results: list[AuctionResult],
    *,
    currency: Any,
    method: Any,
    manual_resale_value: Any,
    recent_count: Any,
    inbound_shipping: Any,
    target_profit: Any,
    seller_commission_pct: Any,
    outbound_shipping: Any,
    other_resale_costs: Any,
    premium_min: Any,
    premium_max: Any,
    allow_no_bid: bool = False,
) -> dict[str, Any]:
    normalized_currency = _require_usd(currency)
    normalized_method = _normalize_method(method)
    normalized_recent_count = _coerce_integer(
        recent_count,
        label="Recent record count",
    )
    if normalized_recent_count < 1:
        raise ArtpriceAnalysisError("Recent record count must be at least 1.")
    if normalized_recent_count > MAX_RECENT_COUNT:
        raise ArtpriceAnalysisError("Recent record count is too large.")

    manual = None
    if normalized_method == "manual":
        manual = _coerce_decimal(
            manual_resale_value,
            label="Manual resale value",
            allow_none=True,
        )
        if manual is None or manual <= 0:
            raise ArtpriceAnalysisError(
                "Manual resale value must be greater than zero when using the manual method."
            )
        manual = _require_two_decimal_places(
            manual,
            label="Manual resale value",
        )

    shipping = _coerce_nonnegative_money(
        inbound_shipping,
        label="Inbound shipping",
    )
    profit = _coerce_nonnegative_money(target_profit, label="Target profit")
    commission = _coerce_decimal(
        seller_commission_pct,
        label="Seller commission",
    )
    assert commission is not None
    if commission < 0 or commission >= 100:
        raise ArtpriceAnalysisError(
            "Seller commission must be at least 0% and less than 100%."
        )
    commission = _require_two_decimal_places(
        commission,
        label="Seller commission",
    )
    outbound = _coerce_nonnegative_money(
        outbound_shipping,
        label="Outbound shipping",
    )
    other_costs = _coerce_nonnegative_money(
        other_resale_costs,
        label="Other resale costs",
    )
    minimum, maximum = _validate_premium_range(premium_min, premium_max)

    expected = choose_resale_value(
        (result.hammer_price for result in results),
        normalized_method,
        manual_value=manual,
        recent_count=normalized_recent_count,
    )
    try:
        net_resale_proceeds, rows = calculate_bid_rows(
            expected_resale_hammer=expected,
            premium_min=minimum,
            premium_max=maximum,
            inbound_shipping=shipping,
            target_profit=profit,
            seller_commission_pct=commission,
            outbound_shipping=outbound,
            other_resale_costs=other_costs,
        )
    except ArtpriceAnalysisError as exc:
        if not allow_no_bid or not str(exc).startswith("No positive bid"):
            raise
        with localcontext() as context:
            context.prec = 50
            net_resale_proceeds = expected * (Decimal("1") - commission / Decimal("100")) - outbound - other_costs
        rows = []

    return {
        "currency": normalized_currency,
        "sold_records_count": len(results),
        "method": normalized_method,
        "expected_resale_hammer": _two_decimal_string(expected),
        "net_resale_proceeds": _two_decimal_string(net_resale_proceeds),
        "assumptions": {
            "manual_resale_value": (
                _two_decimal_string(manual) if manual is not None else None
            ),
            "recent_count": normalized_recent_count,
            "inbound_shipping": _two_decimal_string(shipping),
            "target_profit": _two_decimal_string(profit),
            "seller_commission_pct": _two_decimal_string(commission),
            "outbound_shipping": _two_decimal_string(outbound),
            "other_resale_costs": _two_decimal_string(other_costs),
            "premium_min": minimum,
            "premium_max": maximum,
        },
        "comparables": [_result_to_json(result) for result in results],
        "bid_rows": [
            {
                "premium_pct": int(row["premium_pct"]),
                "max_bid": _two_decimal_string(row["max_bid"]),
                "buyers_premium": _two_decimal_string(row["buyers_premium"]),
                "shipping": _two_decimal_string(row["shipping"]),
                "all_in_acquisition": _two_decimal_string(
                    row["all_in_acquisition"]
                ),
                "projected_profit": _two_decimal_string(row["projected_profit"]),
            }
            for row in rows
        ],
    }


def analyze_artprice_html(
    html_text: str,
    *,
    method: str = "median",
    manual_resale_value: Any = None,
    recent_count: int = 3,
    inbound_shipping: Any = 200,
    target_profit: Any = 100,
    seller_commission_pct: Any = 0,
    outbound_shipping: Any = 0,
    other_resale_costs: Any = 0,
    premium_min: int = 23,
    premium_max: int = 35,
) -> dict[str, Any]:
    """Analyze sold comparables embedded in a saved Artprice HTML page."""

    state = extract_preloaded_state(html_text)
    is_react_page = PRELOADED_STATE_MARKER not in html_text
    if is_react_page:
        preferences = state.get("preferences")
        currency = (
            _currency_value(preferences.get("currency"))
            if isinstance(preferences, Mapping) else None
        )
    else:
        currency = _extract_currency(state)
    if is_react_page and currency is None:
        raise ArtpriceAnalysisError(
            "The saved Artprice page does not specify a currency. Save the results page with Artprice set to USD."
        )
    if is_react_page:
        active_ids = _react_page_data(html_text)[1]
        results = _normalize_results(_react_lot_dicts(state, active_ids))
    else:
        results = _normalize_results(find_lot_dicts(state))
    return _build_analysis(
        results,
        currency=currency,
        method=method,
        manual_resale_value=manual_resale_value,
        recent_count=recent_count,
        inbound_shipping=inbound_shipping,
        target_profit=target_profit,
        seller_commission_pct=seller_commission_pct,
        outbound_shipping=outbound_shipping,
        other_resale_costs=other_resale_costs,
        premium_min=premium_min,
        premium_max=premium_max,
    )


def analyze_artprice_comparables(
    comparables: Iterable[Mapping[str, Any]],
    *,
    currency: str = DEFAULT_CURRENCY,
    method: str = "median",
    manual_resale_value: Any = None,
    recent_count: int = 3,
    inbound_shipping: Any = 200,
    target_profit: Any = 100,
    seller_commission_pct: Any = 0,
    outbound_shipping: Any = 0,
    other_resale_costs: Any = 0,
    premium_min: int = 23,
    premium_max: int = 35,
    allow_no_bid: bool = False,
) -> dict[str, Any]:
    """Recalculate from previously persisted JSON-safe sold comparables."""

    results = _results_from_comparables(comparables)
    return _build_analysis(
        results,
        currency=currency,
        method=method,
        manual_resale_value=manual_resale_value,
        recent_count=recent_count,
        inbound_shipping=inbound_shipping,
        target_profit=target_profit,
        seller_commission_pct=seller_commission_pct,
        outbound_shipping=outbound_shipping,
        other_resale_costs=other_resale_costs,
        premium_min=premium_min,
        premium_max=premium_max,
        allow_no_bid=allow_no_bid,
    )


__all__ = [
    "ArtpriceAnalysisError",
    "AuctionResult",
    "SUPPORTED_METHODS",
    "analyze_artprice_comparables",
    "analyze_artprice_html",
    "_artprice_image_url",
    "calculate_bid_rows",
    "choose_resale_value",
    "extract_preloaded_state",
    "find_lot_dicts",
    "money_to_decimal",
    "parse_auction_results",
]
