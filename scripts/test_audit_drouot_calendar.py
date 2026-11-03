"""Offline checks of public Drouot Calendar readback and preservation audits."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from audit_drouot_calendar import (
    PUBLIC_FIELDS, READBACK_FIELDS, compare_snapshots, expected_record, fetch_snapshot, key, projected_dom, public_row, read_dom,
)


def lot(identity="123", source="Drouot", **overrides):
    value = {field: "" for field in PUBLIC_FIELDS}
    value.update({field: None for field in ("estimate_low", "estimate_high", "current_bid", "sold_price", "bid_count")})
    value.update(source=source, source_lot_id=identity, artist="Joan Miró", artist_watchlist_name="Joan Miró",
                 title="* Le Soleil (after Joan Miro)", medium="Lithograph", auction_house="Example Auctions",
                 lot_number="23", end_at="2026-11-03T15:00:00+00:00", currency="EUR", current_bid=20,
                 first_seen_at="2026-11-01T05:00:00+00:00", last_seen_at="2026-11-01T05:00:00+00:00",
                 lot_url=f"https://drouot.com/en/l/{identity}-print", image_url="https://cdn.drouot.com/photo.jpg",
                 status="new")
    value.update(overrides)
    return value


def snapshot(rows, keys=None):
    return {"lots": rows, "calendar_lot_keys": keys if keys is not None else [key(row) for row in rows],
            "coverage": {"calendar_time_zone": "America/Los_Angeles",
                         "event_start_inclusive": "2026-10-24T00:00:00-07:00",
                         "event_end_exclusive": "2026-11-08T00:00:00-08:00"}}


def reports(rows):
    preview = {"lots": deepcopy(rows), "summary": {"mode": "preview", "errors": []}}
    synced = {"lots": deepcopy(rows), "summary": {"mode": "synced", "errors": [],
              "calendar_result": f"Website calendar synced: {len(rows)} lots (1 new, 0 updated, 0 ended)."}}
    return preview, synced


def superseded_fixture():
    incoming = lot()
    replacement = lot("999", source="Invaluable", lot_url="https://www.invaluable.com/auction-lot/print-23-c-example")
    before, after = snapshot([replacement]), snapshot([replacement])
    after["fetched_at"] = "2026-11-01T06:00:00+00:00"
    expected = expected_record(incoming)
    fields = set(READBACK_FIELDS) - {"end_at", "last_seen_at"}
    row = {field: expected[field] for field in fields}
    row.update(id=456, source="Drouot", source_lot_id="123", active=False, superseded_by_id=789,
               replacement_id=789, replacement_source="Invaluable", replacement_source_lot_id="999",
               replacement_lot_url=replacement["lot_url"], event_at=expected["end_at"],
               source_last_seen_at=expected["last_seen_at"])
    proof = {"format": "secondstate-drouot-superseded-db-readback", "version": 1,
             "captured_at": "2026-11-01T06:01:00+00:00", "provider": "Read-only test connector",
             "workspace_id": "test-workspace", "postgres_id": "test-db", "sql": "SELECT public_fields FROM lots",
             "rows": [row]}
    historical = {key(incoming): {**projected_dom(expected, "America/Los_Angeles"), "calendar_id": 456}}
    return incoming, before, after, proof, historical


class DrouotCalendarAuditTests(unittest.TestCase):
    def test_get_snapshot_retains_only_public_projection_and_never_credentials_or_private_metadata(self):
        incoming = {**lot(), "won_by_us": True, "research": "PRIVATE_RESEARCH"}
        received = {"ok": True, "lots": [incoming], "calendar_lot_keys": ["drouot:123"],
                    "next_cursor": None, "account": "PRIVATE_ACCOUNT", "entries": [{"secret": "PRIVATE_ENTRY"}]}
        calls = []
        def get(url, **kwargs):
            calls.append((url, kwargs))
            return SimpleNamespace(status_code=200, json=lambda: received)
        fake_requests = SimpleNamespace(get=get, RequestException=Exception)
        fake_dotenv = SimpleNamespace(load_dotenv=lambda *_args, **_kwargs: None)
        fake_sync = SimpleNamespace(_validated_base_url=lambda value: value.rstrip("/"))
        with TemporaryDirectory() as directory, patch.dict("os.environ", {"CATALOG_API_KEY": "TEST_ONLY_CREDENTIAL",
                     "SECONDSTATE_BASE_URL": "https://calendar.example"}), patch.dict("sys.modules", {
                         "requests": fake_requests, "dotenv": fake_dotenv, "catalogapp.watchlist_sync": fake_sync}):
            fetch_snapshot(Path(directory), "before", "America/Los_Angeles")
            saved = (Path(directory) / "calendar-before.json").read_text(encoding="utf-8")
        self.assertNotIn("PRIVATE_", saved)
        self.assertNotIn("TEST_ONLY_CREDENTIAL", saved)
        self.assertEqual(calls[0][1]["params"], {"cursor": "0", "page_size": 500, "horizon_days": 7})
        self.assertFalse(calls[0][1]["allow_redirects"])
        with self.assertRaisesRegex(RuntimeError, "nested"):
            public_row({**lot(), "artist": {"private": "PRIVATE_METADATA"}})

    def test_full_api_readback_and_other_source_concurrency(self):
        incoming = lot()
        other = lot("999", source="Invaluable", current_bid=10)
        preview, sync = reports([incoming])
        updated_other = {**other, "current_bid": 15}
        result = compare_snapshots(snapshot([other]), snapshot([incoming, updated_other]), preview, sync)
        self.assertTrue(result["passed"], result["errors"])
        self.assertEqual(result["accepted_api_fields_verified"], 1)
        self.assertEqual(len(result["different_source_concurrent_updates"]), 1)
        self.assertEqual(len(result["suspected_cross_listings"]), 1)
        self.assertIn("no merge", result["suspected_cross_listings"][0]["action"])

    def test_monthly_dom_supplies_fields_and_database_id_outside_api_horizon(self):
        incoming = lot(end_at="2026-11-08T17:00:00+00:00")
        preview, sync = reports([incoming])
        before, after = snapshot([]), snapshot([], [key(incoming)])
        self.assertFalse(compare_snapshots(before, after, preview, sync)["passed"])
        row = {**projected_dom(expected_record(incoming), "America/Los_Angeles"), "calendar_id": 456}
        result = compare_snapshots(before, after, preview, sync, {key(incoming): row})
        self.assertTrue(result["passed"], result["errors"])
        self.assertEqual(result["verified_calendar_ids"], [{"key": "drouot:123", "calendar_id": 456}])
        row["artist"] = "Wrong artist"
        self.assertFalse(compare_snapshots(before, after, preview, sync, {key(incoming): row})["passed"])

    def test_newer_prior_observation_remains_authoritative(self):
        previous = lot(title="Newer source title", last_seen_at="2026-11-01T06:00:00+00:00")
        stale = lot(title="Older title", last_seen_at="2026-11-01T05:00:00+00:00")
        preview, sync = reports([stale])
        result = compare_snapshots(snapshot([previous]), snapshot([previous]), preview, sync)
        self.assertTrue(result["passed"], result["errors"])
        self.assertEqual(result["newer_observations_preserved"], ["drouot:123"])
        self.assertFalse(compare_snapshots(snapshot([previous]), snapshot([stale]), preview, sync)["passed"])

    def test_positive_sold_price_and_saved_image_are_preserved(self):
        previous = lot(sold_price=45, sold_currency="EUR", status="ended",
                       image_url="https://secondstate.art/media/calendar-lots/" + "a" * 64 + ".jpg")
        incoming = lot()
        preview, sync = reports([incoming])
        saved = expected_record(incoming, previous)
        saved["status"] = "ended"
        self.assertTrue(compare_snapshots(snapshot([previous]), snapshot([saved]), preview, sync)["passed"])
        dom = {**projected_dom(saved, "America/Los_Angeles"), "calendar_id": 456}
        dom["image_urls"] = ["/media/calendar-lots/" + "a" * 64 + ".jpg"]
        self.assertTrue(compare_snapshots(snapshot([previous]), snapshot([saved]), preview, sync, {key(saved): dom})["passed"])
        saved["sold_price"] = None
        self.assertFalse(compare_snapshots(snapshot([previous]), snapshot([saved]), preview, sync)["passed"])

    def test_unobserved_drouot_records_and_global_keys_cannot_disappear(self):
        previous = lot("999")
        incoming = lot()
        preview, sync = reports([incoming])
        after = snapshot([incoming, {**previous, "current_bid": 90}])
        self.assertFalse(compare_snapshots(snapshot([previous]), after, preview, sync)["passed"])
        after = snapshot([incoming], [key(incoming), key(previous)])
        result = compare_snapshots(snapshot([previous]), after, preview, sync)
        self.assertFalse(result["passed"])
        self.assertTrue(result["public_field_mismatches"][0]["missing_expected_record"])
        result = compare_snapshots(snapshot([previous]), snapshot([incoming]), preview, sync)
        self.assertEqual(result["prior_global_identity_keys_lost"], [key(previous)])

    def test_receipt_count_and_exact_preview_sync_observations_are_required(self):
        incoming = lot()
        preview, sync = reports([incoming])
        sync["summary"]["calendar_result"] = "Website calendar synced: 0 lots (0 new, 0 updated, 0 ended)."
        self.assertFalse(compare_snapshots(snapshot([]), snapshot([incoming]), preview, sync)["passed"])
        _, sync = reports([{**incoming, "current_bid": 900}])
        self.assertFalse(compare_snapshots(snapshot([]), snapshot([incoming]), preview, sync)["passed"])

    def test_observed_source_slug_change_preserves_source_and_calendar_identity(self):
        previous = lot(lot_url="https://drouot.com/en/l/123-old-slug")
        incoming = lot(lot_url="https://drouot.com/en/l/123-fresh-slug")
        old_alias, new_alias = "drouot:" + previous["lot_url"], "drouot:" + incoming["lot_url"]
        before = snapshot([previous], [key(previous), old_alias])
        after = snapshot([incoming], [key(incoming), new_alias])
        prior_dom = {key(previous): {**projected_dom(previous, "America/Los_Angeles"), "calendar_id": 456}}
        dom = {key(incoming): {**projected_dom(incoming, "America/Los_Angeles"), "calendar_id": 456}}
        result = compare_snapshots(before, after, *reports([incoming]), dom, baseline_dom=prior_dom)
        self.assertTrue(result["passed"], result["errors"])
        self.assertEqual(result["raw_missing_before_keys"], [old_alias])
        self.assertEqual(result["prior_global_identity_keys_lost"], [])
        self.assertEqual(result["resolved_url_alias_changes"], [{"key": "drouot:123", "calendar_id": 456,
                         "old_alias": old_alias, "new_alias": new_alias}])
        historical_only = compare_snapshots(before, after, *reports([incoming]), dom, historical_dom=prior_dom)
        self.assertFalse(historical_only["passed"])
        self.assertEqual(historical_only["prior_global_identity_keys_lost"], [old_alias])
        for change in ("missing_baseline", "changed_database_id", "missing_source_id", "missing_new_alias",
                       "unobserved_url", "wrong_source_id", "unaccepted_lot", "wrong_prior_url"):
            with self.subTest(change=change):
                b, a, p, d, observed = deepcopy(before), deepcopy(after), deepcopy(prior_dom), deepcopy(dom), deepcopy(incoming)
                if change == "missing_baseline": p = {}
                elif change == "changed_database_id": d["drouot:123"]["calendar_id"] = 999
                elif change == "missing_source_id": a["calendar_lot_keys"].remove("drouot:123")
                elif change == "missing_new_alias": a["calendar_lot_keys"].remove(new_alias)
                elif change == "unobserved_url": observed["lot_url"] = previous["lot_url"]
                elif change == "wrong_source_id": observed["lot_url"] = "https://drouot.com/en/l/999-fresh-slug"
                elif change == "wrong_prior_url": p["drouot:123"]["lot_url"] = "https://drouot.com/en/l/123-unproven-slug"
                accepted = [] if change == "unaccepted_lot" else [observed]
                result = compare_snapshots(b, a, *reports(accepted), d, baseline_dom=p)
                self.assertFalse(result["passed"])
                self.assertIn(old_alias, result["prior_global_identity_keys_lost"])
                self.assertEqual(result["resolved_url_alias_changes"], [])

    def test_dom_projection_uses_public_fields_only_and_matches_only_drouot_urls(self):
        incoming = lot()
        row = {**projected_dom(incoming, "America/Los_Angeles"), "id": 456,
               "staff_research": "PRIVATE_RESEARCH", "won_by_us": True}
        wrong_host = {**row, "lot_url": "https://other.example/en/l/999-print"}
        with TemporaryDirectory() as directory:
            path = Path(directory) / "public-dom.json"
            path.write_text(json.dumps([row, wrong_host]), encoding="utf-8")
            projected = read_dom([path])
        self.assertEqual(set(projected), {"drouot:123"})
        self.assertNotIn("PRIVATE", json.dumps(projected))
        self.assertEqual(projected["drouot:123"]["calendar_id"], 456)

    def test_preexisting_supersession_uses_exact_database_readback_separately_from_public_surfaces(self):
        incoming, before, after, proof, historical = superseded_fixture()
        preview, sync = reports([incoming])
        self.assertFalse(compare_snapshots(before, after, preview, sync)["passed"])
        result = compare_snapshots(before, after, preview, sync, superseded_db=proof, historical_dom=historical)
        self.assertTrue(result["passed"], result["errors"])
        self.assertEqual(result["accepted_api_fields_verified"], 0)
        self.assertEqual(result["accepted_dom_fields_verified"], 0)
        self.assertEqual(result["accepted_superseded_db_fields_verified"], 1)
        self.assertEqual(result["verified_calendar_ids"][0]["calendar_id"], 456)
        self.assertEqual(result["verified_calendar_ids"][0]["superseded_by_id"], 789)
        self.assertEqual(result["accepted_without_api_or_dom_readback"], ["drouot:123"])
        self.assertEqual(result["accepted_without_public_field_readback"], [])
        self.assertEqual(result["missing_accepted_global_ids"], [])
        self.assertEqual(result["new_global_source_ids"], [])
        self.assertEqual(result["prior_global_identity_keys_lost"], [])

    def test_superseded_readback_requires_fresh_exact_prices_and_observation_timestamp(self):
        for field, changed in (("current_bid", 999), ("source_last_seen_at", "2026-11-01T04:59:00+00:00"),
                               ("event_at", "2026-11-04T15:00:00+00:00")):
            with self.subTest(field=field):
                incoming, before, after, proof, historical = superseded_fixture()
                proof["rows"][0][field] = changed
                result = compare_snapshots(before, after, *reports([incoming]), superseded_db=proof, historical_dom=historical)
                self.assertFalse(result["passed"])
                self.assertEqual(result["accepted_superseded_db_fields_verified"], 0)
                self.assertEqual(result["missing_accepted_global_ids"], ["drouot:123"])
        incoming, before, after, proof, historical = superseded_fixture()
        proof["captured_at"] = "2026-11-01T05:59:00+00:00"
        with self.assertRaisesRegex(ValueError, "postdate"):
            compare_snapshots(before, after, *reports([incoming]), superseded_db=proof, historical_dom=historical)

    def test_supersession_exception_rejects_unproven_identity_replacement_or_private_fields(self):
        for field, changed in (("active", True), ("id", 9999), ("replacement_id", 1234),
                               ("replacement_source_lot_id", "missing"), ("source_lot_id", "not-accepted"),
                               ("private_research", "not permitted")):
            with self.subTest(field=field):
                incoming, before, after, proof, historical = superseded_fixture()
                proof["rows"][0][field] = changed
                with self.assertRaises(ValueError):
                    compare_snapshots(before, after, *reports([incoming]), superseded_db=proof, historical_dom=historical)
        incoming, before, after, proof, historical = superseded_fixture()
        with self.assertRaisesRegex(ValueError, "historical"):
            compare_snapshots(before, after, *reports([incoming]), superseded_db=proof)

    def test_newly_missing_identity_cannot_be_excused_as_preexisting_supersession(self):
        incoming, before, after, proof, historical = superseded_fixture()
        before["calendar_lot_keys"].append(key(incoming))
        with self.assertRaisesRegex(ValueError, "absence before"):
            compare_snapshots(before, after, *reports([incoming]), superseded_db=proof, historical_dom=historical)
        incoming, before, after, proof, historical = superseded_fixture()
        before = snapshot([])
        with self.assertRaisesRegex(ValueError, "replacement"):
            compare_snapshots(before, after, *reports([incoming]), superseded_db=proof, historical_dom=historical)


if __name__ == "__main__":
    unittest.main()
