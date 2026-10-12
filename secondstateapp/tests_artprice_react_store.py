"""Saved React-on-Rails Artprice pages are parsed without executing page scripts."""

import json
from unittest import TestCase

from secondstateapp.artprice_max_bid import (
    ArtpriceAnalysisError,
    analyze_artprice_comparables,
    analyze_artprice_html,
    extract_preloaded_state,
    parse_auction_results,
)


def react_store_html(
    lots, *, currency="USD", active_lot_ids=None, nested=False, cached_lots=None,
):
    state = {"dbEntities": {"lots": {"data": lots} if nested else lots}}
    if currency is not None:
        state["preferences"] = {"currency": currency}
    if cached_lots is not None:
        state["account"] = {"recent": cached_lots}
    searchbar = (
        '<script type="application/json" data-component-name="Lots::Searchbars::Artist">'
        f'{json.dumps({"lotIds": active_lot_ids})}</script>'
        if active_lot_ids is not None else ""
    )
    return (
        '<html><script data-js-react-on-rails-store="artpriceStore" '
        'type="application/json">'
        f"{json.dumps(state)}</script>{searchbar}</html>"
    )


class ArtpriceReactStoreTests(TestCase):
    def test_react_lot_entities_win_over_larger_unrelated_branch_without_lot_ids(self):
        active_lots = {
            str(lot_id): {
                "id": lot_id,
                "title": f"Search work {lot_id}",
                "price": f"$ {lot_id * 100}",
                "saleDtStart": "1 Jan 2025",
                "auctioneerName": "House",
                "lotstatus": 1,
            }
            for lot_id in (10, 11)
        }
        cached_lots = {
            str(lot_id): {
                "id": lot_id,
                "title": f"Unrelated work {lot_id}",
                "price": "$ 9,000",
                "saleDtStart": "1 Jan 2025",
                "auctioneerName": "House",
                "lotstatus": 1,
            }
            for lot_id in range(20, 25)
        }
        html = react_store_html(active_lots, nested=True, cached_lots=cached_lots)

        analysis = analyze_artprice_html(html)
        self.assertEqual(analysis["sold_records_count"], 2)
        self.assertEqual(analysis["expected_resale_hammer"], "1050.00")
        self.assertEqual(
            [record.provider_id for record in parse_auction_results(html)],
            ["10", "11"],
        )

    def test_react_store_without_lot_entities_does_not_use_account_cache(self):
        cached = {
            "10": {
                "id": 10,
                "title": "Cached work",
                "price": "$ 1,000",
                "saleDtStart": "1 Jan 2025",
                "auctioneerName": "House",
            },
        }
        state = {
            "preferences": {"currency": "USD"},
            "dbEntities": {},
            "account": {"recent": cached},
        }
        html = (
            '<script data-js-react-on-rails-store="artpriceStore" type="application/json">'
            f"{json.dumps(state)}</script>"
        )
        with self.assertRaisesRegex(ArtpriceAnalysisError, "No Artprice lot entities"):
            analyze_artprice_html(html)

    def test_active_search_ids_exclude_cached_lots_even_when_cache_is_larger(self):
        lots = {
            str(lot_id): {
                "id": lot_id,
                "title": f"Work {lot_id}",
                "price": f"$ {lot_id * 100}",
                "saleDtStart": "1 Jan 2025",
                "auctioneerName": "House",
                "lotstatus": 1,
            }
            for lot_id in range(10, 18)
        }
        html = react_store_html(
            lots,
            active_lot_ids=[10, 11],
            nested=True,
            cached_lots={str(key): lots[str(key)] for key in range(12, 18)},
        )

        self.assertEqual(
            [record.provider_id for record in parse_auction_results(html)],
            ["10", "11"],
        )
        analysis = analyze_artprice_html(html)
        self.assertEqual(analysis["sold_records_count"], 2)
        self.assertEqual(analysis["expected_resale_hammer"], "1050.00")
        self.assertEqual(
            [item["provider_id"] for item in analysis["comparables"]],
            ["10", "11"],
        )

    def test_active_search_ids_do_not_fall_back_to_cached_lots(self):
        lots = {
            "10": {
                "id": 10,
                "title": "Cached work",
                "price": "$ 1,000",
                "saleDtStart": "1 Jan 2025",
                "auctioneerName": "House",
                "lotstatus": 1,
            },
        }
        html = react_store_html(lots, active_lot_ids=[11], nested=True)
        with self.assertRaisesRegex(ArtpriceAnalysisError, "No active search lot records"):
            analyze_artprice_html(html)

    def test_react_store_requires_an_explicit_usd_currency(self):
        lots = {
            "10": {
                "id": 10,
                "title": "Work",
                "price": "$ 1,000",
                "saleDtStart": "1 Jan 2025",
                "auctioneerName": "House",
                "lotstatus": 1,
            },
        }
        with self.assertRaisesRegex(ArtpriceAnalysisError, "does not specify a currency"):
            analyze_artprice_html(react_store_html(lots, currency=None))

    def test_uses_usd_hammer_and_preserves_lot_provenance_and_print_details(self):
        html = react_store_html(
            {
                "1234": {
                    "id": 1234,
                    "title": "Nez et oreilles tres gais",
                    "artistOrAssociation": "Alexander CALDER",
                    "category": "Print-Multiple",
                    "technique": "Lithograph in colors",
                    "numberAndEdition": "Ed. AP / 75",
                    "dimension": "29 1/2 x 43 1/3 in",
                    "price": "$ 4,200",
                    "priceWithTaxes": "$ 5,334",
                    "saleDtStart": "29 Jan 2025",
                    "auctioneerName": "Rago",
                    "number": 222,
                    "lotstatus": 1,
                    "url": "/artist/4516/alexander-calder/print-multiple/1234/nez-et-oreilles",
                },
                "unsold": {
                    "id": 9999,
                    "title": "Unsold impression",
                    "price": "$ 12,000",
                    "saleDtStart": "28 Jan 2025",
                    "auctioneerName": "Rago",
                    "lotstatus": 3,
                },
            }
        )

        analysis = analyze_artprice_html(html)
        self.assertEqual(analysis["currency"], "USD")
        self.assertEqual(analysis["sold_records_count"], 1)
        comp = analysis["comparables"][0]
        self.assertEqual(comp["hammer_price"], "4200.00")
        self.assertEqual(comp["provider_id"], "1234")
        self.assertEqual(
            comp["provider_url"],
            "https://www.artprice.com/artist/4516/alexander-calder/print-multiple/1234/nez-et-oreilles",
        )
        self.assertEqual(comp["artist"], "Alexander CALDER")
        self.assertEqual(comp["medium"], "Lithograph in colors")
        self.assertEqual(comp["edition"], "Ed. AP / 75")
        self.assertEqual(comp["size"], "29 1/2 x 43 1/3 in")
        self.assertEqual(
            analyze_artprice_comparables(analysis["comparables"])["comparables"],
            analysis["comparables"],
        )

    def test_rejects_non_usd_store_and_unsafe_lot_link(self):
        lot = {
            "id": 1234,
            "title": "Work",
            "price": "$ 1,000",
            "saleDtStart": "1 Jan 2025",
            "auctioneerName": "House",
            "lotstatus": 1,
            "url": "https://elsewhere.example/artist/1/work",
        }
        with self.assertRaisesRegex(ArtpriceAnalysisError, "not set to USD"):
            analyze_artprice_html(react_store_html({"1234": lot}, currency="EUR"))
        comp = analyze_artprice_html(react_store_html({"1234": lot}))["comparables"][0]
        self.assertNotIn("provider_url", comp)

    def test_malformed_store_error_does_not_echo_source(self):
        secret = "SECRET-ACCOUNT-VALUE"
        html = (
            '<script type="application/json" data-js-react-on-rails-store="artpriceStore">'
            f"{{not-json:{secret}</script>"
        )
        with self.assertRaises(ArtpriceAnalysisError) as raised:
            extract_preloaded_state(html)
        self.assertNotIn(secret, str(raised.exception))
