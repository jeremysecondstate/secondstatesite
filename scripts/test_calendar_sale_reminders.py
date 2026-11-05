"""Focused planner/ledger tests; no real mail or network requests."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import json
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from scripts import calendar_sale_reminders as reminders


def row(identifier="1", **changes):
    result = {"source": "invaluable", "source_lot_id": identifier,
              "lot_url": "https://example.com/lot/" + identifier,
              "auction_house": "Doyle", "sale_title": "Prints & Multiples",
              "sale_url": "https://example.com/sale/one", "end_at": "2026-11-05T18:00:00+00:00",
              "start_at": "", "status": "unchanged", "sold_price": None}
    result.update(changes)
    return result


def now(value="2026-11-04T09:00:00-08:00"):
    return datetime.fromisoformat(value)


def page(rows, cursor=None):
    return {"ok": True, "version": 1, "lots": rows, "next_cursor": cursor,
            "calendar_lot_keys": [item["source"] + ":" + item["source_lot_id"] for item in rows]}


class Response:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class Session:
    def __init__(self, *pages):
        self.pages = iter(pages)
        self.calls = []

    def get(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return Response(next(self.pages))


class ScheduleTests(unittest.TestCase):
    def test_all_fifteen_slots_for_each_owner(self):
        for owner, config in reminders.OWNERS.items():
            zone = ZoneInfo(config["zone"])
            for lead, times in reminders.SCHEDULE.items():
                for label in times:
                    moment = datetime.fromisoformat("2026-11-04T" + label).replace(tzinfo=zone)
                    selected = reminders.due_slots(owner, moment)
                    self.assertEqual(len(selected), 1)
                    self.assertIn(lead, selected[0][1])
        self.assertEqual(sum(map(len, reminders.SCHEDULE.values())), 15)

    def test_no_early_or_stale_slot(self):
        self.assertEqual(reminders.due_slots("jeremy", now("2026-11-04T08:59:59-08:00")), [])
        late = reminders.due_slots("jeremy", now("2026-11-04T09:59:59-08:00"))
        self.assertEqual(late[0][0].hour, 9)
        self.assertEqual(late[0][1], {1, 3})
        next_hour = reminders.due_slots("jeremy", now("2026-11-04T10:00:00-08:00"))
        self.assertEqual(next_hour[0][0].hour, 10)
        self.assertEqual(next_hour[0][1], {5})

    def test_dst_uses_wall_clock_in_both_seasons(self):
        for day, utc_hour in (("2026-07-01", 16), ("2026-12-01", 17)):
            slot, _ = reminders.due_slots("jeremy", now(f"{day}T{utc_hour}:00:00+00:00"))[0]
            self.assertEqual(slot.hour, 9)
        for day, utc_hour in (("2026-07-01", 13), ("2026-12-01", 14)):
            slot, _ = reminders.due_slots("oliver", now(f"{day}T{utc_hour}:00:00+00:00"))[0]
            self.assertEqual(slot.hour, 9)

    def test_no_sales_still_sends_each_due_category(self):
        plan = reminders.make_plan([], now())
        self.assertEqual(len(plan["messages"]), 4)
        self.assertEqual({(m["owner"], m["days_away"]) for m in plan["messages"]},
                         {("jeremy", 1), ("jeremy", 3), ("oliver", 1), ("oliver", 4)})
        for message in plan["messages"]:
            self.assertEqual(message["sales"], [])
            self.assertEqual(message["lead_status"][0]["state"], "no_sales")
            self.assertTrue(message["gmail"]["subject"].endswith(" · No sales"))
            self.assertIn(f"in {message['days_away']} days ({message['sale_date']})",
                          message["gmail"]["payload"]["body"]["content"])

    def test_no_scheduled_category_no_email(self):
        self.assertEqual(reminders.make_plan([], now("2026-11-04T02:00:00-08:00"))["messages"], [])

    def test_owner_subset_and_addresses(self):
        lots = [row(), row("2", auction_house="Forum Auctions", sale_url="https://example.com/two")]
        plan = reminders.make_plan(lots, now())
        streams = {item["owner"]: item for item in plan["messages"] if item["days_away"] == 1}
        self.assertEqual(set(streams), {"jeremy", "oliver"})
        self.assertEqual(len(streams["jeremy"]["sales"]), 2)
        self.assertEqual(len(streams["oliver"]["sales"]), 1)
        self.assertEqual(streams["jeremy"]["gmail"]["from_address"], "sales@secondstate.art")
        self.assertEqual(streams["jeremy"]["gmail"]["to"], "jeremy@secondstate.art, alex@secondstate.art")
        self.assertEqual(streams["oliver"]["gmail"]["from_address"], "sales@secondstate.art")
        self.assertEqual(streams["jeremy"]["gmail"]["link_id"], streams["oliver"]["gmail"]["link_id"])
        self.assertEqual(streams["oliver"]["gmail"]["to"],
                         "oliver@secondstate.art, alex@secondstate.art, OliverGDonson@gmail.com, oliver1@vt.edu")
        self.assertIn("view=oliver", streams["oliver"]["sales"][0]["catalog_links"][0])

    def test_midnight_dates_use_owner_zone_and_pacific_catalog_day(self):
        # 11 PM Pacific November 5 is 2 AM Eastern November 6.
        lot = row(end_at="2026-11-06T07:00:00Z")
        pacific = reminders.event_details(lot, ZoneInfo("America/Los_Angeles"))
        eastern = reminders.event_details(lot, ZoneInfo("America/New_York"))
        self.assertEqual(str(pacific[0]), "2026-11-05")
        self.assertEqual(str(eastern[0]), "2026-11-06")
        self.assertEqual(str(eastern[2]), "2026-11-05")

    def test_date_only_preserved(self):
        lot = row(end_at="2026-11-05")
        for zone in ("America/Los_Angeles", "America/New_York"):
            details = reminders.event_details(lot, ZoneInfo(zone))
            self.assertEqual(str(details[0]), "2026-11-05")
            self.assertIn("Time TBA", details[1])

    def test_ended_sold_and_ambiguous_excluded(self):
        plan = reminders.make_plan([row(status="ended"), row("2", sold_price=100),
                                    row("3", end_at="2026-11-05T10:00:00")], now())
        self.assertEqual(len(plan["messages"]), 4)
        for message in plan["messages"]:
            self.assertEqual(message["sales"], [])
            self.assertEqual(message["lead_status"][0]["state"], "dates_unavailable")
            self.assertIn("cannot be confirmed", message["gmail"]["payload"]["body"]["content"])
            self.assertNotIn("No sales on", message["gmail"]["payload"]["body"]["content"])
        self.assertEqual(plan["ambiguous_date_counts"], {"jeremy": 1, "oliver": 1})

    def test_keeps_lead_categories_in_separate_owner_messages(self):
        moment = now("2026-11-04T18:00:00-08:00")
        lots = [row(str(lead), end_at=f"2026-11-{4 + lead:02}", sale_url=f"https://example.com/{lead}")
                for lead in range(1, 6)]
        plan = reminders.make_plan(lots, moment)
        self.assertEqual(len(plan["messages"]), 4)
        self.assertEqual({message["days_away"] for message in plan["messages"]}, {1, 2, 3, 4})
        for message in plan["messages"]:
            self.assertEqual(message["owner"], "jeremy")
            self.assertEqual(len(message["sales"]), 1)
            self.assertEqual(message["sales"][0]["days_away"], message["days_away"])

    def test_rejects_mixed_categories(self):
        with self.assertRaises(ValueError):
            reminders.compose("jeremy", now(), {1, 3}, [])

    def test_missing_sale_url_preserves_distinct_closing_times(self):
        lots = [row(sale_url=""), row("2", sale_url="", end_at="2026-11-05T19:00:00Z")]
        message, _ = reminders.compose("jeremy", now(), {1}, lots)
        self.assertEqual(len(message["sales"]), 2)
        self.assertIn('href="https://example.com/lot/1"', message["gmail"]["payload"]["body"]["content"])

    def test_external_html_and_invalid_link_are_not_executed(self):
        message, _ = reminders.compose("jeremy", now(), {1}, [row(sale_title="<script>x</script>",
                                                                   sale_url="javascript:alert(1)")])
        html = message["gmail"]["payload"]["body"]["content"]
        self.assertNotIn("<script>", html)
        self.assertNotIn("javascript:", html)
        self.assertIn("&lt;script&gt;", html)


class FetchTests(unittest.TestCase):
    def fetch(self, session):
        with patch.dict(os.environ, {"CATALOG_API_KEY": "test-only"}):
            return reminders.fetch_lots(session)

    def test_paginates_and_accepts_valid_forum_urls(self):
        session = Session(page([row()], "4"), page([row("2", source="forum", lot_url="https://www.forumauctions.co.uk/lot/2")]))
        lots, source = self.fetch(session)
        self.assertEqual(len(lots), 2)
        self.assertEqual(source["page_counts"], [1, 1])
        self.assertEqual(session.calls[1][1]["params"]["cursor"], "4")
        self.assertFalse(session.calls[0][1]["allow_redirects"])

    def test_rejects_duplicate_or_broken_pagination(self):
        for session in (Session(page([row()], "4"), page([row()])),
                        Session(page([row()], "0")),
                        Session(page([row()], "4"), page([row("2")], "4"))):
            with self.assertRaises(ValueError):
                self.fetch(session)

    def test_rejects_missing_inventory_or_partial_response(self):
        invalid = page([row()])
        invalid["calendar_lot_keys"] = []
        with self.assertRaises(ValueError):
            self.fetch(Session(invalid))
        with self.assertRaises(ValueError):
            self.fetch(Session(page([row()], "4"), {"ok": False}))

    def test_preserves_meaningful_fields_for_update_tracking(self):
        enriched = row(artist="Artist", artist_watchlist_name="Canonical Artist", title="A print",
                       lot_number="10A", estimate_low=100, estimate_high=200, current_bid=120,
                       bid_count=2, currency="USD", sold_currency="USD", medium="Etching")
        result, _ = self.fetch(Session(page([enriched])))
        for field in ("artist", "title", "lot_number", "estimate_low", "estimate_high", "current_bid",
                      "bid_count", "currency", "artist_watchlist_name", "sold_currency", "medium"):
            self.assertEqual(result[0][field], enriched[field])


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "deliveries.sqlite3"
        self.message, _ = reminders.compose("jeremy", now(), {1}, [row()])

    def tearDown(self):
        self.directory.cleanup()

    def test_atomic_claim_only_one_wins(self):
        initial = reminders.connect(self.path)
        initial.close()
        def attempt(_):
            db = reminders.connect(self.path)
            try:
                return reminders.claim(db, self.message, now())
            finally:
                db.close()
        with ThreadPoolExecutor(max_workers=4) as workers:
            self.assertEqual(sum(workers.map(attempt, range(8))), 1)

    def test_changed_content_does_not_resend_and_snapshot_is_immutable(self):
        db = reminders.connect(self.path)
        try:
            self.assertTrue(reminders.claim(db, self.message, now()))
            changed = json.loads(json.dumps(self.message))
            changed["gmail"]["payload"]["body"]["content"] = "new body"
            self.assertFalse(reminders.claim(db, changed, now()))
            stored = json.loads(db.execute("SELECT payload FROM deliveries").fetchone()[0])
            self.assertEqual(stored, self.message)
            reminders.mark(db, self.message["key"], "sent", message_id="gmail-123")
        finally:
            db.close()
        reopened = reminders.connect(self.path)
        try:
            self.assertFalse(reminders.claim(reopened, changed, now()))
            self.assertEqual(reopened.execute("SELECT message_id FROM deliveries").fetchone()[0], "gmail-123")
        finally:
            reopened.close()

    def test_unknown_stays_reserved_and_can_be_reconciled(self):
        db = reminders.connect(self.path)
        try:
            reminders.claim(db, self.message, now())
            reminders.mark(db, self.message["key"], "unknown", reason="timeout")
            self.assertFalse(reminders.claim(db, self.message, now()))
            reminders.mark(db, self.message["key"], "sent", message_id="verified-sent-message")
            self.assertEqual(db.execute("SELECT state FROM deliveries").fetchone()[0], "sent")
        finally:
            db.close()

    def test_claim_rejects_wrong_recipients_early_and_late(self):
        db = reminders.connect(self.path)
        try:
            for moment in (now() - timedelta(seconds=1), now() + timedelta(hours=1)):
                with self.assertRaises(ValueError):
                    reminders.claim(db, self.message, moment)
            self.message["gmail"]["to"] = "jeremy@secondstate.art, oliver@secondstate.art, alex@secondstate.art"
            with self.assertRaisesRegex(ValueError, "recipients"):
                reminders.claim(db, self.message, now())
            self.assertEqual(db.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0], 0)
        finally:
            db.close()

    def test_two_categories_claim_independently_within_hour(self):
        other, _ = reminders.compose("jeremy", now(), {3}, [])
        db = reminders.connect(self.path)
        try:
            self.assertTrue(reminders.claim(db, self.message, now() + timedelta(minutes=59, seconds=59)))
            self.assertTrue(reminders.claim(db, other, now() + timedelta(minutes=59, seconds=59)))
            self.assertFalse(reminders.claim(db, self.message, now() + timedelta(minutes=59, seconds=59)))
            self.assertEqual(db.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0], 2)
        finally:
            db.close()

    def test_claim_rejects_previous_owner_sender(self):
        db = reminders.connect(self.path)
        try:
            for owner in reminders.OWNERS:
                slot = now().astimezone(ZoneInfo(reminders.OWNERS[owner]["zone"]))
                message, _ = reminders.compose(owner, slot, {1}, [])
                message["gmail"]["from_address"] = owner + "@secondstate.art"
                with self.assertRaisesRegex(ValueError, "sender"):
                    reminders.claim(db, message, now())
            self.assertEqual(db.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0], 0)
        finally:
            db.close()

    def test_sender_switch_preserves_completed_key_and_payload(self):
        db = reminders.connect(self.path)
        try:
            config = reminders.OWNERS["jeremy"]
            with patch.dict(config, {"from_address": "jeremy@secondstate.art", "link_id": "old-account"}):
                old_message, _ = reminders.compose("jeremy", now(), {1}, [row()])
                self.assertTrue(reminders.claim(db, old_message, now()))
                reminders.mark(db, old_message["key"], "sent", message_id="old-confirmed-id")
            fresh, _ = reminders.compose("jeremy", now(), {1}, [row()])
            self.assertEqual(fresh["gmail"]["from_address"], "sales@secondstate.art")
            self.assertFalse(reminders.claim(db, fresh, now()))
            stored = db.execute("SELECT payload,message_id FROM deliveries").fetchone()
            self.assertEqual(json.loads(stored["payload"]), old_message)
            self.assertEqual(stored["message_id"], "old-confirmed-id")
        finally:
            db.close()

    def test_repeated_subject_uses_distinct_body_references_and_claims(self):
        noon = now("2026-11-04T12:00:00-08:00")
        later, _ = reminders.compose("jeremy", noon, {1}, [row()])
        self.assertNotEqual(self.message["reference"], later["reference"])
        db = reminders.connect(self.path)
        try:
            for message, moment in ((self.message, now()), (later, noon)):
                self.assertEqual(message["gmail"]["subject"], "🟥 1-DAY REMINDER · Jeremy · Nov 5, 2026")
                self.assertIn("Reference: " + message["reference"], message["gmail"]["payload"]["body"]["content"])
                self.assertTrue(reminders.claim(db, message, moment))
                self.assertFalse(reminders.claim(db, message, moment))
        finally:
            db.close()

    def test_claim_rejects_old_tagged_plan_before_reserving(self):
        self.message["gmail"]["subject"] += f" [{self.message['reference']}]"
        db = reminders.connect(self.path)
        try:
            with self.assertRaisesRegex(ValueError, "fresh plan"):
                reminders.claim(db, self.message, now())
            self.assertEqual(db.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0], 0)
        finally:
            db.close()


class PlanIntegrationTests(unittest.TestCase):
    def test_cli_claim_show_and_status_are_safe_on_windows_cp1252_stdout(self):
        fixed_now = now()

        class FrozenDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed_now.astimezone(tz) if tz else fixed_now.replace(tzinfo=None)

        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "ledger.sqlite3"
            plan_path = Path(directory) / "plan.json"
            message, _ = reminders.compose("jeremy", fixed_now, {1}, [])
            plan_path.write_text(json.dumps({"version": 1, "preview_only": False,
                                             "messages": [message]}, ensure_ascii=False), encoding="utf-8")

            def call(*args):
                raw = io.BytesIO()
                with io.TextIOWrapper(raw, encoding="cp1252", errors="strict", write_through=True) as output:
                    with patch.object(reminders, "datetime", FrozenDatetime), patch("sys.stdout", output):
                        code = reminders.main(["--ledger", str(ledger), *args])
                    captured = raw.getvalue().decode("ascii")
                self.assertEqual(code, 0)
                return json.loads(captured)

            claimed = call("claim", "--plan", str(plan_path), "--key", message["key"])
            self.assertTrue(claimed["claimed"])
            self.assertIn("🟥", claimed["gmail"]["subject"])
            stored = call("show", "--key", message["key"])
            self.assertEqual(stored["payload"]["gmail"]["subject"], message["gmail"]["subject"])
            call("unknown", "--key", message["key"], "--reason", "Uncertain 🟥 delivery")
            status = call("status")
            self.assertEqual(status[0]["reason"], "Uncertain 🟥 delivery")

    def test_preview_does_not_mutate_update_tracking(self):
        tracker = Mock(return_value={"change_count": 0})
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "preview.json"
            with patch.object(reminders, "fetch_lots", return_value=([], {"lot_count": 0})), \
                 patch.dict("sys.modules", {"scripts.calendar_reminder_updates": SimpleNamespace(scan_updates=tracker)}), \
                 patch("builtins.print"):
                code = reminders.main(["plan", "--at", now().isoformat(), "--output", str(output)])
            self.assertEqual(code, 0)
            tracker.assert_not_called()
            self.assertTrue(json.loads(output.read_text())["updates"]["tracking_unchanged"])

    def test_normal_plan_scans_updates_even_when_no_email_is_due(self):
        tracker = Mock(return_value={"change_count": 0})
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "plan.json"
            ledger = Path(directory) / "ledger.sqlite3"
            with patch.object(reminders, "fetch_lots", return_value=([], {"lot_count": 0})), \
                 patch.object(reminders, "make_plan", return_value={"messages": [], "ambiguous_date_counts": {}}), \
                 patch.dict("sys.modules", {"scripts.calendar_reminder_updates": SimpleNamespace(scan_updates=tracker)}), \
                 patch("builtins.print"):
                code = reminders.main(["--ledger", str(ledger), "plan", "--output", str(output)])
            self.assertEqual(code, 0)
            tracker.assert_called_once()
            self.assertEqual(tracker.call_args.args[2], ledger)
            self.assertEqual(json.loads(output.read_text())["updates"], {"change_count": 0})

    def test_fetch_failure_never_produces_no_sales_plan(self):
        tracker = Mock()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "failed.json"
            with patch.object(reminders, "fetch_lots", side_effect=ValueError("fetch failed")), \
                 patch.dict("sys.modules", {"scripts.calendar_reminder_updates": SimpleNamespace(scan_updates=tracker)}), \
                 patch("builtins.print"):
                code = reminders.main(["plan", "--output", str(output)])
            self.assertEqual(code, 1)
            tracker.assert_not_called()
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
