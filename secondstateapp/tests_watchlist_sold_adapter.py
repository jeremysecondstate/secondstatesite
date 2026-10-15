"""Posted sale results must have evidence distinct from bids and estimates."""

import json
from pathlib import Path

from bs4 import BeautifulSoup
from django.test import SimpleTestCase

from catalogapp.watchlist_adapters import InvaluableAdapter
from catalogapp.watchlist_models import NormalizedLot


FIXTURES = Path(__file__).parent / "test_fixtures" / "watchlist"
LOT_URL = "https://www.invaluable.com/auction-lot/alexander-calder-nid-daraignee-116-c-synthetic116"


class InvaluableSoldAdapterTests(SimpleTestCase):
    def setUp(self):
        self.adapter = InvaluableAdapter()

    def detail(self, body, **fields):
        metadata = {"lotId": "synthetic116", "url": LOT_URL, "title": "Calder lithograph", "currency": "USD", **fields}
        page = f'<html><script type="application/ld+json">{json.dumps(metadata)}</script><body>{body}</body></html>'
        return self.adapter.parse_lot_detail(page, LOT_URL, "Alexander Calder")

    def test_screenshot_sold_label_overlays_embedded_json(self):
        lot = self.adapter.parse_lot_detail((FIXTURES / "invaluable_detail_sold.html").read_text(encoding="utf-8"), LOT_URL, "Alexander Calder")
        self.assertEqual(lot.sold_price, 11000)
        self.assertEqual(lot.sold_currency, "USD")
        self.assertEqual(lot.current_bid, 6000)
        self.assertEqual(lot.estimate_high, 5000)
        self.assertEqual(lot.content_hash, lot.calculate_content_hash())

    def test_detail_without_json_reads_split_sold_label(self):
        lot = self.adapter.parse_lot_detail('<h1>Calder lithograph</h1><p><b>Sold:</b> <span>$11,000 USD</span></p>', LOT_URL, "Alexander Calder")
        self.assertEqual(lot.sold_price, 11000)
        self.assertEqual(lot.sold_currency, "USD")

    def test_actual_public_closed_detail_reports_login_required(self):
        page = (FIXTURES / "invaluable_closed_bid_detail.html").read_text(encoding="utf-8")
        lot = self.adapter.parse_lot_detail(page, LOT_URL, "Alexander Calder")
        self.assertIsNone(lot.sold_price)
        self.assertIn("sold_price_login", lot.ambiguities)

    def test_adjacent_result_in_actual_closed_detail_structure(self):
        page = (FIXTURES / "invaluable_closed_bid_detail.html").read_text(encoding="utf-8")
        for amount in ("$11,000 USD", "<span>$11,000 USD</span>", "$<!-- -->11,000<!-- --> USD"):
            with self.subTest(amount=amount):
                soup = BeautifulSoup(page, "html.parser")
                button = soup.select_one(".closed-bid-lot-detail > button")
                button.replace_with(BeautifulSoup(amount, "html.parser"))
                lot = self.adapter.parse_lot_detail(str(soup), LOT_URL, "Alexander Calder")
                self.assertEqual(lot.sold_price, 11000)
                self.assertEqual(lot.sold_currency, "USD")
                self.assertNotIn("sold_price_login", lot.ambiguities)

    def test_adjacent_result_does_not_borrow_other_field_or_range(self):
        for value in (
            "Log in to view<span>11,000 USD</span>",
            "$3,000<span> - $5,000</span>",
            "<div>11,000 USD</div>",
            "<span hidden>$11,000 USD</span>",
            "<strong>Current bid:</strong><span>$11,000 USD</span>",
        ):
            with self.subTest(value=value):
                lot = self.detail(f'<div><h1>Calder lithograph</h1><strong>Sold: </strong>{value}<div>October 14, 2026</div></div>')
                self.assertIsNone(lot.sold_price)

    def test_login_prompt_in_related_lot_does_not_mark_main_result(self):
        lot = self.detail('<article class="lot-card"><strong>Sold: </strong><button>Log in to view</button></article>')
        self.assertNotIn("sold_price_login", lot.ambiguities)

    def test_shell_or_unrecognized_document_is_not_a_refreshed_lot(self):
        for page in (
            "", "<html><div id='root'></div></html>",
            '<script type="application/json">{"url": "' + LOT_URL + '"}</script>',
            "<h1>JavaScript is disabled</h1><p>Enable JavaScript to continue</p>",
            "<h1>Verify you are human</h1>",
        ):
            with self.subTest(page=page):
                self.assertIsNone(self.adapter.parse_lot_detail(page, LOT_URL, "Alexander Calder"))

    def test_partial_embedded_metadata_uses_visible_title(self):
        page = '<script type="application/json">{"url": "' + LOT_URL + '", "currentBid": 2000}</script><h1>Calder lithograph</h1><strong>Sold: </strong><button>Log in to view</button>'
        lot = self.adapter.parse_lot_detail(page, LOT_URL, "Alexander Calder")
        self.assertEqual(lot.title, "Calder lithograph")
        self.assertIn("sold_price_login", lot.ambiguities)
        self.assertEqual(lot.content_hash, lot.calculate_content_hash())

    def test_explicit_result_keys_and_currency(self):
        for key in ("soldPrice", "soldFor", "priceRealized", "realizedPrice", "hammerPrice"):
            with self.subTest(key=key):
                lot = self.detail("", **{key: {"amount": 11000, "currency": "CAD"}})
                self.assertEqual(lot.sold_price, 11000)
                self.assertEqual(lot.sold_currency, "CAD")

    def test_explicit_printed_currency_wins_over_estimate_currency(self):
        lot = self.detail('<p>Sold: $11,000 CAD</p>', estimateLow=3000, estimateHigh=5000)
        self.assertEqual(lot.currency, "USD")
        self.assertEqual(lot.sold_currency, "CAD")

    def test_structured_dollar_result_uses_source_currency(self):
        lot = self.detail("", soldPrice="$11,000", soldCurrencyCode="AUD")
        self.assertEqual(lot.sold_currency, "AUD")

    def test_dom_sold_price_attribute_is_explicit(self):
        lot = self.detail('<p data-sold-price="11000" data-sold-currency="EUR"></p>')
        self.assertEqual(lot.sold_price, 11000)
        self.assertEqual(lot.sold_currency, "EUR")

    def test_ended_status_and_bid_are_not_sold_evidence(self):
        lot = self.detail('<p>Current bid: $11,000 USD</p><p>Auction closed</p>', currentBid=11000, price=11000, status="sold", closed=True, bidCount=12)
        self.assertIsNone(lot.sold_price)
        self.assertEqual(lot.sold_currency, "")

    def test_gated_unavailable_and_zero_results_remain_unknown(self):
        for result in ("Sold: Log in to view", "Sold: Not disclosed", "Sold: —", "Sold: $0 USD", "Sold: $3,000 - $5,000"):
            with self.subTest(result=result):
                lot = self.detail(f'<p>{result}</p><p>Estimate: $3,000 USD - $5,000 USD</p><p>October 14, 2026</p>')
                self.assertIsNone(lot.sold_price)

    def test_provenance_and_related_lots_do_not_supply_current_result(self):
        lot = self.detail('<p>Previously sold: $11,000 USD</p><article class="lot-card"><p class="sold-price">Sold: $14,000 USD</p></article><section class="related-lots"><p class="sold-price">Sold: $15,000 USD</p></section>')
        self.assertIsNone(lot.sold_price)

    def test_main_result_does_not_use_an_unrelated_json_lot(self):
        page = '<h1>Calder lithograph</h1><script type="application/ld+json">' + json.dumps({"lotId": "other", "url": "https://www.invaluable.com/auction-lot/other-117", "title": "Other print", "soldPrice": 9000}) + '</script>'
        lot = self.adapter.parse_lot_detail(page, LOT_URL, "Alexander Calder")
        self.assertIsNone(lot.sold_price)
        self.assertEqual(lot.lot_url, LOT_URL)

    def test_dom_result_survives_duplicate_json_without_a_result(self):
        metadata = {"lotId": "synthetic116", "url": LOT_URL, "title": "Calder lithograph", "currentBid": 6000}
        page = f'<script type="application/ld+json">{json.dumps(metadata)}</script><article class="lot-card" data-lot-id="synthetic116"><a href="{LOT_URL}">Lot</a><h3>Calder lithograph</h3><p>Sold: $11,000 USD</p></article>'
        lots = self.adapter.parse_search_page(page, "https://www.invaluable.com/search", "Alexander Calder")
        self.assertEqual(len(lots), 1)
        self.assertEqual(lots[0].sold_price, 11000)
        self.assertEqual(lots[0].current_bid, 6000)

    def test_hidden_result_is_not_imported(self):
        lot = self.detail('<p class="sold-price" hidden>Sold: $11,000 USD</p><p>Sold: Log in to view</p>')
        self.assertIsNone(lot.sold_price)

    def test_current_detail_identity_selected_before_related_json(self):
        raw = [{"lotId": "other", "url": "https://www.invaluable.com/auction-lot/other-117", "title": "Other print", "soldPrice": 9000}, {"lotId": "synthetic116", "url": LOT_URL, "title": "Calder lithograph", "soldPrice": 11000}]
        page = f'<script type="application/ld+json">{json.dumps(raw)}</script>'
        lot = self.adapter.parse_lot_detail(page, LOT_URL, "Alexander Calder")
        self.assertEqual(lot.source_lot_id, "synthetic116")
        self.assertEqual(lot.sold_price, 11000)

    def test_catalog_hit_passes_explicit_result_without_reusing_current_bid(self):
        hit = {"objectID": "205299116", "lotRef": "synthetic116", "lotNumber": "116", "lotTitle": "Calder lithograph", "currencyCode": "USD", "currentBid": 6000, "soldPrice": 11000, "soldCurrencyCode": "CAD"}
        page = json.dumps({"results": [{"hits": [hit]}]})
        lot = self.adapter.parse_search_page(page, "https://www.invaluable.com/search?artistName=Calder", "Calder")[0]
        self.assertEqual(lot.sold_price, 11000)
        self.assertEqual(lot.sold_currency, "CAD")
        self.assertEqual(lot.current_bid, 6000)
        hit.pop("soldPrice")
        lot = self.adapter.parse_search_page(json.dumps({"results": [{"hits": [hit]}]}), "https://www.invaluable.com/search", "Calder")[0]
        self.assertIsNone(lot.sold_price)

    def test_merge_preserves_catalog_identity_and_applies_posted_result(self):
        card = NormalizedLot(source="Invaluable", source_lot_id="205299116", artist="Calder", artist_watchlist_name="Calder", title="Calder lithograph", lot_url=LOT_URL, current_bid=6000, currency="USD")
        detail = self.detail('<p>Sold: $11,000 USD</p>')
        merged = self.adapter.merge_detail(card, detail)
        self.assertEqual(merged.source_lot_id, card.source_lot_id)
        self.assertEqual(merged.lot_url, card.lot_url)
        self.assertEqual(merged.sold_price, 11000)
        self.assertEqual(merged.current_bid, 6000)
        self.assertEqual(merged.content_hash, merged.calculate_content_hash())
