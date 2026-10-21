"""Browser capture bundles stay scoped, bounded and safe to preview/import."""

from copy import deepcopy
from contextlib import ExitStack
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from catalogapp.bookmark_watchlist import BookmarkEntry
from catalogapp.watchlist_adapters import InvaluableAdapter
from catalogapp.watchlist_bookmark_source import load_bookmark_source
from catalogapp.watchlist_cache import WatchlistCache
from catalogapp.watchlist_invaluable_pages import (
    CAPTURE_BUNDLE_FORMAT, _capture_window, import_saved_invaluable_pages,
)
from catalogapp.watchlist_models import NormalizedLot
from scripts import import_invaluable_capture as cli


NOW = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
OLD = NOW - timedelta(days=1)
CALDER = BookmarkEntry(folder_path=("ARTISTS INVALUABLE",), title="Calder", artist="Alexander Calder",
                      source="Invaluable", url="https://www.invaluable.com/search?artistName=Alexander+Calder&Fine+Art=Prints&query=fine+art")
WARHOL = replace(CALDER, title="Warhol", artist="Andy Warhol", url=CALDER.url.replace("Alexander+Calder", "Andy+Warhol"))
WINDOW = {"start_date": "2026-10-21", "end_date": "2026-11-01", "time_zone": "America/New_York"}


def hit(identity="1", *, artist=CALDER.artist, when="2026-10-31T15:00:00Z", **overrides):
    payload = {
        "objectID": identity, "lotRef": f"ref{identity}", "lotNumber": identity, "lotTitle": f"Artwork {identity}",
        "artistName": artist, "supercategoryName": "Fine Art", "categoryName": "Prints",
        "houseName": "Example Auction House", "currencyCode": "USD", "currentBid": 150,
        "dateTimeUTCUnix": datetime.fromisoformat(when.replace("Z", "+00:00")).timestamp(),
    }
    payload.update(overrides)
    return payload


def snapshot(hits=None, *, entry=CALDER, page=0, total=None, size=None, captured=OLD):
    hits = [hit(artist=entry.artist)] if hits is None else hits
    total = len(hits) if total is None else total
    size = max(1, len(hits)) if size is None else size
    return {
        "source_url": entry.url + (f"&page={page + 1}" if page else ""),
        "captured_at": captured.isoformat(),
        "results": [{"page": page, "nbPages": (total + size - 1) // size,
                     "nbHits": total, "hitsPerPage": size, "hits": hits}],
    }


def bundle(snapshots=None, *, window=None, **overrides):
    payload = {"format": CAPTURE_BUNDLE_FORMAT, "version": 1, "exported_at": NOW.isoformat(),
               "window": deepcopy(WINDOW if window is None else window),
               "snapshots": [snapshot()] if snapshots is None else snapshots,
               "progress": [{"complete": True, "private": "IGNORE THIS UNTRUSTED PROGRESS"}]}
    payload.update(overrides)
    return payload


class CaptureBundleTests(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.cache = WatchlistCache(":memory:")
        self.addCleanup(self.cache.close)

    def write(self, payload, name="capture.json"):
        path = Path(self.directory.name) / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def run_import(self, payload, *, entries=(CALDER, WARHOL), horizon=3):
        return import_saved_invaluable_pages([self.write(payload)], entries, self.cache, now=NOW, horizon_days=horizon)

    def seed(self, item=None, *, entry=CALDER, seen=OLD - timedelta(days=1), sold=None):
        item = hit() if item is None else item
        lot = InvaluableAdapter().parse_search_page(json.dumps({"results": [{"hits": [item]}]}), entry.url, entry.artist)[0]
        lot.sold_price = sold
        lot.content_hash = lot.calculate_content_hash()
        self.cache.upsert(lot, watch_url=entry.url, search_hash=lot.content_hash, observed_at=seen, active=sold is None)
        return lot

    def test_multiartist_bundle_preserves_capture_times_and_exceeds_studio_horizon(self):
        payload = bundle([snapshot(), snapshot([hit("2", artist=WARHOL.artist)], entry=WARHOL)])
        with patch("requests.sessions.Session.request", side_effect=AssertionError("Offline import")):
            result = self.run_import(payload)
        self.assertEqual(result.errors, [])
        self.assertEqual({lot.artist for lot in result.lots}, {CALDER.artist, WARHOL.artist})
        self.assertEqual({lot.last_seen_at for lot in result.lots}, {OLD.isoformat()})
        self.assertEqual(result.metrics.new_lots, 2)
        self.assertEqual(result.metrics.pages_fetched, 0)
        self.assertTrue(all(item.state == "partial" for item in result.coverage))
        self.assertNotIn("IGNORE THIS", str(result))

    def test_exact_local_window_includes_boundaries_and_dst_excludes_outside_lots(self):
        # New York's Nov 1 DST transition means the end uses UTC-5, while
        # October 21 starts at UTC-4. A fixed UTC offset gets this wrong.
        times = ("2026-10-21T03:59:59Z", "2026-10-21T04:00:00Z",
                 "2026-11-02T04:59:59Z", "2026-11-02T05:00:00Z")
        result = self.run_import(bundle([snapshot([hit(str(index), when=when) for index, when in enumerate(times)])]))
        self.assertEqual({lot.source_lot_id for lot in result.lots}, {"1", "2"})
        self.assertEqual(result.metrics.new_lots, 2)
        self.assertIsNone(self.cache.get("invaluable:0"))
        self.assertIsNone(self.cache.get("invaluable:3"))
        self.assertIn("2 captured lots fell outside", " ".join(result.notices))

    def test_date_only_window_does_not_shift_the_date_to_previous_day(self):
        window = _capture_window(WINDOW)
        lot = NormalizedLot(source="Invaluable", source_lot_id="1", artist="Calder",
                            artist_watchlist_name="Calder", title="Print", end_at="2026-10-21")
        self.assertTrue(window.contains(lot))
        lot.end_at = "2026-11-01"
        self.assertTrue(window.contains(lot))
        lot.end_at = "2026-11-02"
        self.assertFalse(window.contains(lot))

    def test_cached_fallbacks_do_not_escape_normal_horizon_and_missing_pages_end_nothing(self):
        soon = self.seed(hit("soon", when="2026-10-22T12:00:00Z"))
        later = self.seed(hit("later"))
        self.cache.record_source_error(CALDER.url, "HTTP 202 blocked", OLD)
        with patch.object(self.cache, "mark_missing_ended", side_effect=AssertionError("Never complete")):
            result = self.run_import(bundle([snapshot(total=2, size=1)]))
        self.assertEqual({lot.source_lot_id for lot in result.lots}, {"1", "soon"})
        self.assertEqual(result.fallback_lot_keys, {soon.cache_key})
        self.assertEqual(self.cache.get(later.cache_key).last_seen_at, (OLD - timedelta(days=1)).isoformat())
        self.assertEqual(len(self.cache.active_lots_for_watch_url(CALDER.url)), 3)
        self.assertEqual(result.metrics.ended_lots, 0)
        self.assertEqual(result.coverage[0].state, "partial")
        self.assertIn("HTTP 202", self.cache.connection.execute(
            "SELECT last_error FROM source_runs WHERE watch_url = ?", (CALDER.url,),
        ).fetchone()[0])

    def test_zero_capture_preserves_existing_lots_even_when_progress_claims_complete(self):
        old = self.seed(hit(when="2026-10-22T12:00:00Z"))
        before = self.cache.get(old.cache_key).to_dict()
        result = self.run_import(bundle([snapshot([])]))
        self.assertEqual(result.metrics.new_lots, 0)
        self.assertEqual(self.cache.get(old.cache_key).to_dict(), before)
        self.assertEqual(result.fallback_lot_keys, {old.cache_key})
        self.assertIn("reported zero", " ".join(result.notices))

    def test_repeated_page_uses_latest_capture_and_is_idempotent(self):
        older = snapshot([hit(currentBid=100)], captured=OLD - timedelta(hours=1))
        newer = snapshot([hit(currentBid=200)], captured=OLD)
        first = self.run_import(bundle([newer, older, newer]))
        second = self.run_import(bundle([older, newer]))
        self.assertEqual(first.errors, [])
        self.assertEqual(first.metrics.new_lots, 1)
        self.assertEqual(first.lots[0].current_bid, 200)
        self.assertEqual(second.metrics.unchanged_lots, 1)
        self.assertEqual(self.cache.connection.execute("SELECT COUNT(*) FROM lots").fetchone()[0], 1)
        self.assertEqual(second.lots[0].last_seen_at, OLD.isoformat())

    def test_same_timestamp_page_conflict_rejects_page_but_imports_independent_artist(self):
        old = self.seed()
        before = self.cache.get(old.cache_key).to_dict()
        result = self.run_import(bundle([snapshot(), snapshot([hit(currentBid=900)]),
                                        snapshot([hit("2", artist=WARHOL.artist)], entry=WARHOL)]))
        self.assertEqual({lot.source_lot_id for lot in result.lots}, {"2"})
        self.assertEqual(self.cache.get(old.cache_key).to_dict(), before)
        self.assertIn("same timestamp", " ".join(result.errors))

    def test_differing_cross_page_observations_preserve_cached_lot(self):
        old = self.seed()
        before = self.cache.get(old.cache_key).to_dict()
        result = self.run_import(bundle([snapshot([hit(currentBid=200)], total=2, size=1),
                                        snapshot([hit(currentBid=300)], page=1, total=2, size=1,
                                                 captured=OLD + timedelta(minutes=1))]))
        self.assertEqual(result.lots, [])
        self.assertEqual(self.cache.get(old.cache_key).to_dict(), before)
        self.assertIn("conflicting snapshots", " ".join(result.errors))

    def test_newer_and_sold_cache_observations_survive_bundle_import(self):
        newer = self.seed(hit("1", currentBid=700), seen=NOW)
        sold = self.seed(hit("2"), sold=1000)
        before = {lot.cache_key: self.cache.get(lot.cache_key).to_dict() for lot in (newer, sold)}
        result = self.run_import(bundle([snapshot([hit("1"), hit("2")])]))
        self.assertEqual(result.lots, [])
        self.assertEqual({key: self.cache.get(key).to_dict() for key in before}, before)
        self.assertIn("older snapshot", " ".join(result.notices))
        self.assertIn("sold lot", " ".join(result.notices))

    def test_scope_mismatch_and_contradictory_artist_or_category_never_import(self):
        wrong_scope = snapshot(entry=replace(CALDER, url=CALDER.url.replace("Prints", "Sculpture")))
        wrong_query = snapshot(entry=replace(CALDER, url=CALDER.url.replace("fine+art", "other")))
        wrong_artist = snapshot([hit(artist=WARHOL.artist)])
        wrong_category = snapshot([hit(categoryName="Sculpture")])
        for page in (wrong_scope, wrong_query, wrong_artist, wrong_category):
            with self.subTest(page=page):
                result = self.run_import(bundle([page]))
                self.assertEqual(result.lots, [])
                self.assertEqual(result.metrics.new_lots, 0)
        self.assertEqual(self.cache.connection.execute("SELECT COUNT(*) FROM lots").fetchone()[0], 0)

    def test_bundle_window_replaces_only_the_real_jim_dine_bookmarks_date_controls(self):
        original_url = (
            "https://www.invaluable.com/search?artistName=Jim%2520Dine&Fine%20Art=Prints"
            "&dateTimeUTCUnix%5Bmax%5D=1792565999&dateType=Custom&sort=endDateAsc"
            "&query=fine%2520art&keyword=fine%2520art"
        )
        path = Path(self.directory.name) / "artists.html"
        path.write_text(f'<DL><DT><H3>ARTISTS INVALUABLE</H3><DL><DT><A HREF="{original_url}">'
                        'Dine, Jim: Invaluable — Prints</A></DL></DL>', encoding="utf-8")
        entries, _ = load_bookmark_source(path)
        jim = next(entry for entry in entries if entry.source == "Invaluable")
        normalized = replace(jim, url="https://www.invaluable.com/search?artistName=Jim+Dine&Fine+Art=Prints"
                                     "&query=fine+art&sort=enddateasc")
        page = snapshot([hit(artist="Jim Dine")], entry=normalized)
        result = self.run_import(bundle([page]), entries=(jim,))
        self.assertEqual(result.errors, [])
        self.assertEqual(result.metrics.new_lots, 1)
        self.assertEqual(result.lots[0].artist, "Jim Dine")
        # Recognized source-side date controls are also superseded by the
        # bundle's window; other narrowing controls remain significant.
        dated = deepcopy(page)
        dated["source_url"] += "&dateTimeUTCUnix%5Bmin%5D=1&dateTimeUTCUnix%5Bmax%5D=2&dateType=Custom"
        repeated = self.run_import(bundle([dated]), entries=(jim,))
        self.assertEqual(repeated.errors, [])
        self.assertEqual(repeated.metrics.unchanged_lots, 1)
        for bad_url in (normalized.url.replace("Prints", "Sculpture"),
                        normalized.url.replace("fine+art", "other"), normalized.url + "&auctionType=timed"):
            with self.subTest(source_url=bad_url):
                invalid = {**page, "source_url": bad_url}
                rejected = self.run_import(bundle([invalid]), entries=(jim,))
                self.assertEqual(rejected.metrics.new_lots + rejected.metrics.changed_lots, 0)
                self.assertIn("filters do not match", " ".join(rejected.errors))
        legacy = self.run_import(page, entries=(jim,))
        self.assertIn("filters do not match", " ".join(legacy.errors))

    def test_invalid_envelopes_and_windows_are_rejected_before_cache_writes(self):
        invalid = [bundle(version=True), bundle(version=2), bundle(format="other"), bundle(snapshots={}),
                   bundle(snapshots=[snapshot()] * 501), bundle(exported_at="2027-01-01T00:00:00Z"),
                   bundle(exported_at="2026-10-21T12:00:00"), bundle(window={}),
                   bundle(window={**WINDOW, "time_zone": "Unknown/Nowhere"}),
                   bundle(window={**WINDOW, "start_date": "2026-11-02"}),
                   bundle(window={**WINDOW, "end_date": "2027-01-19"}),
                   bundle(window={**WINDOW, "end_date": "2026-11-31"})]
        for payload in invalid:
            with self.subTest(payload={key: value for key, value in payload.items() if key != "snapshots"}):
                result = self.run_import(payload)
                self.assertEqual(result.lots, [])
                self.assertTrue(result.errors)
        self.assertEqual(self.cache.connection.execute("SELECT COUNT(*) FROM lots").fetchone()[0], 0)

    def test_bounded_read_stops_oversized_files_without_parsing(self):
        path = self.write(bundle())
        with patch("catalogapp.watchlist_invaluable_pages.MAX_CAPTURE_BYTES", 10):
            result = import_saved_invaluable_pages([path], [CALDER], self.cache, now=NOW)
        self.assertEqual(result.lots, [])
        self.assertIn("at most 20 MiB", " ".join(result.errors))

    def test_bundle_pagination_and_required_hit_metadata_are_validated(self):
        bad_pages = []
        for field, value in (("page", True), ("page", 1), ("nbPages", 2), ("nbHits", 2),
                             ("hitsPerPage", 0), ("hitsPerPage", 1001), ("hitsPerPage", None)):
            page = snapshot()
            page["results"][0][field] = value
            bad_pages.append(page)
        duplicate = snapshot([hit(), hit()])
        bad_pages.append(duplicate)
        for field, value in (("lotRef", ""), ("lotTitle", {}), ("artistName", ""), ("objectID", True)):
            bad_pages.append(snapshot([hit(**{field: value})]))
        bad_pages.extend([snapshot(captured=NOW + timedelta(minutes=1)),
                          {**snapshot(), "source_url": CALDER.url.replace("https:", "http:")}])
        for page in bad_pages:
            with self.subTest(page=page):
                result = self.run_import(bundle([page]))
                self.assertEqual(result.lots, [])
                self.assertTrue(result.errors)

    def test_invalid_page_does_not_discard_independent_valid_page(self):
        invalid = snapshot()
        invalid["results"][0]["nbHits"] = -1
        result = self.run_import(bundle([invalid, snapshot([hit("2", artist=WARHOL.artist)], entry=WARHOL)]))
        self.assertEqual({lot.source_lot_id for lot in result.lots}, {"2"})
        self.assertTrue(result.errors)

    def test_bundle_rejects_nonfinite_and_structured_public_hit_fields(self):
        for field, value in (("currentBid", float("nan")), ("estimateHigh", float("inf")),
                             ("estimateLow", float("-inf")), ("bidCount", True),
                             ("houseName", {"name": "Nested house"}), ("photoPath", ["image.jpg"]),
                             ("currencyCode", None)):
            with self.subTest(field=field, value=value):
                result = self.run_import(bundle([snapshot([hit(**{field: value})])]))
                self.assertEqual(result.lots, [])
                self.assertIn("text or a finite number", " ".join(result.errors))
        self.assertEqual(self.cache.connection.execute("SELECT COUNT(*) FROM lots").fetchone()[0], 0)

    def test_bundle_ignores_fields_outside_the_public_export_schema(self):
        result = self.run_import(bundle([snapshot([hit(imageUrl="https://example.com/private-tracking.jpg",
                                                       account={"email": "PRIVATE ACCOUNT"})])]))
        self.assertEqual(result.errors, [])
        self.assertEqual(len(result.lots), 1)
        self.assertEqual(result.lots[0].image_url, "")
        self.assertNotIn("PRIVATE ACCOUNT", str(result))

    def test_legacy_single_snapshot_with_incomplete_pagination_remains_supported(self):
        payload = snapshot([hit(when="2026-10-22T12:00:00Z")])
        payload["results"][0].pop("hitsPerPage")
        payload["results"][0]["nbPages"] = 9
        result = self.run_import(payload)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.metrics.new_lots, 1)


class CaptureCLITests(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.bookmarks = self.root / "artists.html"
        self.bookmarks.write_text(f'<DL><DT><H3>ARTISTS INVALUABLE</H3><DL><DT><A HREF="{CALDER.url}">Calder</A></DL></DL>', encoding="utf-8")
        self.capture = self.root / "capture.json"
        self.capture.write_text(json.dumps(bundle()), encoding="utf-8")
        self.cache_path = self.root / "watchlist.sqlite3"
        self.report = self.root / "report.json"
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch("sys.stdout", new_callable=StringIO))
        self.stack.enter_context(patch("sys.stderr", new_callable=StringIO))
        self.network = self.stack.enter_context(patch("requests.sessions.Session.request", side_effect=AssertionError("No real network")))
        # CLI uses the current time internally. Freeze only the import wrapper,
        # keeping both preview and persistence on the actual implementation.
        original = cli.import_saved_invaluable_pages
        self.stack.enter_context(patch.object(cli, "import_saved_invaluable_pages",
                                             side_effect=lambda *args, **kwargs: original(*args, now=NOW, **kwargs)))

    def run_cli(self, *extra):
        return cli.main([str(self.capture), "--bookmarks", str(self.bookmarks), "--cache", str(self.cache_path),
                         "--report", str(self.report), *extra])

    def test_default_preview_does_not_create_target_cache_or_load_credentials(self):
        with patch("dotenv.load_dotenv") as load, patch.object(cli, "sync_watchlist_lots") as sync:
            self.assertEqual(self.run_cli(), 0)
        self.assertFalse(self.cache_path.exists())
        self.assertEqual(json.loads(self.report.read_text(encoding="utf-8"))["summary"]["observed_lots"], 1)
        load.assert_not_called()
        sync.assert_not_called()

    def test_preview_existing_cache_is_byte_identical_and_report_excludes_pixels_and_fallbacks(self):
        with WatchlistCache(self.cache_path) as cache:
            lot = InvaluableAdapter().parse_search_page(json.dumps({"results": [{"hits": [hit("old", when="2026-10-22T12:00:00Z")]}]}), CALDER.url, CALDER.artist)[0]
            lot.saved_image_base64 = "PIXELS"
            cache.upsert(lot, watch_url=CALDER.url, search_hash=lot.content_hash, observed_at=OLD)
        before = self.cache_path.read_bytes()
        self.assertEqual(self.run_cli(), 0)
        self.assertEqual(before, self.cache_path.read_bytes())
        report = self.report.read_text(encoding="utf-8")
        self.assertNotIn("PIXELS", report)
        self.assertEqual([lot["source_lot_id"] for lot in json.loads(report)["lots"]], ["1"])

    def test_sync_validates_first_and_uploads_observed_lots_only(self):
        response = Mock()
        response.summary.return_value = "Calendar updated: 1 lot"
        with patch.dict("os.environ", {"CATALOG_API_KEY": "test-only-key"}), patch("dotenv.load_dotenv"), \
                patch.object(cli, "sync_watchlist_lots", return_value=response) as sync:
            self.assertEqual(self.run_cli("--sync"), 0)
        self.assertEqual([lot.source_lot_id for lot in sync.call_args.args[0]], ["1"])
        self.assertTrue(self.cache_path.exists())
        report = self.report.read_text(encoding="utf-8")
        self.assertNotIn("test-only-key", report)
        self.assertEqual(json.loads(report)["summary"]["mode"], "synced")

    def test_sync_with_validation_errors_does_not_touch_cache_or_credentials(self):
        self.capture.write_text(json.dumps(bundle(version=999)), encoding="utf-8")
        with patch("dotenv.load_dotenv") as load, patch.object(cli, "sync_watchlist_lots") as sync:
            self.assertEqual(self.run_cli("--sync"), 1)
        self.assertFalse(self.cache_path.exists())
        load.assert_not_called()
        sync.assert_not_called()
