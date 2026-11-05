"""Change/draft state tests; no mail, production fetches or real ledger writes."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from scripts import calendar_reminder_updates as updates


def lot(identifier="1", **changes):
    row = {"source": "invaluable", "source_lot_id": identifier,
           "lot_url": f"https://example.com/lot/{identifier}", "artist": "Picasso",
           "artist_watchlist_name": "Pablo Picasso", "title": "Print", "lot_number": identifier,
           "auction_house": "Doyle", "sale_title": "Prints & Multiples",
           "sale_url": "https://example.com/sale/one", "end_at": "2026-11-05T18:00:00Z",
           "start_at": "", "status": "unchanged", "sold_price": None,
           "estimate_low": 100, "estimate_high": 200, "currency": "USD",
           "current_bid": 50, "bid_count": 1}
    row.update(changes)
    return row


def moment(value="2026-11-04T17:00:00+00:00"):
    return datetime.fromisoformat(value)


def group(result, owner="jeremy", days=1):
    return next(g for stream in result["owners"] if stream["owner"] == owner
                for g in stream["groups"] if g["days_away"] == days)


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.ledger = Path(self.directory.name) / "deliveries.sqlite3"
        self.now = moment()

    def tearDown(self):
        self.directory.cleanup()

    def scan(self, rows, offset=0, at=None):
        return updates.scan_updates(rows, at or self.now + timedelta(hours=offset), self.ledger)

    def make_changed(self):
        self.scan([lot()])
        return self.scan([lot(current_bid=75, bid_count=2)], 1)

    def claim(self, result, owner="jeremy", days=1, at=None):
        item = group(result, owner, days)
        return updates.claim_draft(self.ledger, owner, days, item["target_date"], item["through_event_id"], at or self.now + timedelta(hours=1))

    def record(self, claim, draft_id="draft-one"):
        return updates.record_draft(self.ledger, claim["owner"], claim["days_away"], draft_id,
                                    claim["through_event_id"], claim["claim_token"])

    def test_initial_baseline_and_unchanged_scan_make_no_drafts(self):
        first = self.scan([lot()])
        self.assertTrue(first["baseline_created"])
        self.assertEqual(first["new_event_count"], 0)
        for stream in first["owners"]:
            self.assertTrue(all(g["draft_action"] is None for g in stream["groups"]))
        second = self.scan([lot(status="changed", last_seen_at="noise")], 1)
        self.assertFalse(second["baseline_created"])
        self.assertEqual(second["new_event_count"], 0)

    def test_change_details_scope_and_owner_recipients(self):
        result = self.make_changed()
        self.assertEqual(result["owner_event_counts"], {"jeremy": 1, "oliver": 1})
        item = group(result)
        self.assertEqual(item["pending_events"][0]["changed_fields"], ["current_bid", "bid_count"])
        gmail = item["draft_action"]["gmail"]
        self.assertEqual(gmail["subject"], "🟥 1-DAY UPDATE DRAFT · Jeremy · Nov 5, 2026")
        self.assertIn("Reference: SS-CALENDAR-UPDATES-JEREMY-1D", gmail["payload"]["body"]["content"])
        self.assertIn("2026-11-05", gmail["payload"]["body"]["content"])
        self.assertIn("50 → 75", gmail["payload"]["body"]["content"])
        self.assertNotIn("oliver1@vt.edu", gmail["to"])
        self.assertIn("oliver1@vt.edu", group(result, "oliver")["draft_action"]["gmail"]["to"])
        for owner in ("jeremy", "oliver"):
            self.assertEqual(group(result, owner)["draft_action"]["gmail"]["from_address"], "sales@secondstate.art")

    def test_additions_respect_house_and_separate_categories(self):
        self.scan([])
        result = self.scan([lot("a", auction_house="Forum Auctions"), lot("b", end_at="2026-11-07")], 1)
        self.assertEqual(result["owner_event_counts"], {"jeremy": 2, "oliver": 1})
        self.assertIsNotNone(group(result, "jeremy", 1)["draft_action"])
        self.assertIsNone(group(result, "oliver", 1)["draft_action"])
        self.assertEqual(group(result, "oliver", 3)["pending_event_count"], 1)
        self.assertNotIn("2026-11-05", group(result, "jeremy", 3)["draft_action"]["gmail"]["payload"]["body"]["content"])

    def test_all_horizon_snapshotted_so_rollover_is_not_an_addition(self):
        outside = lot(end_at="2026-11-10")
        self.scan([outside])
        result = self.scan([outside], at=moment("2026-11-05T17:00:00+00:00"))
        self.assertEqual(result["new_event_count"], 0)
        self.assertIsNone(group(result, days=5)["draft_action"])
        with closing(sqlite3.connect(self.ledger)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM reminder_update_snapshots").fetchone()[0], 1)

    def test_owner_date_and_literal_date_only(self):
        self.scan([])
        result = self.scan([lot(end_at="2026-11-06T07:00:00Z")], 1)
        self.assertIsNotNone(group(result, "jeremy", 1)["draft_action"])
        self.assertIsNotNone(group(result, "oliver", 2)["draft_action"])
        self.assertIsNone(group(result, "oliver", 1)["draft_action"])
        result = self.scan([lot(end_at="2026-11-06T07:00:00Z"), lot("date", end_at="2026-11-07")], 2)
        self.assertIsNotNone(group(result, "jeremy", 3)["draft_action"])
        self.assertIsNotNone(group(result, "oliver", 3)["draft_action"])

    def test_sold_and_ended_changes_are_logged(self):
        self.scan([lot("one"), lot("two")])
        result = self.scan([lot("one", sold_price=150), lot("two", status="ended")], 1)
        kinds = {event["kind"] for event in group(result)["pending_events"]}
        self.assertEqual(kinds, {"sold", "ended"})

    def test_disappearance_is_not_cancellation_and_is_logged_once(self):
        self.scan([lot()])
        result = self.scan([], 1)
        item = group(result)
        self.assertEqual(item["pending_events"][0]["kind"], "no_longer_present")
        self.assertIn("does not establish cancellation", item["draft_action"]["gmail"]["payload"]["body"]["content"])
        self.assertEqual(self.scan([], 2)["new_event_count"], 0)
        reappeared = self.scan([lot()], 3)
        self.assertEqual(group(reappeared)["pending_events"][-1]["kind"], "reappeared")

    def test_normal_past_and_horizon_expiration_do_not_signal_removal(self):
        self.scan([lot("past", end_at="2026-11-04T17:30:00Z"), lot("far", end_at="2026-11-11")])
        result = self.scan([], 1)
        self.assertEqual(result["new_event_count"], 0)

    def test_today_changes_are_logged_without_zero_day_draft(self):
        self.scan([])
        result = self.scan([lot(end_at="2026-11-04T23:00:00Z")], 1)
        self.assertEqual(result["new_event_count"], 2)
        self.assertTrue(all(g["draft_action"] is None for owner in result["owners"] for g in owner["groups"]))

    def test_changed_sale_date_updates_old_and_new_categories(self):
        self.scan([lot(end_at="2026-11-05")])
        result = self.scan([lot(end_at="2026-11-07")], 1)
        self.assertEqual(group(result, days=1)["pending_event_count"], 1)
        self.assertEqual(group(result, days=3)["pending_event_count"], 1)

    def test_no_change_keeps_pending_draft_after_failure(self):
        result = self.make_changed()
        repeated = self.scan([lot(current_bid=75, bid_count=2)], 2)
        self.assertEqual(repeated["new_event_count"], 0)
        self.assertEqual(group(repeated)["through_event_id"], group(result)["through_event_id"])
        self.assertIsNotNone(group(repeated)["draft_action"])

    def test_claim_is_atomic_and_uncertain_claim_prevents_duplicate(self):
        result = self.make_changed()
        def claim(_):
            return self.claim(result)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(claim, range(8)))
        winners = [entry for entry in results if entry["claimed"]]
        self.assertEqual(len(winners), 1)
        winner = winners[0]
        updates.unknown_draft(self.ledger, "jeremy", 1, winner["claim_token"], "timeout")
        self.assertFalse(self.claim(result)["claimed"])
        self.record(winner)
        current = updates.draft_status(self.ledger, self.now + timedelta(hours=2))
        self.assertIsNone(group(current)["draft_action"])
        self.assertEqual(group(current)["draft_id"], "draft-one")

    def test_existing_draft_updates_same_id_and_new_events_stay_pending(self):
        result = self.make_changed()
        first = self.claim(result)
        self.scan([lot(current_bid=100, bid_count=3)], 2)
        self.record(first)
        current = updates.draft_status(self.ledger, self.now + timedelta(hours=2))
        item = group(current)
        self.assertEqual(item["pending_event_count"], 1)
        self.assertEqual(item["draft_action"]["kind"], "update")
        self.assertEqual(item["draft_action"]["gmail"]["draft_id"], "draft-one")
        next_claim = self.claim(current, at=self.now + timedelta(hours=2))
        with self.assertRaises(ValueError):
            self.record(next_claim, "different-draft")
        self.record(next_claim)
        self.assertIsNone(group(updates.draft_status(self.ledger, self.now + timedelta(hours=3)))["draft_action"])

    def test_recipient_change_refreshes_existing_draft_without_new_events(self):
        result = self.make_changed()
        config = updates._helper().OWNERS["jeremy"]
        with patch.dict(config, to=["jeremy@secondstate.art", "oliver@secondstate.art", "alex@secondstate.art"]):
            first = self.claim(result)
            updates.unknown_draft(self.ledger, "jeremy", 1, first["claim_token"], "timeout")
        recipients = ["jeremy@secondstate.art", "alex@secondstate.art"]
        with patch.dict(config, to=recipients):
            reserved = self.claim(result)
            self.assertFalse(reserved["claimed"])
            self.assertEqual(reserved["operation"]["payload"]["gmail"], first["gmail"])
            self.record(first)
            current = self.scan([lot(current_bid=75, bid_count=2)], 2)
            self.assertEqual(current["new_event_count"], 0)
            self.assertEqual(group(current)["pending_event_count"], 0)
            self.assertIsNone(group(current, days=2)["draft_action"])
            refresh = self.claim(current)
            self.assertTrue(refresh["claimed"])
            self.assertEqual(refresh["kind"], "update")
            self.assertEqual(refresh["gmail"]["draft_id"], "draft-one")
            self.assertEqual(refresh["gmail"]["to"], ", ".join(recipients))
            self.record(refresh)
            self.assertIsNone(group(updates.draft_status(self.ledger, self.now))["draft_action"])

    def test_subject_change_refreshes_existing_draft_without_new_events(self):
        result = self.make_changed()
        tagged = "🟥 1-DAY UPDATE DRAFT · Jeremy · Nov 5, 2026 [SS-CALENDAR-UPDATES-JEREMY-1D]"
        with patch.object(updates._helper(), "category_subject", return_value=tagged):
            first = self.claim(result)
            self.assertEqual(first["gmail"]["subject"], tagged)
            self.record(first)
        current = updates.draft_status(self.ledger, self.now + timedelta(hours=2))
        self.assertEqual(group(current)["pending_event_count"], 0)
        refresh = self.claim(current)
        self.assertTrue(refresh["claimed"])
        self.assertEqual(refresh["gmail"]["draft_id"], "draft-one")
        self.assertEqual(refresh["gmail"]["subject"], "🟥 1-DAY UPDATE DRAFT · Jeremy · Nov 5, 2026")
        self.assertEqual(refresh["reference"], first["reference"])
        self.record(refresh)
        self.assertFalse(self.claim(current)["claimed"])

    def test_existing_draft_rolls_target_date_and_clears_old_content(self):
        first = self.claim(self.make_changed())
        self.record(first)
        rolled = updates.draft_status(self.ledger, moment("2026-11-05T17:00:00+00:00"))
        item = group(rolled)
        self.assertEqual(item["target_date"], "2026-11-06")
        self.assertEqual(item["through_event_id"], 0)
        self.assertEqual(item["draft_action"]["kind"], "update")
        html = item["draft_action"]["gmail"]["payload"]["body"]["content"]
        self.assertIn("No recorded catalog changes", html)
        self.assertNotIn("Picasso", html)

    def test_old_and_equal_scans_never_regress_snapshot(self):
        self.make_changed()
        for offset in (0, 1):
            stale = self.scan([lot(current_bid=10)], offset)
            self.assertTrue(stale["ignored_stale_scan"])
            self.assertEqual(stale["new_event_count"], 0)
        with closing(sqlite3.connect(self.ledger)) as db:
            payload = json.loads(db.execute("SELECT payload FROM reminder_update_snapshots").fetchone()[0])
        self.assertEqual(payload["current_bid"], 75)

    def test_parallel_identical_scans_log_each_change_once(self):
        self.scan([lot()])
        def scan(_):
            return self.scan([lot(current_bid=75)], 1)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(scan, range(8)))
        self.assertEqual(sum(result["new_event_count"] for result in results), 2)

    def test_markup_escaped_and_bad_urls_omitted(self):
        self.scan([])
        result = self.scan([lot(title="<script>bad</script>", lot_url="javascript:bad", sale_url="javascript:bad")], 1)
        html = group(result)["draft_action"]["gmail"]["payload"]["body"]["content"]
        self.assertNotIn("<script>", html)
        self.assertNotIn("javascript:", html)
        self.assertIn("&lt;script&gt;", html)

    def test_cli_json_survives_windows_pipe_encoding(self):
        self.make_changed()
        output_bytes = io.BytesIO()
        output = io.TextIOWrapper(output_bytes, encoding="cp1252")
        with patch("sys.stdout", output), patch.object(updates, "draft_status", return_value={"emoji": "🟥"}):
            self.assertEqual(updates.main(["--ledger", str(self.ledger), "draft-status"]), 0)
        output.flush()
        self.assertEqual(json.loads(output_bytes.getvalue().decode("cp1252")), {"emoji": "🟥"})
        output.close()

    def test_release_requires_explicit_confirmation_and_proof(self):
        result = self.make_changed()
        claim = self.claim(result)
        updates.unknown_draft(self.ledger, "jeremy", 1, claim["claim_token"], "timeout")
        for options in ({"reason": "Draft list was empty"}, {"confirmed_not_applied": True}):
            with self.assertRaises(ValueError):
                updates.release_draft(self.ledger, "jeremy", 1, claim["claim_token"], **options)
        self.assertFalse(self.claim(result)["claimed"])

    def test_definitive_failed_create_can_release_and_reclaim_with_audit(self):
        result = self.make_changed()
        claim = self.claim(result)
        released = updates.release_draft(self.ledger, "jeremy", 1, claim["claim_token"],
                                         confirmed_not_applied=True, reason="Provider rejected create with HTTP 400; no draft was created.")
        self.assertTrue(released["released"])
        retry = self.claim(result)
        self.assertTrue(retry["claimed"])
        self.assertNotEqual(retry["claim_token"], claim["claim_token"])
        self.assertEqual(retry["kind"], "create")
        with closing(sqlite3.connect(self.ledger)) as db:
            audit = db.execute("SELECT operation_token,operation_payload,proof_reason FROM reminder_update_draft_recoveries").fetchone()
        self.assertEqual(audit[0], claim["claim_token"])
        self.assertEqual(json.loads(audit[1])["gmail"], claim["gmail"])
        self.assertIn("HTTP 400", audit[2])
        with self.assertRaises(ValueError):
            updates.release_draft(self.ledger, "jeremy", 1, claim["claim_token"], confirmed_not_applied=True, reason="Old token")

    def test_verified_missing_draft_resets_id_and_creates_replacement(self):
        first = self.claim(self.make_changed())
        self.record(first)
        changed = self.scan([lot(current_bid=100, bid_count=3)], 2)
        update = self.claim(changed, at=self.now + timedelta(hours=2))
        self.assertEqual(update["kind"], "update")
        updates.release_draft(self.ledger, "jeremy", 1, update["claim_token"], confirmed_not_applied=True,
                              missing_draft=True, reason="Provider returned definitive 404; verified original draft no longer exists and reconciled stable reference.")
        current = updates.draft_status(self.ledger, self.now + timedelta(hours=2))
        self.assertIsNone(group(current)["draft_id"])
        replacement = self.claim(current, at=self.now + timedelta(hours=2))
        self.assertEqual(replacement["kind"], "create")
        self.assertNotIn("draft_id", replacement["gmail"])
        with closing(sqlite3.connect(self.ledger)) as db:
            prior = json.loads(db.execute("SELECT previous_state FROM reminder_update_draft_recoveries").fetchone()[0])
        self.assertEqual(prior["draft_id"], "draft-one")

    def test_sender_change_blocks_wrong_mailbox_update_then_retires_with_audit(self):
        config = updates._helper().OWNERS["jeremy"]
        with patch.dict(config, from_address="jeremy@secondstate.art", link_id="old-link"):
            first = self.claim(self.make_changed())
            self.record(first)
        current = updates.draft_status(self.ledger, self.now + timedelta(hours=2))
        item = group(current)
        self.assertIsNone(item["draft_action"])
        self.assertEqual(item["migration_required"]["previous_sender"], "jeremy@secondstate.art")
        self.assertFalse(self.claim(current)["claimed"])
        retired = updates.retire_draft(self.ledger, "jeremy", 1, "draft-one", confirmed_retired=True,
                                       reason="Readback confirmed matching old draft was moved to TRASH.")
        self.assertTrue(retired["retired"])
        current = updates.draft_status(self.ledger, self.now + timedelta(hours=2))
        replacement = self.claim(current)
        self.assertTrue(replacement["claimed"])
        self.assertEqual(replacement["kind"], "create")
        self.assertNotIn("draft_id", replacement["gmail"])
        self.assertEqual(replacement["gmail"]["from_address"], "sales@secondstate.art")
        self.record(replacement, "sales-draft")
        final = group(updates.draft_status(self.ledger, self.now + timedelta(hours=2)))
        self.assertEqual(final["draft_sender"], "sales@secondstate.art")
        self.assertIsNone(final["draft_action"])
        self.assertIsNone(final["migration_required"])
        with closing(sqlite3.connect(self.ledger)) as db:
            audit = db.execute("SELECT previous_sender,replacement_sender,previous_state,proof_reason FROM reminder_update_draft_retirements").fetchone()
        self.assertEqual(audit[0], "jeremy@secondstate.art")
        self.assertEqual(audit[1], "sales@secondstate.art")
        self.assertEqual(json.loads(audit[2])["draft_id"], "draft-one")
        self.assertIn("TRASH", audit[3])
        with self.assertRaises(ValueError):
            updates.retire_draft(self.ledger, "jeremy", 1, "draft-one", confirmed_retired=True, reason="Old ID")

    def test_sender_change_preserves_uncertain_immutable_operation(self):
        config = updates._helper().OWNERS["jeremy"]
        with patch.dict(config, from_address="jeremy@secondstate.art", link_id="old-link"):
            result = self.make_changed()
            claim = self.claim(result)
            updates.unknown_draft(self.ledger, "jeremy", 1, claim["claim_token"], "timeout")
        blocked = self.claim(result)
        self.assertFalse(blocked["claimed"])
        self.assertEqual(blocked["operation"]["payload"]["gmail"], claim["gmail"])
        self.record(claim)
        current = group(updates.draft_status(self.ledger, self.now + timedelta(hours=2)))
        self.assertEqual(current["draft_sender"], "jeremy@secondstate.art")
        self.assertIsNotNone(current["migration_required"])

    def test_retirement_requires_exact_id_proof_sender_change_and_no_operation(self):
        config = updates._helper().OWNERS["jeremy"]
        with patch.dict(config, from_address="jeremy@secondstate.art"):
            first = self.claim(self.make_changed())
            self.record(first)
            with self.assertRaises(ValueError):
                updates.retire_draft(self.ledger, "jeremy", 1, "draft-one", confirmed_retired=True, reason="Same mailbox")
            changed = self.scan([lot(current_bid=100, bid_count=3)], 2)
            pending = self.claim(changed, at=self.now + timedelta(hours=2))
        with self.assertRaises(ValueError):
            updates.retire_draft(self.ledger, "jeremy", 1, "draft-one", confirmed_retired=True, reason="Pending operation")
        self.record(pending)
        for draft_id, options in (("draft-one", {"reason": "No confirmation"}),
                                  ("draft-one", {"confirmed_retired": True}),
                                  ("wrong-id", {"confirmed_retired": True, "reason": "Wrong ID"})):
            with self.assertRaises(ValueError):
                updates.retire_draft(self.ledger, "jeremy", 1, draft_id, **options)
        current = group(updates.draft_status(self.ledger, self.now + timedelta(hours=2)))
        self.assertEqual(current["draft_id"], "draft-one")

    def test_retired_draft_recreated_even_after_empty_date_rollover(self):
        config = updates._helper().OWNERS["jeremy"]
        with patch.dict(config, from_address="jeremy@secondstate.art"):
            self.record(self.claim(self.make_changed()))
        updates.retire_draft(self.ledger, "jeremy", 1, "draft-one", confirmed_retired=True, reason="Verified old draft in Trash")
        rolled_at = moment("2026-11-05T17:00:00+00:00")
        current = updates.draft_status(self.ledger, rolled_at)
        self.assertEqual(group(current)["through_event_id"], 0)
        claim = self.claim(current, at=rolled_at)
        self.assertTrue(claim["claimed"])
        self.assertEqual(claim["kind"], "create")
        self.assertIn("No recorded catalog changes", claim["gmail"]["payload"]["body"]["content"])
        self.assertNotIn("Picasso", claim["gmail"]["payload"]["body"]["content"])

    def test_legacy_draft_schema_assumes_original_owner_mailbox(self):
        with closing(sqlite3.connect(self.ledger)) as db:
            db.execute("""CREATE TABLE reminder_update_drafts (
                owner TEXT NOT NULL, days INTEGER NOT NULL, draft_id TEXT, target_date TEXT,
                through_event_id INTEGER NOT NULL DEFAULT 0, revision TEXT, updated_at TEXT,
                operation_token TEXT, operation_payload TEXT, operation_state TEXT, operation_reason TEXT,
                PRIMARY KEY(owner,days))""")
            db.execute("INSERT INTO reminder_update_drafts(owner,days,draft_id,target_date) VALUES ('jeremy',1,'legacy-id','2026-11-05')")
            db.commit()
        item = group(updates.draft_status(self.ledger, self.now))
        self.assertEqual(item["draft_sender"], "jeremy@secondstate.art")
        self.assertEqual(item["migration_required"]["draft_id"], "legacy-id")
        self.assertIsNone(item["draft_action"])

    def test_rotating_connector_link_does_not_refresh_same_mailbox_draft(self):
        self.record(self.claim(self.make_changed()))
        config = updates._helper().OWNERS["jeremy"]
        with patch.dict(config, link_id="replacement-connection-same-mailbox"):
            item = group(updates.draft_status(self.ledger, self.now + timedelta(hours=2)))
            self.assertIsNone(item["draft_action"])
            self.assertIsNone(item["migration_required"])


if __name__ == "__main__":
    unittest.main()
