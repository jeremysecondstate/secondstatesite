"""Offline checks for pagination, receipt safety and uncertain-write recovery."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import requests

from calendar_reconciliation import apply_plan, fetch_snapshot, reviewed_plan


def response(payload, status=200):
    return SimpleNamespace(status_code=status, json=lambda: payload)


def row(identity):
    return {"id": identity, "source": "Invaluable", "source_lot_id": f"lot-{identity}",
            "current_bid": "120.50", "bid_count": 3, "fingerprint": "a" * 64,
            "staff_private": "DO_NOT_SAVE"}


class CalendarReconciliationCLITests(unittest.TestCase):
    def plan(self, folder):
        payload = {"version": 1, "operation": "test-run", "reviewed": True,
                   "pairs": [{"keep_id": 1, "remove_id": 2, "keep_fingerprint": "a" * 64,
                              "remove_fingerprint": "b" * 64, "reason": "Verified sale and catalogue lot."}]}
        path = folder / "plan.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return reviewed_plan(path)

    def test_snapshot_pages_preserve_bids_and_strip_unrelated_private_data(self):
        session = Mock()
        session.get.side_effect = [
            response({"ok": True, "version": 1, "lots": [row(1)], "next_cursor": "1", "account": "PRIVATE"}),
            response({"ok": True, "version": 1, "lots": [row(2)], "next_cursor": None}),
        ]
        result = fetch_snapshot("https://calendar.example/calendar/reconciliation/", {"X-API-KEY": "PRIVATE_KEY"}, {}, session=session)
        self.assertEqual(result["lot_count"], 2)
        self.assertEqual(result["lots"][0]["current_bid"], "120.50")
        self.assertNotIn("PRIVATE", json.dumps(result))
        self.assertNotIn("DO_NOT_SAVE", json.dumps(result))
        self.assertEqual(session.get.call_args_list[1].kwargs["params"]["cursor"], "1")
        self.assertFalse(session.get.call_args.kwargs["allow_redirects"])

    def test_bad_pagination_cannot_be_presented_as_complete(self):
        session = Mock()
        session.get.return_value = response({"ok": True, "version": 1, "lots": [row(1)], "next_cursor": "0"})
        with self.assertRaisesRegex(ValueError, "non-advancing"):
            fetch_snapshot("https://calendar.example", {}, {}, session=session)

    def test_existing_receipt_prevents_any_post(self):
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            plan, digest = self.plan(folder)
            receipt = folder / "receipt.json"
            receipt.write_text("ORIGINAL", encoding="utf-8")
            session = Mock()
            with self.assertRaises(FileExistsError):
                apply_plan("https://calendar.example", {}, plan, digest, receipt, session=session)
            session.post.assert_not_called()
            self.assertEqual(receipt.read_text(encoding="utf-8"), "ORIGINAL")

    def test_transport_failure_saves_operation_without_retry_or_secrets(self):
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            plan, digest = self.plan(folder)
            receipt = folder / "attempt.json"
            session = Mock()
            session.post.side_effect = requests.Timeout("PRIVATE_TRANSPORT_DETAIL")
            with self.assertRaisesRegex(RuntimeError, "unknown"):
                apply_plan("https://calendar.example", {"X-API-KEY": "PRIVATE_KEY"}, plan, digest, receipt, session=session)
            session.post.assert_called_once()
            saved = receipt.read_text(encoding="utf-8")
            self.assertNotIn("PRIVATE", saved)
            self.assertEqual(json.loads(saved)["operation"], "test-run")
            self.assertEqual(json.loads(saved)["outcome"], "unknown")

    def test_success_receipt_preserves_rollback_format(self):
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            plan, digest = self.plan(folder)
            receipt = folder / "receipt.json"
            expected = {"format": "secondstate-calendar-duplicate-receipt-v1", "operation": "test-run",
                        "request_hash": digest, "changes": [{"remove_id": 2, "keep_id": 1, "active_before": True}]}
            session = Mock()
            session.post.return_value = response({"ok": True, "receipt": expected, "replayed": True})
            result = apply_plan("https://calendar.example", {}, plan, digest, receipt, session=session)
            self.assertEqual(result["format"], expected["format"])
            self.assertEqual(result["changes"], expected["changes"])
            self.assertTrue(result["attempt"]["replayed"])
            self.assertEqual(json.loads(receipt.read_text(encoding="utf-8")), result)

    def test_conflict_is_saved_as_rejected_without_retry(self):
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            plan, digest = self.plan(folder)
            receipt = folder / "attempt.json"
            session = Mock()
            session.post.return_value = response({"ok": False, "error": "Lot changed since review."}, 409)
            with self.assertRaisesRegex(RuntimeError, "rejected"):
                apply_plan("https://calendar.example", {}, plan, digest, receipt, session=session)
            self.assertEqual(json.loads(receipt.read_text(encoding="utf-8"))["outcome"], "rejected")
            session.post.assert_called_once()


if __name__ == "__main__":
    unittest.main()
