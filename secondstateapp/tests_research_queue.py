"""No provider calls: durable selection, finite snapshots, and recovery safety."""
import copy
import json
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db.models.deletion import ProtectedError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .models import AuctionBidBoardAnalysis, AuctionEmailBatch, AuctionEmailBatchItem, AuctionWatchLot, LiveArtResaleAnalysis
from .research_queue import QueueError, change_item, get_run, run_json, select_lot, selected_queue_state, worker_action
from .research_queue_models import ResearchQueueItem, ResearchQueueOperation, ResearchQueueRun


class ResearchQueueTests(TestCase):
    def setUp(self):
        self.lots = [AuctionWatchLot.objects.create(source="test", source_lot_id=str(i), artist="Test artist", title=f"Work {i}") for i in range(4)]
        self.owner = str(uuid.uuid4())
        self.thread = str(uuid.uuid4())

    def start(self, **overrides):
        payload = {"action": "start", "request_id": str(uuid.uuid4()), "owner_token": self.owner, "thread_id": self.thread}
        payload.update(overrides)
        return worker_action(payload)["run"]

    def call(self, run, action, **values):
        if action == "finish" and "audit" not in values:
            values["audit"] = self.audit(run)
        return worker_action({"action": action, "run_id": run["id"], "owner_token": self.owner, **values})

    def audit(self, run):
        current = run_json(get_run(run["id"]))
        return {"schema_version": 1, "run_id": run["id"], "thread_id": current["thread_id"],
                "lot_ids": [item["lot_id"] for item in current["items"]],
                "completed": [item["lot_id"] for item in current["items"] if item["status"] == "done"],
                "pending": [item["lot_id"] for item in current["items"] if item["status"] == "needs_attention"],
                "bookkeeping_complete": True, "usage_accounted": True, "operations_settled": True, "cleanup_complete": True,
                "lot_receipts": {str(item["lot_id"]): f"synthetic-receipts/lot-{item['lot_id']}.json" for item in current["items"]}}

    def claim(self, run):
        return self.call(run, "claim")["item"]

    def finish_item(self, run, item, **overrides):
        payload = {"item_id": item["id"], "disposition": "triaged", "reason": "Original listing establishes this work is outside the current acquisition scope.", "source_proof": {"source": "saved original listing", "finding": "Outside scope"}}
        payload.update(overrides)
        return self.call(run, "outcome", **payload)

    def test_selection_is_shared_durable_deduplicated_and_has_no_link_prerequisites(self):
        item = select_lot(self.lots[0].pk, True)
        select_lot(self.lots[0].pk, True)
        self.assertEqual(ResearchQueueItem.objects.count(), 1)
        self.assertEqual(item.status, "queued")
        self.assertEqual(selected_queue_state(), {self.lots[0].pk: {"status": "queued", "disposition": ""}})
        with self.assertRaises(ProtectedError):
            self.lots[0].delete()

    def test_start_is_idempotent_and_cannot_steal_an_existing_running_pass(self):
        select_lot(self.lots[0].pk, True)
        request = str(uuid.uuid4())
        run = self.start(request_id=request)
        self.assertEqual(self.start(request_id=request)["id"], run["id"])
        with self.assertRaises(QueueError):
            self.start()
        with self.assertRaises(QueueError):
            self.start(request_id=request, owner_token=str(uuid.uuid4()))
        self.assertEqual(ResearchQueueRun.objects.count(), 1)

    def test_reorder_notes_and_late_additions_do_not_mutate_snapshot(self):
        for lot in self.lots[:2]:
            select_lot(lot.pk, True)
        change_item(self.lots[1].pk, {"action": "move", "direction": "up"})
        change_item(self.lots[1].pk, {"action": "note", "note": "Original note"})
        run = self.start()
        self.assertEqual([row["lot_id"] for row in run["items"]], [self.lots[1].pk, self.lots[0].pk])
        change_item(self.lots[1].pk, {"action": "note", "note": "Changed note"})
        change_item(self.lots[0].pk, {"action": "move", "direction": "up"})
        select_lot(self.lots[2].pk, True)
        self.lots[1].title = "Changed title"
        self.lots[1].save()
        refreshed = self.call(run, "claim")["run"]
        self.assertEqual(refreshed["items"][0]["note_snapshot"], "Original note")
        self.assertEqual(refreshed["items"][0]["lot_snapshot"]["title"], "Work 1")
        self.assertEqual(len(refreshed["items"]), 2)

    def test_removing_unclaimed_skips_it_and_claimed_item_keeps_result(self):
        for lot in self.lots[:2]:
            select_lot(lot.pk, True)
        run = self.start()
        item = self.claim(run)
        select_lot(self.lots[0].pk, False)
        select_lot(self.lots[1].pk, False)
        self.finish_item(run, item)
        finished = self.call(run, "finish")["run"]
        self.assertEqual([row["disposition"] for row in finished["items"]], ["triaged", "skipped"])
        self.assertFalse(ResearchQueueItem.objects.filter(selected=True).exists())
        self.assertEqual(ResearchQueueItem.objects.get(lot=self.lots[0]).latest_result["disposition"], "triaged")

    def test_empty_and_completed_selections_do_no_work_until_explicit_requeue(self):
        self.assertEqual(self.start()["items"], [])
        select_lot(self.lots[0].pk, True)
        run = self.start()
        item = self.claim(run)
        self.finish_item(run, item)
        self.call(run, "finish")
        select_lot(self.lots[0].pk, False)
        select_lot(self.lots[0].pk, True)
        self.assertEqual(self.start()["items"], [])
        with self.assertRaises(QueueError):
            change_item(self.lots[0].pk, {"action": "requeue"})
        change_item(self.lots[0].pk, {"action": "requeue", "reason": "Staff requests refreshed research."})
        self.assertEqual(len(self.start()["items"]), 1)

    def test_blocked_lot_does_not_repeat_and_other_snapshot_items_continue(self):
        for lot in self.lots[:2]:
            select_lot(lot.pk, True)
        run = self.start()
        first = self.claim(run)
        block = {"item_id": first["id"], "reason": "Browser authentication challenge", "reopening_condition": "Staff confirms browser session is authenticated"}
        self.call(run, "block", **block)
        self.call(run, "block", **block)
        with self.assertRaises(QueueError):
            self.call(run, "block", **{**block, "reason": "Different reason"})
        second = self.claim(run)
        self.assertEqual(second["lot_id"], self.lots[1].pk)
        self.finish_item(run, second)
        self.call(run, "finish")
        self.assertEqual(self.start()["items"], [])
        self.assertEqual(ResearchQueueItem.objects.get(lot=self.lots[0]).status, "needs_attention")

    def test_unknown_operations_survive_block_and_prevent_unsafe_recovery(self):
        select_lot(self.lots[0].pk, True)
        run = self.start()
        item = self.claim(run)
        operation = str(uuid.uuid4())
        self.call(run, "intent", item_id=item["id"], operation_id=operation, kind="search", details={"query": "Test artist Work 0"})
        self.call(run, "intent", item_id=item["id"], operation_id=operation, kind="search", details={"query": "Test artist Work 0"})
        with self.assertRaises(QueueError):
            self.call(run, "intent", item_id=item["id"], operation_id=str(uuid.uuid4()), kind="search", details={"query": "Another query"})
        with self.assertRaises(QueueError):
            self.finish_item(run, item)
        self.call(run, "block", item_id=item["id"], reason="Lost response", reopening_condition="Reconcile provider receipt before another search")
        with self.assertRaises(QueueError):
            self.call(run, "finish")
        with self.assertRaises(QueueError):
            change_item(self.lots[0].pk, {"action": "requeue", "reason": "Request retry"})
        with self.assertRaises(QueueError):
            self.claim(run)
        with self.assertRaises(QueueError):
            self.call(run, "handoff", expected_owner_token=self.owner, new_owner_token=str(uuid.uuid4()), reason="Prior owner terminal", recovery_checks={"prior_owner_terminal": True, "no_active_descendants": True, "business_operations_clear": True})
        receipt = {"provider_request_id": "test-receipt", "found": False}
        self.call(run, "settle", item_id=item["id"], operation_id=operation, result=receipt, units_spent="1.00")
        self.call(run, "settle", item_id=item["id"], operation_id=operation, result=receipt, units_spent="1.00")
        self.assertEqual(ResearchQueueOperation.objects.count(), 1)
        with self.assertRaises(QueueError):
            self.call(run, "settle", item_id=item["id"], operation_id=operation, result={"different": True}, units_spent="0")
        self.call(run, "finish")
        change_item(self.lots[0].pk, {"action": "requeue", "reason": "Provider receipt reconciled; retry approved."})
        self.assertEqual(len(self.start()["items"]), 1)

    def test_safe_owner_handoff_preserves_claim_and_never_uses_timeout_theft(self):
        select_lot(self.lots[0].pk, True)
        run = self.start()
        item = self.claim(run)
        self.assertEqual(self.claim(run)["id"], item["id"])
        with self.assertRaises(QueueError):
            self.call(run, "claim", owner_token=str(uuid.uuid4()))
        replacement = str(uuid.uuid4())
        handoff = {"expected_owner_token": self.owner, "new_owner_token": replacement, "reason": "Confirmed previous thread finished", "recovery_checks": {"prior_owner_terminal": True, "no_active_descendants": True, "business_operations_clear": True}}
        self.call(run, "handoff", **handoff)
        self.call(run, "handoff", **handoff)
        with self.assertRaises(QueueError):
            self.claim(run)
        self.owner = replacement
        self.assertEqual(self.claim(run)["id"], item["id"])

    def test_researched_requires_checks_and_existing_current_saved_revisions(self):
        select_lot(self.lots[0].pk, True)
        run = self.start()
        item = self.claim(run)
        checks = {key: True for key in ("google_original_researched", "liveart_browser_researched", "evidence_saved_reloaded", "board_saved_reloaded", "costs_verified", "selection_verified", "email_flags_verified")}
        with self.assertRaises(QueueError):
            self.finish_item(run, item, disposition="researched", checks=checks, proof={})
        analysis = LiveArtResaleAnalysis.objects.create(lot=self.lots[0], retrieved_at=timezone.now(), candidates=[{"id": "comp-1", "entry_method": "manual_web"}], selected_ids=["comp-1"])
        board = AuctionBidBoardAnalysis.objects.create(lot=self.lots[0], selected_ids=["comp-1"], evidence_snapshot={"selected_records": analysis.candidates, "source_summary": {}}, analysis={"scenarios": [{"value": 100}]})
        proof = {"liveart_analysis_id": analysis.pk, "liveart_updated_at": analysis.updated_at.isoformat(), "bid_board_analysis_id": board.pk, "bid_board_updated_at": board.updated_at.isoformat()}
        bad = {**proof, "bid_board_updated_at": "old-revision"}
        with self.assertRaises(QueueError):
            self.finish_item(run, item, disposition="researched", checks=checks, proof=bad)
        payload = {"disposition": "researched", "checks": checks, "proof": proof}
        result = self.finish_item(run, item, **payload)["run"]["items"][0]
        self.assertEqual(result["saved_revisions"]["liveart"]["id"], analysis.pk)
        board.analysis = {"changed": True}
        board.save()
        # Idempotent outcome replay returns the originally settled revision.
        replay = self.finish_item(run, item, **payload)["run"]["items"][0]
        self.assertEqual(replay["saved_revisions"]["bid_board"]["analysis"], {"scenarios": [{"value": 100}]})

    def test_email_flag_verification_gap_is_explicit_and_does_not_assert_success(self):
        select_lot(self.lots[0].pk, True)
        run = self.start()
        item = self.claim(run)
        with self.assertRaises(QueueError):
            self.finish_item(run, item, disposition="skipped", source_proof={})
        with self.assertRaises(QueueError):
            self.finish_item(run, item, disposition="valuation_unavailable", reason="")

    def test_valuation_unavailable_requires_saved_proof_but_allows_empty_comps_and_explicit_gap(self):
        select_lot(self.lots[0].pk, True)
        run = self.start()
        item = self.claim(run)
        with self.assertRaises(QueueError):
            self.finish_item(run, item, disposition="valuation_unavailable")
        analysis = LiveArtResaleAnalysis.objects.create(lot=self.lots[0], retrieved_at=timezone.now(), candidates=[], selected_ids=[])
        board = AuctionBidBoardAnalysis.objects.create(lot=self.lots[0], evidence_snapshot={"selected_records": [], "source_summary": {}}, analysis={"valuation_unavailable": True})
        proof = {"liveart_analysis_id": analysis.pk, "liveart_updated_at": analysis.updated_at.isoformat(), "bid_board_analysis_id": board.pk, "bid_board_updated_at": board.updated_at.isoformat(), "verification_gaps": {"email_flags": "Email controls unavailable in the current browser session; no flags changed."}}
        checks = {key: True for key in ("google_original_researched", "liveart_browser_researched", "evidence_saved_reloaded", "board_saved_reloaded", "costs_verified", "selection_verified")}
        checks["email_flags_verified"] = False
        result = self.finish_item(run, item, disposition="valuation_unavailable", reason="No valid sold comparable after original and LiveArt browser research.", checks=checks, proof=proof)["run"]["items"][0]
        self.assertEqual(result["disposition"], "valuation_unavailable")
        self.assertFalse(result["outcome"]["checks"]["email_flags_verified"])
        self.assertIn("bid_board", result["saved_revisions"])

    def test_explicit_stop_preserves_unknown_operations_and_global_start_guard(self):
        for lot in self.lots[:2]:
            select_lot(lot.pk, True)
        run = self.start()
        item = self.claim(run)
        operation = str(uuid.uuid4())
        self.call(run, "intent", item_id=item["id"], operation_id=operation, kind="search", details={"query": "Original query"})
        receipt = {"reason": "User explicitly stopped this pass.", "reopening_condition": "User requests another pass after outstanding search is reconciled.", "source_proof": {"human_stop": "Stop this worker now."}}
        stopped = self.call(run, "stop", **receipt)["run"]
        self.assertEqual(stopped["status"], "blocked")
        self.assertTrue(all(row["status"] == "needs_attention" for row in stopped["items"]))
        self.call(run, "stop", **receipt)
        self.assertIsNone(ResearchQueueOperation.objects.get(pk=operation).settled_at)
        select_lot(self.lots[2].pk, True)
        with self.assertRaises(QueueError):
            self.start()
        with self.assertRaises(QueueError):
            self.call(run, "settle", item_id=item["id"], operation_id=operation, result={"provider_request_id": "confirmed"})
        with self.assertRaises(QueueError):
            self.call(run, "settle", item_id=item["id"], operation_id=operation, result={"provider_request_id": "confirmed"}, units_spent=None)
        settled = self.call(run, "settle", item_id=item["id"], operation_id=operation, result={"provider_request_id": "confirmed", "usage_unknown": True}, units_spent=None)["operation"]
        self.assertIsNone(settled["units_spent"])
        self.assertEqual(settled["status"], "settled")
        self.call(run, "finish")
        self.assertEqual(len(self.start()["items"]), 1)

    def test_requeue_during_existing_pass_cannot_extend_its_frozen_generation(self):
        for lot in self.lots[:2]:
            select_lot(lot.pk, True)
        run = self.start()
        first = self.claim(run)
        with self.assertRaises(QueueError):
            change_item(self.lots[0].pk, {"action": "requeue", "reason": "Cannot duplicate currently claimed work"})
        self.finish_item(run, first)
        item = change_item(self.lots[0].pk, {"action": "requeue", "reason": "Staff requests a fresh comparison after this pass"})
        self.assertEqual(item.generation, 2)
        self.assertEqual(item.requeue_history[0]["previous_status"], "done")
        second = self.claim(run)
        self.assertEqual(second["lot_id"], self.lots[1].pk)
        self.finish_item(run, second)
        # Lost-response replay of generation 1 must never overwrite generation 2.
        self.finish_item(run, first)
        item.refresh_from_db()
        self.assertEqual(item.status, "queued")
        self.assertIsNone(self.claim(run))
        self.call(run, "finish")
        subsequent = self.start()
        self.assertEqual([row["lot_id"] for row in subsequent["items"]], [self.lots[0].pk])
        self.assertEqual(get_run(run["id"]).items.get(pk=first["id"]).queue_generation, 1)
        self.assertEqual(get_run(subsequent["id"]).items.get().queue_generation, 2)

    def test_shared_block_unknown_receipt_survives_restart_and_rejects_new_start(self):
        for lot in self.lots[:2]:
            select_lot(lot.pk, True)
        run = self.start()
        item = self.claim(run)
        operation = str(uuid.uuid4())
        self.call(run, "intent", item_id=item["id"], operation_id=operation, kind="save_board", details={"request_digest": "synthetic-save"})
        self.call(run, "block", item_id=item["id"], reason="Site-wide save response unavailable", reopening_condition="Verify the original save receipt and restore site access", shared_block=True, source_proof={"http_status": 503})
        persisted = run_json(get_run(run["id"]))
        self.assertEqual(persisted["status"], "blocked")
        self.assertEqual(persisted["items"][0]["operations"][0]["status"], "intent")
        select_lot(self.lots[2].pk, True)
        with self.assertRaises(QueueError):
            self.start(owner_token=str(uuid.uuid4()), thread_id=str(uuid.uuid4()))
        self.assertEqual(ResearchQueueRun.objects.count(), 1)
        self.assertEqual(ResearchQueueItem.objects.get(lot=self.lots[2]).status, "queued")
        self.assertIsNone(ResearchQueueOperation.objects.get(pk=operation).settled_at)

    def test_unclaimed_removal_preserves_all_financial_and_email_state(self):
        lot = self.lots[0]
        lot.current_bid, lot.sold_price, lot.currency, lot.won_by_us = "123.00", "456.00", "USD", True
        lot.save()
        LiveArtResaleAnalysis.objects.create(lot=lot, retrieved_at=timezone.now(), candidates=[{"id": "saved-comp", "hammer_usd": "900.00"}], selected_ids=["saved-comp"], assumptions={"target_profit": "100.00"}, scenarios=[{"resale_hammer": "900.00"}], data_units_spent="2.00")
        AuctionBidBoardAnalysis.objects.create(lot=lot, include_in_email=True, assumptions={"starting_hammer": "123.00"}, selected_ids=["saved-comp"], evidence_snapshot={"selected_records": [{"id": "saved-comp"}]}, analysis={"selected_bid": "150.00"})
        batch = AuctionEmailBatch.objects.create()
        AuctionEmailBatchItem.objects.create(batch=batch, lot=lot, lot_snapshot={"saved": "tray selection"})
        tracked = [AuctionWatchLot, LiveArtResaleAnalysis, AuctionBidBoardAnalysis, AuctionEmailBatch, AuctionEmailBatchItem]
        before = {model.__name__: list(model.objects.values()) for model in tracked}
        select_lot(lot.pk, True)
        run = self.start()
        change_item(lot.pk, {"action": "remove"})
        self.assertIsNone(self.claim(run))
        snapshot = run_json(get_run(run["id"]))["items"][0]
        self.assertEqual(snapshot["disposition"], "skipped")
        self.assertIsNone(snapshot["claimed_at"])
        self.assertTrue(snapshot["outcome"]["source_proof"]["staff_queue_removal"])
        audit = self.audit(run)
        audit["lot_receipts"] = {}
        audit["server_receipts"] = {str(lot.pk): {"run_id": run["id"], "item_id": snapshot["id"]}}
        self.call(run, "finish", audit=audit)
        after = {model.__name__: list(model.objects.values()) for model in tracked}
        self.assertEqual(before, after)
        self.assertEqual(ResearchQueueOperation.objects.count(), 0)

    def test_finish_requires_whole_snapshot_audit_and_cannot_fabricate_claimed_receipt(self):
        for lot in self.lots[:2]:
            select_lot(lot.pk, True)
        run = self.start()
        first = self.claim(run)
        self.finish_item(run, first)
        select_lot(self.lots[1].pk, False)
        audit = self.audit(run)
        invalid = [None, {**audit, "lot_ids": [self.lots[0].pk]}, {**audit, "completed": [self.lots[0].pk], "pending": [self.lots[1].pk]}, {**audit, "usage_accounted": False}, {**audit, "thread_id": str(uuid.uuid4())}]
        for candidate in invalid:
            with self.subTest(audit=candidate), self.assertRaises(QueueError):
                self.call(run, "finish", audit=candidate)
        forged = copy.deepcopy(audit)
        forged["lot_receipts"].pop(str(self.lots[0].pk))
        forged["server_receipts"] = {str(self.lots[0].pk): {"run_id": run["id"], "item_id": first["id"]}}
        with self.assertRaises(QueueError):
            self.call(run, "finish", audit=forged)
        self.assertEqual(get_run(run["id"]).status, "running")
        finished = self.call(run, "finish", audit=audit)["run"]
        self.assertEqual(finished["completion_audit"], audit)
        self.call(run, "finish", audit=audit)
        with self.assertRaises(QueueError):
            self.call(run, "finish", audit={**audit, "cleanup_complete": False})

    def test_unavailable_cannot_bypass_required_checks_or_use_old_saved_revision(self):
        select_lot(self.lots[0].pk, True)
        run = self.start()
        item = self.claim(run)
        analysis = LiveArtResaleAnalysis.objects.create(lot=self.lots[0], retrieved_at=timezone.now())
        board = AuctionBidBoardAnalysis.objects.create(lot=self.lots[0], evidence_snapshot={"selected_records": [], "source_summary": {}}, analysis={"valuation_unavailable": True})
        proof = {"liveart_analysis_id": analysis.pk, "liveart_updated_at": analysis.updated_at.isoformat(), "bid_board_analysis_id": board.pk, "bid_board_updated_at": board.updated_at.isoformat()}
        checks = {key: True for key in ("google_original_researched", "liveart_browser_researched", "evidence_saved_reloaded", "board_saved_reloaded", "costs_verified", "selection_verified", "email_flags_verified")}
        for overrides in ({"checks": {**checks, "board_saved_reloaded": False}}, {"proof": {**proof, "liveart_updated_at": "old-revision"}}, {"source_proof": {}}, {"checks": {**checks, "email_flags_verified": False}}):
            with self.subTest(overrides=overrides), self.assertRaises(QueueError):
                self.finish_item(run, item, **{"disposition": "valuation_unavailable", "checks": checks, "proof": proof, **overrides})
        self.assertEqual(get_run(run["id"]).items.get().status, "researching")

    def test_current_record_ids_and_dates_cannot_hide_evidence_saved_after_board(self):
        select_lot(self.lots[0].pk, True)
        run = self.start()
        item = self.claim(run)
        candidate = {"id": "comp-1", "hammer_usd": "100.00", "provider": "LiveArt"}
        analysis = LiveArtResaleAnalysis.objects.create(lot=self.lots[0], retrieved_at=timezone.now(), candidates=[{**candidate, "selected": True}], selected_ids=["comp-1"], source_summary={"selected_count": 1})
        board = AuctionBidBoardAnalysis.objects.create(lot=self.lots[0], selected_ids=["comp-1"], evidence_snapshot={"selected_records": [candidate], "source_summary": {"selected_count": 1}}, analysis={"valuation": "100.00"})
        checks = {key: True for key in ("google_original_researched", "liveart_browser_researched", "evidence_saved_reloaded", "board_saved_reloaded", "costs_verified", "selection_verified", "email_flags_verified")}
        # This represents an evidence Save after the Board Save, with a revised
        # comparable amount. Both current record timestamps are supplied truthfully.
        analysis.candidates = [{**candidate, "hammer_usd": "200.00", "selected": True}]
        analysis.save()
        proof = {"liveart_analysis_id": analysis.pk, "liveart_updated_at": analysis.updated_at.isoformat(), "bid_board_analysis_id": board.pk, "bid_board_updated_at": board.updated_at.isoformat()}
        for disposition in ("researched", "valuation_unavailable"):
            with self.subTest(disposition=disposition), self.assertRaisesMessage(QueueError, "evidence changed"):
                self.finish_item(run, item, disposition=disposition, checks=checks, proof=proof)
        board.evidence_snapshot = {"selected_records": [{**candidate, "hammer_usd": "200.00"}], "source_summary": {"selected_count": 1}}
        board.save()
        proof["bid_board_updated_at"] = board.updated_at.isoformat()
        result = self.finish_item(run, item, disposition="researched", checks=checks, proof=proof)["run"]["items"][0]
        self.assertEqual(result["saved_revisions"]["bid_board"]["evidence_snapshot"]["selected_records"][0]["hammer_usd"], "200.00")

    def test_run_status_exposes_current_saved_revision_metadata_without_changing_scope(self):
        select_lot(self.lots[0].pk, True)
        run = self.start()
        self.assertEqual(run["items"][0]["current_saved_proof"], {})
        analysis = LiveArtResaleAnalysis.objects.create(lot=self.lots[0], retrieved_at=timezone.now())
        board = AuctionBidBoardAnalysis.objects.create(lot=self.lots[0])
        refreshed = run_json(get_run(run["id"]))["items"][0]
        self.assertEqual(refreshed["current_saved_proof"], {"liveart_analysis_id": analysis.pk, "liveart_updated_at": analysis.updated_at.isoformat(), "bid_board_analysis_id": board.pk, "bid_board_updated_at": board.updated_at.isoformat()})
        self.assertEqual(refreshed["lot_snapshot"], run["items"][0]["lot_snapshot"])
        self.assertEqual(refreshed["status"], "queued")
        self.assertEqual(refreshed["saved_revisions"], {})


class ResearchQueueBoundaryTests(TestCase):
    def setUp(self):
        self.lot = AuctionWatchLot.objects.create(source="test", source_lot_id="auth")
        self.staff = get_user_model().objects.create_user("queue-staff", is_staff=True)
        self.url = reverse("research_queue_selection", args=[self.lot.pk])

    def test_selection_requires_staff_session_and_csrf(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post(self.url, json.dumps({"selected": True}), content_type="application/json").status_code, 403)
        client.force_login(self.staff)
        self.assertEqual(client.post(self.url, json.dumps({"selected": True}), content_type="application/json").status_code, 403)
        csrf = "a" * 32
        client.cookies["csrftoken"] = csrf
        response = client.post(self.url, json.dumps({"selected": True}), content_type="application/json", HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["selected"])
        self.assertEqual(response.json()["selected_count"], 1)

    @patch.dict("os.environ", {"CATALOG_API_KEY": "existing-test-key"})
    def test_worker_uses_existing_catalog_key_and_no_staff_session_bypass(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.staff)
        url = reverse("research_queue_worker")
        self.assertEqual(client.get(url).status_code, 401)
        response = client.post(url, json.dumps({"action": "start", "request_id": str(uuid.uuid4()), "owner_token": str(uuid.uuid4())}), content_type="application/json", HTTP_X_API_KEY="existing-test-key")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["run"]["items"], [])
        self.assertEqual(response.json()["run"]["status"], "completed")

    @patch.dict("os.environ", {"CATALOG_API_KEY": "existing-test-key"})
    def test_selection_survives_real_calendar_sync_and_is_shared_across_staff_sessions(self):
        self.client.force_login(self.staff)
        selected = self.client.post(self.url, json.dumps({"selected": True}), content_type="application/json")
        self.assertEqual(selected.status_code, 200)
        note_url = reverse("auction_research_queue_item", args=[self.lot.pk])
        self.client.post(note_url, json.dumps({"action": "note", "note": "Preserve this staff note across source refreshes"}), content_type="application/json")
        queue_before = ResearchQueueItem.objects.values().get(lot=self.lot)
        payload = {"lots": [
            {"source": self.lot.source, "source_lot_id": self.lot.source_lot_id, "artist": "Refreshed artist", "title": "Updated source title", "status": "ended", "event_at": "2026-10-28T13:00:00-04:00", "research_queue_selected": False},
            {"source": "test", "source_lot_id": "new-import-never-selected", "artist": "Refreshed artist", "title": "New catalog import", "research_queue_selected": True},
        ]}
        response = self.client.post(reverse("auction_calendar_sync"), json.dumps(payload), content_type="application/json", HTTP_X_API_KEY="existing-test-key")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["updated"], 1)
        self.assertEqual(response.json()["created"], 1)
        self.lot.refresh_from_db()
        self.assertEqual(self.lot.title, "Updated source title")
        self.assertFalse(self.lot.active)
        self.assertEqual(ResearchQueueItem.objects.values().get(lot=self.lot), queue_before)
        self.assertEqual(ResearchQueueItem.objects.count(), 1)
        other = get_user_model().objects.create_user("queue-other-staff", is_staff=True)
        second_browser = Client()
        second_browser.force_login(other)
        review = second_browser.get(reverse("auction_research_queue"))
        self.assertEqual(review.status_code, 200)
        self.assertEqual(review.context["research_queue_count"], 1)
        self.assertContains(review, "Updated source title")
        self.assertContains(review, "Preserve this staff note across source refreshes")
        repeat = second_browser.post(self.url, json.dumps({"selected": True}), content_type="application/json")
        self.assertEqual(repeat.json()["selected_count"], 1)
        self.assertEqual(ResearchQueueItem.objects.count(), 1)

    @patch.dict("os.environ", {"CATALOG_API_KEY": "existing-test-key"})
    def test_nonstaff_or_catalog_key_cannot_inspect_or_mutate_staff_queue(self):
        client = Client(enforce_csrf_checks=True)
        csrf = "a" * 32
        client.cookies["csrftoken"] = csrf
        request = {"content_type": "application/json", "HTTP_X_CSRFTOKEN": csrf, "HTTP_X_API_KEY": "existing-test-key"}
        self.assertEqual(client.get(reverse("auction_research_queue")).status_code, 302)
        self.assertEqual(client.post(self.url, json.dumps({"selected": True}), **request).status_code, 302)
        member = get_user_model().objects.create_user("queue-ordinary-member")
        client.force_login(member)
        self.assertEqual(client.get(reverse("auction_research_queue")).status_code, 302)
        self.assertEqual(client.post(self.url, json.dumps({"selected": True}), **request).status_code, 302)
        self.assertEqual(ResearchQueueItem.objects.count(), 0)
        client.force_login(self.staff)
        self.assertEqual(client.get(self.url).status_code, 405)

    def test_staff_note_failure_preserves_posted_text_and_does_not_save_it(self):
        self.client.force_login(self.staff)
        select_lot(self.lot.pk, True)
        item_url = reverse("auction_research_queue_item", args=[self.lot.pk])
        posted = "<script>example</script>" + "x" * 10000
        response = self.client.post(item_url, {"action": "note", "note": posted})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.context["queue_items"][0].note, posted)
        self.assertContains(response, "&lt;script&gt;example&lt;/script&gt;", status_code=400)
        self.assertEqual(ResearchQueueItem.objects.get(lot=self.lot).note, "")

    def test_staff_item_mutations_require_csrf_and_invalid_retry_preserves_prior_outcome(self):
        select_lot(self.lot.pk, True)
        item = ResearchQueueItem.objects.get(lot=self.lot)
        item.status, item.disposition, item.latest_result = "done", "triaged", {"reason": "Existing verified triage"}
        item.save()
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.staff)
        item_url = reverse("auction_research_queue_item", args=[self.lot.pk])
        for action in ("remove", "note", "move", "requeue"):
            with self.subTest(action=action):
                self.assertEqual(client.post(item_url, {"action": action, "reason": "Request a retry"}).status_code, 403)
        csrf = "b" * 32
        client.cookies["csrftoken"] = csrf
        invalid = client.post(item_url, {"action": "requeue", "reason": "  "}, HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(invalid.status_code, 400)
        item.refresh_from_db()
        self.assertEqual((item.status, item.disposition, item.generation), ("done", "triaged", 1))
        self.assertEqual(item.latest_result, {"reason": "Existing verified triage"})
        valid = client.post(item_url, {"action": "requeue", "reason": "Staff approved refreshed comparables"}, HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(valid.status_code, 302)
        item.refresh_from_db()
        self.assertEqual((item.status, item.disposition, item.generation), ("queued", "", 2))
        self.assertEqual(item.requeue_history[0]["reason"], "Staff approved refreshed comparables")

    def test_real_manual_evidence_and_board_save_reload_can_complete_selected_lot(self):
        self.client.force_login(self.staff)
        self.lot.artist, self.lot.title, self.lot.medium = "Test artist", "Work on paper", "Color lithograph"
        self.lot.current_bid, self.lot.bid_count, self.lot.currency = "100.00", 0, "USD"
        self.lot.save()
        select_lot(self.lot.pk, True)
        owner = str(uuid.uuid4())
        run = worker_action({"action": "start", "request_id": str(uuid.uuid4()), "owner_token": owner, "thread_id": str(uuid.uuid4())})["run"]
        item = worker_action({"action": "claim", "run_id": run["id"], "owner_token": owner})["item"]
        evidence_url = reverse("auction_lot_liveart_analysis", args=[self.lot.pk])
        entry = {"artist": self.lot.artist, "price_basis": "hammer", "currency": "USD", "category": "prints_and_multiples", "status": "sold", "title": "Work on paper", "sale_date": "2024-06-12", "auction_house": "Test auction house", "lot_number": "72", "hammer_usd": "3305.00", "provider_url": "https://www.liveart.ai/price-database/artwork/synthetic-test-sale", "evidence_note": "Synthetic offline test record: sold; USD hammer excluding buyer premium; verified Prints & Multiples.", "medium": "Color lithograph", "edition": "10/65"}
        added = self.client.post(evidence_url, json.dumps({"action": "add_manual", "entry": entry, "confirmed": True, "selected_ids": []}), content_type="application/json")
        self.assertEqual(added.status_code, 200, added.content)
        research = added.json()
        saved = self.client.post(evidence_url, json.dumps({"action": "save", "research_id": research["research_id"], "selected_ids": [research["added_id"]], "assumptions": {}}), content_type="application/json")
        self.assertEqual(saved.status_code, 200, saved.content)
        board_url = reverse("auction_lot_bid_board", args=[self.lot.pk])
        board = self.client.post(board_url, json.dumps({"action": "save", "selected_ids": [research["added_id"]], "assumptions": {}}), content_type="application/json")
        self.assertEqual(board.status_code, 200, board.content)
        self.assertEqual(self.client.get(evidence_url).status_code, 200)
        self.assertEqual(self.client.get(reverse("auction_lot_saved_bid_board", args=[self.lot.pk])).status_code, 200)
        proof = run_json(get_run(run["id"]))["items"][0]["current_saved_proof"]
        checks = {key: True for key in ("google_original_researched", "liveart_browser_researched", "evidence_saved_reloaded", "board_saved_reloaded", "costs_verified", "selection_verified", "email_flags_verified")}
        result = worker_action({"action": "outcome", "run_id": run["id"], "owner_token": owner, "item_id": item["id"], "disposition": "researched", "reason": "Synthetic integration test exercised the existing Save/reload endpoints.", "proof": proof, "checks": checks})
        self.assertEqual(result["run"]["items"][0]["disposition"], "researched")
        self.assertEqual(ResearchQueueItem.objects.get(lot=self.lot).status, "done")
