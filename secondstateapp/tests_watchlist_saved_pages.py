"""Offline Heritage imports preserve complete local watchlist membership."""

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from catalogapp.bookmark_watchlist import BookmarkEntry
from catalogapp.watchlist_adapters import HeritageAdapter
from catalogapp.watchlist_cache import WatchlistCache
from catalogapp.watchlist_saved_pages import import_saved_heritage_pages


NOW = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)
ENTRY = BookmarkEntry(
    folder_path=("HERITAGE",),
    title="2026 October 22 Prints & Multiples Signature Auction",
    url="https://fineart.ha.com/c/search/results.zx?auction_name=8280&dept=1544&mode=live",
    source="Heritage",
)


def card(number, *, sale="8280", bid="Starting Bid: $2,000", day="Oct 22, 2026"):
    return f"""
      <li class="item-block">
        <div class="item-info">
          <a href="/c/search.zx?saleNo={sale}">Auction {sale}</a> | Lot {number}
          <a class="item-title" href="/itm/prints-and-multiples/work/a/{sale}-{number}.s">
            <b>Pablo Picasso (1881-1973)</b><br>
            <i>Portrait {number}</i>, 1957<br>
            Lithograph in colors
          </a>
        </div>
        <span class="live-auction-date">Live Auction: {day}</span>
        <div class="item-value">{bid}</div>
      </li>
    """


class SavedHeritagePagesTests(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.cache = WatchlistCache(":memory:")
        self.addCleanup(self.cache.close)

    def page(self, name, content):
        path = Path(self.directory.name) / name
        path.write_text(
            "<html><body>Welcome Private Account Name<ul>" + content + "</ul></body></html>",
            encoding="utf-8",
        )
        return path

    def run_import(self, paths, **kwargs):
        return import_saved_heritage_pages(paths, ENTRY, self.cache, now=NOW, horizon_days=30, **kwargs)

    def test_multiple_pages_deduplicate_and_store_only_lots_without_network(self):
        first = self.page("page1.html", card("65001") + card("65002"))
        second = self.page("page2.html", card("65002") + card("65003", bid="Current Bid: $2,500"))
        with (
            patch.object(HeritageAdapter, "fetch_search_page", side_effect=AssertionError("No network")),
            patch.object(HeritageAdapter, "fetch_lot_detail", side_effect=AssertionError("No network")),
        ):
            result = self.run_import([first, second, first])

        self.assertEqual([lot.lot_number for lot in result.lots], ["65001", "65002", "65003"])
        self.assertEqual(result.metrics.new_lots, 3)
        self.assertEqual(result.metrics.pages_fetched, 0)
        self.assertEqual(result.metrics.detail_pages_fetched, 0)
        self.assertEqual(result.lots[0].bid_label, "No bids")
        self.assertEqual(result.lots[2].current_bid, 2500)
        self.assertEqual({lot.artist_watchlist_name for lot in result.lots}, {"Pablo Picasso"})
        stored = "\n".join(self.cache.connection.iterdump())
        self.assertNotIn("Private Account Name", stored)
        self.assertNotIn("<html>", stored)

    def test_partial_import_preserves_missing_membership_and_observation_time(self):
        old = HeritageAdapter().parse_search_page(card("64999"), ENTRY.url, "")[0]
        old_seen = datetime(2026, 10, 9, 12, tzinfo=timezone.utc)
        self.cache.upsert(old, watch_url=ENTRY.url, search_hash=old.content_hash, observed_at=old_seen)
        page = self.page("page1.html", card("65001"))

        with patch.object(self.cache, "mark_missing_ended", side_effect=AssertionError("Partial snapshot")):
            result = self.run_import([page])

        self.assertEqual({lot.lot_number for lot in result.lots}, {"64999", "65001"})
        self.assertEqual(result.metrics.ended_lots, 0)
        self.assertEqual(result.metrics.cache_hits, 1)
        cached = self.cache.get(old.cache_key)
        self.assertEqual(cached.last_seen_at, old_seen.isoformat())
        self.assertNotEqual(cached.status, "ended")
        self.assertEqual(len(self.cache.active_lots_for_watch_url(ENTRY.url)), 2)

    def test_repeated_snapshot_is_unchanged_and_updated_bid_is_changed(self):
        page = self.page("page1.html", card("65001"))
        self.run_import([page])
        repeated = self.run_import([page])
        self.assertEqual(repeated.metrics.unchanged_lots, 1)
        self.assertEqual(repeated.metrics.new_lots, 0)
        self.assertEqual(repeated.metrics.cache_hits, 1)

        self.page("page1.html", card("65001", bid="Current Bid: $3,000"))
        updated = self.run_import([page])
        self.assertEqual(updated.metrics.changed_lots, 1)
        self.assertEqual(updated.lots[0].current_bid, 3000)

    def test_partial_gallery_snapshot_reports_coverage_and_repairs_cached_missing_dates(self):
        old_card = card("65001").replace('<span class="live-auction-date">Live Auction: Oct 22, 2026</span>', "")
        old = HeritageAdapter().parse_search_page(old_card, ENTRY.url, "")[0]
        self.assertEqual(old.start_at, "")
        self.cache.upsert(old, watch_url=ENTRY.url, search_hash=old.content_hash, observed_at=NOW)
        page = self.page("gallery.html", '<a class="trigger">2026 October 22 Prints Auction</a>'
                         '<span class="number-bid-buy-results">151</span>' + old_card)
        result = self.run_import([page])
        self.assertEqual(result.lots[0].start_at, "2026-10-22")
        self.assertEqual(result.metrics.changed_lots, 1)
        self.assertEqual(result.metrics.ended_lots, 0)
        self.assertIn("1 of 151", result.notices[0])
        self.assertEqual(self.cache.get(old.cache_key).start_at, "2026-10-22")

    def test_missing_date_and_complete_snapshot_have_distinct_notices(self):
        no_date = card("65001").replace('<span class="live-auction-date">Live Auction: Oct 22, 2026</span>', "")
        result = self.run_import([self.page("undated.html", no_date)])
        self.assertIn("no verified sale date", result.notices[0])
        result = self.run_import([self.page("complete.html", '<span class="number-bid-buy-results">1</span>'+card("65001"))])
        self.assertEqual(len(result.notices), 1)
        self.assertIn("no usable saved thumbnail", result.notices[0])
        self.assertNotIn("advertised Heritage lots", result.notices[0])
        self.assertNotIn("no verified sale date", result.notices[0])

    def test_mismatched_second_page_rejects_all_files_before_cache_writes(self):
        first = self.page("page1.html", card("65001"))
        other_sale = self.page("wrong-sale.html", card("65002", sale="9999"))
        with self.assertRaisesRegex(ValueError, "wrong-sale.html.*does not match"):
            self.run_import([first, other_sale])
        self.assertEqual(self.cache.active_lots_for_watch_url(ENTRY.url), [])

    def test_unreadable_and_empty_catalog_pages_leave_existing_lots_active(self):
        first = self.page("page1.html", card("65001"))
        self.run_import([first])
        for name, text in [("login.html", "Please sign in"), ("empty.html", "0 available items")]:
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    self.run_import([self.page(name, text)])
                self.assertEqual(len(self.cache.active_lots_for_watch_url(ENTRY.url)), 1)

    def test_horizon_and_changed_filter_do_not_delete_cached_lots(self):
        first = self.page("page1.html", card("65001", day="Dec 22, 2026"))
        result = self.run_import([first])
        self.assertEqual(result.lots, [])
        self.assertEqual(len(self.cache.active_lots_for_watch_url(ENTRY.url)), 1)
        second = self.page("page2.html", card("65002"))
        result = self.run_import([second], new_changed_only=True)
        self.assertEqual([lot.lot_number for lot in result.lots], ["65002"])
        self.assertEqual(len(self.cache.active_lots_for_watch_url(ENTRY.url)), 2)

    def test_import_accepts_saleno_bookmarks_and_preserves_live_source_error(self):
        entry = replace(ENTRY, url="https://fineart.ha.com/c/search.zx?saleNo=8280")
        self.cache.record_source_error(entry.url, "HTTP 403", NOW)
        result = import_saved_heritage_pages(
            [self.page("page1.html", card("65001"))], entry, self.cache, now=NOW, horizon_days=30
        )
        self.assertEqual(len(result.lots), 1)
        error = self.cache.connection.execute(
            "SELECT last_error FROM source_runs WHERE watch_url = ?", (entry.url,)
        ).fetchone()[0]
        self.assertEqual(error, "HTTP 403")

    def test_requires_selected_heritage_sale_and_html_files(self):
        page = self.page("page1.html", card("65001"))
        invalid_entries = [
            replace(ENTRY, source="Invaluable"),
            replace(ENTRY, url="https://example.com/c/search.zx?auction_name=8280"),
            replace(ENTRY, url="https://fineart.ha.com/c/search.zx"),
            replace(ENTRY, url="https://fineart.ha.com/c/search.zx?auction_name=8280&saleNo=9999"),
        ]
        for entry in invalid_entries:
            with self.subTest(entry=entry):
                with self.assertRaises(ValueError):
                    import_saved_heritage_pages([page], entry, self.cache, now=NOW)
        with self.assertRaises(ValueError):
            self.run_import([])
        with self.assertRaises(ValueError):
            self.run_import([self.page("catalog.mhtml", card("65001"))])
