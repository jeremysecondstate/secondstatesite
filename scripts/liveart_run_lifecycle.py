"""Local lifecycle guard and conservative archive watchdog for LiveArt run chats.

This helper never runs research, modifies business state, or writes Codex databases.
The default config is private_data/liveart-worker-runs/config.json. Example schema:
{
  "schema_version": 1, "automation_id": "artprice-worker",
  "migration_epoch_ms": 1792902000000,
  "expected_cwd": "C:/dev/secondstatesite", "expected_project_id": null,
  "state_db": "C:/Users/USER/.codex/state_5.sqlite",
  "history_db": "C:/Users/USER/.codex/thread_history_1.sqlite",
  "business_control": "C:/dev/secondstatesite/private_data/artprice-worker-validation/liveart-continuous-control-20261024.json",
  "codex_cli": "C:/Users/USER/AppData/Local/OpenAI/Codex/bin/VERSION/codex.exe",
  "archive_after_seconds": 7200, "command_timeout_seconds": 30
}
expected_project_id is required: null requires a NULL/empty database project ID.
The fixed marker LIVEART_STANDALONE_RUN_V1 must be the exact first body line,
either directly or after Codex's validated four-line native automation wrapper.
Registry, lock and event files are beside config; no source content is logged.
Use start/finish --thread-id UUID from the run chat. A busy start exits zero with
status=busy. Only started/already_started without recovery_only permits normal
work. recovery_started (or already_started with recovery_only) permits only
reconciling the prior run's known outcomes: no new lots or paid queries. Recovery
must finish and wait for the next fresh run before normal work. A finish
records a safe business boundary, but the guard is not reused until the old root
and every descendant also have terminal database turns. No timeout releases it.
watchdog is dry-run unless --apply; age is measured from last root/child activity,
not read status. Archival uses only the supported `codex archive UUID` command.
Database/schema uncertainty, pinned chats, and active descendants fail closed.
After touching lots, finish also requires --audit PATH: a version-1 JSON audit
with thread_id, lot_ids, completed, pending, lot_receipts and true
bookkeeping_complete/usage_accounted/operations_settled/cleanup_complete flags.
Pending lots need concrete external_blockers. Missing routine completion work
returns completion_pending and stays actionable. An active turn of the same
finished owner automatically resumes recorded unfinished work via start;
it needs no new human token and never writes research or usage ledgers.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import ntpath
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import tempfile
import time
from uuid import UUID


MARKER = "LIVEART_STANDALONE_RUN_V1"
NATIVE_HEADER = (
    "Automation: LiveArt Worker",
    "Automation ID: artprice-worker",
    "Automation memory: $CODEX_HOME/automations/artprice-worker/memory.md",
)
TERMINAL = {"completed", "failed", "interrupted"}
KNOWN_EDGES = {"open", "closed"}
MAX_JSON_BYTES = 10 * 1024 * 1024
MAX_TREE = 1024
DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "private_data/liveart-worker-runs/config.json"


class LifecycleError(Exception):
    """Safe, concise error without database content or credentials."""


class LockBusy(LifecycleError):
    pass


def now_ms():
    return int(time.time() * 1000)


def thread_uuid(value):
    try:
        result = str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise LifecycleError("Invalid thread UUID.") from None
    if result != value.lower():
        raise LifecycleError("Use a canonical thread UUID.")
    return result


def read_json(path):
    try:
        with Path(path).open("rb") as stream:
            raw = stream.read(MAX_JSON_BYTES + 1)
        if len(raw) > MAX_JSON_BYTES:
            raise ValueError
        value = json.loads(raw.decode("utf-8-sig"))
        if not isinstance(value, dict):
            raise ValueError
        return value
    except (OSError, UnicodeError, ValueError):
        raise LifecycleError("Required JSON file is missing, oversized, or invalid.") from None


def atomic_json(path, value):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n",
                                         dir=path.parent, prefix=".lifecycle-", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except OSError:
        raise LifecycleError("Could not persist lifecycle state.") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@contextmanager
def file_lock(path):
    """Nonblocking OS lock; a crashed/closed process cannot retain ownership."""
    stream = None
    locked = False
    try:
        stream = Path(path).open("a+b")
        if stream.seek(0, 2) == 0:
            stream.write(b" ")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError:
            raise LockBusy("Another lifecycle operation is running.") from None
        yield
    finally:
        if stream is not None:
            if locked:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            stream.close()


@dataclass(frozen=True)
class Config:
    path: Path
    automation_id: str
    migration_epoch_ms: int
    expected_cwd: str
    expected_project_id: str | None
    state_db: Path
    history_db: Path
    business_control: Path
    codex_cli: str | None
    archive_after_seconds: int
    command_timeout_seconds: int
    allow_legacy_catalog_start: bool = False

    @property
    def registry(self):
        return self.path.parent / "registry.json"

    @property
    def lock(self):
        return self.path.parent / "registry.lock"


def load_config(path):
    path = Path(path).resolve()
    value = read_json(path)
    try:
        assert value["schema_version"] == 1
        assert value["automation_id"] == "artprice-worker"
        epoch = value["migration_epoch_ms"]
        assert type(epoch) is int and epoch > 0
        cwd = value["expected_cwd"]
        assert isinstance(cwd, str) and (ntpath.isabs(cwd) or Path(cwd).is_absolute())
        project = value["expected_project_id"]
        assert project is None or isinstance(project, str) and project.strip()
        age = value.get("archive_after_seconds", 7200)
        timeout = value.get("command_timeout_seconds", 30)
        assert type(age) is int and age >= 7200
        assert type(timeout) is int and 1 <= timeout <= 60
        paths = [Path(value[k]) for k in ("state_db", "history_db", "business_control")]
        assert all(p.is_absolute() for p in paths)
        cli = value.get("codex_cli")
        assert cli is None or isinstance(cli, str)
    except (KeyError, TypeError, ValueError, AssertionError):
        raise LifecycleError("Invalid lifecycle configuration; see --help.") from None
    legacy = value.get("allow_legacy_catalog_start", False)
    if type(legacy) is not bool:
        raise LifecycleError("Invalid legacy catalog-start configuration.")
    return Config(path, value["automation_id"], epoch, cwd, project, *paths, cli, age, timeout, legacy)


@contextmanager
def database(path):
    connection = None
    try:
        connection = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        yield connection
    except sqlite3.Error:
        raise LifecycleError("Codex database is unavailable or its schema changed.") from None
    finally:
        if connection is not None:
            connection.close()


def timestamp(row, key):
    millisecond = row[key + "_ms"]
    second = row[key]
    if millisecond is not None and (type(millisecond) is not int or millisecond <= 0):
        raise LifecycleError("Uncertain thread timestamp.")
    if type(second) is not int or second <= 0:
        raise LifecycleError("Uncertain thread timestamp.")
    # Use the later clock if projection updates do not arrive together.
    return max(millisecond or 0, second * 1000)


def same_cwd(left, right):
    def normalize(value):
        if not isinstance(value, str):
            raise LifecycleError("Run workspace path is invalid.")
        value = value.replace("/", "\\")
        if value.startswith("\\\\?\\UNC\\"):
            value = "\\\\" + value[8:]
        elif value.startswith("\\\\?\\"):
            value = value[4:]
        return ntpath.normcase(ntpath.normpath(value))
    return normalize(left) == normalize(right)


def marked_run_message(message):
    if not isinstance(message, str):
        return False
    lines = message.splitlines()
    if not lines:
        return False
    if lines[0] == MARKER:
        return True
    if len(lines) < 6 or tuple(lines[:3]) != NATIVE_HEADER or lines[4] != "" or lines[5] != MARKER:
        return False
    last_run_prefix = "Last run: "
    if not lines[3].startswith(last_run_prefix):
        return False
    value = lines[3][len(last_run_prefix):]
    return 1 <= len(value) <= 128 and value.isprintable()


def scoped_root(db, config, ident, manual=False):
    row = db.execute("SELECT * FROM threads WHERE id=?", (ident,)).fetchone()
    if row is None:
        raise LifecycleError("Run thread is not present in Codex state.")
    message = row["first_user_message"]
    if not manual and not marked_run_message(message):
        raise LifecycleError("Thread is not a marked standalone LiveArt run.")
    if not same_cwd(row["cwd"], config.expected_cwd) or (row["project_id"] or None) != config.expected_project_id:
        raise LifecycleError("Run workspace or project does not match.")
    if not manual and timestamp(row, "created_at") < config.migration_epoch_ms:
        raise LifecycleError("Run predates the standalone migration.")
    if row["agent_path"] not in (None, "", "/root") or db.execute(
            "SELECT 1 FROM thread_spawn_edges WHERE child_thread_id=?", (ident,)).fetchone():
        raise LifecycleError("Only standalone root chats are eligible.")
    return row


def inspect_tree(config, ident, require_terminal=True, continuation=False, manual=False):
    """Fresh read-only snapshots of both databases, including every descendant."""
    ident = thread_uuid(ident)
    with database(config.state_db) as state, database(config.history_db) as history:
        registered_manual = registry(config)["runs"].get(ident, {}).get("manual_queue") is True
        root = scoped_root(state, config, ident, manual=manual or registered_manual)
        pending = [ident]
        seen = set()
        signature = []
        last_activity = 0
        pinned = False
        terminal = True
        while pending:
            current = pending.pop()
            if current in seen or len(seen) >= MAX_TREE:
                raise LifecycleError("Uncertain or oversized descendant tree.")
            seen.add(current)
            row = root if current == ident else state.execute("SELECT * FROM threads WHERE id=?", (current,)).fetchone()
            if row is None:
                raise LifecycleError("A descendant is missing from Codex state.")
            turn = history.execute(
                "SELECT turn_id,rollout_ordinal,status,started_at,completed_at FROM thread_turns "
                "WHERE thread_id=? ORDER BY rollout_ordinal DESC LIMIT 1", (current,)).fetchone()
            if turn is None:
                raise LifecycleError("Latest run or descendant turn is unknown.")
            if turn["status"] not in TERMINAL | {"inProgress"}:
                raise LifecycleError("Latest turn status is unknown.")
            node_requires_terminal = require_terminal or (continuation and current != ident)
            if turn["status"] not in TERMINAL or turn["completed_at"] is None:
                terminal = False
                if node_requires_terminal:
                    raise LifecycleError("Run or descendant still active or uncertain.")
            if continuation and current == ident and (turn["status"] != "inProgress" or turn["completed_at"] is not None):
                raise LifecycleError("Continuation requires an active new root turn.")
            for field in ("started_at", "completed_at"):
                value = turn[field]
                if value is not None and (type(value) is not int or value <= 0):
                    raise LifecycleError("Uncertain turn timestamp.")
            activity = max(timestamp(row, "updated_at"), timestamp(row, "created_at"),
                           (turn["started_at"] or 0) * 1000, (turn["completed_at"] or 0) * 1000)
            # The history DB is a projection. An appended, as-yet-unprojected
            # user turn must never look like an old completed turn to cleanup.
            try:
                rollout = Path(row["rollout_path"])
                before = rollout.stat()
                projection = history.execute(
                    "SELECT next_rollout_byte_offset,next_rollout_ordinal "
                    "FROM thread_history_projection_state WHERE thread_id=?", (current,)).fetchone()
                after = rollout.stat()
            except (OSError, TypeError, ValueError):
                raise LifecycleError("Rollout freshness cannot be verified.") from None
            file_signature = (str(rollout), after.st_size, after.st_mtime_ns)
            if node_requires_terminal and (
                    projection is None or projection["next_rollout_byte_offset"] != after.st_size
                    or before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns):
                raise LifecycleError("Rollout history has unprojected or changing activity.")
            activity = max(activity, after.st_mtime_ns // 1_000_000)
            last_activity = max(last_activity, activity)
            pinned |= bool(row["is_pinned"]) or row["thread_section_id"] == "pinned"
            signature.append((current, row["archived"], row["is_pinned"], row["thread_section_id"],
                              activity, tuple(turn), file_signature,
                              tuple(projection) if projection else None))
            edges = state.execute("SELECT child_thread_id,status FROM thread_spawn_edges WHERE parent_thread_id=?",
                                  (current,)).fetchall()
            for edge in edges:
                if edge["status"] not in KNOWN_EDGES:
                    raise LifecycleError("Descendant relationship status is unknown.")
                pending.append(thread_uuid(edge["child_thread_id"]))
        return {"thread_id": ident, "archived": bool(root["archived"]), "pinned": pinned,
                "terminal": terminal, "last_activity_ms": last_activity,
                "signature": sorted(signature), "descendant_count": len(seen) - 1}


def business_clear(config):
    control = read_json(config.business_control)
    required = ("active_batch", "paid_query_lock", "in_flight")
    if any(k not in control for k in required):
        raise LifecycleError("Business control is missing its operation guards.")
    if control["active_batch"] is not None or control["paid_query_lock"] is not None:
        return False
    if not isinstance(control["in_flight"], list):
        raise LifecycleError("Business in-flight state is invalid.")
    if control["in_flight"]:
        return False
    lots = control.get("lots", {})
    if not isinstance(lots, dict) or any(not isinstance(v, dict) for v in lots.values()):
        raise LifecycleError("Business lot state is invalid.")
    return not any(lot.get("claim") is not None or lot.get("claims_cleared") is False
                   for lot in lots.values())


def completion_audit(config, ident, audit_path=None):
    """Check durable completion separately from execution ownership.

    This is a validation gate, never a writer of research or usage ledgers.
    Historical pending work cannot retain global ownership, but an active run
    cannot call its routine receipt/bookkeeping omissions a successful finish.
    """
    control = read_json(config.business_control)
    lots = control.get("lots", {})
    if not isinstance(lots, dict) or any(not isinstance(v, dict) for v in lots.values()):
        raise LifecycleError("Business lot state is invalid.")
    owners = {ident}
    runs = registry(config)["runs"]
    record = runs.get(ident, {})
    if record.get("manual_queue"):
        queue_path = config.path.parent / "manual-queue.json"
        if queue_path.exists():
            pointer = read_json(queue_path).get("current")
            if pointer is not None and not isinstance(pointer, dict):
                raise LifecycleError("Manual queue pointer is invalid; preserve it for reconciliation.")
            if isinstance(pointer, dict) and pointer.get("owner_thread_id") == ident:
                return queue_completion_audit(config, ident, pointer, audit_path)
    while record.get("recovery_only") and record.get("prior_thread_id"):
        predecessor = thread_uuid(record["prior_thread_id"])
        if predecessor in owners or len(owners) >= MAX_TREE or predecessor not in runs:
            raise LifecycleError("Recovery scope ancestry is invalid.")
        owners.add(predecessor)
        record = runs[predecessor]
    touched = {str(key) for key, lot in lots.items() if lot.get("owner_thread_id") in owners}
    summaries = [control.get(key) for key in ("active_batch", "last_batch", "latest_checkpoint")]
    history = control.get("batch_history", [])
    if not isinstance(history, list):
        raise LifecycleError("Business batch history is invalid.")
    summaries.extend(history)
    for summary in summaries:
        if isinstance(summary, dict) and owners.intersection((summary.get("thread_id"), summary.get("owner_thread_id"))):
            values = summary.get("lot_ids", [])
            if not isinstance(values, list) or any(type(v) not in (int, str) for v in values):
                raise LifecycleError("Business batch lot IDs are invalid.")
            touched.update(str(value) for value in values)
    result = {"required": bool(touched), "passed": not touched, "lot_ids": sorted(touched), "issues": []}
    if audit_path is None:
        if touched:
            result["issues"].append("A current-run completion audit is required; use finish --audit PATH.")
        return result
    path = Path(audit_path).resolve()
    try:
        path.relative_to(config.business_control.parent.resolve())
    except ValueError:
        raise LifecycleError("Completion audit must be inside the business-control directory.") from None
    result["audit_path"] = str(path)
    try:
        audit = read_json(path)
    except LifecycleError:
        result["passed"] = False
        result["issues"].append("Completion audit is missing or invalid; save the audit and retry finish in this run.")
        return result
    result["audit_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    issues = result["issues"]
    if audit.get("schema_version") != 1 or audit.get("thread_id") != ident:
        issues.append("Completion audit identity or schema does not match this run.")
    sets = {}
    for key in ("lot_ids", "completed", "pending"):
        values = audit.get(key)
        if (not isinstance(values, list) or any(type(v) not in (int, str) for v in values)
                or len({str(v) for v in values}) != len(values)):
            issues.append(f"Completion audit {key} must contain distinct lot IDs.")
            sets[key] = set()
        else:
            sets[key] = {str(v) for v in values}
    if sets["lot_ids"] != touched or sets["completed"] & sets["pending"] or sets["completed"] | sets["pending"] != touched:
        issues.append("Completion audit must account for every touched lot exactly once.")
    for key in ("bookkeeping_complete", "usage_accounted", "operations_settled", "cleanup_complete"):
        if audit.get(key) is not True:
            issues.append(f"Completion audit requires {key}=true.")
    receipts = audit.get("lot_receipts", {})
    if not isinstance(receipts, dict):
        receipts = {}
    for lot_id in touched:
        receipt = receipts.get(lot_id)
        receipt_path = Path(receipt) if isinstance(receipt, str) and receipt else None
        if receipt_path is not None and not receipt_path.is_absolute():
            receipt_path = path.parent / receipt_path
        if receipt_path is None or not receipt_path.is_file():
            issues.append(f"Completion audit lacks an existing receipt reference for lot {lot_id}.")
        if lot_id in sets["completed"] and lots.get(lot_id, {}).get("scope_complete") is not True:
            issues.append(f"Lot {lot_id} is not complete in business control.")
    blockers = audit.get("external_blockers", {})
    if not isinstance(blockers, dict):
        blockers = {}
    allowed = {"external_site_failure", "access_denied", "evidence_unavailable", "tool_restriction", "deployment_restriction"}
    human_stop = False
    if audit.get("human_stop") is True and record.get("manual_queue"):
        try:
            proof = manual_authorization(config, ident, audit.get("authorization_item_id"), command="stop")
            human_stop = proof["item_id"] == audit.get("authorization_item_id")
        except LifecycleError:
            issues.append("Manual stop audit requires the actual current human stop message.")
    for lot_id in sets["pending"] if not human_stop else ():
        blocker = blockers.get(lot_id)
        if not isinstance(blocker, dict):
            blocker = {}
        text_fields = ("required_step", "observed_failure", "reopening_condition")
        attempts = blocker.get("recovery_attempts")
        valid_attempts = (isinstance(attempts, list) and bool(attempts) and all(
            isinstance(a, dict) and all(isinstance(a.get(k), str) and a[k].strip() for k in ("action", "result"))
            for a in attempts))
        if (blocker.get("kind") not in allowed or blocker.get("no_authorized_useful_action_remaining") is not True
                or not all(isinstance(blocker.get(k), str) and blocker[k].strip() for k in text_fields)
                or not valid_attempts):
            issues.append(f"Lot {lot_id} needs completion or a concrete external-blocker audit; routine bookkeeping is not a blocker.")
    result["passed"] = not issues
    return result


def queue_completion_audit(config, ident, pointer, audit_path=None):
    """Audit the entire immutable queue, independently of legacy control lots."""
    run = pointer.get("run")
    result = {"required": True, "passed": False, "lot_ids": [], "issues": []}
    if not isinstance(run, dict) or not isinstance(run.get("items"), list):
        result["issues"].append("The original snapshot response is still uncertain; reconcile it before finish.")
        return result
    items = run["items"]
    result["lot_ids"] = [str(item["lot_id"]) for item in items]
    if not items:
        result.update(required=False, passed=True)
        return result
    if audit_path is None:
        result["issues"].append("A completion audit covering the entire frozen queue is required; use --audit PATH.")
        return result
    path = Path(audit_path).resolve()
    if not path.is_relative_to(config.business_control.parent.resolve()):
        raise LifecycleError("Completion audit must be inside the business-control directory.")
    result["audit_path"] = str(path)
    try:
        audit = read_json(path)
    except LifecycleError:
        result["issues"].append("The queue completion audit is missing or invalid.")
        return result
    result["audit_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    issues = result["issues"]
    if audit.get("schema_version") != 1 or audit.get("thread_id") != ident or audit.get("run_id") != run.get("id"):
        issues.append("Queue completion audit identity must match this thread and frozen run.")
    sets = {}
    for key in ("lot_ids", "completed", "pending"):
        values = audit.get(key)
        if (not isinstance(values, list) or any(type(value) not in (int, str) for value in values)
                or len({str(value) for value in values}) != len(values)):
            issues.append(f"Queue completion audit {key} must contain distinct lot IDs.")
            sets[key] = set()
        else:
            sets[key] = {str(value) for value in values}
    done = {str(item["lot_id"]) for item in items if item.get("status") == "done"}
    attention = {str(item["lot_id"]) for item in items if item.get("status") == "needs_attention"}
    if (sets["lot_ids"] != set(result["lot_ids"]) or sets["completed"] != done or sets["pending"] != attention
            or done | attention != set(result["lot_ids"])):
        issues.append("The audit must partition every frozen lot according to its actual terminal server status.")
    for flag in ("bookkeeping_complete", "usage_accounted", "operations_settled", "cleanup_complete"):
        if audit.get(flag) is not True:
            issues.append(f"Queue completion audit requires {flag}=true.")
    receipts = audit.get("lot_receipts", {})
    receipts = receipts if isinstance(receipts, dict) else {}
    server_receipts = audit.get("server_receipts", {})
    server_receipts = server_receipts if isinstance(server_receipts, dict) else {}
    human_stop = False
    if audit.get("human_stop") is True:
        try:
            proof = recorded_stop_authorization(config, pointer, audit.get("authorization_item_id"))
            human_stop = proof["item_id"] == audit.get("authorization_item_id")
        except LifecycleError:
            issues.append("A human-stop audit requires the recorded genuine human stop message.")
    blockers = audit.get("external_blockers", {})
    blockers = blockers if isinstance(blockers, dict) else {}
    allowed = {"external_site_failure", "access_denied", "evidence_unavailable", "tool_restriction", "deployment_restriction"}
    for item in items:
        lot_id = str(item["lot_id"])
        operations = item.get("operations", [])
        if any(operation.get("status") != "settled" for operation in operations):
            issues.append(f"Lot {lot_id} has an unsettled queue operation; its protection must remain.")
        outcome = item.get("outcome", {})
        outcome = outcome if isinstance(outcome, dict) else {}
        source = outcome.get("source_proof", {})
        source = source if isinstance(source, dict) else {}
        untouched_server_receipt = (source.get("staff_queue_removal") is True or
            item.get("claimed_at") is None and not operations and
            (outcome.get("shared_block") is True or human_stop and
             (bool(source.get("human_stop")) or outcome.get("explicit_stop") is True)))
        server_reference = server_receipts.get(lot_id)
        server_receipt_valid = (untouched_server_receipt and isinstance(server_reference, dict)
                                and server_reference.get("run_id") == run["id"]
                                and server_reference.get("item_id") == item["id"])
        receipt = receipts.get(lot_id)
        receipt_path = Path(receipt) if isinstance(receipt, str) and receipt else None
        if receipt_path is not None and not receipt_path.is_absolute():
            receipt_path = path.parent / receipt_path
        if not server_receipt_valid and (receipt_path is None or not receipt_path.is_file()):
            issues.append(f"Queue lot {lot_id} needs an existing receipt or eligible durable server cancellation receipt.")
        if lot_id in attention and not human_stop:
            blocker = blockers.get(lot_id, {})
            blocker = blocker if isinstance(blocker, dict) else {}
            attempts = blocker.get("recovery_attempts")
            if (blocker.get("kind") not in allowed or blocker.get("no_authorized_useful_action_remaining") is not True
                    or not all(isinstance(blocker.get(key), str) and blocker[key].strip()
                               for key in ("required_step", "observed_failure", "reopening_condition"))
                    or not isinstance(attempts, list) or not attempts or not all(isinstance(attempt, dict)
                    and all(isinstance(attempt.get(key), str) and attempt[key].strip() for key in ("action", "result")) for attempt in attempts)):
                issues.append(f"Queue lot {lot_id} needs its concrete external-blocker audit.")
    result["passed"] = not issues
    return result


def reactivate(config, ident, data, record, *, authorization_item_id=None, unfinished_audit=None):
    """Caller holds the registry lock; recheck an active turn and settled descendants."""
    if record.get("status") != "finished" or data["active_thread_id"] != ident:
        raise LifecycleError("Continuation requires the same registered finished owner.")
    finished_at = record.get("finished_at_ms")
    if type(finished_at) is not int or finished_at <= 0:
        raise LifecycleError("Finished boundary is unknown.")
    current = inspect_tree(config, ident, require_terminal=False, continuation=True)
    if current["archived"]:
        raise LifecycleError("An archived run cannot resume work.")
    root = next(item for item in current["signature"] if item[0] == ident)
    turn_id, _ordinal, status, started_at, completed_at = root[5]
    if status != "inProgress" or completed_at is not None:
        raise LifecycleError("Continuation requires an active root turn.")
    if authorization_item_id is not None and started_at * 1000 <= finished_at:
        raise LifecycleError("Continuation requires a root turn started after the finish boundary.")
    if authorization_item_id is not None:
        with database(config.history_db) as history:
            item = history.execute(
                "SELECT item_type,created_at_ms FROM thread_items WHERE thread_id=? AND turn_id=? AND item_id=?",
                (ident, turn_id, authorization_item_id)).fetchone()
            if (item is None or item["item_type"] != "userMessage" or
                    type(item["created_at_ms"]) is not int or item["created_at_ms"] <= finished_at):
                raise LifecycleError("A later human authorization message in the active turn is required.")
    elif not unfinished_audit or not unfinished_audit["required"] or unfinished_audit["passed"]:
        raise LifecycleError("Automatic continuation requires recorded unfinished work from this run.")
    control_before = config.business_control.read_bytes()
    if not business_clear(config):
        raise LifecycleError("Business operation guards are not clear.")
    again = inspect_tree(config, ident, require_terminal=False, continuation=True)
    before_children = [entry for entry in current["signature"] if entry[0] != ident]
    after_children = [entry for entry in again["signature"] if entry[0] != ident]
    after_root = next(entry for entry in again["signature"] if entry[0] == ident)
    if (before_children != after_children or root[5] != after_root[5]
            or config.business_control.read_bytes() != control_before):
        raise LifecycleError("Run, descendant or business state changed during continuation.")
    history = record.get("continuation_history", [])
    if not isinstance(history, list):
        raise LifecycleError("Continuation history is invalid.")
    prior = {key: value for key, value in record.items() if key != "continuation_history"}
    record["continuation_history"] = [*history, prior]
    record["status"] = "active"
    record["resumed_at_ms"] = now_ms()
    record["continuation_turn_id"] = turn_id
    record.pop("finished_at_ms", None)
    record["recovery_only"] = bool(prior.get("recovery_only")) if unfinished_audit else False
    if authorization_item_id is not None:
        record["authorization_item_id"] = authorization_item_id
        record["authorization_turn_id"] = turn_id
    else:
        record["automatic_continuation"] = {"lot_ids": unfinished_audit["lot_ids"], "issues": unfinished_audit["issues"]}
    atomic_json(config.registry, data)
    event(config, "automatic_unfinished_resume" if unfinished_audit else "user_directed_resume", thread_id=ident,
          continuation_turn_id=turn_id)
    return {"status": "resumed", "thread_id": ident, "work_allowed": True,
            "recovery_only": record["recovery_only"], "lot_ids": unfinished_audit["lot_ids"] if unfinished_audit else None}


def resume(config, ident, authorization_item_id):
    """Resume a finished root only on an explicitly identified later human turn.

    The caller must verify that the referenced human message authorizes this
    continuation. This check establishes provenance, not its semantic intent.
    A later scheduled root, live child, unsettled operation or stale projection
    fails closed. The previous finished record remains in continuation_history.
    """
    ident = thread_uuid(ident)
    authorization_item_id = thread_uuid(authorization_item_id)
    with file_lock(config.lock):
        data = registry(config)
        record = data["runs"].get(ident)
        if not record:
            raise LifecycleError("Continuation requires the same registered finished owner.")
        return reactivate(config, ident, data, record, authorization_item_id=authorization_item_id)


def registry(config):
    if not config.registry.exists():
        return {"schema_version": 1, "automation_id": config.automation_id,
                "active_thread_id": None, "runs": {}}
    value = read_json(config.registry)
    if value.get("schema_version") != 1 or value.get("automation_id") != config.automation_id or not isinstance(value.get("runs"), dict) or "active_thread_id" not in value:
        raise LifecycleError("Lifecycle registry is invalid.")
    if any(not isinstance(record, dict) for record in value["runs"].values()):
        raise LifecycleError("Lifecycle registry contains an invalid run.")
    active = value.get("active_thread_id")
    if active is not None and (thread_uuid(active) not in value["runs"]):
        raise LifecycleError("Lifecycle registry owner is missing.")
    return value


def event(config, action, **fields):
    record = {"at_ms": now_ms(), "action": action, **fields}
    with (config.path.parent / "events.jsonl").open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(record, ensure_ascii=True) + "\n")
        stream.flush()


def manual_message_text(raw):
    try:
        message = json.loads(raw)
        content = message["content"]
        if message.get("type") != "userMessage" or not isinstance(content, list) or not content:
            raise ValueError
        if any(not isinstance(part, dict) or part.get("type") not in {"text", "input_text"}
               or not isinstance(part.get("text"), str) for part in content):
            raise ValueError
        return " ".join(" ".join(part["text"] for part in content).split()).casefold().rstrip(".! ")
    except (ValueError, KeyError, TypeError):
        raise LifecycleError("The human authorization message cannot be verified.") from None


def stored_manual_authorization(config, ident, item_id, turn_id):
    """Harmless later steering does not revoke an already authorized snapshot."""
    item_id = thread_uuid(item_id)
    with database(config.history_db) as history:
        item = history.execute("SELECT item_type,item_json FROM thread_items WHERE thread_id=? AND turn_id=? AND item_id=?",
                               (ident, turn_id, item_id)).fetchone()
        if (item is None or item["item_type"] != "userMessage" or
                manual_message_text(item["item_json"]) not in {"process my liveart queue", "please process my liveart queue"}):
            raise LifecycleError("The original human queue authorization cannot be verified.")


def is_stop_message(text):
    return bool(re.match(r"^(?:please )?(?:stop|pause|cancel)(?:\s|$)", text))


def recorded_stop_authorization(config, pointer, authorization_item_id=None):
    """Validate the original real stop, retaining it through later steering.

    The journal precedes the server stop request. Reusing that exact receipt is
    required after a lost response; a new human message cannot rewrite it.
    """
    journal = pointer.get("journal", [])
    if not isinstance(journal, list):
        raise LifecycleError("The recorded stop journal is invalid.")
    stop = next((entry for entry in journal if isinstance(entry, dict) and entry.get("action") == "stop"), None)
    try:
        source = stop["payload"]["source_proof"]["human_stop"]
        ident = thread_uuid(source["thread_id"])
        item_id = thread_uuid(source["item_id"])
        turn_id = thread_uuid(source["turn_id"])
    except (TypeError, KeyError):
        raise LifecycleError("A recorded genuine human stop receipt is required.") from None
    if authorization_item_id is not None and item_id != thread_uuid(authorization_item_id):
        raise LifecycleError("The audit must reference the original recorded human stop item.")
    with database(config.state_db) as state, database(config.history_db) as history:
        scoped_root(state, config, ident, manual=True)
        item = history.execute("SELECT item_type,created_at_ms,item_json FROM thread_items "
                               "WHERE thread_id=? AND turn_id=? AND item_id=?", (ident, turn_id, item_id)).fetchone()
        if (item is None or item["item_type"] != "userMessage" or type(item["created_at_ms"]) is not int
                or type(pointer.get("created_at_ms")) is not int or item["created_at_ms"] < pointer["created_at_ms"]
                or not is_stop_message(manual_message_text(item["item_json"]))):
            raise LifecycleError("The recorded human stop cannot be verified against this snapshot.")
        return {"thread_id": ident, "item_id": item_id, "turn_id": turn_id, "created_at_ms": item["created_at_ms"]}


def human_stop_requested(config, ident, since_item_id):
    with database(config.history_db) as history:
        original = history.execute("SELECT created_at_ms FROM thread_items WHERE thread_id=? AND item_id=? AND item_type='userMessage'",
                                   (ident, since_item_id)).fetchone()
        if original is None:
            raise LifecycleError("The latest human steering message cannot be verified.")
        items = history.execute("SELECT item_json FROM thread_items WHERE thread_id=? AND item_type='userMessage' "
                                "AND created_at_ms>=?", (ident, original["created_at_ms"])).fetchall()
        return any(is_stop_message(manual_message_text(item["item_json"])) for item in items)


def manual_authorization(config, ident, authorization_item_id=None, *, command="queue"):
    """Accept only the actual latest human message in the current active root turn.

    A CLI flag, an old first message, an agent message, or quoted instructions
    cannot manufacture permission. The narrow command is deliberately exact.
    """
    ident = thread_uuid(ident)
    if authorization_item_id is not None:
        authorization_item_id = thread_uuid(authorization_item_id)
    with database(config.state_db) as state, database(config.history_db) as history:
        root = scoped_root(state, config, ident, manual=True)
        if root["archived"]:
            raise LifecycleError("An archived run cannot start work.")
        turn = history.execute(
            "SELECT turn_id,status,started_at,completed_at FROM thread_turns WHERE thread_id=? "
            "ORDER BY rollout_ordinal DESC LIMIT 1", (ident,)).fetchone()
        if turn is None or turn["status"] != "inProgress" or turn["completed_at"] is not None:
            raise LifecycleError("Manual queue work requires an active current root turn.")
        item = history.execute(
            "SELECT item_id,item_type,created_at_ms,item_json FROM thread_items "
            "WHERE thread_id=? AND turn_id=? AND item_type='userMessage' "
            "ORDER BY created_at_ms DESC LIMIT 1", (ident, turn["turn_id"])).fetchone()
        if (item is None or authorization_item_id is not None and item["item_id"] != authorization_item_id
                or type(item["created_at_ms"]) is not int
                or type(turn["started_at"]) is not int
                or item["created_at_ms"] < turn["started_at"] * 1000):
            raise LifecycleError("The current human authorization message cannot be verified.")
        text = manual_message_text(item["item_json"])
        accepted = ({"stop", "please stop", "stop processing my liveart queue", "stop my liveart queue",
                     "please stop processing my liveart queue"} if command == "stop" else
                    {"process my liveart queue", "please process my liveart queue"})
        if text not in accepted and not (command == "stop" and is_stop_message(text)):
            raise LifecycleError("The current human message does not explicitly authorize this manual queue command.")
        return {"item_id": thread_uuid(item["item_id"]), "turn_id": turn["turn_id"],
                "created_at_ms": item["created_at_ms"]}


def start_manual(config, ident, authorization_item_id=None):
    """Acquire existing conservative guards for one finite, human selected queue."""
    ident = thread_uuid(ident)
    with file_lock(config.lock):
        proof = manual_authorization(config, ident, authorization_item_id)
        current = inspect_tree(config, ident, require_terminal=False, continuation=True, manual=True)
        data = registry(config)
        previous = data["active_thread_id"]
        record = data["runs"].get(ident)
        if previous == ident and record:
            if not record.get("manual_queue"):
                raise LifecycleError("The current owner belongs to a prior catalog run; finish its recorded scope first.")
            if record.get("status") == "finished":
                if record.get("authorization_item_id") == proof["item_id"]:
                    return {"status": "already_finished", "thread_id": ident, "work_allowed": False}
                result = reactivate(config, ident, data, record, authorization_item_id=proof["item_id"])
                result["authorization"] = proof
                return result
            if record.get("status") in {"archived", "reconciled_terminal"}:
                raise LifecycleError("This manual owner has already been replaced.")
            return {"status": "already_started", "thread_id": ident, "work_allowed": True,
                    "recovery_only": bool(record.get("recovery_only")), "authorization": proof}
        recovery_only = False
        if previous:
            try:
                inspect_tree(config, previous)
            except LifecycleError:
                return {"status": "busy", "thread_id": ident, "work_allowed": False}
            recovery_only = not business_clear(config)
        elif not business_clear(config):
            return {"status": "busy", "thread_id": ident, "work_allowed": False}
        # Recheck the actual current human message and all activity before mutation.
        if manual_authorization(config, ident, proof["item_id"]) != proof:
            raise LifecycleError("Manual authorization changed during startup.")
        again = inspect_tree(config, ident, require_terminal=False, continuation=True, manual=True)
        if current["signature"] != again["signature"]:
            raise LifecycleError("Run or descendant state changed during manual startup.")
        if previous:
            inspect_tree(config, previous)
            data["runs"][previous]["status"] = "reconciled_terminal"
            data["runs"][previous]["reconciled_at_ms"] = now_ms()
        prior_record = data["runs"].get(ident)
        record = {"thread_id": ident, "status": "active", "started_at_ms": now_ms(),
                  "manual_queue": True, "recovery_only": recovery_only, "prior_thread_id": previous,
                  "authorization_item_id": proof["item_id"], "authorization_turn_id": proof["turn_id"]}
        if prior_record:
            record["continuation_history"] = [*prior_record.get("continuation_history", []),
                                                {k: v for k, v in prior_record.items() if k != "continuation_history"}]
        data["runs"][ident] = record
        data["active_thread_id"] = ident
        atomic_json(config.registry, data)
        status = "recovery_started" if recovery_only else "started"
        event(config, "manual_" + status, thread_id=ident)
        return {"status": status, "thread_id": ident, "work_allowed": True,
                "recovery_only": recovery_only, "prior_thread_id": previous, "authorization": proof}


def start(config, ident):
    ident = thread_uuid(ident)
    with file_lock(config.lock):
        current = inspect_tree(config, ident, require_terminal=False)
        if current["archived"]:
            raise LifecycleError("An archived run cannot start work.")
        data = registry(config)
        previous = data["active_thread_id"]
        existing = data["runs"].get(ident)
        if existing and existing.get("manual_queue"):
            return {"status": "manual_required", "thread_id": ident, "work_allowed": False,
                    "reason": "Use the manual queue helper to verify the actual current human request."}
        if existing and existing.get("status") in {"finished", "reconciled_terminal", "archived"}:
            if existing.get("status") == "finished" and previous == ident and not existing.get("manual_queue"):
                audit = completion_audit(config, ident, existing.get("completion_audit_path"))
                if audit["required"] and not audit["passed"]:
                    return reactivate(config, ident, data, existing, unfinished_audit=audit)
            return {"status": "already_finished", "thread_id": ident, "work_allowed": False}
        if previous == ident:
            return {"status": "already_started", "thread_id": ident, "work_allowed": True,
                    "recovery_only": bool(existing.get("recovery_only")),
                    "prior_thread_id": existing.get("prior_thread_id")}
        recovery_only = False
        if previous:
            try:
                inspect_tree(config, previous)
            except LifecycleError:
                event(config, "start_busy", thread_id=ident, active_thread_id=previous)
                return {"status": "busy", "thread_id": ident, "work_allowed": False}
            recovery_only = not business_clear(config)
            data["runs"][previous]["status"] = "reconciled_terminal"
            data["runs"][previous]["reconciled_at_ms"] = now_ms()
        elif not business_clear(config):
            event(config, "start_busy", thread_id=ident, reason="business_guard_not_clear")
            return {"status": "busy", "thread_id": ident, "work_allowed": False}
        if not recovery_only and not config.allow_legacy_catalog_start:
            return {"status": "manual_required", "thread_id": ident, "work_allowed": False,
                    "reason": "Fresh work requires the manually selected LiveArt queue entry point."}
        data["runs"][ident] = {"thread_id": ident, "status": "active", "started_at_ms": now_ms(),
                              "recovery_only": recovery_only, "prior_thread_id": previous}
        data["active_thread_id"] = ident
        atomic_json(config.registry, data)
        status = "recovery_started" if recovery_only else "started"
        event(config, status, thread_id=ident, prior_thread_id=previous)
        return {"status": status, "thread_id": ident, "work_allowed": True,
                "recovery_only": recovery_only, "prior_thread_id": previous}


def finish(config, ident, audit_path=None):
    ident = thread_uuid(ident)
    with file_lock(config.lock):
        inspect_tree(config, ident, require_terminal=False)
        data = registry(config)
        if ident not in data["runs"]:
            raise LifecycleError("Cannot finish an unregistered run.")
        record = data["runs"][ident]
        if record.get("status") in {"finished", "reconciled_terminal", "archived"}:
            return {"status": "already_finished", "thread_id": ident}
        if data["active_thread_id"] != ident:
            raise LifecycleError("Only the registered owner can finish.")
        inspect_tree(config, ident, require_terminal=False, continuation=True)
        clear = business_clear(config)
        audit = completion_audit(config, ident, audit_path) if clear else None
        record["status"] = "checkpoint_pending" if not clear else "finished" if audit["passed"] else "completion_pending"
        record["finished_at_ms" if record["status"] == "finished" else "checkpoint_pending_at_ms"] = now_ms()
        if audit is not None:
            record["completion_audit"] = audit
            if audit.get("audit_path"):
                record["completion_audit_path"] = audit["audit_path"]
        # Keep the active guard until a later start sees terminal DB turns too.
        atomic_json(config.registry, data)
        event(config, record["status"], thread_id=ident)
        result = {"status": record["status"], "thread_id": ident, "guard_retained_until_terminal": True}
        if record["status"] == "completion_pending":
            result.update(work_allowed=True, recovery_only=bool(record.get("recovery_only")),
                          lot_ids=audit["lot_ids"], issues=audit["issues"])
        return result


def resolve_cli(config):
    def valid(value):
        if not value:
            return None
        path = Path(value)
        if path.is_absolute() and path.is_file() and path.name.lower() in {"codex.exe", "codex"}:
            return str(path.resolve())
        return None

    for candidate in (config.codex_cli, shutil.which("codex")):
        if found := valid(candidate):
            return found
    local = os.environ.get("LOCALAPPDATA")
    if local:
        root = Path(local) / "OpenAI/Codex/bin"
        candidates = sorted(root.glob("*/codex.exe"), key=lambda p: p.stat().st_mtime, reverse=True)
        for candidate in candidates:
            if candidate.resolve().is_relative_to(root.resolve()) and (found := valid(candidate)):
                return found
    raise LifecycleError("A current Codex executable could not be resolved.")


def discover(config):
    manual = {ident for ident, record in registry(config)["runs"].items() if record.get("manual_queue")}
    with database(config.state_db) as db:
        rows = db.execute(
            "SELECT id FROM threads WHERE archived=0 "
            "AND (first_user_message LIKE ? OR first_user_message LIKE ?)",
            (MARKER + "%", NATIVE_HEADER[0] + "%")).fetchall()
        found = []
        for row in rows:
            if row["id"] in manual:
                continue
            try:
                scoped_root(db, config, row["id"])
                found.append(thread_uuid(row["id"]))
            except LifecycleError:
                continue
        return found


def archive_eligible(config, snapshot, clock):
    if snapshot["archived"] or snapshot["pinned"] or not snapshot["terminal"]:
        return False
    return clock - snapshot["last_activity_ms"] >= config.archive_after_seconds * 1000


def watchdog(config, apply=False):
    results = []
    # Separate lock: a slow CLI must not hold the start/finish registry lock.
    with file_lock(config.path.parent / "watchdog.lock"):
        executable = resolve_cli(config) if apply else None
        for ident in discover(config):
            try:
                first = inspect_tree(config, ident)
                if not archive_eligible(config, first, now_ms()):
                    results.append({"thread_id": ident, "status": "protected_or_recent"})
                    continue
                with file_lock(config.lock):
                    data = registry(config)
                    if data["active_thread_id"] == ident and not business_clear(config):
                        results.append({"thread_id": ident, "status": "business_checkpoint_pending"})
                        continue
                if not apply:
                    results.append({"thread_id": ident, "status": "would_archive"})
                    continue
                # Fresh snapshots immediately before the supported CLI command.
                latest = inspect_tree(config, ident)
                if latest["signature"] != first["signature"] or not archive_eligible(config, latest, now_ms()):
                    results.append({"thread_id": ident, "status": "changed_before_archive"})
                    continue
                with file_lock(config.lock):
                    data = registry(config)
                    if data["active_thread_id"] == ident and not business_clear(config):
                        results.append({"thread_id": ident, "status": "business_checkpoint_pending"})
                        continue
                try:
                    completed = subprocess.run([executable, "archive", ident], shell=False,
                                               capture_output=True, text=True, check=False,
                                               timeout=config.command_timeout_seconds,
                                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                    returncode = completed.returncode
                    # Output is deliberately not persisted: the saved DB state confirms archival.
                    try:
                        archived = inspect_tree(config, ident)["archived"]
                    except LifecycleError:
                        archived = False
                    outcome = "archived" if archived else "archive_unconfirmed"
                except (subprocess.TimeoutExpired, OSError):
                    returncode = None
                    outcome = "archive_unconfirmed"
                with file_lock(config.lock):
                    data = registry(config)
                    record = data["runs"].setdefault(ident, {"thread_id": ident})
                    record["archive_attempt_at_ms"] = now_ms()
                    record["archive_status"] = outcome
                    if outcome == "archived":
                        record["status"] = "archived"
                    atomic_json(config.registry, data)
                    event(config, outcome, thread_id=ident, returncode=returncode)
                results.append({"thread_id": ident, "status": outcome})
            except LifecycleError as error:
                results.append({"thread_id": ident, "status": "protected", "reason": str(error)})
        with file_lock(config.lock):
            counts = {}
            for result in results:
                counts[result["status"]] = counts.get(result["status"], 0) + 1
            event(config, "watchdog_checked", apply=apply, discovered=len(results), outcomes=counts)
        return {"status": "checked", "apply": apply, "runs": results}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    sub = parser.add_subparsers(dest="action", required=True)
    start_parser = sub.add_parser("start")
    start_parser.add_argument("--thread-id", required=True)
    start_parser.add_argument("--manual", action="store_true", help="Require the actual current human queue request.")
    start_parser.add_argument("--authorization-item-id")
    finish_parser = sub.add_parser("finish")
    finish_parser.add_argument("--thread-id", required=True)
    finish_parser.add_argument("--audit", type=Path, help="Current-run JSON completion audit; required after touching lots.")
    resume_parser = sub.add_parser("resume")
    resume_parser.add_argument("--thread-id", required=True)
    resume_parser.add_argument("--authorization-item-id", required=True)
    sub.add_parser("watchdog").add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        if args.action == "watchdog":
            result = watchdog(config, args.apply)
        elif args.action == "resume":
            result = resume(config, args.thread_id, args.authorization_item_id)
        elif args.action == "finish":
            result = finish(config, args.thread_id, args.audit)
        elif args.action == "start" and args.manual:
            result = start_manual(config, args.thread_id, args.authorization_item_id)
        else:
            result = globals()[args.action](config, args.thread_id)
        code = 0
    except LockBusy as error:
        result, code = {"status": "busy", "work_allowed": False, "reason": str(error)}, 0
    except (LifecycleError, OSError) as error:
        result, code = {"status": "error", "work_allowed": False, "reason": str(error) if isinstance(error, LifecycleError) else "Local lifecycle I/O failed."}, 1
    print(json.dumps(result, ensure_ascii=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
