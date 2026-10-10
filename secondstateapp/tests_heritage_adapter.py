"""Synthetic fixtures mirror Heritage's visible catalog and lot-detail markup."""

from datetime import datetime, timezone

from django.test import SimpleTestCase

from catalogapp.bookmark_watchlist import parse_bookmarks_html
from catalogapp.watchlist_adapters import HeritageAdapter, adapter_for_url
from catalogapp.watchlist_cache import WatchlistCache
from catalogapp.watchlist_exports import render_ics
from catalogapp.watchlist_fetch import SourceAccessError
from catalogapp.watchlist_service import WatchlistService


URL = "https://fineart.ha.com/c/search/results.zx?dept=1544&mode=live&auction_name=8280"
NOW = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)


def card(number="65001", artist="Example Artist", bid="Starting Bid: $2,000", sale="8280"):
    return f'''<li class="item-block list" id="{sale}-internal-{number}">
      <a class="photo-holder" href="/itm/print/a/{sale}-{number}.s">
        <img class="thumbnail" src="https://dyn1.heritagestatic.com/ha?p=1-2-3-12345678&amp;w=120&amp;h=300&amp;it=product"></a>
      <div class="item-info"><p><a href="/c/search.zx?saleNo={sale}&amp;ic4=tracking">Auction {sale}</a> | Lot {number}</p>
        <a class="item-title short" href="/itm/print/a/{sale}-{number}.s?ic4=ListView-ShortDescription">
          <b>{artist} (1900-1980)</b><br><i>Test Print</i>, 1962<br>Linocut in colors on paper<br>Signed</a>
        <p>Estimate: $4,000 - $6,000.</p><div class="live-auction-date">Live auction on Oct 22, 2026</div>
      </div><div class="item-value">{bid}</div></li>'''


def catalog(*cards, next_page=False):
    pagination = '<a class="pageindex" href="?dept=1544&amp;mode=live&amp;auction_name=8280&amp;page=25~2">2</a>' if next_page else ""
    return '<a class="trigger"><span>2026 October 22 Prints &amp; Multiples Signature® Auction</span></a>' + "".join(cards) + pagination


class HeritageAdapterTests(SimpleTestCase):
    def setUp(self):
        self.adapter = HeritageAdapter()

    def test_real_card_shape_preserves_artist_date_money_and_stable_identity(self):
        page = catalog(card(), card("65002", "Another Artist", "Current Bid: $1,400"))
        self.assertIsInstance(adapter_for_url(URL), HeritageAdapter)
        lots = self.adapter.parse_search_page(page, URL, "")
        self.assertEqual(len(lots), 2)
        lot = lots[0]
        self.assertEqual((lot.artist, lot.artist_watchlist_name), ("Example Artist", "Example Artist"))
        self.assertEqual(lot.source_lot_id, "8280-65001")
        self.assertEqual(lot.title, "Test Print, 1962")
        self.assertEqual(lot.medium, "Linocut in colors on paper")
        self.assertEqual(lot.start_at, "2026-10-22")
        self.assertEqual((lot.estimate_low, lot.estimate_high, lot.currency), (4000, 6000, "USD"))
        self.assertEqual(lot.bid_label, "No bids")
        self.assertIsNone(lot.current_bid)
        self.assertNotIn("ic4", lot.lot_url)
        self.assertNotIn("ic4", lot.sale_url)
        self.assertEqual(lots[1].current_bid, 1400)
        self.assertIsNone(lots[1].bid_count)
        self.assertFalse(self.adapter.needs_detail(lot))
        self.assertEqual(
            lot.image_url,
            "https://dyn1.heritagestatic.com/ha?p=1-2-3-12345678&w=612&h=600&it=product",
        )
        self.assertEqual(self.adapter.extract_lot_links(page, URL), [lot.lot_url for lot in lots])
        ics = render_ics(lots, generated_at=NOW)
        self.assertEqual(ics.count("BEGIN:VEVENT"), 1)
        self.assertIn("DTSTART;VALUE=DATE:20261022", ics)

    def test_duplicate_cards_collapse_and_other_sale_does_not_match(self):
        self.assertEqual(len(self.adapter.parse_search_page(catalog(card(), card()), URL, "")), 1)
        with self.assertRaisesRegex(SourceAccessError, "auction number"):
            self.adapter.parse_search_page(catalog(card(sale="9999")), URL, "")

    def test_saved_gallery_cards_use_sale_heading_bid_fields_and_remote_lazy_images(self):
        page = catalog('''<li class="item-block gallery">
          <a class="photo-holder"><img src="./saved_files/ha(4)"
            data-src="https://dyn1.heritagestatic.com/ha?p=1-2-3-12345678&amp;w=200&amp;h=400&amp;it=product"></a>
          <a class="item-title short" href="https://fineart.ha.com/itm/print/a/8280-65001.s">
            <b>Example Artist (1900-1980)</b><br><i>Gallery Print</i>, 1962<br>Linocut on paper</a>
          <div class="lotno"><a href="https://fineart.ha.com/c/search.zx?saleNo=8280">Auction 8280</a> | Lot: 65001</div>
          <div class="current-amount">Estimate: $4,000 - $6,000.<br>
            <span class="bid-value"><span class="bid-text">Current Bid:</span><span class="bid-amount">$2,500</span></span>
            <span class="time-remaining">12 days</span></div></li>''')
        lot = self.adapter.parse_search_page(page, URL, "")[0]
        self.assertEqual(lot.start_at, "2026-10-22")
        self.assertEqual(lot.current_bid, 2500)
        self.assertEqual(lot.sale_url, "https://fineart.ha.com/c/search.zx?saleNo=8280")
        self.assertEqual(lot.image_url, "https://dyn1.heritagestatic.com/ha?p=1-2-3-12345678&w=612&h=600&it=product")
        self.assertFalse(self.adapter.needs_detail(lot))
        without_remote = page.replace('data-src="https://dyn1.heritagestatic.com/ha?p=1-2-3-12345678&amp;w=200&amp;h=400&amp;it=product"', "")
        lot = self.adapter.parse_search_page(without_remote.replace("Current Bid:", "Starting Bid:"), URL, "")[0]
        self.assertEqual(lot.image_url, "")
        self.assertIsNone(lot.current_bid)
        self.assertEqual(lot.bid_count, 0)

    def test_preview_normalization_preserves_other_allowed_public_image_urls(self):
        original = "https://dyn1.heritagestatic.com/ha?p=1-2-3-12345678&amp;w=120&amp;h=300&amp;it=product"
        urls = [
            "https://www.heritagestatic.com/c/i/artwork.jpg?w=120&amp;h=300",
            "https://fineart.ha.com/images/print.jpg?w=120&amp;h=300",
            "https://dyn1.heritagestatic.com/other?p=1-2-3-12345678&amp;w=120",
            "https://dyn1.heritagestatic.com/ha?p=unrecognized&amp;w=120&amp;h=300",
        ]
        for url in urls:
            with self.subTest(url=url):
                lot = self.adapter.parse_search_page(catalog(card().replace(original, url)), URL, "")[0]
                self.assertEqual(lot.image_url, url.replace("&amp;", "&"))
        blocked = "https://unrelated.example/artwork.jpg"
        lot = self.adapter.parse_search_page(catalog(card().replace(original, blocked)), URL, "")[0]
        self.assertEqual(lot.image_url, "")

    def test_date_heading_fallback_requires_a_single_bookmarked_sale_and_single_day(self):
        page = catalog(card().replace('<div class="live-auction-date">Live auction on Oct 22, 2026</div>', ""))
        search = "https://fineart.ha.com/c/search/results.zx?keyword=print"
        self.assertEqual(self.adapter.parse_search_page(page, search, "")[0].start_at, "")
        for title in ("2026 October 22-23", "2026 October 22–23", "2026 October 32"):
            with self.subTest(title=title):
                self.assertEqual(self.adapter.parse_search_page(page.replace("2026 October 22", title), URL, "")[0].start_at, "")

    def test_unreadable_shell_is_not_a_successful_empty_sale(self):
        for page in ("<div id='app'></div>", "<h1>Access denied</h1>", '<li class="item-block"></li>'):
            with self.assertRaises(SourceAccessError):
                self.adapter.parse_search_page(page, URL, "")
        self.assertEqual(self.adapter.parse_search_page("<main>No results found</main>", URL, ""), [])

    def test_pagination_is_bounded_to_sale_and_detects_incomplete_pages(self):
        page = catalog(card(), next_page=True)
        second_url = self.adapter.extract_next_page_url(page, URL)
        self.assertIn("page=25~2", second_url)
        self.assertEqual(self.adapter.extract_next_page_url(catalog(card("65026")), second_url), "")
        for bad in (page.replace("auction_name=8280", "auction_name=9999"), page.replace("page=25~2", "page=25~4")):
            with self.assertRaises(SourceAccessError):
                self.adapter.extract_next_page_url(bad, URL)
        truncated = catalog(card()) + '<span class="number-bid-buy-results">151</span>'
        with self.assertRaisesRegex(SourceAccessError, "more catalog lots"):
            self.adapter.extract_next_page_url(truncated, URL)

    def test_detail_uses_session_time_not_proxy_deadline_or_phone_bid_count(self):
        html = '''<div id="auction-description"><span itemprop="description">
          <b>Example Artist (1900-1980)</b><br><i>Test Print</i>, 1962<br>Linocut on paper
          </span>Estimate: $4,000 - $6,000.</div><div id="bidBlockTop">Current Bid: $2,200</div>
          <div id="auction-info"><div class="auction-home-link">2026 October 22 Prints &amp; Multiples Signature® Auction #8280
            <a href="/c/auction-home.zx?saleNo=8280">(go to Auction Home page)</a></div>
            <div class="bidding-end">Proxy Bidding Ends October 22nd 10:50 am CT</div>
            <div>Bids + Registered Phone Bidders: <span id="number-bids">8</span></div>
            <div class="additional-info"><div class="left">This lot is in: 1 - Floor Session
            (Lots 65001-65118) - 11:00 AM Central Time, Thursday, October 22, 2026.</div></div></div>
          <img src="https://dyn2.heritagestatic.com/ha?p=1-2-3-12345678&amp;w=120&amp;h=300&amp;it=product">'''
        lot = self.adapter.parse_lot_detail(html, "https://fineart.ha.com/itm/print/a/8280-65001.s", "")
        self.assertEqual(lot.start_at, "2026-10-22T11:00:00-05:00")
        self.assertEqual(lot.end_at, "")
        self.assertEqual(lot.current_bid, 2200)
        self.assertIsNone(lot.bid_count)
        self.assertEqual(lot.image_url, "https://dyn2.heritagestatic.com/ha?p=1-2-3-12345678&w=612&h=600&it=product")
        self.assertIn("DTSTART:20261022T160000Z", render_ics([lot], generated_at=NOW))
        recommended = html.replace("Current Bid: $2,200", "Starting Bid: $2,000") + '<aside>Current Bid: $500</aside>'
        lot = self.adapter.parse_lot_detail(recommended, "https://fineart.ha.com/itm/print/a/8280-65001.s", "")
        self.assertIsNone(lot.current_bid)
        self.assertEqual(lot.bid_count, 0)


class HeritageServiceTests(SimpleTestCase):
    def test_sale_selection_pagination_cache_bid_change_and_failed_refresh(self):
        entry = parse_bookmarks_html(f'<DL><H3>HERITAGE</H3><DL><A HREF="{URL}">10-22 SALE</A></DL></DL>')[0]
        class Fetcher:
            pages_fetched = 0
            blocked = False
            bid = "Current Bid: $1,400"

            def fetch(self, url):
                self.pages_fetched += 1
                if self.blocked:
                    return "<div id='app'></div>"
                return catalog(card("65002", "Another Artist", self.bid)) if "page=" in url else catalog(card(), next_page=True)

        fetcher = Fetcher()
        with WatchlistCache(":memory:") as cache:
            service = WatchlistService(cache, fetcher=fetcher, now=lambda: NOW)
            result = service.refresh([entry], selected_artists=["10-22 SALE"], horizon_days=30)
            self.assertFalse(result.errors)
            self.assertEqual(len(result.lots), 2)
            self.assertEqual(result.metrics.pages_fetched, 2)
            self.assertEqual(result.metrics.detail_pages_fetched, 0)
            self.assertEqual(result.metrics.new_lots, 2)
            again = service.refresh([entry], selected_artists=["10-22 SALE"], horizon_days=30)
            self.assertEqual(again.metrics.cache_hits, 2)
            self.assertEqual({lot.artist_watchlist_name for lot in again.lots}, {"Example Artist", "Another Artist"})
            self.assertEqual(service.refresh([entry], selected_artists=["10-22 SALE"], horizon_days=7).lots, [])
            fetcher.bid = "Current Bid: $1,600"
            changed = service.refresh([entry], selected_artists=["10-22 SALE"], horizon_days=30)
            self.assertEqual(changed.metrics.changed_lots, 1)
            fetcher.blocked = True
            failure = service.refresh([entry], selected_artists=["10-22 SALE"], horizon_days=30)
            self.assertEqual(len(failure.lots), 2)
            self.assertEqual(failure.metrics.ended_lots, 0)
            self.assertTrue(failure.errors)
            self.assertNotIn("10-22 SALE", {lot.artist_watchlist_name for lot in failure.lots})

    def test_incomplete_pagination_keeps_previous_lots_active(self):
        entry = parse_bookmarks_html(f'<A HREF="{URL}">10-22 SALE</A>')[0]
        adapter = HeritageAdapter()
        prior = adapter.parse_search_page(catalog(card("65099")), URL, "")[0]
        class Fetcher:
            pages_fetched = 0
            def fetch(self, url):
                self.pages_fetched += 1
                return catalog(card()) + '<span class="number-bid-buy-results">151</span>'
        with WatchlistCache(":memory:") as cache:
            cache.upsert(prior, watch_url=entry.url, search_hash=prior.content_hash, observed_at=NOW)
            result = WatchlistService(cache, fetcher=Fetcher(), now=lambda: NOW).refresh(
                [entry], selected_artists=[entry.watch_label], horizon_days=30)
            self.assertTrue(result.errors)
            self.assertEqual(result.metrics.ended_lots, 0)
            self.assertEqual({lot.source_lot_id for lot in result.lots}, {"8280-65001", "8280-65099"})

    def test_repeated_catalog_page_never_ends_omitted_cached_lots(self):
        entry = parse_bookmarks_html(f'<A HREF="{URL}">10-22 SALE</A>')[0]
        prior = HeritageAdapter().parse_search_page(catalog(card("65099")), URL, "")[0]
        class Fetcher:
            pages_fetched = 0
            def fetch(self, url):
                self.pages_fetched += 1
                return catalog(card(), next_page=True)
        with WatchlistCache(":memory:") as cache:
            cache.upsert(prior, watch_url=entry.url, search_hash=prior.content_hash, observed_at=NOW)
            result = WatchlistService(cache, fetcher=Fetcher(), now=lambda: NOW).refresh(
                [entry], selected_artists=[entry.watch_label], horizon_days=30)
            self.assertTrue(result.errors)
            self.assertEqual(result.metrics.ended_lots, 0)
            self.assertEqual({lot.source_lot_id for lot in result.lots}, {"8280-65001", "8280-65099"})
