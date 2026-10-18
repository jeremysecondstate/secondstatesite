"""Doyle catalog coverage, identity, dates, and saved artwork safety."""

from pathlib import Path
import tempfile
from datetime import datetime, timezone

from django.test import SimpleTestCase
from PIL import Image

from catalogapp.doyle import DoyleAdapter, attach_saved_doyle_images
from catalogapp.watchlist_fetch import SourceAccessError


URL = "https://doyle.com/auction/search/?au=9224&pn=1&mc=219"


def card(number="1", artist="Rembrandt van Rijn (1606-1669)", identity="1487841", sale="9224", image="./saved_files/art.jpg"):
    return f'''<div class="auction-grid-lot" data-lotwithsuffix="{number}">
      <div class="auction-lot" data-ended="1" data-endtime="-1">
        <div class="auction-lot-image"><a href="/auction/lot/lot-{number}---artist/?lot={identity}&amp;au={sale}&amp;pn=2&amp;so=0">
          <img src="{image}"></a></div>
        <p class="auction-lot-title"><a href="/auction/lot/lot-{number}---artist/?lot={identity}&amp;au={sale}&amp;pn=2&amp;so=0">
          <span class="lot-title">Lot {number}<br>{artist}</span></a></p>
        <div class="estimate"><strong>Estimate: $1,000 - $1,500</strong></div>
      </div></div>'''


def catalog(*cards):
    return '''<h2 class="auction-details-title">Prints &amp; Multiples</h2>
      <div class="auction-details-buttons"><a href="/auction/26pm03-prints--multiples?au=9224">Auction details</a></div>
      <select id="Filter_AuctionId"><option value="9999">Other Sale 10/22/2026</option>
        <option value="9224" selected>Prints &amp; Multiples 10/20/2026</option></select>
      <a class="auction-tab-current">Current lots (182)</a>''' + "".join(cards)


class DoyleAdapterTests(SimpleTestCase):
    def setUp(self):
        self.adapter = DoyleAdapter()

    def test_snapshot_observation_uses_only_unambiguous_catalog_load_time(self):
        script = '<script>var pageLoadTimeStamp = 1792273075;</script>'
        expected = datetime(2026, 10, 17, 21, 37, 55, tzinfo=timezone.utc)
        self.assertEqual(self.adapter.snapshot_observed_at(script), expected)
        for bad in (script.replace("pageLoadTimeStamp", "auctionStartTime"),
                    script.replace("1792273075", "99999999999"),
                    '<p>var pageLoadTimeStamp = 1792273075;</p>',
                    script + script.replace("1792273075", "1792274075")):
            with self.subTest(bad=bad):
                self.assertIsNone(self.adapter.snapshot_observed_at(bad))

    def test_sale_includes_unbookmarked_artists_and_preserves_number_suffix(self):
        page = catalog(card(), card("72A", "Jean (Hans) Arp (1886-1966)", "1490000"), card())
        lots = self.adapter.parse_search_page(page, URL, "Some other bookmarked artist")
        self.assertEqual(len(lots), 2)
        first, second = lots
        self.assertEqual((first.artist, first.artist_watchlist_name), ("Rembrandt van Rijn", "Rembrandt van Rijn"))
        self.assertEqual(first.source_lot_id, "9224-1487841")
        self.assertEqual(first.title, "Lot 1")
        self.assertEqual(first.start_at, "2026-10-20")
        self.assertEqual(first.end_at, "")
        self.assertEqual(first.status, "unchanged")
        self.assertEqual((first.estimate_low, first.estimate_high, first.currency), (1000, 1500, "USD"))
        self.assertEqual(first.lot_url, "https://doyle.com/auction/lot/lot-1---artist?au=9224&lot=1487841")
        self.assertEqual(first.image_url, "")
        self.assertEqual(first.sale_title, "Prints & Multiples")
        self.assertEqual(second.artist, "Jean (Hans) Arp")
        self.assertEqual(second.lot_number, "72A")
        self.assertTrue(self.adapter.needs_detail(first))
        self.assertEqual(self.adapter.catalog_total(page), 182)

    def test_attribution_and_birth_year_are_not_mistaken_for_title(self):
        lots = self.adapter.parse_search_page(catalog(card(artist="After Pablo Picasso (1881-1973)"), card("2", "Living Artist (b. 1942)", "1487842")), URL, "")
        self.assertEqual([lot.artist for lot in lots], ["After Pablo Picasso", "Living Artist"])
        self.assertEqual([lot.title for lot in lots], ["Lot 1", "Lot 2"])

    def test_mixed_sales_or_unreadable_response_cannot_be_successful_empty_catalog(self):
        for page in (catalog(card(sale="9999")), "<h1>JavaScript is required to continue.</h1>", catalog('<div class="auction-grid-lot"></div>')):
            with self.subTest(page=page), self.assertRaises(SourceAccessError):
                self.adapter.parse_search_page(page, URL, "")
        self.assertEqual(self.adapter.parse_search_page('<a class="auction-tab-current">Current lots (0)</a>', URL, ""), [])

    def test_missing_selected_sale_date_does_not_take_another_sale_date(self):
        page = catalog(card()).replace("Prints &amp; Multiples 10/20/2026", "Prints &amp; Multiples")
        self.assertEqual(self.adapter.parse_search_page(page, URL, "")[0].start_at, "")

    def test_sale_title_falls_back_to_the_matching_auction_option(self):
        page = catalog(card()).replace('<h2 class="auction-details-title">Prints &amp; Multiples</h2>', "")
        self.assertEqual(self.adapter.parse_search_page(page, URL, "")[0].sale_title, "Prints & Multiples")

    def test_one_malformed_or_conflicting_card_cannot_hide_among_valid_cards(self):
        for bad in ('<div class="auction-grid-lot"></div>', card(artist=""), card(artist="Conflicting Artist")):
            with self.subTest(bad=bad), self.assertRaises(SourceAccessError):
                self.adapter.parse_search_page(catalog(card(), bad), URL, "")

    def test_pagination_follows_only_forward_same_sale_links(self):
        page = '<nav class="pagination"><a href="?au=9224&amp;pn=2"><i class="fal fa-chevron-right"></i></a></nav>'
        self.assertEqual(self.adapter.extract_next_page_url(page, URL), "https://doyle.com/auction/search/?au=9224&pn=2")
        self.assertEqual(self.adapter.extract_next_page_url(page.replace('<a href', '<a disabled href'), URL), "")
        for bad in (page.replace("au=9224", "au=9999"), page.replace("pn=2", "pn=3"), page.replace("pn=2", "pn=1")):
            with self.subTest(bad=bad), self.assertRaises(SourceAccessError):
                self.adapter.extract_next_page_url(bad, URL)

    def test_pagination_must_account_for_every_advertised_lot(self):
        page = catalog(card()).replace("Current lots (182)", "Current lots (2)")
        with self.assertRaisesRegex(SourceAccessError, "more catalog lots"):
            self.adapter.extract_next_page_url(page, URL)
        next_page = '<nav class="pagination"><a href="?au=9224&amp;pn=2"><i class="fa-chevron-right"></i></a></nav>'
        size = '<select class="auction-results-per-page"><option selected value="2">2</option></select>'
        with self.assertRaisesRegex(SourceAccessError, "incomplete"):
            self.adapter.extract_next_page_url(page + size, URL)
        self.assertTrue(self.adapter.extract_next_page_url(page + next_page + size.replace('value="2"', 'value="1"'), URL))
        final = page + size.replace('value="2"', 'value="1"')
        self.assertEqual(self.adapter.extract_next_page_url(final, URL.replace("pn=1", "pn=2")), "")
        selected = '<nav class="pagination"><select><option selected value="?au=9224&amp;pn=2">2</option></select></nav>'
        # Only catalog-path options represent the current page; sort/per-page
        # options also live in the pagination container.
        selected = selected.replace('value="?', 'value="/auction/search/?')
        with self.assertRaisesRegex(SourceAccessError, "different catalog page"):
            self.adapter.extract_next_page_url(final + selected, URL)

    def test_remote_images_require_known_public_hosts(self):
        good = "https://goauctiondoyle.blob.core.windows.net/stock/123-small.jpg"
        bad = "https://unrelated.example/image.jpg"
        self.assertEqual(self.adapter.parse_search_page(catalog(card(image=good)), URL, "")[0].image_url, good)
        self.assertEqual(self.adapter.parse_search_page(catalog(card(image=bad)), URL, "")[0].image_url, "")

    def test_saved_images_match_lot_identity_and_stay_in_companion_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            page_path = Path(directory) / "saved.html"
            folder = Path(directory) / "saved_files"
            folder.mkdir()
            image = Image.new("RGB", (32, 32), "white")
            image.putpixel((1, 1), (0, 0, 0))
            image.save(folder / "art.jpg")
            image.save(Path(directory) / "outside.jpg")
            page = catalog(card(), card("2", "Another Artist", "1487842", image="./saved_files/../outside.jpg"))
            lots = self.adapter.parse_search_page(page, URL, "")
            notice = attach_saved_doyle_images(page, page_path, lots)
            self.assertTrue(lots[0].saved_image_base64)
            self.assertFalse(lots[1].saved_image_base64)
            self.assertEqual(lots[0].content_hash, lots[0].calculate_content_hash())
            self.assertIn("1 Doyle lots", notice[0])

    def test_structured_detail_can_supply_verified_title_without_fabricating_time(self):
        page = catalog() + '''<script type="application/ld+json">{"@type":"VisualArtwork","name":"The Artist's Mother", "artist":{"name":"Rembrandt van Rijn"},"artMedium":"Etching"}</script>'''
        lot = self.adapter.parse_lot_detail(page, "https://doyle.com/auction/lot/lot-1---artist/?lot=1487841&au=9224", "")
        self.assertEqual(lot.title, "The Artist's Mother")
        self.assertEqual(lot.medium, "Etching")
        self.assertEqual(lot.start_at, "2026-10-20")
        self.assertIsNone(self.adapter.parse_lot_detail("<h1>Browser check</h1>", lot.lot_url, ""))

    def test_supplied_sale_snapshots_cover_every_advertised_lot_with_images(self):
        directory = Path(__file__).resolve().parents[1] / "docs" / "doyle"
        lots = []
        for path in sorted(directory.glob("DOYLE-1020-*.html")):
            page = path.read_text(encoding="utf-8-sig")
            parsed = self.adapter.parse_search_page(page, URL, "")
            self.assertEqual(self.adapter.catalog_total(page), 182)
            self.assertEqual(attach_saved_doyle_images(page, path, parsed), [])
            page_url = URL.replace("pn=1", "pn=2") if path.stem.endswith("-2") else URL
            next_page = self.adapter.extract_next_page_url(page, page_url)
            self.assertEqual(bool(next_page), path.stem.endswith("-1"))
            lots.extend(parsed)
        self.assertEqual(len(lots), 182)
        self.assertEqual(len({lot.cache_key for lot in lots}), 182)
        self.assertEqual(len({lot.artist for lot in lots}), 67)
        self.assertTrue(all(lot.saved_image_base64 for lot in lots))
        self.assertTrue(all(lot.start_at == "2026-10-20" for lot in lots))
        self.assertIn("72A", {lot.lot_number for lot in lots})
