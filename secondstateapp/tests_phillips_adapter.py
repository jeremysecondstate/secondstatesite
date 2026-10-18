"""Phillips fixtures preserve real card and React Router reference shapes."""

from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase
from PIL import Image

from catalogapp.phillips import PhillipsAdapter, attach_saved_phillips_images
from catalogapp.watchlist_fetch import SourceAccessError


URL = "https://www.phillips.com/auction/NY030726/browse"
AUCTION = {
    "auctionCode": "NY030726", "auctionName": "Editions & Works on Paper",
    "auctionLocation": "New York", "auctionTimezone": "America/New_York",
    "auctionStartDateTime": "2026-10-22T21:00:00.000000Z",
    "auctionEndDateTime": "2026-10-24T16:00:00.000000Z",
    "auctionCurrency": {"currencyCode": "USD", "currencySign": "$"},
    "totalLotCount": 2,
    "sessions": [
        {"title": "Session I: Evening Sale", "startDateTime": "2026-10-22T21:00:00.000000Z",
         "lotNumberStart": "101", "lotNumberEnd": "177"},
        {"title": "Session II: Day Sale", "startDateTime": "2026-10-24T15:00:00.000000Z",
         "lotNumberStart": "178", "lotNumberEnd": "302"},
    ],
    "lots": [
        {"objectNumber": "236058", "lotNumberFull": "101", "makerName": "David Hockney"},
        {"objectNumber": "235187", "lotNumberFull": "220", "makerName": "Frank Stella"},
    ],
}


def stream(route):
    values = []

    def encode(value):
        position = len(values)
        values.append(None)
        if isinstance(value, dict):
            values[position] = {f"_{encode(key)}": encode(item) for key, item in value.items()}
        elif isinstance(value, list):
            values[position] = [encode(item) for item in value]
        else:
            values[position] = value
        return position

    encode({"loaderData": {"routes/detail": route}})
    return f'<script>window.__reactRouterContext.streamController.enqueue({json.dumps(json.dumps(values))});</script>'


def card(number="101", object_number="236058", artist="David Hockney", title="Flowers"):
    return f'''<a class="seldon-object-tile pah-lot-object-tile" href="https://www.phillips.com/detail/example/{object_number}">
      <img src="./sale_files/{object_number}_001.jpg"
        id="https://dist.phillips.com/auction-assets/NY030726/{object_number}_001.jpg?fit=cover&amp;width=928">
      <span class="seldon-object-tile__lot-number">{number}</span>
      <span class="seldon-object-tile__maker"><div>{artist}</div></span>
      <cite class="seldon-object-tile__title"><span>{title}</span></cite>
      <div class="seldon-object-tile__estimate"><div class="seldon-detail__value">$35,000–55,000</div></div>
    </a>'''


def catalog(auction=None, cards=None):
    return stream({"auction": deepcopy(AUCTION) if auction is None else auction}) + (
        card() + card("220", "235187", "Frank Stella", "Shards V") if cards is None else cards
    )


class PhillipsAdapterTests(SimpleTestCase):
    def setUp(self):
        self.adapter = PhillipsAdapter()

    def test_catalog_includes_unwatched_artists_and_each_actual_session(self):
        page = catalog()
        lots = self.adapter.parse_search_page(page, URL, "PHILLIPS-1022")
        self.assertEqual(len(lots), 2)
        first, second = lots
        self.assertEqual((first.artist, first.artist_watchlist_name), ("David Hockney", "David Hockney"))
        self.assertEqual((second.artist, second.artist_watchlist_name), ("Frank Stella", "Frank Stella"))
        self.assertEqual(first.source_lot_id, "NY030726-236058")
        self.assertEqual(first.start_at, "2026-10-22T17:00:00-04:00")
        self.assertEqual(second.start_at, "2026-10-24T11:00:00-04:00")
        self.assertEqual(second.end_at, "")
        self.assertEqual((first.estimate_low, first.estimate_high, first.currency), (35000, 55000, "USD"))
        self.assertIsNone(first.current_bid)
        self.assertEqual(first.sale_url, URL)
        self.assertEqual(first.image_url, "https://dist.phillips.com/auction-assets/NY030726/236058_001.jpg?fit=bounds&width=900&height=900")
        self.assertFalse(self.adapter.needs_detail(first))
        self.assertEqual(self.adapter.catalog_total(page), 2)
        self.assertEqual(self.adapter.extract_lot_links(page, URL), [lot.lot_url for lot in lots])
        self.assertEqual(self.adapter.extract_next_page_url(page, URL), "")

    def test_boundary_lots_use_session_ranges_and_priority_deadline_is_ignored(self):
        auction = deepcopy(AUCTION)
        auction["auctionDetails"] = "Priority bidding ends October 20, 2026, 5pm ET"
        auction["lots"][0]["lotNumberFull"] = "177"
        auction["lots"][1]["lotNumberFull"] = "178"
        lots = self.adapter.parse_search_page(catalog(auction, card("177") + card("178", "235187")), URL, "")
        self.assertEqual([lot.start_at for lot in lots], ["2026-10-22T17:00:00-04:00", "2026-10-24T11:00:00-04:00"])

    def test_wrong_sale_or_mismatched_lot_inventory_cannot_import(self):
        wrong_sale = deepcopy(AUCTION)
        wrong_sale["auctionCode"] = "NY999926"
        for page in (catalog(wrong_sale), catalog(cards=card("102"))):
            with self.subTest(page=page[:80]), self.assertRaises(SourceAccessError):
                self.adapter.parse_search_page(page, URL, "")
        with self.assertRaises(SourceAccessError):
            self.adapter.parse_search_page(catalog(), "https://www.phillips.com/auction", "")

    def test_multiday_without_exact_session_or_overlapping_sessions_fails(self):
        for sessions in ([], [AUCTION["sessions"][1]], [AUCTION["sessions"][0]] * 2):
            auction = deepcopy(AUCTION)
            auction["sessions"] = sessions
            with self.subTest(sessions=sessions), self.assertRaises(SourceAccessError):
                self.adapter.parse_search_page(catalog(auction, card()), URL, "")

    def test_partial_snapshot_is_parseable_but_live_refresh_cannot_call_it_complete(self):
        page = catalog(cards=card() + card())
        self.assertEqual(len(self.adapter.parse_search_page(page, URL, "")), 1)
        with self.assertRaisesRegex(SourceAccessError, "more catalog lots"):
            self.adapter.extract_next_page_url(page, URL)
        for page in ("<div id='app'></div>", "<h1>Access denied</h1>", catalog(cards="")):
            with self.subTest(page=page[:80]), self.assertRaises(SourceAccessError):
                self.adapter.parse_search_page(page, URL, "")

    def test_embedded_detail_never_becomes_an_extra_catalog_lot(self):
        detail = {
            "objectNumber": "235187", "lotNumberFull": "220", "makerName": "Frank Stella",
            "description": "Shards V", "medium": "Lithograph and screenprint",
            "sessionStartDateTime": "2026-10-24T15:00:00Z", "startBidAmount": 3500,
            "estimate": {"mainEstimate": {"currencyCode": "USD", "lowEstimate": 5000, "highEstimate": 7000}},
            "mainImagePath": "https://dist.phillips.com/auction-assets/NY030726/235187_001.jpg",
        }
        page = stream({"auction": AUCTION, "lot": detail}) + card()
        self.assertEqual(len(self.adapter.parse_search_page(page, URL, "")), 1)
        lot = self.adapter.parse_lot_detail(page, "https://www.phillips.com/detail/frank-stella/235187", "")
        self.assertEqual(lot.start_at, "2026-10-24T11:00:00-04:00")
        self.assertEqual(lot.medium, "Lithograph and screenprint")
        self.assertEqual(lot.estimate_low, 5000)
        self.assertIsNone(lot.current_bid)
        self.assertIsNone(self.adapter.parse_lot_detail(page, "https://www.phillips.com/detail/other/999999", ""))

    def test_single_day_event_fallback_and_local_image_names_are_not_remote_urls(self):
        event = {"@type": "Event", "url": URL, "name": r"Editions \u0026 Works on Paper",
                 "startDate": "2026-10-22T21:00:00Z", "endDate": "2026-10-22T23:00:00Z",
                 "offers": {"priceCurrency": "USD"}, "location": {"name": "New York"}}
        page = '<script type="application/ld+json">' + json.dumps(event) + '</script>'
        page += card().replace('id="https://dist.phillips.com/auction-assets/NY030726/236058_001.jpg?fit=cover&amp;width=928"', "")
        lot = self.adapter.parse_search_page(page, URL, "")[0]
        self.assertEqual(lot.sale_title, "Editions & Works on Paper")
        self.assertEqual(lot.start_at, "2026-10-22T21:00:00+00:00")
        self.assertEqual(lot.image_url, "")

    def test_saved_images_are_confined_to_companion_folder_and_matching_lots(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "sale.html"
            assets = Path(folder) / "sale_files"
            assets.mkdir()
            image = BytesIO()
            pixels = Image.new("RGB", (80, 60), "red")
            pixels.paste("blue", (0, 0, 40, 30))
            pixels.save(image, format="PNG")
            (assets / "236058_001.jpg").write_bytes(image.getvalue())
            (Path(folder) / "outside.jpg").write_bytes(image.getvalue())
            page = catalog()
            lots = self.adapter.parse_search_page(page, URL, "")
            notices = attach_saved_phillips_images(page, path, lots)
            self.assertTrue(lots[0].saved_image_base64)
            self.assertEqual(lots[0].content_hash, lots[0].calculate_content_hash())
            self.assertFalse(lots[1].saved_image_base64)
            self.assertIn("1 Phillips", notices[0])
            unsafe = page.replace("./sale_files/236058_001.jpg", "./sale_files/../outside.jpg")
            unsafe_lots = self.adapter.parse_search_page(unsafe, URL, "")
            attach_saved_phillips_images(unsafe, path, unsafe_lots)
            self.assertFalse(unsafe_lots[0].saved_image_base64)
