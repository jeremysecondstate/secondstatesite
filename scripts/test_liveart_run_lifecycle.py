"""Synthetic-only checks; never invokes Codex or reads a live worker database."""

from contextlib import closing
from dataclasses import replace
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest import mock
from uuid import uuid4

from scripts import liveart_run_lifecycle as lifecycle


NOW = 1_800_000_000_000
OLD = NOW // 1000 - 7201


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.state = self.folder / "state.sqlite"
        self.history = self.folder / "history.sqlite"
        self.control = self.folder / "control.json"
        self.executable = self.folder / "codex.exe"
        self.executable.write_bytes(b"synthetic executable; never run")
        with closing(sqlite3.connect(self.state)) as db, db:
            db.executescript("""
                CREATE TABLE threads (
                    id TEXT PRIMARY KEY, cwd TEXT, project_id TEXT,
                    first_user_message TEXT, created_at INTEGER, created_at_ms INTEGER,
                    updated_at INTEGER, updated_at_ms INTEGER, agent_path TEXT,
                    archived INTEGER, is_pinned INTEGER, thread_section_id TEXT,
                    rollout_path TEXT);
                CREATE TABLE thread_spawn_edges (
                    parent_thread_id TEXT, child_thread_id TEXT PRIMARY KEY, status TEXT);
                CREATE TABLE thread_read_receipts (
                    thread_id TEXT PRIMARY KEY, first_unread_turn INTEGER);
            """)
        with closing(sqlite3.connect(self.history)) as db, db:
            db.executescript("""
                CREATE TABLE thread_turns (
                    thread_id TEXT, turn_id TEXT, rollout_ordinal INTEGER,
                    status TEXT, started_at INTEGER, completed_at INTEGER);
                CREATE TABLE thread_history_projection_state (
                    thread_id TEXT PRIMARY KEY, next_rollout_byte_offset INTEGER,
                    next_rollout_ordinal INTEGER);
                CREATE TABLE thread_items (
                    thread_id TEXT, turn_id TEXT, item_id TEXT,
                    item_type TEXT, created_at_ms INTEGER, item_json TEXT);
            """)
        self.write_control()
        config_path = self.folder / "config.json"
        config_path.write_text(json.dumps({
            "schema_version": 1, "automation_id": "artprice-worker",
            "migration_epoch_ms": 1, "expected_cwd": "C:/dev/secondstatesite",
            "expected_project_id": None, "state_db": str(self.state),
            "history_db": str(self.history), "business_control": str(self.control),
            "codex_cli": str(self.executable), "archive_after_seconds": 7200,
            "command_timeout_seconds": 1,
            "allow_legacy_catalog_start": True,
        }), encoding="utf-8")
        self.config = lifecycle.load_config(config_path)
        clock = mock.patch.object(lifecycle, "now_ms", return_value=NOW)
        clock.start()
        self.addCleanup(clock.stop)

    def write_control(self, **overrides):
        value = {"active_batch": None, "paid_query_lock": None, "in_flight": [], "lots": {}}
        value.update(overrides)
        self.control.write_text(json.dumps(value), encoding="utf-8")

    def add_thread(self, *, marker=None, status="completed", when=OLD,
                   cwd="C:/dev/secondstatesite", project=None, parent=None,
                   pinned=False, section=None, edge_status="open", archived=False):
        ident = str(uuid4())
        rollout = self.folder / (ident + ".jsonl")
        rollout.write_bytes(b'{"synthetic": true}\n')
        os.utime(rollout, (when, when))
        with closing(sqlite3.connect(self.state)) as db, db:
            db.execute("INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                ident, cwd, project, marker if marker is not None else lifecycle.MARKER + "\nWork instructions",
                when, when * 1000, when, when * 1000,
                "/root/child" if parent else None, int(archived), int(pinned), section, str(rollout)))
            if parent:
                db.execute("INSERT INTO thread_spawn_edges VALUES (?,?,?)", (parent, ident, edge_status))
        with closing(sqlite3.connect(self.history)) as db, db:
            db.execute("INSERT INTO thread_turns VALUES (?,?,?,?,?,?)", (
                ident, str(uuid4()), 1, status, when, when if status in lifecycle.TERMINAL else None))
            db.execute("INSERT INTO thread_history_projection_state VALUES (?,?,?)",
                       (ident, rollout.stat().st_size, 2))
        return ident

    def set_turn(self, ident, status, when=OLD):
        with closing(sqlite3.connect(self.history)) as db, db:
            db.execute("UPDATE thread_turns SET status=?,started_at=?,completed_at=? WHERE thread_id=?",
                       (status, when, when if status in lifecycle.TERMINAL else None, ident))

    def update_thread(self, ident, **fields):
        with closing(sqlite3.connect(self.state)) as db, db:
            db.execute("UPDATE threads SET " + ",".join(k + "=?" for k in fields) + " WHERE id=?",
                       (*fields.values(), ident))

    def archive_mock(self, args, **kwargs):
        self.assertEqual(args[:2], [str(self.executable.resolve()), "archive"])
        self.assertIs(kwargs["shell"], False)
        self.assertEqual(kwargs["timeout"], 1)
        self.update_thread(args[2], archived=1)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    def outcomes(self, **kwargs):
        return {row["thread_id"]: row["status"] for row in lifecycle.watchdog(self.config, **kwargs)["runs"]}

    def test_exact_marker_workspace_project_epoch_and_roots(self):
        good = self.add_thread(cwd=r"\\?\C:\dev\SECONDSTATESITE", marker=lifecycle.MARKER + "\r\nTask")
        for marker in ("mention " + lifecycle.MARKER, " " + lifecycle.MARKER,
                       lifecycle.MARKER + "_old", "Old context\n" + lifecycle.MARKER):
            self.add_thread(marker=marker)
        self.add_thread(cwd="C:/dev/other")
        self.add_thread(project="other-project")
        self.add_thread(parent=good)
        self.add_thread(when=1)
        config = replace(self.config, migration_epoch_ms=2000)
        self.assertEqual(lifecycle.discover(config), [good])
        self.assertTrue(lifecycle.same_cwd(r"\\?\UNC\server\share", r"\\server\share"))

    def test_two_hour_age_is_activity_based_and_read_independent(self):
        old = self.add_thread()
        recent = self.add_thread(when=NOW // 1000 - 7199)
        with closing(sqlite3.connect(self.state)) as db, db:
            db.execute("INSERT INTO thread_read_receipts VALUES (?,?)", (old, 1))
        with mock.patch.object(lifecycle.subprocess, "run") as command:
            first = self.outcomes()
            with closing(sqlite3.connect(self.state)) as db, db:
                db.execute("UPDATE thread_read_receipts SET first_unread_turn=NULL")
            self.assertEqual(first, self.outcomes())
            command.assert_not_called()
        self.assertEqual(first[old], "would_archive")
        self.assertEqual(first[recent], "protected_or_recent")

    def test_native_wrapper_requires_exact_identity_and_body_anchor(self):
        message = "\n".join((
            "Automation: LiveArt Worker",
            "Automation ID: artprice-worker",
            "Automation memory: $CODEX_HOME/automations/artprice-worker/memory.md",
            "Last run: 2026-10-25T04:10:58.336Z (1792901458336)",
            "", lifecycle.MARKER, "Bounded work.",
        ))
        valid = self.add_thread(marker=message)
        crlf = self.add_thread(marker=message.replace("\n", "\r\n"))
        for invalid in (
            message.replace("Automation ID: artprice-worker", "Automation ID: another-worker"),
            message.replace("Automation: LiveArt Worker", "Automation: Other Worker"),
            message.replace("/artprice-worker/memory.md", "/another-worker/memory.md"),
            message.replace("Last run: ", "Other field: "),
            message.replace("2026-10-25T04:10:58.336Z (1792901458336)", "x" * 129),
            message.replace("\n\n" + lifecycle.MARKER, "\nSome history\n" + lifecycle.MARKER),
            message.replace("\n\n" + lifecycle.MARKER, "\n\n\n" + lifecycle.MARKER),
            "Discuss this old conversation:\n" + message,
        ):
            with self.subTest(prefix=invalid[:100]):
                self.assertFalse(lifecycle.marked_run_message(invalid))
                self.add_thread(marker=invalid)
        self.assertEqual(set(lifecycle.discover(self.config)), {valid, crlf})
        self.assertEqual(lifecycle.start(self.config, valid)["status"], "started")

    def test_recent_descendant_and_pinned_chats_are_protected(self):
        parent = self.add_thread()
        self.add_thread(parent=parent, when=NOW // 1000 - 60)
        pinned = self.add_thread(pinned=True)
        section = self.add_thread(section="pinned")
        pinned_child_parent = self.add_thread()
        self.add_thread(parent=pinned_child_parent, pinned=True)
        results = self.outcomes()
        for ident in (parent, pinned, section, pinned_child_parent):
            self.assertEqual(results[ident], "protected_or_recent")

    def test_active_unknown_missing_or_unreconciled_descendant_is_protected(self):
        for status in ("inProgress", "futureStatus"):
            with self.subTest(status=status):
                parent = self.add_thread()
                self.add_thread(parent=parent, status=status)
                with self.assertRaises(lifecycle.LifecycleError):
                    lifecycle.inspect_tree(self.config, parent)
        parent = self.add_thread()
        self.add_thread(parent=parent, edge_status="unrecognized")
        with self.assertRaises(lifecycle.LifecycleError):
            lifecycle.inspect_tree(self.config, parent)
        missing = self.add_thread()
        with closing(sqlite3.connect(self.state)) as db, db:
            db.execute("INSERT INTO thread_spawn_edges VALUES (?,?,?)", (missing, str(uuid4()), "open"))
        with self.assertRaises(lifecycle.LifecycleError):
            lifecycle.inspect_tree(self.config, missing)
        no_turn = self.add_thread()
        with closing(sqlite3.connect(self.history)) as db, db:
            db.execute("DELETE FROM thread_turns WHERE thread_id=?", (no_turn,))
        with self.assertRaises(lifecycle.LifecycleError):
            lifecycle.inspect_tree(self.config, no_turn)

    def test_unprojected_resume_blocks_cleanup_and_reclaim(self):
        previous = self.add_thread(status="inProgress")
        lifecycle.start(self.config, previous)
        self.set_turn(previous, "completed")
        with (self.folder / (previous + ".jsonl")).open("ab") as stream:
            stream.write(b'{"new_user_turn":true}\n')
        with self.assertRaisesRegex(lifecycle.LifecycleError, "unprojected"):
            lifecycle.inspect_tree(self.config, previous)
        new = self.add_thread(status="inProgress")
        self.assertEqual(lifecycle.start(self.config, new)["status"], "busy")
        with mock.patch.object(lifecycle.subprocess, "run") as command:
            self.assertEqual(self.outcomes(apply=True)[previous], "protected")
            command.assert_not_called()

    def test_current_active_start_finish_allow_projection_lag(self):
        ident = self.add_thread(status="inProgress")
        with closing(sqlite3.connect(self.history)) as db, db:
            db.execute("DELETE FROM thread_history_projection_state WHERE thread_id=?", (ident,))
        self.assertEqual(lifecycle.start(self.config, ident)["status"], "started")
        self.assertEqual(lifecycle.finish(self.config, ident)["status"], "finished")

    def test_start_finish_idempotence_and_terminal_reclaim(self):
        previous = self.add_thread(status="inProgress")
        current = self.add_thread(status="inProgress")
        self.assertEqual(lifecycle.start(self.config, previous)["status"], "started")
        self.assertEqual(lifecycle.start(self.config, previous)["status"], "already_started")
        self.assertEqual(lifecycle.start(self.config, current)["status"], "busy")
        self.assertEqual(lifecycle.finish(self.config, previous)["status"], "finished")
        self.assertEqual(lifecycle.finish(self.config, previous)["status"], "already_finished")
        self.assertEqual(lifecycle.start(self.config, previous)["status"], "already_finished")
        self.assertEqual(lifecycle.start(self.config, current)["status"], "busy")
        self.set_turn(previous, "completed")
        self.assertEqual(lifecycle.start(self.config, current)["status"], "started")
        data = lifecycle.registry(self.config)
        self.assertEqual(data["active_thread_id"], current)
        self.assertEqual(data["runs"][previous]["status"], "reconciled_terminal")
        self.assertEqual(list(self.folder.glob(".lifecycle-*")), [])

    def add_continuation_turn(self, ident, *, item_type="userMessage", created_at=NOW + 2000):
        turn_id, item_id = str(uuid4()), str(uuid4())
        with closing(sqlite3.connect(self.history)) as db, db:
            db.execute("INSERT INTO thread_turns VALUES (?,?,?,?,?,?)",
                       (ident, turn_id, 2, "inProgress", NOW // 1000 + 1, None))
            db.execute("INSERT INTO thread_items (thread_id,turn_id,item_id,item_type,created_at_ms) VALUES (?,?,?,?,?)",
                       (ident, turn_id, item_id, item_type, created_at))
        return item_id

    def test_user_directed_continuation_preserves_finished_boundary(self):
        ident = self.add_thread(status="inProgress")
        lifecycle.start(self.config, ident)
        self.assertEqual(lifecycle.finish(self.config, ident)["status"], "finished")
        self.assertEqual(lifecycle.start(self.config, ident)["status"], "already_finished")
        authorization = self.add_continuation_turn(ident)
        result = lifecycle.resume(self.config, ident, authorization)
        self.assertEqual(result["status"], "resumed")
        self.assertTrue(result["work_allowed"])
        record = lifecycle.registry(self.config)["runs"][ident]
        self.assertEqual(record["continuation_history"][0]["status"], "finished")
        self.assertEqual(record["continuation_history"][0]["finished_at_ms"], NOW)
        self.assertEqual(lifecycle.finish(self.config, ident)["status"], "finished")
        self.assertEqual(lifecycle.registry(self.config)["runs"][ident]["continuation_history"][0]["status"], "finished")

    def test_continuation_rejects_dirty_guards_and_unverified_authorization(self):
        ident = self.add_thread(status="inProgress")
        lifecycle.start(self.config, ident)
        lifecycle.finish(self.config, ident)
        authorization = self.add_continuation_turn(ident)
        before = self.config.registry.read_bytes()
        for values in ({"active_batch": {"lot": 123}}, {"paid_query_lock": {"owner": ident}},
                       {"in_flight": [123]}, {"lots": {"123": {"claim": {"owner": ident}}}},
                       {"lots": {"123": {"claims_cleared": False}}}):
            self.write_control(**values)
            with self.assertRaisesRegex(lifecycle.LifecycleError, "guards"):
                lifecycle.resume(self.config, ident, authorization)
            self.assertEqual(self.config.registry.read_bytes(), before)
        self.write_control()
        with self.assertRaisesRegex(lifecycle.LifecycleError, "human authorization"):
            lifecycle.resume(self.config, ident, str(uuid4()))
        with closing(sqlite3.connect(self.history)) as db, db:
            db.execute("UPDATE thread_items SET item_type='agentMessage' WHERE item_id=?", (authorization,))
        with self.assertRaisesRegex(lifecycle.LifecycleError, "human authorization"):
            lifecycle.resume(self.config, ident, authorization)
        self.assertEqual(self.config.registry.read_bytes(), before)

    def test_continuation_rejects_active_or_unprojected_descendant_and_changed_owner(self):
        ident = self.add_thread(status="inProgress")
        lifecycle.start(self.config, ident)
        lifecycle.finish(self.config, ident)
        authorization = self.add_continuation_turn(ident)
        child = self.add_thread(parent=ident, status="inProgress")
        with self.assertRaisesRegex(lifecycle.LifecycleError, "active or uncertain"):
            lifecycle.resume(self.config, ident, authorization)
        self.set_turn(child, "completed")
        with (self.folder / (child + ".jsonl")).open("ab") as stream:
            stream.write(b'{"unprojected":true}\n')
        with self.assertRaisesRegex(lifecycle.LifecycleError, "unprojected"):
            lifecycle.resume(self.config, ident, authorization)
        data = lifecycle.registry(self.config)
        other = self.add_thread(status="inProgress")
        data["active_thread_id"] = other
        data["runs"][other] = {"thread_id": other, "status": "active"}
        lifecycle.atomic_json(self.config.registry, data)
        with self.assertRaisesRegex(lifecycle.LifecycleError, "same registered"):
            lifecycle.resume(self.config, ident, authorization)

    def test_no_timeout_releases_an_active_owner(self):
        previous = self.add_thread(status="inProgress", when=OLD - 365 * 24 * 3600)
        lifecycle.start(self.config, previous)
        current = self.add_thread(status="inProgress")
        self.assertEqual(lifecycle.start(self.config, current)["status"], "busy")
        self.assertEqual(lifecycle.registry(self.config)["active_thread_id"], previous)

    def write_run_lot(self, ident, *, complete=False, **overrides):
        self.write_control(lots={"3399": {"owner_thread_id": ident, "scope_complete": complete,
                                          "claim": None, "known_data_units": 27,
                                          "query": {"status": "success", "never_repeat_successful": True}}},
                           latest_checkpoint={"thread_id": ident, "lot_ids": [3399]}, **overrides)

    def write_audit(self, ident, *, complete=True, **overrides):
        receipt = self.folder / "3399-receipt.json"
        receipt.write_text(json.dumps({"lot_id": 3399}), encoding="utf-8")
        audit = {"schema_version": 1, "thread_id": ident, "lot_ids": [3399],
                 "completed": [3399] if complete else [], "pending": [] if complete else [3399],
                 "bookkeeping_complete": True, "usage_accounted": True,
                 "operations_settled": True, "cleanup_complete": True,
                 "lot_receipts": {"3399": str(receipt)}}
        audit.update(overrides)
        path = self.folder / "batch-audit.json"
        path.write_text(json.dumps(audit), encoding="utf-8")
        return path

    def test_finish_cannot_turn_missing_or_incomplete_receipts_into_completion(self):
        ident = self.add_thread(status="inProgress")
        lifecycle.start(self.config, ident)
        self.write_run_lot(ident)
        before = self.control.read_bytes()
        for audit in (None, self.folder / "missing.json"):
            result = lifecycle.finish(self.config, ident, audit)
            self.assertEqual(result["status"], "completion_pending")
            self.assertTrue(result["work_allowed"])
            self.assertTrue(result["issues"])
        path = self.write_audit(ident, complete=False, pending_reason="receipt blocked by policy")
        self.assertEqual(lifecycle.finish(self.config, ident, path)["status"], "completion_pending")
        path.write_text("malformed", encoding="utf-8")
        self.assertEqual(lifecycle.finish(self.config, ident, path)["status"], "completion_pending")
        self.assertEqual(lifecycle.start(self.config, ident)["status"], "already_started")
        self.assertEqual(self.control.read_bytes(), before)

    def test_finish_audit_checks_identity_coverage_receipts_and_usage(self):
        ident = self.add_thread(status="inProgress")
        lifecycle.start(self.config, ident)
        self.write_run_lot(ident, complete=True)
        for change in ({"thread_id": str(uuid4())}, {"lot_ids": []}, {"completed": [3399, 3399]},
                       {"completed": [], "pending": []}, {"usage_accounted": False},
                       {"bookkeeping_complete": False}, {"cleanup_complete": False},
                       {"lot_receipts": {"3399": "missing.json"}}):
            with self.subTest(change=change):
                path = self.write_audit(ident, **change)
                self.assertEqual(lifecycle.finish(self.config, ident, path)["status"], "completion_pending")
        path = self.write_audit(ident)
        self.assertEqual(lifecycle.finish(self.config, ident, path)["status"], "finished")
        self.add_continuation_turn(ident)
        self.assertEqual(lifecycle.start(self.config, ident)["status"], "already_finished")

    def test_finish_allows_settled_documented_external_blocker_without_retry_loop(self):
        ident = self.add_thread(status="inProgress")
        lifecycle.start(self.config, ident)
        self.write_run_lot(ident)
        blocker = {"kind": "access_denied", "required_step": "Read the source sale page",
                   "observed_failure": "The source page shows access denied for this account",
                   "recovery_attempts": [{"action": "Check the supported signed-in source", "result": "Access denied"}],
                   "reopening_condition": "The source grants access",
                   "no_authorized_useful_action_remaining": True}
        path = self.write_audit(ident, complete=False, external_blockers={"3399": blocker})
        self.assertEqual(lifecycle.finish(self.config, ident, path)["status"], "finished")
        self.add_continuation_turn(ident)
        self.assertEqual(lifecycle.start(self.config, ident)["status"], "already_finished")
        self.set_turn(ident, "completed")
        next_run = self.add_thread(status="inProgress")
        self.assertEqual(lifecycle.start(self.config, next_run)["status"], "started")

    def legacy_finished_unfinished_run(self):
        ident = self.add_thread(status="inProgress")
        lifecycle.start(self.config, ident)
        lifecycle.finish(self.config, ident)
        # Simulate a legacy finish that checked guards but omitted receipt completion.
        self.write_run_lot(ident)
        return ident

    def test_start_automatically_resumes_unfinished_same_owner_without_human_token(self):
        ident = self.legacy_finished_unfinished_run()
        self.add_continuation_turn(ident, item_type="agentMessage")
        before = self.control.read_bytes()
        result = lifecycle.start(self.config, ident)
        self.assertEqual(result["status"], "resumed")
        self.assertTrue(result["work_allowed"])
        self.assertEqual(result["lot_ids"], ["3399"])
        self.assertEqual(lifecycle.start(self.config, ident)["status"], "already_started")
        record = lifecycle.registry(self.config)["runs"][ident]
        self.assertEqual(len(record["continuation_history"]), 1)
        self.assertEqual(record["continuation_history"][0]["status"], "finished")
        self.assertEqual(self.control.read_bytes(), before)  # No duplicate query, charge, or usage merge.
        self.assertEqual(lifecycle.finish(self.config, ident)["status"], "completion_pending")

    def test_automatic_resume_can_repair_premature_finish_within_the_same_turn(self):
        ident = self.legacy_finished_unfinished_run()
        before = self.control.read_bytes()
        self.assertEqual(lifecycle.start(self.config, ident)["status"], "resumed")
        self.assertEqual(self.control.read_bytes(), before)

    def test_automatic_resume_never_reclaims_terminal_root_or_active_descendant(self):
        ident = self.legacy_finished_unfinished_run()
        before = self.config.registry.read_bytes()
        self.set_turn(ident, "completed")
        with self.assertRaisesRegex(lifecycle.LifecycleError, "active new root"):
            lifecycle.start(self.config, ident)
        self.add_continuation_turn(ident, item_type="agentMessage")
        child = self.add_thread(parent=ident, status="inProgress")
        with self.assertRaisesRegex(lifecycle.LifecycleError, "active or uncertain"):
            lifecycle.start(self.config, ident)
        self.set_turn(child, "completed")
        with (self.folder / (child + ".jsonl")).open("ab") as stream:
            stream.write(b'{"unprojected":true}\n')
        with self.assertRaisesRegex(lifecycle.LifecycleError, "unprojected"):
            lifecycle.start(self.config, ident)
        self.assertEqual(self.config.registry.read_bytes(), before)

    def test_automatic_resume_preserves_unknown_operations_and_replaced_owner(self):
        ident = self.legacy_finished_unfinished_run()
        self.add_continuation_turn(ident, item_type="agentMessage")
        before = self.config.registry.read_bytes()
        for guard in ({"paid_query_lock": {"owner": ident}}, {"in_flight": [3399]}, {"active_batch": {"lot_ids": [3399]}}):
            self.write_run_lot(ident, **guard)
            with self.assertRaisesRegex(lifecycle.LifecycleError, "guards"):
                lifecycle.start(self.config, ident)
            self.assertEqual(self.config.registry.read_bytes(), before)
        self.write_run_lot(ident)
        data = lifecycle.registry(self.config)
        other = self.add_thread(status="inProgress")
        data["active_thread_id"] = other
        data["runs"][other] = {"thread_id": other, "status": "active"}
        lifecycle.atomic_json(self.config.registry, data)
        self.assertEqual(lifecycle.start(self.config, ident)["status"], "already_finished")
        self.assertEqual(lifecycle.registry(self.config)["active_thread_id"], other)

    def test_finish_cannot_succeed_with_active_descendants(self):
        ident = self.add_thread(status="inProgress")
        lifecycle.start(self.config, ident)
        self.add_thread(parent=ident, status="inProgress")
        with self.assertRaisesRegex(lifecycle.LifecycleError, "active or uncertain"):
            lifecycle.finish(self.config, ident)
        self.assertEqual(lifecycle.registry(self.config)["runs"][ident]["status"], "active")

    def test_recovery_audit_covers_predecessor_lots_without_changing_their_owner(self):
        previous = self.add_thread(status="inProgress")
        lifecycle.start(self.config, previous)
        self.write_run_lot(previous, paid_query_lock={"owner": previous})
        self.set_turn(previous, "completed")
        recovery = self.add_thread(status="inProgress")
        self.assertEqual(lifecycle.start(self.config, recovery)["status"], "recovery_started")
        self.set_turn(recovery, "completed")
        recovery = self.add_thread(status="inProgress")
        self.assertEqual(lifecycle.start(self.config, recovery)["status"], "recovery_started")
        self.write_run_lot(previous, complete=True)
        before = self.control.read_bytes()
        self.assertEqual(lifecycle.completion_audit(self.config, recovery)["lot_ids"], ["3399"])
        path = self.write_audit(recovery)
        self.assertEqual(lifecycle.finish(self.config, recovery, path)["status"], "finished")
        self.assertEqual(self.control.read_bytes(), before)

    def test_business_guards_prevent_finish_reclaim_and_archive(self):
        ident = self.add_thread(status="inProgress")
        lifecycle.start(self.config, ident)
        for values in ({"active_batch": {"lot": 123}}, {"paid_query_lock": {"owner": ident}},
                       {"in_flight": [123]}, {"lots": {"123": {"claim": {"owner": ident}}}}):
            with self.subTest(guard=values):
                self.write_control(**values)
                self.assertEqual(lifecycle.finish(self.config, ident)["status"], "checkpoint_pending")
                self.set_turn(ident, "completed")
                self.assertEqual(self.outcomes()[ident], "business_checkpoint_pending")
                self.set_turn(ident, "inProgress")
        self.write_control()
        self.assertEqual(lifecycle.finish(self.config, ident)["status"], "finished")

    def test_terminal_dirty_predecessor_allows_recovery_only_until_next_run(self):
        previous = self.add_thread(status="inProgress")
        recovery = self.add_thread(status="inProgress")
        next_run = self.add_thread(status="inProgress")
        lifecycle.start(self.config, previous)
        self.write_control(paid_query_lock={"owner": previous})
        original_control = self.control.read_bytes()
        self.assertEqual(lifecycle.start(self.config, recovery)["status"], "busy")
        self.set_turn(previous, "interrupted")
        result = lifecycle.start(self.config, recovery)
        self.assertEqual(result["status"], "recovery_started")
        self.assertTrue(result["recovery_only"])
        self.assertEqual(result["prior_thread_id"], previous)
        self.assertEqual(self.control.read_bytes(), original_control)
        again = lifecycle.start(self.config, recovery)
        self.assertEqual(again["status"], "already_started")
        self.assertTrue(again["recovery_only"])
        self.assertEqual(lifecycle.start(self.config, next_run)["status"], "busy")
        self.assertEqual(lifecycle.finish(self.config, recovery)["status"], "checkpoint_pending")
        self.write_control()
        self.assertEqual(lifecycle.finish(self.config, recovery)["status"], "finished")
        self.assertEqual(lifecycle.start(self.config, next_run)["status"], "busy")
        self.set_turn(recovery, "completed")
        normal = lifecycle.start(self.config, next_run)
        self.assertEqual(normal["status"], "started")
        self.assertFalse(normal["recovery_only"])

    def test_dirty_guard_without_registered_predecessor_fails_closed(self):
        self.write_control(in_flight=[123])
        ident = self.add_thread(status="inProgress")
        self.assertEqual(lifecycle.start(self.config, ident)["status"], "busy")
        self.assertFalse(self.config.registry.exists())

    def test_lock_is_exclusive_and_released_after_exception(self):
        with lifecycle.file_lock(self.config.lock):
            with self.assertRaises(lifecycle.LockBusy):
                with lifecycle.file_lock(self.config.lock):
                    self.fail("Contending process acquired the lock")
        with self.assertRaises(RuntimeError):
            with lifecycle.file_lock(self.config.lock):
                raise RuntimeError("release on exception")
        with lifecycle.file_lock(self.config.lock):
            pass

    def test_watchdog_default_is_dry_and_logs_empty_and_nonempty_checks(self):
        with mock.patch.object(lifecycle.subprocess, "run") as command:
            self.assertEqual(self.outcomes(), {})
            ident = self.add_thread()
            self.assertEqual(self.outcomes()[ident], "would_archive")
            command.assert_not_called()
        self.assertFalse(self.config.registry.exists())
        entries = [json.loads(line) for line in (self.folder / "events.jsonl").read_text().splitlines()]
        self.assertEqual([row["discovered"] for row in entries], [0, 1])
        self.assertTrue(all(row["action"] == "watchdog_checked" for row in entries))

    def test_archive_uses_argument_vector_and_confirms_state(self):
        ident = self.add_thread()
        with mock.patch.object(lifecycle.subprocess, "run", side_effect=self.archive_mock) as command:
            self.assertEqual(self.outcomes(apply=True)[ident], "archived")
            self.assertEqual(command.call_count, 1)
        self.assertEqual(lifecycle.registry(self.config)["runs"][ident]["status"], "archived")
        self.assertEqual(lifecycle.discover(self.config), [])

    def test_resume_between_checks_never_archives(self):
        ident = self.add_thread()
        original = lifecycle.inspect_tree
        inspections = 0

        def inspect(*args, **kwargs):
            nonlocal inspections
            inspections += 1
            if inspections == 2:
                self.set_turn(ident, "inProgress", NOW // 1000)
            return original(*args, **kwargs)

        with mock.patch.object(lifecycle, "inspect_tree", side_effect=inspect), \
                mock.patch.object(lifecycle.subprocess, "run") as command:
            self.assertEqual(self.outcomes(apply=True)[ident], "protected")
            command.assert_not_called()

    def test_projection_advance_between_checks_prevents_archive(self):
        ident = self.add_thread()
        original = lifecycle.inspect_tree
        inspections = 0

        def inspect(*args, **kwargs):
            nonlocal inspections
            inspections += 1
            if inspections == 2:
                with closing(sqlite3.connect(self.history)) as db, db:
                    db.execute("UPDATE thread_history_projection_state SET next_rollout_ordinal=3")
            return original(*args, **kwargs)

        with mock.patch.object(lifecycle, "inspect_tree", side_effect=inspect), \
                mock.patch.object(lifecycle.subprocess, "run") as command:
            self.assertEqual(self.outcomes(apply=True)[ident], "changed_before_archive")
            command.assert_not_called()

    def test_archive_failure_timeout_or_unconfirmed_is_recorded(self):
        for result in (subprocess.CompletedProcess([], 1, "", ""),
                       subprocess.CompletedProcess([], 0, "", ""),
                       subprocess.TimeoutExpired(["codex", "archive"], 1)):
            with self.subTest(result=type(result).__name__):
                ident = self.add_thread()
                behavior = {"side_effect": result} if isinstance(result, Exception) else {"return_value": result}
                with mock.patch.object(lifecycle.subprocess, "run", **behavior):
                    self.assertEqual(self.outcomes(apply=True)[ident], "archive_unconfirmed")
                self.assertEqual(lifecycle.registry(self.config)["runs"][ident]["archive_status"], "archive_unconfirmed")

    def test_cli_resolution_uses_config_path_then_known_upgrade_directory(self):
        with mock.patch.object(lifecycle.shutil, "which", return_value=None):
            self.assertEqual(lifecycle.resolve_cli(self.config), str(self.executable.resolve()))
            upgraded = self.folder / "OpenAI/Codex/bin/new-version/codex.exe"
            upgraded.parent.mkdir(parents=True)
            upgraded.write_bytes(b"synthetic")
            stale = replace(self.config, codex_cli=str(self.folder / "missing/codex.exe"))
            with mock.patch.dict(os.environ, {"LOCALAPPDATA": str(self.folder)}):
                self.assertEqual(lifecycle.resolve_cli(stale), str(upgraded.resolve()))
            with mock.patch.dict(os.environ, {"LOCALAPPDATA": str(self.folder / "unrelated")}):
                with self.assertRaises(lifecycle.LifecycleError):
                    lifecycle.resolve_cli(stale)


if __name__ == "__main__":
    unittest.main()
