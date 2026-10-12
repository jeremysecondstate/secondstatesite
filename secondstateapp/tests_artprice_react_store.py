"""Saved React-on-Rails Artprice pages are parsed without executing page scripts."""

import json
from unittest import TestCase

from secondstateapp.artprice_max_bid import (
    ArtpriceAnalysisError,
    analyze_artprice_comparables,
    analyze_artprice_html,
    extract_preloaded_state,
)


def react_store_html(lots, *, currency="USD"):
    state = {"preferences": {"currency": currency}, "dbEntities": {"lots": lots}}
    return (
        '<html><script data-js-react-on-rails-store="artpriceStore" '
        'type="application/json">'
        f"{json.dumps(state)}</script></html>"
    )


class ArtpriceReactStoreTests(TestCase):
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
