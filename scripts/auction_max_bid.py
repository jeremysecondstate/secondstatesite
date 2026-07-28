#!/usr/bin/env python3
"""CLI wrapper for :mod:`secondstateapp.artprice_max_bid`."""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from secondstateapp.artprice_max_bid import (  # noqa: E402
    ArtpriceAnalysisError,
    analyze_artprice_html,
)


def _decimal_argument(value: str) -> Decimal:
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError("must be a valid number") from exc


def format_money(value: Any) -> str:
    return f"${Decimal(str(value)):,.2f}"


def print_comps(comparables: list[dict[str, Any]]) -> None:
    print("\nSOLD COMPARABLES")
    print("-" * 100)
    print(f"{'Date':<14} {'Hammer':>12}  {'Auction house':<28}  Title")
    print("-" * 100)

    for comparable in comparables:
        title = str(comparable["title"]).replace("\n", " ")
        if len(title) > 46:
            title = title[:43] + "..."
        auction_house = str(comparable["auction_house"])
        print(
            f"{str(comparable['sale_date']):<14} "
            f"{format_money(comparable['hammer_price']):>12}  "
            f"{auction_house[:28]:<28}  "
            f"{title}"
        )


def print_bid_table(analysis: dict[str, Any]) -> None:
    assumptions = analysis["assumptions"]
    print("\nASSUMPTIONS")
    print("-" * 72)
    print(
        "Expected resale hammer:       "
        f"{format_money(analysis['expected_resale_hammer'])}"
    )
    print(
        "Seller commission:            "
        f"{Decimal(assumptions['seller_commission_pct']):.2f}%"
    )
    print(
        "Net resale proceeds:          "
        f"{format_money(analysis['net_resale_proceeds'])}"
    )
    print(
        "Minimum target profit:        "
        f"{format_money(assumptions['target_profit'])}"
    )

    print("\nMAXIMUM BID TABLE")
    print("-" * 92)
    print(
        f"{'Buyer premium':>13}  "
        f"{'Max hammer bid':>16}  "
        f"{'Premium $':>12}  "
        f"{'Shipping':>11}  "
        f"{'All-in cost':>14}  "
        f"{'Profit':>11}"
    )
    print("-" * 92)

    for row in analysis["bid_rows"]:
        print(
            f"{row['premium_pct']:>12.0f}%  "
            f"{format_money(row['max_bid']):>16}  "
            f"{format_money(row['buyers_premium']):>12}  "
            f"{format_money(row['shipping']):>11}  "
            f"{format_money(row['all_in_acquisition']):>14}  "
            f"{format_money(row['projected_profit']):>11}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Extract sold hammer prices from saved Artprice-style HTML and "
            "calculate maximum bids for a desired resale profit."
        )
    )
    parser.add_argument("html_file", type=Path, help="Path to the saved HTML file")
    parser.add_argument(
        "--method",
        choices=["median", "mean", "recent", "max", "min", "manual"],
        default="median",
        help="How to estimate the expected resale hammer; default: median",
    )
    parser.add_argument(
        "--resale-value",
        type=_decimal_argument,
        default=None,
        help="Expected resale hammer price; required when --method manual",
    )
    parser.add_argument(
        "--recent-count",
        type=int,
        default=3,
        help="Number of newest records used by --method recent; default: 3",
    )
    parser.add_argument(
        "--shipping",
        type=_decimal_argument,
        default=Decimal("200"),
        help="Inbound shipping cost after purchase; default: $200",
    )
    parser.add_argument(
        "--target-profit",
        type=_decimal_argument,
        default=Decimal("100"),
        help="Minimum desired resale profit; default: $100",
    )
    parser.add_argument(
        "--seller-commission",
        type=_decimal_argument,
        default=Decimal("0"),
        help="Commission charged when you resell, as a percent; default: 0",
    )
    parser.add_argument(
        "--outbound-shipping",
        type=_decimal_argument,
        default=Decimal("0"),
        help="Shipping cost you pay when reselling; default: $0",
    )
    parser.add_argument(
        "--other-resale-costs",
        type=_decimal_argument,
        default=Decimal("0"),
        help="Other resale costs such as photography, insurance, or listing fees",
    )
    parser.add_argument(
        "--premium-min",
        type=int,
        default=23,
        help="Lowest buyer's premium percentage; default: 23",
    )
    parser.add_argument(
        "--premium-max",
        type=int,
        default=35,
        help="Highest buyer's premium percentage; default: 35",
    )
    parser.add_argument(
        "--show-comps",
        action="store_true",
        help="Print all extracted sold comparable records",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if not args.html_file.exists():
        parser.error(f"File does not exist: {args.html_file}")
    if not args.html_file.is_file():
        parser.error(f"Path is not a file: {args.html_file}")

    try:
        html_text = args.html_file.read_text(encoding="utf-8", errors="replace")
        analysis = analyze_artprice_html(
            html_text,
            method=args.method,
            manual_resale_value=args.resale_value,
            recent_count=args.recent_count,
            inbound_shipping=args.shipping,
            target_profit=args.target_profit,
            seller_commission_pct=args.seller_commission,
            outbound_shipping=args.outbound_shipping,
            other_resale_costs=args.other_resale_costs,
            premium_min=args.premium_min,
            premium_max=args.premium_max,
        )
    except (ArtpriceAnalysisError, OSError) as exc:
        parser.error(str(exc))

    print(f"\nFile: {args.html_file}")
    print(f"Sold records extracted: {analysis['sold_records_count']}")
    print(f"Resale valuation method: {analysis['method']}")

    if args.show_comps:
        print_comps(analysis["comparables"])
    print_bid_table(analysis)


if __name__ == "__main__":
    main()
