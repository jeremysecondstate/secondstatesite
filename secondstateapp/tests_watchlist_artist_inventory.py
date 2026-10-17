"""Pure regressions for the per-artist bookmark/Calendar reconciliation view."""

from dataclasses import replace
from types import SimpleNamespace
from unittest import TestCase

from catalogapp.bookmark_watchlist import parse_bookmarks_html
from catalogapp.watchlist_artist_inventory import artist_inventory_rows
from catalogapp.watchlist_coverage import WatchCoverage
from catalogapp.watchlist_models import NormalizedLot


def entry(name="Will Barnet", *, source="Invaluable", title="Barnett, Will: Invaluable — Prints", extra=""):
    host = "www.invaluable.com" if source == "Invaluable" else "www.liveauctioneers.com"
    query = "artistName" if source == "Invaluable" else "keyword"
    return parse_bookmarks_html(
        f'<DL><DT><H3>ARTISTS INVALUABLE</H3><DL><DT><A HREF="https://{host}/search?{query}={name}{extra}">{title}</A></DL></DL>'
    )[0]


def lot(name="Will Barnet", *, source="Invaluable", identity="1"):
    return NormalizedLot(source, identity, name, name, "Print")


def stored(name="Will Barnet", *, source="Invaluable", count=1, upcoming=1, synced="2026-10-17T15:00:00Z"):
    return dict(name=name, normalized_name="barnet will", source=source,
                lot_count=count, upcoming_count=upcoming, last_synced_at=synced)


class ArtistInventoryTests(TestCase):
    def test_new_bookmark_uses_url_artist_and_has_action_before_any_lots(self):
        rows = artist_inventory_rows([entry()], [], [], [])
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.artist, "Will Barnet")
        self.assertEqual((row.local_count, row.calendar_count, row.upcoming_count), (0, 0, 0))
        self.assertEqual(row.status, "pending")
        self.assertTrue(row.syncable)
        self.assertIn("artistName=Will+Barnet", row.watch_urls[0])

    def test_unavailable_calendar_is_unknown_instead_of_claiming_zero(self):
        row = artist_inventory_rows([entry()], [], [])[0]
        self.assertIsNone(row.calendar_count)
        self.assertIsNone(row.upcoming_count)

    def test_local_lots_deduplicate_by_cache_key_and_calendar_counts_keep_scope(self):
        first = lot()
        rows = artist_inventory_rows([entry()], [first, replace(first, title="Updated"), lot(identity="2")], [],
                                     [stored(count=15, upcoming=7)])
        self.assertEqual((rows[0].local_count, rows[0].calendar_count, rows[0].upcoming_count), (2, 15, 7))
        self.assertEqual(rows[0].last_synced_at, "2026-10-17T15:00:00Z")

    def test_artist_aliases_match_but_nearby_names_and_sources_stay_separate(self):
        rows = artist_inventory_rows(
            [entry(), entry("Will Barnett"), entry(source="LiveAuctioneers")],
            [lot(), lot(source="LiveAuctioneers")], [],
            [stored("Barnet, Will", count=4), stored(source="LiveAuctioneers", count=9)],
        )
        by_key = {(row.artist, row.source): row for row in rows}
        self.assertEqual(len(by_key), 3)
        self.assertEqual(by_key[("Will Barnet", "Invaluable")].calendar_count, 4)
        self.assertEqual(by_key[("Will Barnett", "Invaluable")].calendar_count, 0)
        self.assertEqual(by_key[("Will Barnet", "LiveAuctioneers")].calendar_count, 9)
        self.assertEqual(by_key[("Will Barnet", "LiveAuctioneers")].local_count, 1)

    def test_calendar_only_artist_is_visible_without_a_sync_action(self):
        row = artist_inventory_rows([], [], [], [SimpleNamespace(**stored())])[0]
        self.assertEqual(row.artist, "Will Barnet")
        self.assertEqual(row.status, "calendar_only")
        self.assertFalse(row.syncable)
        self.assertEqual(row.watch_urls, ())

    def test_stored_artist_link_does_not_add_blank_source_duplicate(self):
        rows = artist_inventory_rows([entry()], [], [], [stored(source="", count=0, upcoming=0)])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].source, "Invaluable")
        self.assertEqual(rows[0].calendar_count, 0)
        self.assertTrue(rows[0].syncable)
        orphan = artist_inventory_rows([], [], [], [stored(source="", count=0, upcoming=0)])[0]
        self.assertFalse(orphan.syncable)

    def test_latest_check_wins_for_same_watch_without_conflating_blocked_and_empty(self):
        watch = entry()
        blocked = WatchCoverage(watch.artist, watch.source, watch.url, state="blocked", checked_at="2026-10-17T15:00:00Z")
        empty = replace(blocked, state="empty", checked_at="2026-10-17T14:00:00Z")
        row = artist_inventory_rows([watch], [], [blocked, empty], [])[0]
        self.assertEqual(row.status, "blocked")
        row = artist_inventory_rows([watch], [], [blocked, replace(empty, checked_at="2026-10-17T16:00:00Z")], [])[0]
        self.assertEqual(row.status, "empty")

    def test_successful_second_watch_does_not_hide_blocked_or_unchecked_watch(self):
        first, second = entry(), entry(extra="&Fine+Art=Prints")
        completed = WatchCoverage(second.artist, second.source, second.url, state="verified", checked_at="2026-10-17T16:00:00Z")
        blocked = WatchCoverage(first.artist, first.source, first.url, state="blocked", checked_at="2026-10-17T14:00:00Z")
        self.assertEqual(artist_inventory_rows([first, second], [], [completed, blocked], [])[0].status, "blocked")
        self.assertEqual(artist_inventory_rows([first, second], [], [completed], [])[0].status, "pending")

    def test_equivalent_bookmarks_and_repeated_inventory_rows_do_not_duplicate_counts(self):
        watch = entry()
        alias = replace(watch, url=watch.url + "&utm_source=duplicate")
        record = stored(count=3)
        row = artist_inventory_rows([watch, alias], [], [], [record, record])[0]
        self.assertEqual(len(row.watch_urls), 1)
        self.assertEqual(row.calendar_count, 3)

    def test_new_zero_lot_artists_sort_before_existing_artists(self):
        watches = [entry("Banksy"), entry("Zuniga"), entry("Albers"), entry("Calder")]
        known_empty = WatchCoverage("Albers", "Invaluable", watches[2].url, state="empty")
        rows = artist_inventory_rows(watches, [lot("Banksy")], [known_empty], [stored("Calder")])
        self.assertEqual([row.artist for row in rows], ["Zuniga", "Albers", "Banksy", "Calder"])

