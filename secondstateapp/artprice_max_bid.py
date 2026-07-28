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


PRELOADED_STATE_MARKER = "window.__PRELOADED_STATE__"
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


def extract_preloaded_state(html_text: str) -> dict[str, Any]:
    """Decode the JSON assigned to ``window.__PRELOADED_STATE__``.

    ``raw_decode`` permits normal JavaScript trailing text such as a semicolon
    without relying on the saved page's line structure.
    """

    if not isinstance(html_text, str):
        raise ArtpriceAnalysisError("The uploaded Artprice page could not be read as text.")

    marker_index = html_text.find(PRELOADED_STATE_MARKER)
    if marker_index == -1:
        raise ArtpriceAnalysisError(
            "Could not find the Artprice preloaded state marker "
            "(window.__PRELOADED_STATE__) in the uploaded page."
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


def find_lot_dicts(node: Any) -> list[dict[str, Any]]:
    """Find the largest coherent group of auction lots in a state tree.

    Artprice has moved the results container between releases, so traversal is
    iterative and structure-agnostic. Selecting one sibling group avoids
    mixing the search results with lot-shaped records from unrelated
    cached/account branches.
    """

    candidates: list[list[dict[str, Any]]] = []
    standalone_lots: list[dict[str, Any]] = []

    stack = [node]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            if _looks_like_lot(value):
                standalone_lots.append(value)

            children = list(value.values())
            dict_lots = [
                child
                for child in children
                if isinstance(child, dict) and _looks_like_lot(child)
            ]
            if dict_lots:
                candidates.append(dict_lots)
            stack.extend(reversed(children))
        elif isinstance(value, list):
            list_lots = [
                child
                for child in value
                if isinstance(child, dict) and _looks_like_lot(child)
            ]
            if list_lots:
                candidates.append(list_lots)
            stack.extend(reversed(value))

    if candidates:
        return max(candidates, key=len)
    if standalone_lots:
        return standalone_lots
    raise ArtpriceAnalysisError(
        "No auction lot records were found in the embedded Artprice data."
    )


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


def _require_two_decimal_places(value: Decimal, *, label: str) -> Decimal:
    rounded = _rounded_money(value)
    if value != rounded:
        raise ArtpriceAnalysisError(f"{label} must have at most two decimal places.")
    return rounded


def _normalize_results(lots: Iterable[Mapping[str, Any]]) -> list[AuctionResult]:
    results: list[AuctionResult] = []
    seen: set[tuple[str, str, Decimal]] = set()

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
        )
        dedupe_key = (result.title, result.sale_date, result.hammer_price)
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


def _result_to_json(result: AuctionResult) -> dict[str, str | None]:
    return {
        "sale_date": result.sale_date,
        "hammer_price": _two_decimal_string(result.hammer_price),
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
            }
        )
    return _normalize_results(lots)


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
    currency = _extract_currency(state)
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
    )


__all__ = [
    "ArtpriceAnalysisError",
    "AuctionResult",
    "SUPPORTED_METHODS",
    "analyze_artprice_comparables",
    "analyze_artprice_html",
    "calculate_bid_rows",
    "choose_resale_value",
    "extract_preloaded_state",
    "find_lot_dicts",
    "money_to_decimal",
    "parse_auction_results",
]
