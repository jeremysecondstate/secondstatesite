"""Decimal-only, side-effect-free Archive bid ladder and resale calculations.

Every displayed bid is an available step on the configured ladder. Ceilings use
a monotone search of that same ladder and recheck the rounded cash flows, so a
fractional mathematical ceiling is never rounded up into an unaffordable bid.
"""

from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_HALF_UP


CENT = Decimal("0.01")
MAX_MONEY = Decimal("1000000000000")
CASE_KEYS = ("conservative", "working", "optimistic")
CASE_LABELS = dict(zip(CASE_KEYS, ("Conservative", "Working", "Optimistic")))
DEFAULT_TIERS = [
    {"up_to": "1000.00", "increment": "50.00"},
    {"up_to": "5000.00", "increment": "100.00"},
    {"up_to": "10000.00", "increment": "250.00"},
    {"up_to": "50000.00", "increment": "500.00"},
    {"up_to": None, "increment": "1000.00"},
]
DEFAULTS = {
    "starting_hammer": None,
    "starting_basis": "opening",
    "buyer_premium_pct": "25.00",
    "purchase_tax_pct": "0.00",
    "purchase_tax_basis": "hammer_premium",
    "acquisition_costs": "200.00",
    "selling_commission_pct": "0.00",
    "selling_costs": "0.00",
    "minimum_profit": "500.00",
    "minimum_return_pct": "20.00",
    "increment_mode": "fixed",
    "fixed_increment": "100.00",
    "tiers": DEFAULT_TIERS,
    "downside_factor": "0.80",
    "upside_factor": "1.10",
    "resale_overrides": {key: None for key in CASE_KEYS},
}


class BidBoardError(ValueError):
    pass


def money(value):
    return f"{value.quantize(CENT, rounding=ROUND_HALF_UP):.2f}"


def decimal_value(value, name, *, maximum=MAX_MONEY, minimum=Decimal(0)):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise BidBoardError(f"{name} must be a number.") from None
    if isinstance(value, bool) or not number.is_finite() or not minimum <= number <= maximum or number.as_tuple().exponent < -2:
        raise BidBoardError(f"{name} must be between {minimum} and {maximum}, with at most two decimals.")
    return number


def normalize_assumptions(supplied=None):
    if not isinstance(supplied, (dict, type(None))):
        raise BidBoardError("Bid assumptions must be an object.")
    supplied = supplied or {}
    unknown = set(supplied) - set(DEFAULTS)
    if unknown:
        raise BidBoardError(f"Unsupported bid assumption: {', '.join(sorted(unknown))}.")
    result = {**DEFAULTS, **supplied}
    for field in ("buyer_premium_pct", "purchase_tax_pct", "selling_commission_pct"):
        result[field] = money(decimal_value(result[field], field.replace("_", " "), maximum=Decimal(100)))
    if Decimal(result["selling_commission_pct"]) >= 100:
        raise BidBoardError("Selling commission must be less than 100%.")
    for field in ("acquisition_costs", "selling_costs", "minimum_profit"):
        result[field] = money(decimal_value(result[field], field.replace("_", " ")))
    result["minimum_return_pct"] = money(decimal_value(result["minimum_return_pct"], "Minimum return on cost", maximum=Decimal(10000)))
    result["fixed_increment"] = money(decimal_value(result["fixed_increment"], "Fixed increment", minimum=CENT))
    result["downside_factor"] = money(decimal_value(result["downside_factor"], "Conservative factor", minimum=Decimal("0.25"), maximum=Decimal(1)))
    result["upside_factor"] = money(decimal_value(result["upside_factor"], "Optimistic factor", minimum=Decimal(1), maximum=Decimal(2)))
    if result["starting_hammer"] in (None, ""):
        result["starting_hammer"] = None
    else:
        result["starting_hammer"] = money(decimal_value(result["starting_hammer"], "Starting hammer", minimum=CENT))
    for field, allowed in (
        ("starting_basis", ("current", "opening")),
        ("increment_mode", ("fixed", "tiers")),
        ("purchase_tax_basis", ("hammer", "hammer_premium", "acquisition")),
    ):
        if result[field] not in allowed:
            raise BidBoardError(f"Choose a valid {field.replace('_', ' ')}.")
    overrides = result["resale_overrides"]
    if not isinstance(overrides, dict) or set(overrides) - set(CASE_KEYS):
        raise BidBoardError("Resale overrides must contain conservative, working, or optimistic values.")
    result["resale_overrides"] = {
        key: None if overrides.get(key) in (None, "") else money(decimal_value(overrides[key], f"{key.title()} resale override"))
        for key in CASE_KEYS
    }
    tiers = result["tiers"]
    if not isinstance(tiers, list) or not 1 <= len(tiers) <= 20:
        raise BidBoardError("Use between 1 and 20 auction increment tiers.")
    normalized_tiers, previous = [], Decimal(0)
    for index, tier in enumerate(tiers):
        if not isinstance(tier, dict) or set(tier) != {"up_to", "increment"}:
            raise BidBoardError("Each tier requires an up_to amount and an increment.")
        increment = decimal_value(tier["increment"], "Tier increment", minimum=CENT)
        upper = None if tier["up_to"] in (None, "") else decimal_value(tier["up_to"], "Tier upper amount", minimum=CENT)
        if upper is None and index != len(tiers) - 1 or upper is not None and upper <= previous:
            raise BidBoardError("Tier upper amounts must increase; only the final tier may be open ended.")
        if upper is not None:
            previous = upper
        normalized_tiers.append({"up_to": money(upper) if upper is not None else None, "increment": money(increment)})
    if normalized_tiers[-1]["up_to"] is not None:
        raise BidBoardError("The final increment tier must have no upper amount.")
    result["tiers"] = normalized_tiers
    return result


class BidLadder:
    """Compact indexed ladder: tiers change at their stated boundary.

    A step that would cross a boundary lands on that boundary first. Fixed
    ladders are anchored to the supplied current/opening bid, never to zero.
    """

    def __init__(self, assumptions):
        self.assumptions = assumptions
        current = Decimal(assumptions["starting_hammer"])
        self.tiers = [(None, Decimal(assumptions["fixed_increment"]))] if assumptions["increment_mode"] == "fixed" else [
            (Decimal(tier["up_to"]) if tier["up_to"] is not None else None, Decimal(tier["increment"]))
            for tier in assumptions["tiers"]
        ]
        if assumptions["starting_basis"] == "current":
            current = self.next(current)
        self.segments = []
        offset = 0
        for upper, step in self.tiers:
            if upper is not None and upper <= current:
                continue
            if current > MAX_MONEY:
                break
            bound = min(upper, MAX_MONEY + CENT) if upper is not None else MAX_MONEY + CENT
            count = int(((bound - current) / step).to_integral_value(rounding=ROUND_CEILING))
            self.segments.append((offset, count, current, step))
            offset += count
            if upper is None or upper > MAX_MONEY:
                break
            current = upper
        self.count = offset

    def next(self, bid):
        for upper, step in self.tiers:
            if upper is None or bid < upper:
                return min(bid + step, upper) if upper is not None else bid + step
        raise BidBoardError("No next increment is available.")

    def at(self, index):
        if index < 0 or index >= self.count:
            return None
        for offset, count, first, step in self.segments:
            if index < offset + count:
                return first + (index - offset) * step
        return None

    def index_at_or_below(self, value):
        answer = -1
        for offset, count, first, step in self.segments:
            if value < first:
                break
            answer = offset + min(count - 1, int((value - first) // step))
        return answer


def acquisition(bid, assumptions):
    premium = (bid * Decimal(assumptions["buyer_premium_pct"]) / 100).quantize(CENT, rounding=ROUND_HALF_UP)
    costs = Decimal(assumptions["acquisition_costs"])
    tax_basis = bid
    if assumptions["purchase_tax_basis"] in ("hammer_premium", "acquisition"):
        tax_basis += premium
    if assumptions["purchase_tax_basis"] == "acquisition":
        tax_basis += costs
    tax = (tax_basis * Decimal(assumptions["purchase_tax_pct"]) / 100).quantize(CENT, rounding=ROUND_HALF_UP)
    return {"hammer": bid, "buyer_premium": premium, "purchase_tax_basis_amount": tax_basis, "purchase_tax": tax, "acquisition_costs": costs, "all_in_acquisition": bid + premium + tax + costs}


def cash_flow(bid, resale, assumptions, *, minimum_profit=None):
    cost = acquisition(bid, assumptions)
    commission = (resale * Decimal(assumptions["selling_commission_pct"]) / 100).quantize(CENT, rounding=ROUND_HALF_UP)
    selling_costs = Decimal(assumptions["selling_costs"])
    net = resale - commission - selling_costs
    profit = net - cost["all_in_acquisition"]
    target = Decimal(assumptions["minimum_profit"]) if minimum_profit is None else minimum_profit
    meets_profit = profit >= target
    # Compare exact cash amounts, not the rounded percentage displayed in UI.
    meets_return = profit * 100 >= cost["all_in_acquisition"] * Decimal(assumptions["minimum_return_pct"])
    return {**cost, "gross_resale_hammer": resale, "selling_commission": commission, "selling_costs": selling_costs, "net_resale_proceeds": net, "net_profit": profit,
            "return_on_cost_pct": profit / cost["all_in_acquisition"] * 100,
            "profit_on_gross_pct": profit / resale * 100 if resale else None,
            "meets_profit": meets_profit, "meets_return": meets_return, "qualifies": meets_profit and meets_return,
            "profit_500": profit >= 500, "profit_1000": profit >= 1000}


def ceiling(ladder, resale, assumptions, *, minimum_profit=None):
    low, high, best = 0, ladder.count - 1, None
    while low <= high:
        midpoint = (low + high) // 2
        bid = ladder.at(midpoint)
        if cash_flow(bid, resale, assumptions, minimum_profit=minimum_profit)["qualifies"]:
            best, low = bid, midpoint + 1
        else:
            high = midpoint - 1
    if best is not None and not cash_flow(best, resale, assumptions, minimum_profit=minimum_profit)["qualifies"]:
        raise BidBoardError("The available bid does not satisfy both minimums.")
    return best


def detail_for(bid, resale, assumptions, ladder):
    flow = cash_flow(bid, resale, assumptions)
    gross = ((flow["all_in_acquisition"] + Decimal(assumptions["selling_costs"])) / (1 - Decimal(assumptions["selling_commission_pct"]) / 100)).quantize(CENT, rounding=ROUND_CEILING)
    low, high = 0, int(gross * 100) + 1
    while low < high:
        middle = (low + high) // 2
        if cash_flow(bid, Decimal(middle) / 100, assumptions)["net_profit"] >= 0:
            high = middle
        else:
            low = middle + 1
    gross = Decimal(low) / 100
    next_bid = ladder.next(bid)
    extra = acquisition(next_bid, assumptions)["all_in_acquisition"] - flow["all_in_acquisition"]
    return {**{key: money(value) if isinstance(value, Decimal) else value for key, value in flow.items()}, "bid": money(bid), "break_even_resale": money(gross), "one_more_bid": {
        "bid": money(next_bid), "hammer_increment": money(next_bid - bid), "additional_all_in_cost": money(extra), "profit_reduction": money(extra),
        "net_profit": money(flow["net_profit"] - extra), "available": next_bid <= MAX_MONEY,
    }}


def build_board(assumptions, evidence_scenarios=None, source_summary=None, *, page=0, selected_bid=None, selected_case="working", focus_selected=False):
    assumptions = normalize_assumptions(assumptions)
    if isinstance(page, bool) or not isinstance(page, int) or page < 0 or page > 100000000000000:
        raise BidBoardError("Choose a valid bid page.")
    if selected_case not in CASE_KEYS:
        raise BidBoardError("Choose a valid resale case.")
    evidence = {scenario["key"]: scenario for scenario in evidence_scenarios or []}
    cases = []
    for key, legacy in zip(CASE_KEYS, ("downside", "typical", "upside")):
        derived = evidence.get(legacy, {})
        override = assumptions["resale_overrides"][key]
        resale = override if override is not None else derived.get("resale_hammer")
        cases.append({"key": key, "label": CASE_LABELS[key], "resale_hammer": resale, "evidence_resale_hammer": derived.get("resale_hammer"),
                      "origin": "manual" if override is not None else "evidence" if resale is not None else "unavailable",
                      "basis": "Manual resale override" if override is not None else derived.get("basis", "Select eligible sold USD hammer evidence or enter a manual resale assumption.")})
    notices = []
    count = (source_summary or {}).get("combined_comp_count", 0)
    if count == 0:
        notices.append("No eligible selected sale evidence. Manual resale assumptions, when supplied, are not evidence-derived.")
    elif count < 3:
        notices.append(f"Only {count} unique selected sale{'s' if count != 1 else ''}; these sensitivity cases use limited evidence.")
    values = [Decimal(case["resale_hammer"]) for case in cases if case["resale_hammer"] is not None]
    if len(values) == 3 and not values[0] <= values[1] <= values[2]:
        notices.append("Manual resale cases are not in ascending order; review the assumptions.")
    increment_notice = "Configured fixed increment; verify the auction house's bidding rules." if assumptions["increment_mode"] == "fixed" else "Configurable example tier schedule, not verified house rules. A crossing step lands on the tier boundary."
    result = {"assumptions": assumptions, "cases": cases, "source_summary": source_summary or {}, "rows": [], "shortlist": [], "detail": None,
              "profit_targets": [], "pagination": {"page": 0, "page_size": 8, "page_count": 0, "has_previous": False, "has_next": False},
              "increment_notice": increment_notice, "notices": notices, "selected_case": selected_case, "selected_bid": None, "selected_bid_index": None,
              "calculation_basis": "USD cash flows, each premium, tax and commission rounded to cents (half up). Return on cost = net profit / all-in acquisition. Both minimums are checked against unrounded ratios. Ceilings are conditional, not probabilities."}
    if assumptions["starting_hammer"] is None:
        result["notices"].append("Enter an opening or current hammer to create the available bid ladder.")
        return result
    ladder = BidLadder(assumptions)
    if not ladder.count:
        result["notices"].append("No available bid remains within the supported range.")
        return result
    by_case = {case["key"]: Decimal(case["resale_hammer"]) if case["resale_hammer"] is not None else None for case in cases}
    for key in CASE_KEYS:
        resale = by_case[key]
        bid = ceiling(ladder, resale, assumptions) if resale is not None else None
        result["shortlist"].append({"case_key": key, "label": {"conservative": "Conservative ceiling", "working": "Working-case ceiling", "optimistic": "Optimistic stretch"}[key], "bid": money(bid) if bid is not None else None,
            "detail": detail_for(bid, resale, assumptions, ladder) if bid is not None else None,
            "conservative_downside": detail_for(bid, by_case["conservative"], assumptions, ladder) if bid is not None and by_case["conservative"] is not None else None,
            "reason": None if bid is not None else "Resale assumption unavailable" if resale is None else "No available bid satisfies both minimums"})
    if selected_bid not in (None, ""):
        chosen = decimal_value(selected_bid, "Selected bid", minimum=CENT)
        if ladder.at(ladder.index_at_or_below(chosen)) != chosen:
            raise BidBoardError("The selected hammer is not an available bid on this ladder.")
    else:
        preferred = next(item for item in result["shortlist"] if item["case_key"] == selected_case)
        chosen = Decimal(preferred["bid"]) if preferred["bid"] is not None else ladder.at(min(page * 8, ladder.count - 1))
    selected_index = ladder.index_at_or_below(chosen)
    if focus_selected:
        page = selected_index // 8
    # Include eight further bids beyond the largest gross resale, enough to
    # expose loss-making outcomes without materializing thousands of rows.
    end_index = max(15, selected_index, ladder.index_at_or_below(max(values, default=ladder.at(0))) + 8)
    row_count = min(ladder.count, end_index + 1)
    page_count = (row_count + 7) // 8
    page = min(page, page_count - 1)
    result["pagination"] = {"page": page, "page_size": 8, "page_count": page_count, "has_previous": page > 0, "has_next": page + 1 < page_count, "row_count": row_count}
    for index in range(page * 8, min((page + 1) * 8, row_count)):
        bid = ladder.at(index)
        result["rows"].append({"bid": money(bid), "bid_index": index,
            "label": ("Opening bid" if assumptions["starting_basis"] == "opening" else "Next bid") if index == 0 else f"+{index} step{'s' if index != 1 else ''}",
            "all_in_acquisition": money(acquisition(bid, assumptions)["all_in_acquisition"]),
            "cells": [{"case_key": key, **detail_for(bid, resale, assumptions, ladder)} if resale is not None else {"case_key": key, "available": False, "qualifies": False} for key, resale in by_case.items()]})
    result["selected_bid"] = money(chosen)
    result["selected_bid_index"] = selected_index
    if by_case[selected_case] is not None:
        result["detail"] = {"case_key": selected_case, **detail_for(chosen, by_case[selected_case], assumptions, ladder)}
    for target in sorted({Decimal(0), Decimal(500), Decimal(1000), Decimal(2000), Decimal(assumptions["minimum_profit"])}):
        ceilings = {}
        for key, resale in by_case.items():
            bid = ceiling(ladder, resale, assumptions, minimum_profit=target) if resale is not None else None
            ceilings[key] = money(bid) if bid is not None else None
        result["profit_targets"].append({"minimum_profit": money(target), "minimum_return_pct": assumptions["minimum_return_pct"], "ceilings": ceilings})
    return result
