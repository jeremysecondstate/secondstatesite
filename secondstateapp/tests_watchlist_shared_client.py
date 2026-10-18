"""A new PC can restore shared state without pretending it checked auction sites."""

from dataclasses import asdict, replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock
from unittest.mock import patch
from urllib.parse import urlsplit

import requests

from django.test import TestCase as DjangoTestCase

from catalogapp.bookmark_watchlist import BookmarkEntry
from catalogapp.watchlist_cache import WatchlistCache
from catalogapp.watchlist_coverage import WatchCoverage
from catalogapp.watchlist_models import NormalizedLot
from catalogapp.watchlist_registry import load_watchlist
from catalogapp.watchlist_shared import (
    SharedWatchlistSnapshot, fetch_shared_watchlist, merge_shared_watchlist, publish_shared_watchlist,
)
from catalogapp.watchlist_sync import CalendarSyncError


FIRST = "2026-10-10T12:00:00+00:00"
OLD = "2026-10-16T12:00:00+00:00"
NOW = datetime(2026, 10, 17, 18, tzinfo=timezone.utc)
WATCH = BookmarkEntry(("Artists",), "Will Barnet",
                      "https://www.invaluable.com/search?artistName=Will+Barnet",
                      artist="Will Barnet", source="Invaluable")


def lot(**overrides):
    values = dict(source="Invaluable", source_lot_id="123", artist="Will Barnet",
                  artist_watchlist_name="Will Barnet", title="A print", end_at="2026-10-20",
                  lot_url="https://www.invaluable.com/auction-lot/print-123",
                  first_seen_at=FIRST, last_seen_at=OLD)
    values.update(overrides)
    return NormalizedLot(**values)


def payload(**overrides):
    values = dict(ok=True, version=1, entries=[{**asdict(WATCH), "enabled": True}],
                  artist_artprice_links={}, coverage=[], lots=[lot().to_dict()],
                  calendar_lot_keys=["invaluable:123", "invaluable:historical"], next_cursor=None)
    values.update(overrides)
    return values


def session(*pages, status=200):
    transport = Mock()
    transport.get.side_effect = [Mock(status_code=status, json=Mock(return_value=page)) for page in pages]
    return transport


class SharedWatchlistTransportTests(TestCase):
    def test_reads_all_pages_with_auth_no_redirects_or_source_requests(self):
        transport = session(payload(next_cursor="7"), payload(lots=[lot(source_lot_id="456").to_dict()],
                            calendar_lot_keys=["invaluable:123", "invaluable:456", "invaluable:historical"]))
        result = fetch_shared_watchlist(base_url="https://secondstate.art/", api_key="key",
                                        horizon_days=3, session=transport)
        self.assertEqual([item.source_lot_id for item in result.lots], ["123", "456"])
        self.assertEqual(result.entries, [WATCH])
        self.assertEqual(result.calendar_lot_keys, {"invaluable:123", "invaluable:456", "invaluable:historical"})
        self.assertEqual(result.enabled_watch_urls, {WATCH.url})
        self.assertEqual(transport.get.call_count, 2)
        for call in transport.get.call_args_list:
            self.assertEqual(call.args, ("https://secondstate.art/calendar/watchlist/",))
            self.assertEqual(call.kwargs["headers"]["X-API-KEY"], "key")
            self.assertFalse(call.kwargs["allow_redirects"])
            self.assertEqual(call.kwargs["params"]["horizon_days"], 3)
        self.assertEqual(transport.get.call_args_list[0].kwargs["params"]["cursor"], "0")
        self.assertEqual(transport.get.call_args_list[1].kwargs["params"]["cursor"], "7")
        transport.post.assert_not_called()

    def test_network_auth_redirect_and_missing_deployment_have_clear_errors(self):
        transport = Mock()
        transport.get.side_effect = requests.ConnectionError("unavailable")
        with self.assertRaisesRegex(CalendarSyncError, "local data"):
            fetch_shared_watchlist(base_url="https://secondstate.art", api_key="key", session=transport)
        for status in (302, 401, 403, 500):
            with self.subTest(status=status), self.assertRaisesRegex(CalendarSyncError, str(status)):
                fetch_shared_watchlist(base_url="https://secondstate.art", api_key="key",
                                       session=session({}, status=status))
        with self.assertRaisesRegex(CalendarSyncError, "Deploy"):
            fetch_shared_watchlist(base_url="https://secondstate.art", api_key="key",
                                   session=session({}, status=404))

    def test_missing_or_invalid_identity_inventory_fails_closed(self):
        missing = payload()
        del missing["calendar_lot_keys"]
        for page in (missing, payload(calendar_lot_keys="invaluable:123"),
                     payload(calendar_lot_keys=["invaluable:"]), payload(calendar_lot_keys=["invaluable:123"] * 2)):
            with self.subTest(page=page), self.assertRaises(CalendarSyncError):
                fetch_shared_watchlist(base_url="https://secondstate.art", api_key="key", session=session(page))

    def test_invalid_lot_or_metadata_rejects_entire_snapshot(self):
        cases = [payload(entries=[{**asdict(WATCH), "url": "file:///private"}]),
                 payload(entries=[{**asdict(WATCH), "enabled": "yes"}]),
                 payload(lots=[lot().to_dict(), lot().to_dict()]),
                 payload(lots=[lot(last_seen_at="2026-02-31").to_dict()]),
                 payload(lots=[{**lot().to_dict(), "lot_url": "https://user:password@invaluable.com/private"}]),
                 payload(lots=[lot(current_bid=float("nan")).to_dict()]),
                 payload(coverage=[{"watch_url": WATCH.url, "state": "verified", "checked_at": ""}]),
                 payload(artist_artprice_links={"Will Barnet": "https://private.example/link"})]
        for page in cases:
            with self.subTest(page=page), self.assertRaises(CalendarSyncError):
                fetch_shared_watchlist(base_url="https://secondstate.art", api_key="key", session=session(page))

    def test_cyclic_cursor_and_page_failure_never_return_partial_data(self):
        for transport in (session(payload(next_cursor="7"), payload(lots=[lot(source_lot_id="456").to_dict()], next_cursor="7")),
                          session(payload(next_cursor="https://evil.example")),
                          session(payload(next_cursor="7"), {})):
            with self.assertRaises(CalendarSyncError):
                fetch_shared_watchlist(base_url="https://secondstate.art", api_key="key", session=transport)

    def test_unknown_local_fields_are_excluded_from_downloaded_records(self):
        record = lot().to_dict()
        record.update(local_path="C:/Users/private", cookie="secret", saved_image_base64="private-data")
        result = fetch_shared_watchlist(base_url="https://secondstate.art", api_key="key",
                                        session=session(payload(lots=[record])))
        self.assertEqual(result.lots[0].saved_image_base64, "")
        self.assertNotIn("local_path", result.lots[0].to_dict())

    def test_publish_shares_only_curated_entries_and_original_source_checks(self):
        check = WatchCoverage("Will Barnet", "Invaluable", WATCH.url, "verified", checked_at=OLD,
                              detail="C:/local/errors.log", covered_until="2026-10-24T12:00:00+00:00")
        transport = Mock()
        transport.post.return_value = Mock(status_code=200, json=Mock(return_value={"ok": True, "entries_received": 1}))
        result = publish_shared_watchlist([WATCH], base_url="https://secondstate.art", api_key="key",
                                           coverage=[check, replace(check, checked_at="")],
                                           enabled_watch_urls=[], session=transport)
        self.assertEqual(result, 1)
        request = transport.post.call_args.kwargs
        self.assertFalse(request["allow_redirects"])
        self.assertEqual(set(request["json"]), {"entries", "artist_artprice_links", "coverage"})
        self.assertFalse(request["json"]["entries"][0]["enabled"])
        self.assertEqual(len(request["json"]["coverage"]), 1)
        self.assertEqual(request["json"]["coverage"][0]["checked_at"], OLD)
        self.assertNotIn("detail", request["json"]["coverage"][0])
        transport.get.assert_not_called()

    def test_publish_requires_confirmation_and_does_not_follow_redirects(self):
        transport = Mock()
        for status, body in ((302, {}), (401, {}), (200, {}), (200, {"ok": True, "entries_received": 0})):
            transport.post.return_value = Mock(status_code=status, json=Mock(return_value=body))
            with self.subTest(status=status, body=body), self.assertRaises(CalendarSyncError):
                publish_shared_watchlist([WATCH], base_url="https://secondstate.art", api_key="key", session=transport)

    def test_private_url_parameters_never_leave_this_pc(self):
        transport = Mock()
        private = replace(WATCH, url=WATCH.url + "&access_token=secret")
        with self.assertRaisesRegex(CalendarSyncError, "public artist"):
            publish_shared_watchlist([private], base_url="https://secondstate.art", api_key="key", session=transport)
        transport.post.assert_not_called()
        with self.assertRaisesRegex(CalendarSyncError, "public artist"):
            publish_shared_watchlist([WATCH], base_url="https://secondstate.art", api_key="key", session=transport,
                artist_artprice_links={"Will Barnet": "https://www.artprice.com/artist/1474/will-r-barnet?access_token=secret"})
        transport.post.assert_not_called()

    def test_incomplete_identity_inventory_cannot_hide_existing_calendar_lot(self):
        with self.assertRaisesRegex(CalendarSyncError, "incomplete Calendar lot inventory"):
            fetch_shared_watchlist(base_url="https://secondstate.art", api_key="key",
                                   session=session(payload(calendar_lot_keys=[])))

    def test_https_and_credentials_are_required_before_requests(self):
        transport = Mock()
        for url, key in (("http://secondstate.art", "key"), ("https://secondstate.art", ""),
                         ("https://user:pass@secondstate.art", "key")):
            for method, args in ((fetch_shared_watchlist, ()), (publish_shared_watchlist, ([WATCH],))):
                with self.assertRaises(CalendarSyncError):
                    method(*args, base_url=url, api_key=key, session=transport)
        transport.get.assert_not_called()
        transport.post.assert_not_called()


class SharedWatchlistRestoreTests(TestCase):
    def setUp(self):
        self.cache = WatchlistCache(":memory:")
        self.addCleanup(self.cache.close)

    def snapshot(self, **overrides):
        values = dict(entries=[WATCH], lots=[lot()], enabled_watch_urls=frozenset({WATCH.url}),
                      calendar_lot_keys=frozenset({"invaluable:123", "invaluable:historical"}))
        values.update(overrides)
        return SharedWatchlistSnapshot(**values)

    def test_new_pc_restores_all_memberships_and_registry_without_freshness_claim(self):
        added = replace(WATCH, artist="Käthe Kollwitz", title="Käthe Kollwitz", url="https://www.invaluable.com/search?artistName=Kathe+Kollwitz")
        second_lot = lot(source_lot_id="456", artist="Käthe Kollwitz", artist_watchlist_name="Käthe Kollwitz")
        remote = self.snapshot(entries=[WATCH, added], lots=[lot(), second_lot])
        with TemporaryDirectory() as directory:
            registry = Path(directory) / "watchlist.json"
            merged = merge_shared_watchlist(remote, cache=self.cache, registry_path=registry)
            self.assertEqual(load_watchlist(registry)[0], [WATCH, added])
        self.assertEqual(len(merged.lots), 2)
        self.assertEqual(merged.calendar_lot_keys, remote.calendar_lot_keys)
        for watch in (WATCH, added):
            restored = self.cache.active_lots_for_watch_url(watch.url)
            self.assertEqual(len(restored), 1)
            self.assertEqual(restored[0].first_seen_at, FIRST)
            self.assertEqual(restored[0].last_seen_at, OLD)
        checks = self.cache.coverage_for_entries([WATCH, added], observed_at=NOW, horizon_days=7)
        self.assertEqual([check.state for check in checks], ["pending", "pending"])
        self.assertEqual(self.cache.connection.execute("SELECT count(*) FROM source_runs").fetchone()[0], 0)

    def test_existing_local_watches_and_newer_lot_observations_win(self):
        local = lot(title="Newer local title", current_bid=100)
        self.cache.upsert(local, watch_url=WATCH.url, search_hash="fresh-card", observed_at=NOW)
        other = replace(WATCH, artist="Other Artist", title="Other Artist", url="https://www.invaluable.com/search?artistName=Other+Artist")
        merged = merge_shared_watchlist(self.snapshot(), cache=self.cache, entries=[WATCH, other])
        restored = self.cache.get(local.cache_key)
        self.assertEqual(restored.title, "Newer local title")
        self.assertEqual(restored.last_seen_at, NOW.isoformat())
        self.assertEqual(restored.first_seen_at, FIRST)
        self.assertEqual(self.cache.lookup(local).search_hash, "fresh-card")
        self.assertEqual(merged.entries, [WATCH, other])

    def test_remote_lots_only_match_exact_artist_identity_and_source(self):
        wrong_artist = lot(artist="Will Barnett", artist_watchlist_name="Will Barnett")
        wrong_source = lot(source="LiveAuctioneers", source_lot_id="456")
        merged = merge_shared_watchlist(self.snapshot(lots=[wrong_artist, wrong_source]), cache=self.cache)
        self.assertEqual(merged.lots, [])
        self.assertEqual(self.cache.lots_for_watch_url(WATCH.url), [])

    def test_whole_sale_restore_matches_doyle_id_and_phillips_code_across_url_forms(self):
        doyle = BookmarkEntry(("Doyle",), "DOYLE-1020",
            "https://doyle.com/auction/search?au=9224&mc=219&pn=1", source="Doyle")
        phillips = BookmarkEntry(("Phillips",), "PHILLIPS-1022",
            "https://www.phillips.com/auction/NY030726/browse", source="Phillips")
        records = [
            lot(source="Doyle", source_lot_id="9224-1", artist="Unbookmarked Artist",
                artist_watchlist_name="Unbookmarked Artist",
                lot_url="https://doyle.com/auction/lot/lot-1-example/?lot=100001&au=9224",
                sale_url="https://www.doyle.com/auction/26pm03-prints--multiples?au=9224"),
            lot(source="Phillips", source_lot_id="NY030726-236058", artist="Another Artist",
                artist_watchlist_name="Another Artist",
                lot_url="https://www.phillips.com/detail/example/236058",
                sale_url="https://phillips.com/auction/NY030726/"),
        ]
        restored = merge_shared_watchlist(self.snapshot(entries=[doyle, phillips], lots=records), cache=self.cache)
        self.assertEqual({item.cache_key for item in restored.lots}, {item.cache_key for item in records})
        for watch, original in zip((doyle, phillips), records):
            saved = self.cache.active_lots_for_watch_url(watch.url)
            self.assertEqual([item.cache_key for item in saved], [original.cache_key])
            self.assertEqual(saved[0].last_seen_at, OLD)

    def test_whole_sale_restore_rejects_different_ids_domains_and_ambiguous_urls(self):
        cases = [
            ("Doyle", "https://doyle.com/auction/search?au=9224", [
                "https://doyle.com/auction/26pm03-prints--multiples?au=9999",
                "https://doyle.com/auction/26pm03-prints--multiples",
                "https://doyle.com/auction/26pm03-prints--multiples?au=9224&au=9999",
                "https://doyle.com/auction/26pm03-prints--multiples?au=9224&au=",
                "https://example.com/auction/26pm03-prints--multiples?au=9224",
                "https://doyle.com.evil.example/auction/search?au=9224",
                "https://doyle.com/unrelated?au=9224",
            ]),
            ("Phillips", "https://www.phillips.com/auction/NY030726/browse", [
                "https://www.phillips.com/auction/NY999926",
                "https://www.phillips.com/auction/NY030726/unrelated",
                "https://example.com/auction/NY030726",
                "https://phillips.com.evil.example/auction/NY030726",
                "https://user:password@www.phillips.com/auction/NY030726",
            ]),
        ]
        for source, watch_url, sale_urls in cases:
            watch = BookmarkEntry((source,), "A sale", watch_url, source=source)
            for sale_url in sale_urls:
                with self.subTest(source=source, sale_url=sale_url):
                    record = lot(source=source, source_lot_id="outside-sale", sale_url=sale_url)
                    # Exercise the merge boundary too; normal transport rejects
                    # credentials before NormalizedLot canonicalizes its URLs.
                    record.sale_url = sale_url
                    merged = merge_shared_watchlist(self.snapshot(entries=[watch], lots=[record]), cache=self.cache)
                    self.assertEqual(merged.lots, [])
                    self.assertEqual(self.cache.lots_for_watch_url(watch.url), [])

    def test_whole_sale_restore_retains_heritage_exact_url_behavior(self):
        watch = BookmarkEntry(("Heritage",), "A sale",
            "https://fineart.ha.com/c/search/results.zx?auction_name=8280", source="Heritage")
        mismatch = lot(source="Heritage", source_lot_id="8280-65001",
            sale_url="https://fineart.ha.com/c/search.zx?saleNo=8280")
        merged = merge_shared_watchlist(self.snapshot(entries=[watch], lots=[mismatch]), cache=self.cache)
        self.assertEqual(merged.lots, [])
        exact = replace(mismatch, sale_url=watch.url)
        merged = merge_shared_watchlist(self.snapshot(entries=[watch], lots=[exact]), cache=self.cache)
        self.assertEqual([item.cache_key for item in merged.lots], [exact.cache_key])

    def test_source_check_coverage_restores_timestamp_without_becoming_new(self):
        check = WatchCoverage(WATCH.artist, WATCH.source, WATCH.url, "verified", checked_at=OLD,
                              covered_until="2026-10-24T12:00:00+00:00")
        merge_shared_watchlist(self.snapshot(coverage=[check]), cache=self.cache)
        raw = self.cache.coverage_for_entries([WATCH])[0]
        self.assertEqual((raw.state, raw.checked_at), ("verified", OLD))
        today = self.cache.coverage_for_entries([WATCH], observed_at=NOW, horizon_days=7)[0]
        self.assertEqual(today.state, "pending")
        self.assertEqual(today.checked_at, OLD)

    def test_stale_remote_coverage_does_not_replace_newer_local_failure(self):
        self.cache.record_watch_coverage(WATCH.url, "blocked", observed_at=NOW, detail="Local source block")
        check = WatchCoverage(WATCH.artist, WATCH.source, WATCH.url, "verified", checked_at=OLD)
        merge_shared_watchlist(self.snapshot(coverage=[check]), cache=self.cache)
        restored = self.cache.coverage_for_entries([WATCH])[0]
        self.assertEqual((restored.state, restored.checked_at, restored.detail),
                         ("blocked", NOW.isoformat(), "Local source block"))

    def test_equal_timestamps_preserve_local_edits_and_missing_remote_lots_remain(self):
        local = lot(title="Local title")
        self.cache.upsert(local, watch_url=WATCH.url, search_hash="card", observed_at=datetime.fromisoformat(OLD))
        absent = lot(source_lot_id="456")
        self.cache.upsert(absent, watch_url=WATCH.url, search_hash="second", observed_at=NOW)
        merge_shared_watchlist(self.snapshot(), cache=self.cache)
        self.assertEqual(self.cache.get(local.cache_key).title, "Local title")
        self.assertEqual(len(self.cache.active_lots_for_watch_url(WATCH.url)), 2)

    def test_older_remote_lot_cannot_revive_newer_local_ended_record(self):
        self.cache.upsert(lot(), watch_url=WATCH.url, search_hash="ended", observed_at=NOW, active=False)
        merge_shared_watchlist(self.snapshot(), cache=self.cache)
        self.assertEqual(self.cache.active_lots_for_watch_url(WATCH.url), [])
        self.assertEqual(self.cache.get("invaluable:123").status, "ended")

    def test_newer_remote_observation_preserves_known_sold_price_and_saved_image(self):
        local = lot(sold_price=400, sold_currency="USD", saved_image_base64="saved-artwork")
        self.cache.upsert(local, watch_url=WATCH.url, search_hash="card", observed_at=datetime.fromisoformat(OLD))
        remote = lot(last_seen_at=NOW.isoformat(), title="Corrected title")
        merge_shared_watchlist(self.snapshot(lots=[remote]), cache=self.cache)
        restored = self.cache.get(local.cache_key)
        self.assertEqual((restored.title, restored.sold_price, restored.saved_image_base64),
                         ("Corrected title", 400, "saved-artwork"))
        self.assertEqual(restored.last_seen_at, NOW.isoformat())
        self.assertEqual(self.cache.active_lots_for_watch_url(WATCH.url), [])

    def test_remote_without_original_timestamps_does_not_invent_todays_check(self):
        merge_shared_watchlist(self.snapshot(lots=[lot(first_seen_at="", last_seen_at="")]), cache=self.cache)
        restored = self.cache.get("invaluable:123")
        self.assertEqual((restored.first_seen_at, restored.last_seen_at), ("", ""))
        with self.assertRaises(ValueError):
            self.cache.import_shared_coverage(WatchCoverage(WATCH.artist, WATCH.source, WATCH.url, "verified"))

    def test_repeated_load_is_idempotent_and_does_not_enable_disabled_shared_artist(self):
        snapshot = self.snapshot(enabled_watch_urls=frozenset())
        for _ in range(2):
            merged = merge_shared_watchlist(snapshot, cache=self.cache, entries=[WATCH])
        self.assertEqual(merged.enabled_watch_urls, frozenset())
        self.assertEqual(len(self.cache.active_lots_for_watch_url(WATCH.url)), 1)

    def test_current_website_link_wins_over_stale_pc_link_and_retains_local_only_artists(self):
        other = replace(WATCH, artist="Käthe Kollwitz", title="Käthe Kollwitz", url="https://www.invaluable.com/search?artistName=Kathe+Kollwitz")
        correct = "https://www.artprice.com/artist/1474/will-r-barnet"
        local_only = "https://www.artprice.com/artist/15398/kathe-kollwitz"
        merged = merge_shared_watchlist(self.snapshot(artist_artprice_links={"Will Barnet": correct}),
            cache=self.cache, entries=[WATCH, other], artist_artprice_links={
                "Will Barnet": "https://www.artprice.com/artist/1/stale-link", "Käthe Kollwitz": local_only,
            })
        self.assertEqual(merged.artist_artprice_links, {"Will Barnet": correct, "Käthe Kollwitz": local_only})


class SharedWatchlistRoundTripTests(DjangoTestCase):
    def test_real_endpoint_restores_another_pc_with_original_provenance(self):
        from secondstateapp.models import AuctionWatchLot

        client = self.client

        class Transport:
            def get(self, url, **kwargs):
                return client.get(urlsplit(url).path, kwargs["params"],
                                  HTTP_X_API_KEY=kwargs["headers"]["X-API-KEY"])

            def post(self, url, **kwargs):
                return client.post(urlsplit(url).path, json.dumps(kwargs["json"]),
                                   content_type="application/json", HTTP_X_API_KEY=kwargs["headers"]["X-API-KEY"])

        kwargs = {"base_url": "https://secondstate.art", "api_key": "test-key", "session": Transport()}
        check = WatchCoverage(WATCH.artist, WATCH.source, WATCH.url, "verified", checked_at=OLD,
                              covered_until="2026-10-24T12:00:00+00:00")
        AuctionWatchLot.objects.create(source="Invaluable", source_lot_id="123", artist="Will Barnet",
            artist_watchlist_name="Will Barnet", title="A print", event_at=NOW,
            lot_url=lot().lot_url, source_first_seen_at=datetime.fromisoformat(FIRST),
            source_last_seen_at=datetime.fromisoformat(OLD))
        AuctionWatchLot.objects.create(source="Invaluable", source_lot_id="historical", artist="Will Barnet",
            artist_watchlist_name="Will Barnet", title="An old sale", event_at=datetime(2000, 1, 1, tzinfo=timezone.utc))
        with patch.dict(os.environ, {"CATALOG_API_KEY": "test-key"}), \
                patch("secondstateapp.watchlist_shared_views.timezone.now", return_value=NOW):
            self.assertEqual(publish_shared_watchlist([WATCH], coverage=[check], **kwargs), 1)
            shared = fetch_shared_watchlist(**kwargs)
            self.assertEqual(shared.entries, [WATCH])
            self.assertEqual(shared.calendar_lot_keys, {"invaluable:123", "invaluable:historical", "invaluable:" + lot().lot_url})
            self.assertEqual(len(shared.lots), 1)
            with WatchlistCache(":memory:") as second_pc:
                merged = merge_shared_watchlist(shared, cache=second_pc)
                self.assertEqual(merged.lots[0].last_seen_at, OLD)
                self.assertEqual(second_pc.coverage_for_entries([WATCH])[0].checked_at, OLD)
                self.assertEqual(second_pc.coverage_for_entries([WATCH], observed_at=NOW)[0].state, "pending")
