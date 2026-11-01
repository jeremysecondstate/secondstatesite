"""Synthetic offline manual-queue integration; no credentials or live API calls."""

from contextlib import closing
from dataclasses import replace
import copy
import json
from pathlib import Path
import sqlite3
import unittest
from uuid import uuid4

from scripts import liveart_research_queue as queue
from scripts import liveart_run_lifecycle as lifecycle
from scripts import test_liveart_run_lifecycle as fixtures


class FakeAPI:
    def __init__(self, lots=range(101, 106)):
        self.lots = list(lots)
        self.run = None
        self.calls = []
        self.fail_after = None
        self.before = None

    def call(self, action, payload=None):
        payload = payload or {}
        self.calls.append((action, copy.deepcopy(payload)))
        if self.before:
            self.before(action, payload)
        extra = {}
        if action == "start":
            if self.run is None:
                self.run = {"id": str(uuid4()), "request_id": payload["request_id"],
                            "owner_token": payload["owner_token"], "thread_id": payload["thread_id"], "status": "running", "recovery_log": [],
                            "items": [{"id": index, "lot_id": lot, "position": index,
                                       "lot_snapshot": {"title": str(lot)}, "note_snapshot": "Only this selected work",
                                       "status": "queued", "claimed_at": None, "outcome": {}, "operations": []} for index, lot in enumerate(self.lots, 1)]}
            elif self.run["request_id"] != payload["request_id"]:
                raise queue.QueueError("Unexpected second snapshot")
        elif action == "handoff":
            self.run["owner_token"] = payload["new_owner_token"]
            self.run["thread_id"] = payload["thread_id"]
        elif action == "claim":
            item = next((item for item in self.run["items"] if item["status"] == "researching"), None)
            item = item or next((item for item in self.run["items"] if item["status"] == "queued"), None)
            if item:
                item["status"] = "researching"
                item["claimed_at"] = "2026-10-27T12:00:00Z"
            extra.update(item_id=item["id"] if item else None, item=item)
        elif action in {"intent", "settle", "outcome", "block"}:
            item = next(item for item in self.run["items"] if item["id"] == payload["item_id"])
            if action == "intent":
                operation = next((op for op in item["operations"] if op["operation_id"] == payload["operation_id"]), None)
                if operation is None:
                    operation = {"operation_id": payload["operation_id"], "kind": payload["kind"],
                                 "details": payload.get("details", {}), "status": "intent"}
                    item["operations"].append(operation)
                extra["operation"] = operation
            elif action == "settle":
                operation = next(op for op in item["operations"] if op["operation_id"] == payload["operation_id"])
                operation.update(status="settled", result=payload["result"], units_spent=payload["units_spent"])
                extra["operation"] = operation
            else:
                item["status"] = "done" if action == "outcome" else "needs_attention"
        elif action == "amend":
            item = next(item for item in self.run["items"] if item["id"] == payload["item_id"])
            entry = next((entry for entry in self.run["recovery_log"] if entry.get("amendment_id") == payload["amendment_id"]), None)
            if entry is None:
                outcome = {key: payload[key] for key in ("disposition", "reason", "checks", "proof")}
                entry = {"event": "amendment", "item_id": item["id"], "outcome": outcome,
                         **{key: payload[key] for key in ("amendment_id", "reason", "authorization", "correction_operation_ids")},
                         "saved_revisions": {"test": "corrected"}}
                self.run["recovery_log"].append(entry)
                item.update(effective_outcome=outcome, effective_saved_revisions=entry["saved_revisions"])
            extra["amendment"] = entry
        elif action == "stop":
            self.run["status"] = "blocked"
            for item in self.run["items"]:
                if item["status"] in {"queued", "researching"}:
                    item["status"] = "needs_attention"
                    item["outcome"] = {"explicit_stop": True, "source_proof": payload["source_proof"]}
        elif action == "finish":
            if any(item["status"] in {"queued", "researching"} for item in self.run["items"]) or queue.unsettled(self.run):
                raise queue.QueueError("Unfinished snapshot")
            self.run["status"] = "completed"
        result = copy.deepcopy({"ok": True, "run": self.run, **extra})
        if self.fail_after == action:
            self.fail_after = None
            raise queue.QueueError("Synthetic lost response")
        return result


class ManualQueueTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.LifecycleTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.config = replace(self.f.config, allow_legacy_catalog_start=False, migration_epoch_ms=2000)
        self.api = FakeAPI()

    def human(self, ident=None, text="Process my LiveArt queue", kind="userMessage"):
        ident = ident or self.f.add_thread(marker="An existing on-demand chat", when=1)
        with closing(sqlite3.connect(self.f.history)) as db, db:
            ordinal = db.execute("SELECT max(rollout_ordinal) FROM thread_turns WHERE thread_id=?", (ident,)).fetchone()[0] + 1
            turn, item = str(uuid4()), str(uuid4())
            db.execute("INSERT INTO thread_turns VALUES (?,?,?,?,?,?)", (ident, turn, ordinal, "inProgress", fixtures.NOW // 1000 + ordinal, None))
            db.execute("INSERT INTO thread_items VALUES (?,?,?,?,?,?)", (ident, turn, item, kind,
                       fixtures.NOW + ordinal * 1000, json.dumps({"type": kind, "content": [{"type": "text", "text": text}]})))
        return ident, item

    def audit(self, ident, **overrides):
        run = self.api.run
        receipts = {}
        for item in run["items"]:
            path = self.f.folder / f"lot-{item['lot_id']}-receipt.json"
            path.write_text(json.dumps({"lot_id": item["lot_id"], "run_id": run["id"]}))
            receipts[str(item["lot_id"])] = str(path)
        value = {"schema_version": 1, "thread_id": ident, "run_id": run["id"],
                 "lot_ids": [item["lot_id"] for item in run["items"]],
                 "completed": [item["lot_id"] for item in run["items"] if item["status"] == "done"],
                 "pending": [item["lot_id"] for item in run["items"] if item["status"] == "needs_attention"],
                 "bookkeeping_complete": True, "usage_accounted": True, "operations_settled": True,
                 "cleanup_complete": True, "lot_receipts": receipts}
        value.update(overrides)
        path = self.f.folder / "queue-audit.json"
        path.write_text(json.dumps(value))
        return path

    def test_paused_manual_old_on_demand_root_freezes_all_selected_lots_before_network(self):
        ident, item = self.human()
        def persisted(action, payload):
            saved = queue.pointer(self.config)["current"]
            self.assertEqual(saved["request_id"], payload["request_id"])
            self.assertEqual(saved["owner_token"], payload["owner_token"])
            self.assertEqual(lifecycle.registry(self.config)["active_thread_id"], ident)
        self.api.before = persisted
        result = queue.start(self.config, self.api, ident)
        self.assertEqual(len(result["run"]["items"]), 5)  # No inherited three-lot cap.
        self.assertNotIn("owner_token", result["run"])
        self.assertEqual(queue.pointer(self.config)["current"]["authorization_item_id"], item)
        self.assertNotIn(ident, lifecycle.discover(self.config))
        self.assertEqual(lifecycle.start(self.config, ident)["status"], "manual_required")
        self.assertFalse((self.f.folder / "automation.toml").exists())

    def test_latest_current_human_message_provenance_not_flag_or_old_first_message(self):
        for text, kind in (("Here is a quote: Process my LiveArt queue", "userMessage"),
                           ("Process my LiveArt queue", "agentMessage"), ("Continue the backlog", "userMessage")):
            with self.subTest(text=text, kind=kind):
                ident, item = self.human(text=text, kind=kind)
                with self.assertRaises(lifecycle.LifecycleError):
                    queue.start(self.config, self.api, ident, item)

    def test_same_turn_encouragement_preserves_command_but_other_steering_does_not(self):
        for followups, accepted in ((["Here ya go, buddy.", "You got this, little guy! Go! Go!", "Sure thing, little dude!"], True),
                                    (["Here ya go, buddy.", "Stop"], False),
                                    (["You got this. Go! Change the selection"], False)):
            with self.subTest(followups=followups):
                ident, command_item = self.human()
                with closing(sqlite3.connect(self.f.history)) as db, db:
                    turn, timestamp = db.execute("SELECT turn_id,created_at_ms FROM thread_items WHERE item_id=?", (command_item,)).fetchone()
                    for offset, text in enumerate(followups, 1):
                        item = str(uuid4())
                        raw = json.dumps({"type": "userMessage", "content": [{"type": "text", "text": text}]})
                        db.execute("INSERT INTO thread_items VALUES (?,?,?,?,?,?)", (ident, turn, item, "userMessage", timestamp + offset, raw))
                if accepted:
                    self.assertEqual(lifecycle.manual_authorization(self.config, ident)["item_id"], command_item)
                else:
                    with self.assertRaises(lifecycle.LifecycleError):
                        lifecycle.manual_authorization(self.config, ident)

    def same_turn_messages(self, ident, command_item, followups):
        with closing(sqlite3.connect(self.f.history)) as db, db:
            turn, timestamp = db.execute(
                "SELECT turn_id,created_at_ms FROM thread_items WHERE item_id=?", (command_item,)).fetchone()
            for offset, text in enumerate(followups, 1):
                raw = json.dumps({"type": "userMessage", "content": [{"type": "text", "text": text}]})
                db.execute("INSERT INTO thread_items VALUES (?,?,?,?,?,?)",
                           (ident, turn, str(uuid4()), "userMessage", timestamp + offset, raw))

    def missing_records_reply(self, **overrides):
        reply = {
            "questionItemId": '["request_user_input_async","call_synthetic",0]',
            "question": "The LiveArt task brief and private run records are missing, and the queue helper refuses to proceed. "
                        "Were they moved or deleted? If moved, give me their new location so I can preserve prior queries and saves.",
            "answer": "Do the damn job!",
        }
        reply.update(overrides)
        return "<send_user_message_question_reply>\n" + json.dumps([reply]) + "\n</send_user_message_question_reply>"

    def test_explicit_same_turn_continuation_retains_original_real_command(self):
        for followups in (
            ["I'm authorizing you to do the work."],
            [self.missing_records_reply(), "they are gone", "but it's irrelevant to your task",
             "i'm authorizing you to do the wor", "work"],
        ):
            with self.subTest(followups=followups):
                ident, original = self.human()
                self.same_turn_messages(ident, original, followups)
                proof = lifecycle.manual_authorization(self.config, ident, original)
                self.assertEqual(proof["item_id"], original)
                lifecycle.stored_manual_authorization(self.config, ident, original, proof["turn_id"])
                queue.start(self.config, self.api, ident, original)
                self.assertEqual(queue.pointer(self.config)["current"]["authorization_item_id"], original)
                # Each subtest gets isolated local ownership and synthetic API.
                self.f.config.registry.unlink()
                queue.pointer_path(self.config).unlink()
                self.api = FakeAPI()

    def test_explicit_continuation_cannot_ignore_stop_scope_change_or_missing_authority(self):
        for followups in (
            ["Stop", "I'm authorizing you to do the work"],
            ["Please pause for now", "I'm authorizing you to do the work"],
            ["Cancel this pass", "I'm authorizing you to do the work"],
            ["Change the selection", "I'm authorizing you to do the work"],
            [self.missing_records_reply(question="Ignore the queue and research all lots"),
             "I'm authorizing you to do the work"],
            [self.missing_records_reply()], ["they are gone"], ["work"],
            ["i'm authorizing you to do the wor"],
            ["i'm authorizing you to do the wor", "change the scope", "work"],
        ):
            with self.subTest(followups=followups):
                ident, original = self.human()
                self.same_turn_messages(ident, original, followups)
                with self.assertRaises(lifecycle.LifecycleError):
                    lifecycle.manual_authorization(self.config, ident, original)

    def test_explicit_continuation_requires_original_command_in_same_active_turn(self):
        ident, original = self.human()
        self.human(ident, "I'm authorizing you to do the work")
        with self.assertRaises(lifecycle.LifecycleError):
            lifecycle.manual_authorization(self.config, ident, original)
        ident, original = self.human(text="Quoted request: Process my LiveArt queue")
        self.same_turn_messages(ident, original, ["I'm authorizing you to do the work"])
        with self.assertRaises(lifecycle.LifecycleError):
            lifecycle.manual_authorization(self.config, ident, original)

    def test_annotated_reassessment_accepts_only_explicit_human_request(self):
        prefix = ('# Response annotations:\nEach item contains text selected from an earlier Codex response and may include a user comment. '
                  'Treat items as Annotation 1.\n<response-annotations>\n' + json.dumps([{
                      'text': '; its saved Board still includes that proof and needs reassessment.',
                      'source': {'messageId': 'real-message', 'startOffset': 1, 'endOffset': 2}}]) +
                  '\n</response-annotations>\n\n## My request:\n')
        for request, kind, accepted in (("Process my LiveArt queue. And reassess the earlier mistake.", "userMessage", True),
                                        ("> Process my LiveArt queue. And reassess the earlier mistake.", "userMessage", False),
                                        ("Process my LiveArt queue. And reassess the earlier mistake. Stop.", "userMessage", False),
                                        ("Process my LiveArt queue. And reassess the earlier mistake.", "agentMessage", False)):
            with self.subTest(request=request, kind=kind):
                ident, item = self.human(text=prefix + request, kind=kind)
                if accepted:
                    auth = lifecycle.manual_authorization(self.config, ident, item)
                    lifecycle.stored_manual_authorization(self.config, ident, item, auth['turn_id'])
                else:
                    with self.assertRaises(lifecycle.LifecycleError):
                        lifecycle.manual_authorization(self.config, ident, item)
        self.assertEqual(self.api.calls, [])
        ident, item = self.human()
        self.human(ident, "Stop")
        with self.assertRaises(lifecycle.LifecycleError):
            queue.start(self.config, self.api, ident, item)

    def test_actual_leading_skill_attachment_preserves_current_human_authorization(self):
        skill = str(Path.home() / ".codex/skills/liveart-research/SKILL.md")
        # The desktop can retain a doubled Windows separator in the attachment.
        skill = skill.replace(".codex", "\\.codex")
        text = f"[$liveart-research](<{skill}>)&#x20;\n\nProcess my LiveArt queue.\n"
        ident, item = self.human(text=text)
        result = queue.start(self.config, self.api, ident, item)
        self.assertEqual(result["status"], "ready")
        saved = queue.pointer(self.config)["current"]
        lifecycle.stored_manual_authorization(self.config, ident, item, saved["authorization_turn_id"])
        self.human(ident, "Status?")
        lifecycle.stored_manual_authorization(self.config, ident, item, saved["authorization_turn_id"])
        with self.assertRaises(lifecycle.LifecycleError):
            lifecycle.manual_authorization(self.config, ident, item)

    def test_skill_attachment_cannot_hide_other_prose_paths_or_agent_origin(self):
        skill = str(Path.home() / ".codex/skills/liveart-research/SKILL.md")
        attachment = f"[$liveart-research](<{skill}>)&#x20;\n\n"
        command = "Process my LiveArt queue."
        for text, kind in (
            (attachment + command, "agentMessage"),
            (attachment.replace("$liveart-research", "$other") + command, "userMessage"),
            (attachment.replace("SKILL.md", "other.md") + command, "userMessage"),
            (attachment + attachment + command, "userMessage"),
            ("Here is a quote:\n" + attachment + command, "userMessage"),
            (attachment + "> " + command, "userMessage"),
            (attachment + command + " Also do something else.", "userMessage"),
        ):
            with self.subTest(text=text, kind=kind):
                ident, item = self.human(text=text, kind=kind)
                with self.assertRaises(lifecycle.LifecycleError):
                    queue.start(self.config, self.api, ident, item)
        self.assertEqual(self.api.calls, [])

    def test_spaced_skill_attachment_preserves_exact_current_human_authorization(self):
        skill = str(Path.home() / ".codex/skills/liveart-research/SKILL.md")
        attachment = f"[$liveart-research](<{skill}>) &#x20;\n"
        ident, item = self.human(text=attachment + "Process my LiveArt queue.\n")
        result = queue.start(self.config, self.api, ident, item)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(queue.pointer(self.config)["current"]["authorization_item_id"], item)
        call_count = len(self.api.calls)
        for text in (attachment + "Process my LiveArt queue. Also do something else.",
                     attachment + "> Process my LiveArt queue.",
                     attachment + attachment + "Process my LiveArt queue."):
            with self.subTest(text=text):
                self.human(ident, text=text)
                with self.assertRaises(lifecycle.LifecycleError):
                    queue.start(self.config, self.api, ident)
        self.assertEqual(len(self.api.calls), call_count)

    def reconciliation_reply(self, *, answer=None, kind="userMessage", original_text="Process my LiveArt queue"):
        ident, original = self.human(text=original_text)
        question_id = json.dumps(["request_user_input_async", "call_syntheticApproval", 0], separators=(",", ":"))
        reply = {"questionItemId": question_id, "question": lifecycle.RECONCILIATION_QUESTION,
                 "answer": answer or lifecycle.RECONCILIATION_ANSWER}
        text = "<send_user_message_question_reply>\n" + json.dumps([reply]) + "\n</send_user_message_question_reply>\n"
        _, item = self.human(ident, text=text, kind=kind)
        with closing(sqlite3.connect(self.f.history)) as db:
            turn = db.execute("SELECT turn_id FROM thread_items WHERE item_id=?", (item,)).fetchone()[0]
        receipt = {"status": "reconciled", "actor_thread_id": ident, "authorization_item_id": item,
                   "authorization_turn_id": turn, "original_authorization_item_id": original,
                   "reconciliation_completed": True,
                   "approval": {"question": reply["question"], "answer": reply["answer"], "question_item_id": question_id}}
        path = self.config.business_control.parent / f"manual-queue-start-{ident[:8]}.json"
        return ident, item, turn, receipt, path

    def test_recorded_explicit_reconciliation_reply_continues_original_queue_request(self):
        ident, item, turn, receipt, path = self.reconciliation_reply()
        path.write_text(json.dumps(receipt), encoding="utf-8")
        result = queue.start(self.config, self.api, ident, item)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(queue.pointer(self.config)["current"]["authorization_item_id"], item)
        self.assertEqual(queue.start(self.config, self.api, ident, item)["run"]["id"], result["run"]["id"])
        lifecycle.stored_manual_authorization(self.config, ident, item, turn)
        self.human(ident, "Status?")
        lifecycle.stored_manual_authorization(self.config, ident, item, turn)
        with self.assertRaises(lifecycle.LifecycleError):
            lifecycle.manual_authorization(self.config, ident, item)

    def test_reconciliation_reply_requires_matching_completed_receipt_and_real_original(self):
        for change in ("missing", "actor", "item", "turn", "original", "incomplete", "status", "approval"):
            with self.subTest(change=change):
                ident, item, turn, receipt, path = self.reconciliation_reply()
                if change in {"actor", "item", "turn", "original"}:
                    key = {"actor": "actor_thread_id", "item": "authorization_item_id", "turn": "authorization_turn_id",
                           "original": "original_authorization_item_id"}[change]
                    receipt[key] = str(uuid4())
                elif change == "incomplete":
                    receipt["reconciliation_completed"] = False
                elif change == "status":
                    receipt["status"] = "proposed"
                elif change == "approval":
                    receipt["approval"]["question_item_id"] = json.dumps(["request_user_input_async", "call_other", 0])
                if change != "missing":
                    path.write_text(json.dumps(receipt), encoding="utf-8")
                with self.assertRaises(lifecycle.LifecycleError):
                    lifecycle.manual_authorization(self.config, ident, item)
        self.assertEqual(self.api.calls, [])

    def test_reconciliation_reply_cannot_replace_human_command_provenance(self):
        for kwargs in ({"answer": "No"}, {"kind": "agentMessage"}, {"original_text": "Quoted: Process my LiveArt queue"}):
            with self.subTest(kwargs=kwargs):
                ident, item, turn, receipt, path = self.reconciliation_reply(**kwargs)
                path.write_text(json.dumps(receipt), encoding="utf-8")
                with self.assertRaises(lifecycle.LifecycleError):
                    lifecycle.manual_authorization(self.config, ident, item)
                with self.assertRaises(lifecycle.LifecycleError):
                    lifecycle.stored_manual_authorization(self.config, ident, item, turn)
        self.assertEqual(self.api.calls, [])

    def test_fresh_unflagged_start_denied_and_existing_legacy_recovery_preserved(self):
        marked = self.f.add_thread(status="inProgress")
        self.assertEqual(lifecycle.start(self.config, marked)["status"], "manual_required")
        self.assertFalse(self.config.registry.exists())
        lifecycle.start(self.f.config, marked)
        self.f.write_control(paid_query_lock={"owner": marked})
        self.f.set_turn(marked, "completed")
        recovery = self.f.add_thread(status="inProgress")
        self.assertTrue(lifecycle.start(self.config, recovery)["recovery_only"])

    def test_start_lost_response_reuses_durable_request_and_never_includes_late_selection(self):
        ident, _ = self.human()
        self.api.fail_after = "start"
        with self.assertRaises(queue.QueueError):
            queue.start(self.config, self.api, ident)
        original = queue.pointer(self.config)["current"]["request_id"]
        self.api.lots.append(999)
        first = queue.start(self.config, self.api, ident)
        again = queue.start(self.config, self.api, ident)
        self.assertEqual(first["run"]["id"], again["run"]["id"])
        self.assertEqual({call[1]["request_id"] for call in self.api.calls}, {original})
        self.assertNotIn(999, [item["lot_id"] for item in again["run"]["items"]])

    def test_claim_skips_done_blocked_and_scope_cannot_expand(self):
        ident, _ = self.human()
        queue.start(self.config, self.api, ident)
        self.api.run["items"][0]["status"] = "done"
        self.api.run["items"][1]["status"] = "needs_attention"
        self.assertEqual(queue.coordinate(self.config, self.api, ident, "claim")["item_id"], 3)
        with self.assertRaisesRegex(queue.QueueError, "outside"):
            queue.coordinate(self.config, self.api, ident, "intent", {"item_id": 999, "kind": "search"})
        self.api.run["items"].append({"id": 99, "lot_id": 999, "position": 99, "status": "queued",
                                     "lot_snapshot": {}, "note_snapshot": "", "operations": []})
        with self.assertRaisesRegex(queue.QueueError, "scope changed"):
            queue.coordinate(self.config, self.api, ident, "status")

    def test_lost_intent_response_never_authorizes_query_or_save_reexecution(self):
        ident, _ = self.human()
        queue.start(self.config, self.api, ident)
        queue.coordinate(self.config, self.api, ident, "claim")
        payload = {"item_id": 1, "kind": "search", "details": {"query": '"Known title"'}}
        self.api.fail_after = "intent"
        with self.assertRaises(queue.QueueError):
            queue.coordinate(self.config, self.api, ident, "intent", payload)
        retry = queue.coordinate(self.config, self.api, ident, "intent", payload)
        self.assertFalse(retry["operation_execution_allowed"])
        self.assertEqual(len(self.api.run["items"][0]["operations"]), 1)
        with self.assertRaisesRegex(queue.QueueError, "durable ID"):
            queue.coordinate(self.config, self.api, ident, "intent", {**payload, "operation_id": str(uuid4())})
        with self.assertRaisesRegex(queue.QueueError, "Usage"):
            queue.coordinate(self.config, self.api, ident, "settle", {"item_id": 1, "operation_id": retry["operation"]["operation_id"], "result": {"saved": True}})

    def test_resume_never_takes_active_or_unprojected_prior_or_unknown_operations(self):
        prior, _ = self.human()
        queue.start(self.config, self.api, prior)
        current, _ = self.human()
        before = len(self.api.calls)
        with self.assertRaises(lifecycle.LifecycleError):
            queue.resume(self.config, self.api, current)
        self.assertEqual(len(self.api.calls), before)
        self.f.set_turn(prior, "completed")
        self.api.run["items"][0]["operations"] = [{"operation_id": str(uuid4()), "status": "intent"}]
        with self.assertRaisesRegex(queue.QueueError, "unsettled"):
            queue.resume(self.config, self.api, current)
        self.assertFalse(any(action == "handoff" for action, _ in self.api.calls))
        self.assertEqual(queue.pointer(self.config)["current"]["owner_thread_id"], prior)

    def test_terminal_resume_lost_handoff_response_reconciles_without_second_transfer(self):
        prior, _ = self.human()
        queue.start(self.config, self.api, prior)
        self.f.set_turn(prior, "completed")
        current, _ = self.human()
        self.api.fail_after = "handoff"
        with self.assertRaises(queue.QueueError):
            queue.resume(self.config, self.api, current)
        result = queue.resume(self.config, self.api, current)
        self.assertEqual(result["status"], "resumed")
        self.assertEqual(sum(action == "handoff" for action, _ in self.api.calls), 1)
        self.assertEqual(queue.pointer(self.config)["current"]["owner_thread_id"], current)

    def test_cross_workspace_resume_uses_registered_prior_scope_and_retains_tree_guards(self):
        prior_config = replace(self.config, expected_cwd="C:/managed/secondstatesite", expected_project_id="old-project")
        prior, _ = self.human(self.f.add_thread(cwd=prior_config.expected_cwd, project="old-project"))
        queue.start(prior_config, self.api, prior)
        child = self.f.add_thread(parent=prior, status="inProgress", cwd=prior_config.expected_cwd)
        current, _ = self.human()
        before = len(self.api.calls)
        self.assertEqual(lifecycle.start_manual(self.config, current)["status"], "busy")
        self.f.set_turn(prior, "completed")
        with self.assertRaisesRegex(lifecycle.LifecycleError, "active or uncertain"):
            queue.resume(self.config, self.api, current)
        self.assertEqual(len(self.api.calls), before)
        self.f.set_turn(child, "completed")
        result = queue.resume(self.config, self.api, current)
        self.assertEqual(result["status"], "resumed")
        self.assertEqual(queue.pointer(self.config)["current"]["owner_thread_id"], current)
        self.assertEqual(lifecycle.registry(self.config)["runs"][current]["workspace"],
                         {"cwd": self.config.expected_cwd, "project_id": None})

    def test_cross_workspace_prior_still_requires_unchanged_projected_history(self):
        prior_config = replace(self.config, expected_cwd="C:/managed/secondstatesite")
        prior, _ = self.human(self.f.add_thread(cwd=prior_config.expected_cwd))
        queue.start(prior_config, self.api, prior)
        self.f.set_turn(prior, "completed")
        with (self.f.folder / (prior + ".jsonl")).open("ab") as stream:
            stream.write(b'{"new_user_turn":true}\n')
        current, _ = self.human()
        before = len(self.api.calls)
        self.assertEqual(lifecycle.start_manual(self.config, current)["status"], "busy")
        with self.assertRaisesRegex(lifecycle.LifecycleError, "unprojected"):
            queue.resume(self.config, self.api, current)
        self.assertEqual(len(self.api.calls), before)
        self.assertEqual(lifecycle.registry(self.config)["active_thread_id"], prior)

    def test_legacy_cross_workspace_prior_requires_owner_specific_matching_authority(self):
        prior_config = replace(self.config, expected_cwd="C:/managed/secondstatesite")
        prior, _ = self.human(self.f.add_thread(cwd=prior_config.expected_cwd))
        queue.start(prior_config, self.api, prior)
        self.f.set_turn(prior, "completed")
        data = lifecycle.registry(self.config)
        data["runs"][prior].pop("workspace")  # Existing pre-provenance manual record.
        lifecycle.atomic_json(self.config.registry, data)
        current, _ = self.human()
        self.assertEqual(lifecycle.start_manual(self.config, current)["status"], "busy")
        value = lifecycle.read_json(self.config.path)
        value.update(expected_cwd=prior_config.expected_cwd,
                     migration_epoch_ms=self.config.migration_epoch_ms,
                     allow_legacy_catalog_start=self.config.allow_legacy_catalog_start)
        managed = self.config.path.parent / f"config.managed-{prior[:8]}.json"
        value["business_control"] = str(self.f.folder / "unrelated-control.json")
        managed.write_text(json.dumps(value), encoding="utf-8")
        self.assertEqual(lifecycle.start_manual(self.config, current)["status"], "busy")
        value["business_control"] = str(self.config.business_control)
        managed.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(lifecycle.LifecycleError, "workspace or project"):
            wrong, _ = self.human(self.f.add_thread(cwd="C:/unrelated"))
            lifecycle.start_manual(self.config, wrong)
        self.assertEqual(queue.resume(self.config, self.api, current)["status"], "resumed")

    def test_reconcile_settles_only_matching_verified_receipt_preserving_business_guards(self):
        prior, _ = self.human()
        queue.start(self.config, self.api, prior)
        queue.coordinate(self.config, self.api, prior, "claim")
        op = queue.coordinate(self.config, self.api, prior, "intent", {"item_id": 1, "kind": "search"})["operation"]["operation_id"]
        self.f.set_turn(prior, "completed")
        self.f.write_control(paid_query_lock={"owner": prior})
        before = self.f.control.read_bytes()
        current, _ = self.human()
        payload = {"item_id": 1, "operation_id": op, "units_spent": None, "result": {"usage_unknown": True, "observed": "saved results"}}
        receipt = self.f.folder / "verified-receipt.json"
        receipt.write_text(json.dumps({**payload, "outcome_verified": True, "verification": {
            "source": "https://secondstate.art/observed", "observed_at": "2026-10-27T12:00:00Z", "observed_result": "The original saved query results exist"}}))
        result = queue.reconcile(self.config, self.api, current, payload, receipt)
        self.assertEqual(result["status"], "reconciled")
        self.assertFalse(result["operation_execution_allowed"])
        self.assertEqual(self.f.control.read_bytes(), before)
        self.assertEqual(queue.pointer(self.config)["current"]["owner_thread_id"], prior)
        self.assertFalse(any(action == "handoff" for action, _ in self.api.calls))

    def test_finish_requires_all_frozen_items_and_audit_and_never_archives_manual(self):
        ident, _ = self.human()
        queue.start(self.config, self.api, ident)
        self.assertEqual(queue.coordinate(self.config, self.api, ident, "finish")["status"], "completion_pending")
        for item in self.api.run["items"]:
            item["status"] = "done"
        queue.coordinate(self.config, self.api, ident, "status")
        result = queue.coordinate(self.config, self.api, ident, "finish")
        self.assertEqual(result["status"], "completion_pending")
        # Legacy control has no touched owners: the queue itself still needs an audit.
        self.assertEqual(lifecycle.finish(self.config, ident)["status"], "completion_pending")
        audit = self.audit(ident)
        result = queue.coordinate(self.config, self.api, ident, "finish", audit_path=audit)
        self.assertEqual(result["lifecycle"]["status"], "finished")
        self.assertTrue(queue.pointer(self.config)["current"]["finished"])
        self.assertNotIn(ident, lifecycle.discover(self.config))

    def test_new_intent_guard_checked_after_claim_but_exact_replay_remains_nonexecutable(self):
        ident, _ = self.human()
        queue.start(self.config, self.api, ident)
        queue.coordinate(self.config, self.api, ident, "claim")
        first = {"item_id": 1, "kind": "search", "details": {"query": "first"}}
        queue.coordinate(self.config, self.api, ident, "intent", first)
        self.f.write_control(paid_query_lock={"owner": "uncertain"})
        before = len(self.api.calls)
        with self.assertRaisesRegex(queue.QueueError, "guards"):
            queue.coordinate(self.config, self.api, ident, "intent", {"item_id": 1, "kind": "save_evidence"})
        self.assertEqual(len(self.api.calls), before)
        result = queue.coordinate(self.config, self.api, ident, "intent", first)
        self.assertFalse(result["operation_execution_allowed"])

    def test_harmless_midrun_steering_keeps_scope_and_settle_but_stop_prevents_new_research(self):
        ident, _ = self.human()
        queue.start(self.config, self.api, ident)
        queue.coordinate(self.config, self.api, ident, "claim")
        operation = queue.coordinate(self.config, self.api, ident, "intent", {"item_id": 1, "kind": "search"})["operation"]
        self.f.set_turn(ident, "completed")
        self.human(ident, "How far along are you?")
        payload = {"item_id": 1, "operation_id": operation["operation_id"], "result": {"observed": "saved results"}, "units_spent": "27.00"}
        queue.coordinate(self.config, self.api, ident, "settle", payload)
        self.assertEqual(len(queue.pointer(self.config)["current"]["scope"]), 5)
        self.f.set_turn(ident, "completed")
        self.human(ident, "Please stop for now")
        with self.assertRaisesRegex(queue.QueueError, "stopped"):
            queue.coordinate(self.config, self.api, ident, "claim")
        queue.coordinate(self.config, self.api, ident, "settle", payload)
        self.f.set_turn(ident, "completed")
        self.human(ident, "How are you doing?")
        with self.assertRaisesRegex(queue.QueueError, "stopped"):
            queue.coordinate(self.config, self.api, ident, "claim")

    def test_lost_finish_response_later_manual_request_finalizes_completed_snapshot_without_handoff(self):
        prior, _ = self.human()
        queue.start(self.config, self.api, prior)
        for item in self.api.run["items"]:
            item["status"] = "done"
        queue.coordinate(self.config, self.api, prior, "status")
        self.api.fail_after = "finish"
        with self.assertRaises(queue.QueueError):
            queue.coordinate(self.config, self.api, prior, "finish", audit_path=self.audit(prior))
        self.f.set_turn(prior, "completed")
        current, _ = self.human()
        result = queue.resume(self.config, self.api, current)
        self.assertEqual(result["status"], "completion_pending")
        result = queue.resume(self.config, self.api, current, audit_path=self.audit(current))
        self.assertEqual(result["status"], "completed_reconciled")
        self.assertEqual(result["lifecycle"]["status"], "finished")
        self.assertFalse(any(action == "handoff" for action, _ in self.api.calls))

    def test_full_queue_audit_rejects_missing_coverage_receipts_and_false_usage(self):
        ident, _ = self.human()
        queue.start(self.config, self.api, ident)
        for item in self.api.run["items"]:
            item["status"] = "done"
        queue.coordinate(self.config, self.api, ident, "status")
        for change in ({"lot_ids": []}, {"completed": [101]}, {"lot_receipts": {}},
                       {"usage_accounted": False}, {"run_id": str(uuid4())}):
            with self.subTest(change=change):
                result = queue.coordinate(self.config, self.api, ident, "finish", audit_path=self.audit(ident, **change))
                self.assertEqual(result["status"], "completion_pending")
        self.assertFalse(any(action == "finish" for action, _ in self.api.calls))

    def test_staff_removed_unclaimed_item_uses_truthful_server_receipt(self):
        self.api = FakeAPI([101])
        ident, _ = self.human()
        queue.start(self.config, self.api, ident)
        self.api.run["items"][0].update(status="done", disposition="skipped", outcome={"source_proof": {"staff_queue_removal": True}})
        queue.coordinate(self.config, self.api, ident, "status")
        audit = self.audit(ident, lot_receipts={}, server_receipts={"101": {"run_id": self.api.run["id"], "item_id": 1}})
        self.assertEqual(queue.coordinate(self.config, self.api, ident, "finish", audit_path=audit)["lifecycle"]["status"], "finished")

    def test_manual_stop_requires_actual_human_stop_and_preserves_unknown_intents(self):
        ident, _ = self.human()
        queue.start(self.config, self.api, ident)
        with self.assertRaises(lifecycle.LifecycleError):
            queue.stop(self.config, self.api, ident)
        self.f.set_turn(ident, "completed")
        self.human(ident, "Stop")
        self.api.run["items"][0]["operations"] = [{"operation_id": str(uuid4()), "status": "intent"}]
        self.f.write_control(in_flight=[101])
        before = self.f.control.read_bytes()
        result = queue.stop(self.config, self.api, ident)
        self.assertEqual(result["status"], "stopped")
        self.assertFalse(result["work_allowed"])
        self.assertEqual(result["lifecycle"]["status"], "checkpoint_pending")
        self.assertEqual(self.f.control.read_bytes(), before)
        self.assertEqual(len(queue.unsettled(self.api.run)), 1)
        self.assertFalse(queue.pointer(self.config)["current"].get("finished", False))

    def test_human_stop_pending_audit_needs_no_fictional_external_blocker(self):
        self.api = FakeAPI([101])
        ident, _ = self.human()
        queue.start(self.config, self.api, ident)
        self.f.set_turn(ident, "completed")
        _, stop_item = self.human(ident, "Stop")
        result = queue.stop(self.config, self.api, ident)
        self.assertEqual(result["lifecycle"]["status"], "completion_pending")
        audit = self.audit(ident, human_stop=True, authorization_item_id=stop_item, lot_receipts={},
                           server_receipts={"101": {"run_id": self.api.run["id"], "item_id": 1}})
        result = queue.stop(self.config, self.api, ident, audit)
        self.assertEqual(result["lifecycle"]["status"], "finished")

    def test_stop_cleanup_reuses_original_genuine_stop_after_harmless_later_steering(self):
        self.api = FakeAPI([101])
        ident, _ = self.human()
        queue.start(self.config, self.api, ident)
        queue.coordinate(self.config, self.api, ident, "claim")
        operation = queue.coordinate(self.config, self.api, ident, "intent", {"item_id": 1, "kind": "search"})["operation"]
        self.f.set_turn(ident, "completed")
        _, stop_item = self.human(ident, "Stop")
        self.api.fail_after = "stop"
        with self.assertRaises(queue.QueueError):
            queue.stop(self.config, self.api, ident)
        original_stop = next(payload for action, payload in self.api.calls if action == "stop")
        self.f.set_turn(ident, "completed")
        _, status_item = self.human(ident, "How far along are you?")
        queue.coordinate(self.config, self.api, ident, "settle", {
            "item_id": 1, "operation_id": operation["operation_id"],
            "result": {"observed": "The original response is retained"}, "units_spent": "27.00"})
        with self.assertRaisesRegex(queue.QueueError, "stopped"):
            queue.coordinate(self.config, self.api, ident, "intent", {"item_id": 1, "kind": "save_board"})
        wrong = self.audit(ident, human_stop=True, authorization_item_id=status_item)
        result = queue.stop(self.config, self.api, ident, wrong)
        self.assertEqual(result["lifecycle"]["status"], "completion_pending")
        valid = self.audit(ident, human_stop=True, authorization_item_id=stop_item)
        result = queue.coordinate(self.config, self.api, ident, "finish", audit_path=valid)
        self.assertEqual(result["lifecycle"]["status"], "finished")
        self.assertTrue(queue.pointer(self.config)["current"]["finished"])
        self.assertTrue(all(payload == original_stop for action, payload in self.api.calls if action == "stop"))

    def test_forged_recorded_stop_cannot_turn_status_message_into_stop_authorization(self):
        ident, status_item = self.human()
        queue.start(self.config, self.api, ident)
        data = queue.pointer(self.config)
        turn = data["current"]["authorization_turn_id"]
        data["current"]["journal"].append({"action": "stop", "payload": {"source_proof": {
            "human_stop": {"thread_id": ident, "item_id": status_item, "turn_id": turn}}}})
        queue.persist(self.config, data)
        before = len(self.api.calls)
        with self.assertRaisesRegex(lifecycle.LifecycleError, "cannot be verified"):
            queue.stop(self.config, self.api, ident)
        self.assertEqual(len(self.api.calls), before)


    def test_correction_is_journaled_bound_to_real_later_human_and_replayed_after_lost_response(self):
        self.api = FakeAPI([101])
        ident, _ = self.human()
        queue.start(self.config, self.api, ident)
        item = self.api.run["items"][0]
        item.update(status="done", outcome={"disposition": "researched", "reason": "Original"}, saved_revisions={"test": "original"})
        queue.coordinate(self.config, self.api, ident, "status")
        self.f.set_turn(ident, "completed")
        instruction = "Use my resale exemption, 0% tax."
        _, human_id = self.human(ident, instruction)
        with closing(sqlite3.connect(self.f.history)) as db:
            turn_id = db.execute("SELECT turn_id FROM thread_items WHERE item_id=?", (human_id,)).fetchone()[0]
        authorization = {"thread_id": ident, "turn_id": turn_id, "item_id": human_id, "instruction": instruction}
        context = {"amendment_id": str(uuid4()), "reason": "Apply the user-confirmed exemption.", "authorization": authorization}
        intent = {"item_id": 1, "kind": "save_board", "details": {"correction": context}}
        def journal_precedes_network(action, payload):
            if action in {"intent", "amend"}:
                journal = queue.pointer(self.config)["current"]["journal"]
                self.assertTrue(any(entry["action"] == action and entry["payload"].get("item_id") == 1 for entry in journal))
        self.api.before = journal_precedes_network
        response = queue.coordinate(self.config, self.api, ident, "intent", intent)
        self.assertTrue(response["operation_execution_allowed"])
        operation_id = response["operation"]["operation_id"]
        queue.coordinate(self.config, self.api, ident, "settle", {"item_id": 1, "operation_id": operation_id, "result": {"saved": True}, "units_spent": "0"})
        proof = {"liveart_analysis_id": 11, "liveart_updated_at": "current-a", "bid_board_analysis_id": 22, "bid_board_updated_at": "current-b"}
        item["current_saved_proof"] = proof
        amendment = {**context, "item_id": 1, "correction_operation_ids": [operation_id], "disposition": "researched", "checks": {}, "proof": proof}
        self.api.fail_after = "amend"
        with self.assertRaises(queue.QueueError):
            queue.coordinate(self.config, self.api, ident, "amend", amendment)
        result = queue.coordinate(self.config, self.api, ident, "amend", amendment)
        self.assertEqual(len(result["run"]["recovery_log"]), 1)
        self.assertEqual(item["outcome"]["reason"], "Original")
        before = len(self.api.calls)
        with self.assertRaisesRegex(queue.QueueError, "actual later human"):
            queue.coordinate(self.config, self.api, ident, "amend", {**amendment, "authorization": {**authorization, "instruction": "Invented instruction"}})
        self.assertEqual(len(self.api.calls), before)
        audit = self.audit(ident)
        current = queue.pointer(self.config)["current"]
        self.assertTrue(lifecycle.queue_completion_audit(self.config, ident, current, audit)["passed"])
        changed = copy.deepcopy(current)
        changed["run"]["items"][0]["current_saved_proof"]["bid_board_updated_at"] = "changed"
        self.assertFalse(lifecycle.queue_completion_audit(self.config, ident, changed, audit)["passed"])
        changed = copy.deepcopy(current)
        changed["run"]["items"][0]["operations"][0]["kind"] = "search"
        self.assertFalse(lifecycle.queue_completion_audit(self.config, ident, changed, audit)["passed"])
        for mutation in ("outcome", "saved_revisions", "recovery_log"):
            response = {"run": copy.deepcopy(current["run"])}
            if mutation == "recovery_log":
                response["run"]["recovery_log"] = []
            else:
                response["run"]["items"][0][mutation] = {"changed": True}
            with self.subTest(mutation=mutation), self.assertRaises(queue.QueueError):
                queue.record_response(self.config, {"current": copy.deepcopy(current)}, response)


if __name__ == "__main__":
    unittest.main()
