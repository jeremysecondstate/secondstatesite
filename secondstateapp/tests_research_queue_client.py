"""Actual desktop client and Django endpoint contracts, entirely offline.

Only urllib's transport is replaced. Requests still pass through WorkerAPI's
serialization/authentication, Django middleware/views, durable models, and the
real manual ownership/audit code. Codex histories and receipts are temporary
synthetic fixtures; no provider research or financial saves occur.
"""
import io
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from unittest.mock import patch

from django.test import Client, TestCase

from scripts import liveart_research_queue as worker
from scripts import liveart_run_lifecycle as lifecycle
from scripts import test_liveart_research_queue as client_fixtures

from .models import AuctionBidBoardAnalysis, AuctionWatchLot, LiveArtResaleAnalysis
from .research_queue import select_lot
from .research_queue_models import ResearchQueueItem, ResearchQueueOperation, ResearchQueueRun


class DjangoWorkerTransport:
    """An urllib opener that can lose a response after Django saved the write."""

    def __init__(self):
        self.client = Client(enforce_csrf_checks=True)
        self.calls = []
        self.fail_after = None

    def open(self, request, timeout):
        parsed = urlsplit(request.full_url)
        if parsed.scheme != "https" or parsed.netloc != "testserver" or parsed.path != "/calendar/research-queue/worker/":
            raise AssertionError("Integration transport must never leave the offline worker route")
        if timeout != 30:
            raise AssertionError("WorkerAPI's bounded HTTP timeout changed")
        headers = {name.lower(): value for name, value in request.header_items()}
        payload = json.loads(request.data) if request.data else {}
        action = payload.get("action", "status")
        self.calls.append((action, payload))
        target = parsed.path + ("?" + parsed.query if parsed.query else "")
        response = self.client.generic(
            request.get_method(), target, data=request.data or b"",
            content_type=headers.get("content-type", "application/json"), secure=True,
            HTTP_X_API_KEY=headers.get("x-api-key", ""), HTTP_ACCEPT=headers.get("accept", ""),
        )
        if response.status_code >= 400:
            raise HTTPError(request.full_url, response.status_code, "Offline Django endpoint rejected request", response.headers, io.BytesIO(response.content))
        if self.fail_after == action:
            self.fail_after = None
            raise URLError("Synthetic lost response after the endpoint committed")
        return io.BytesIO(response.content)


class DesktopQueueEndpointTests(TestCase):
    def setUp(self):
        # Reuse the worker's current synthetic history/projection fixture and
        # human-message builder, without replacing its API with the FakeAPI.
        self.fixture = client_fixtures.ManualQueueTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.config = self.fixture.config
        self.transport = DjangoWorkerTransport()
        opener = patch.object(worker, "build_opener", return_value=self.transport)
        opener.start()
        self.addCleanup(opener.stop)
        auth = patch.dict("os.environ", {"CATALOG_API_KEY": "offline-existing-catalog-key"})
        auth.start()
        self.addCleanup(auth.stop)
        self.no_process = patch.object(lifecycle.subprocess, "run", side_effect=AssertionError("Manual integration must not launch or archive a chat"))
        self.no_process.start()
        self.addCleanup(self.no_process.stop)
        self.api = worker.WorkerAPI("https://testserver", "offline-existing-catalog-key")
        self.receipts = {}

    def selected_lots(self, count):
        lots = [AuctionWatchLot.objects.create(source="offline-client-test", source_lot_id=str(index), artist="Synthetic artist", title=f"Synthetic work {index}") for index in range(count)]
        for lot in lots:
            select_lot(lot.pk, True)
        return lots

    def complete_next(self, ident, *, disposition="triaged", journal_operation=False):
        claim = worker.coordinate(self.config, self.api, ident, "claim")
        item = claim["item"]
        self.assertIsNotNone(item)
        path = self.fixture.f.folder / f"lot-{item['lot_id']}-receipt.json"
        source_proof = {"source": "offline synthetic listing fixture", "receipt_path": str(path)}
        reason = "Synthetic original-listing review places this work outside the current acquisition scope."
        operation = None
        if journal_operation:
            intent = worker.coordinate(self.config, self.api, ident, "intent", {
                "item_id": item["id"], "kind": "other",
                "details": {"local_fixture_review": True, "lot_id": item["lot_id"]},
            })
            self.assertTrue(intent["operation_execution_allowed"])
            operation = intent["operation"]["operation_id"]
        receipt = {"run_id": claim["run"]["id"], "item_id": item["id"], "lot_id": item["lot_id"],
                   "disposition": disposition, "reason": reason, "source_proof": source_proof,
                   "operation_id": operation, "units_spent": "0.00", "synthetic": True}
        path.write_text(json.dumps(receipt), encoding="utf-8")
        if operation:
            settled = worker.coordinate(self.config, self.api, ident, "settle", {
                "item_id": item["id"], "operation_id": operation,
                "units_spent": "0.00", "result": {"local_fixture_review": "recorded", "receipt_path": str(path)},
            })
            self.assertEqual(settled["operation"]["status"], "settled")
        outcome = worker.coordinate(self.config, self.api, ident, "outcome", {
            "item_id": item["id"], "disposition": disposition, "reason": reason, "source_proof": source_proof,
        })
        self.assertEqual(next(row for row in outcome["run"]["items"] if row["id"] == item["id"])["disposition"], disposition)
        self.receipts[str(item["lot_id"])] = str(path)
        return item

    def audit(self, ident, **changes):
        run = worker.pointer(self.config)["current"]["run"]
        value = {"schema_version": 1, "thread_id": ident, "run_id": run["id"],
                 "lot_ids": [row["lot_id"] for row in run["items"]],
                 "completed": [row["lot_id"] for row in run["items"] if row["status"] == "done"],
                 "pending": [row["lot_id"] for row in run["items"] if row["status"] == "needs_attention"],
                 "bookkeeping_complete": True, "usage_accounted": True,
                 "operations_settled": True, "cleanup_complete": True,
                 "lot_receipts": {str(row["lot_id"]): self.receipts[str(row["lot_id"])] for row in run["items"]}}
        value.update(changes)
        path = self.fixture.f.folder / f"queue-{ident}-audit.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def assert_no_financial_research(self):
        self.assertEqual(LiveArtResaleAnalysis.objects.count(), 0)
        self.assertEqual(AuctionBidBoardAnalysis.objects.count(), 0)

    def test_actual_client_processes_more_than_three_once_and_defers_late_selection(self):
        lots = self.selected_lots(5)
        ident, _ = self.fixture.human()
        started = worker.start(self.config, self.api, ident)
        self.assertEqual([row["lot_id"] for row in started["run"]["items"]], [lot.pk for lot in lots])
        self.assertNotIn("owner_token", started["run"])
        late = AuctionWatchLot.objects.create(source="offline-client-test", source_lot_id="late", title="Selected after snapshot")
        select_lot(late.pk, True)
        replay = worker.start(self.config, self.api, ident)
        self.assertEqual(replay["run"]["id"], started["run"]["id"])
        processed = [self.complete_next(ident, disposition="triaged" if index % 2 else "skipped", journal_operation=True)["lot_id"] for index in range(5)]
        self.assertEqual(processed, [lot.pk for lot in lots])
        self.assertIsNone(worker.coordinate(self.config, self.api, ident, "claim")["item_id"])
        refused = worker.coordinate(self.config, self.api, ident, "finish", audit_path=self.audit(ident, usage_accounted=False))
        self.assertEqual(refused["status"], "completion_pending")
        self.assertFalse(any(action == "finish" for action, _ in self.transport.calls))
        audit = self.audit(ident)
        finished = worker.coordinate(self.config, self.api, ident, "finish", audit_path=audit)
        self.assertEqual(finished["run"]["status"], "completed")
        self.assertEqual(finished["lifecycle"]["status"], "finished")
        saved_run = ResearchQueueRun.objects.get(pk=started["run"]["id"])
        self.assertEqual(saved_run.completion_audit, json.loads(audit.read_text(encoding="utf-8")))
        self.assertEqual(ResearchQueueOperation.objects.filter(settled_at__isnull=False).count(), 5)
        self.assertEqual(ResearchQueueItem.objects.get(lot=late).status, "queued")
        self.assertTrue(worker.pointer(self.config)["current"]["finished"])
        self.assertEqual(worker.start(self.config, self.api, ident)["status"], "already_finished")
        self.fixture.f.set_turn(ident, "completed")
        self.fixture.human(ident)
        next_run = worker.start(self.config, self.api, ident)
        self.assertEqual([row["lot_id"] for row in next_run["run"]["items"]], [late.pk])
        self.complete_next(ident, disposition="skipped")
        self.assertEqual(worker.coordinate(self.config, self.api, ident, "finish", audit_path=self.audit(ident))["lifecycle"]["status"], "finished")
        self.assertEqual(ResearchQueueRun.objects.count(), 2)
        self.assert_no_financial_research()

    def test_lost_start_and_finish_reconcile_completed_real_run_without_new_work_or_handoff(self):
        lots = self.selected_lots(2)
        prior, _ = self.fixture.human()
        self.transport.fail_after = "start"
        with self.assertRaises(worker.QueueError):
            worker.start(self.config, self.api, prior)
        saved_request = worker.pointer(self.config)["current"]["request_id"]
        self.assertEqual(ResearchQueueRun.objects.count(), 1)
        late = AuctionWatchLot.objects.create(source="offline-client-test", source_lot_id="lost-start-late")
        select_lot(late.pk, True)
        recovered = worker.start(self.config, self.api, prior)
        self.assertEqual(recovered["run"]["request_id"], saved_request)
        self.assertEqual([row["lot_id"] for row in recovered["run"]["items"]], [lot.pk for lot in lots])
        self.complete_next(prior, disposition="triaged")
        self.complete_next(prior, disposition="skipped")
        self.transport.fail_after = "finish"
        with self.assertRaises(worker.QueueError):
            worker.coordinate(self.config, self.api, prior, "finish", audit_path=self.audit(prior))
        persisted = ResearchQueueRun.objects.get(pk=recovered["run"]["id"])
        self.assertEqual(persisted.status, "completed")
        self.assertFalse(worker.pointer(self.config)["current"].get("finished", False))
        self.fixture.f.set_turn(prior, "completed")
        current, _ = self.fixture.human()
        pending = worker.resume(self.config, self.api, current)
        self.assertEqual(pending["status"], "completion_pending")
        self.assertFalse(pending["work_allowed"])
        reconciled = worker.resume(self.config, self.api, current, audit_path=self.audit(current))
        self.assertEqual(reconciled["status"], "completed_reconciled")
        self.assertEqual(reconciled["lifecycle"]["status"], "finished")
        self.assertFalse(reconciled["work_allowed"])
        self.assertFalse(any(action == "handoff" for action, _ in self.transport.calls))
        self.assertEqual(sum(action == "claim" for action, _ in self.transport.calls), 2)
        self.assertEqual(sum(action == "finish" for action, _ in self.transport.calls), 1)
        self.assertEqual(ResearchQueueRun.objects.count(), 1)
        self.assertEqual(ResearchQueueItem.objects.get(lot=late).status, "queued")
        persisted.refresh_from_db()
        self.assertEqual(persisted.thread_id, prior)
        self.assertEqual(persisted.completion_audit["thread_id"], prior)
        self.assertTrue(worker.pointer(self.config)["current"]["finished"])
        self.assert_no_financial_research()
