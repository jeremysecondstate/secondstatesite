"""Manual, finite LiveArt queue coordination; never performs research or saves.

start/resume require the actual current human message 'Process my LiveArt queue'
in an active root chat in the configured workspace. Scheduling may stay PAUSED.
The server selects and freezes scope. Local durable request IDs precede network
calls, so a lost start response cannot create a second snapshot. No backlog is
imported, no continuous loop runs, and no three-lot cap applies.

Uses only the existing CATALOG_API_KEY / X-API-KEY coordination endpoint. All
research, paid provider calls and evidence/Board saves remain in their existing
supported workflows. intent/settle record those operations and their receipts;
they never execute or retry an external research/save operation.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import liveart_run_lifecycle as lifecycle


class QueueError(lifecycle.LifecycleError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class WorkerAPI:
    """Fixed coordination route; credentials never enter output or local files."""

    def __init__(self, base_url, api_key):
        parsed = urlsplit(base_url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.path not in {"", "/"}):
            raise QueueError("SECONDSTATE_BASE_URL must be an HTTPS site origin.")
        if not isinstance(api_key, str) or not api_key.strip():
            raise QueueError("Existing CATALOG_API_KEY is required for queue coordination.")
        self.url = base_url.rstrip("/") + "/calendar/research-queue/worker/"
        self.api_key = api_key.strip()

    def call(self, action, payload=None):
        data = None if action == "status" else json.dumps({"action": action, **(payload or {})}).encode("utf-8")
        url = self.url
        if action == "status" and payload:
            url += "?" + urlencode(payload)
        request = Request(url, data=data, headers={"X-API-KEY": self.api_key,
                          "Accept": "application/json", "Content-Type": "application/json"},
                          method="GET" if action == "status" else "POST")
        try:
            with build_opener(NoRedirect()).open(request, timeout=30) as response:
                raw = response.read(lifecycle.MAX_JSON_BYTES + 1)
            if len(raw) > lifecycle.MAX_JSON_BYTES:
                raise ValueError
            result = json.loads(raw)
        except HTTPError as error:
            raise QueueError(f"Queue coordination returned HTTP {error.code}; reconcile status before retrying.") from None
        except (URLError, OSError, ValueError):
            raise QueueError("Queue response is uncertain; retain the request/operation ID and reconcile status.") from None
        if not isinstance(result, dict) or result.get("ok") is not True:
            raise QueueError("Queue coordination was not confirmed; reconcile status before retrying.")
        return result


def pointer_path(config):
    return config.path.parent / "manual-queue.json"


def pointer(config):
    path = pointer_path(config)
    if not path.exists():
        return {"schema_version": 1, "current": None, "history": []}
    value = lifecycle.read_json(path)
    if (value.get("schema_version") != 1 or not isinstance(value.get("history"), list)
            or value.get("current") is not None and not isinstance(value["current"], dict)):
        raise QueueError("Manual queue pointer is invalid; preserve it for reconciliation.")
    if value["current"]:
        current = value["current"]
        for key in ("request_id", "owner_token", "owner_thread_id", "authorization_item_id"):
            lifecycle.thread_uuid(current.get(key))
    return value


def persist(config, data):
    lifecycle.atomic_json(pointer_path(config), data)


def public(value):
    if isinstance(value, dict):
        return {key: public(item) for key, item in value.items() if key not in {"owner_token", "expected_owner_token", "new_owner_token"}}
    if isinstance(value, list):
        return [public(item) for item in value]
    return value


def frozen_scope(run):
    if not isinstance(run, dict) or not isinstance(run.get("items"), list):
        raise QueueError("The server did not return a finite queue snapshot.")
    lifecycle.thread_uuid(run.get("id"))
    if run.get("status") not in {"running", "blocked", "completed"}:
        raise QueueError("The server run status is unknown; retain ownership for reconciliation.")
    ids, lots, scope = set(), set(), []
    prior_position = 0
    for item in run["items"]:
        if (not isinstance(item, dict) or type(item.get("lot_id")) is not int or item["lot_id"] <= 0
                or type(item.get("id")) is not int or item["id"] <= 0
                or type(item.get("position")) is not int or item["position"] <= prior_position
                or not isinstance(item.get("lot_snapshot"), dict) or not isinstance(item.get("note_snapshot"), str)
                or item.get("status") not in {"queued", "researching", "done", "needs_attention"}
                or not isinstance(item.get("operations"), list)):
            raise QueueError("The server snapshot contains an invalid lot.")
        if item.get("id") in ids or item["lot_id"] in lots:
            raise QueueError("The server snapshot contains duplicate items.")
        ids.add(item.get("id"))
        lots.add(item["lot_id"])
        prior_position = item["position"]
        scope.append({key: item.get(key) for key in ("id", "lot_id", "position", "lot_snapshot", "note_snapshot")})
    return scope


def record_response(config, data, response):
    run = response.get("run")
    scope = frozen_scope(run)
    current = data["current"]
    if run.get("request_id") != current["request_id"]:
        raise QueueError("Server request identity changed; preserve the original snapshot request.")
    allowed_tokens = {current["owner_token"], current.get("handoff", {}).get("new_owner_token")}
    if run.get("owner_token") not in allowed_tokens:
        raise QueueError("Server execution ownership changed; no operation may be repeated.")
    if current.get("run_id") not in {None, run["id"]}:
        raise QueueError("Server run identity changed; preserve the existing snapshot.")
    if current.get("scope") is not None and current["scope"] != scope:
        raise QueueError("Server snapshot scope changed; no further work is allowed.")
    prior = current.get("run")
    if isinstance(prior, dict):
        for old, new in zip(prior["items"], run["items"]):
            if old.get("status") in {"done", "needs_attention"} and new.get("status") != old["status"]:
                raise QueueError("A terminal snapshot item was reopened; no repeated research is allowed.")
            new_operations = {operation.get("operation_id"): operation for operation in new["operations"]}
            for operation in old["operations"]:
                updated = new_operations.get(operation.get("operation_id"))
                if updated is None or operation.get("status") == "settled" and updated != operation:
                    raise QueueError("A recorded operation disappeared or changed; preserve its original receipt.")
    current["run_id"] = run["id"]
    current["scope"] = scope
    current["run"] = copy.deepcopy(run)
    current["updated_at_ms"] = lifecycle.now_ms()
    persist(config, data)
    return response


def require_owner(config, ident, current, *, allow_settlement=False):
    ident = lifecycle.thread_uuid(ident)
    if current is None or current.get("owner_thread_id") != ident:
        raise QueueError("This chat does not own the selected snapshot; use a verified manual resume.")
    lifecycle.stored_manual_authorization(config, ident, current.get("authorization_item_id"), current.get("authorization_turn_id"))
    lifecycle.inspect_tree(config, ident, require_terminal=False, continuation=True)
    registry = lifecycle.registry(config)
    record = registry["runs"].get(ident, {})
    if (registry["active_thread_id"] != ident or not record.get("manual_queue")
            or record.get("recovery_only") or record.get("status") not in {"active", "completion_pending", "checkpoint_pending"}):
        raise QueueError("Manual lifecycle ownership does not permit fresh queue work.")
    if (current.get("stopped") or lifecycle.human_stop_requested(config, ident, current["authorization_item_id"])) and not allow_settlement:
        raise QueueError("The current human stopped this pass; only settling known outcomes and cleanup are allowed.")


def start(config, api, ident, authorization_item_id=None):
    allowance = lifecycle.start_manual(config, ident, authorization_item_id)
    if not allowance.get("work_allowed") or allowance.get("recovery_only"):
        return allowance
    with lifecycle.file_lock(config.path.parent / "manual-queue.lock"):
        data = pointer(config)
        current = data["current"]
        proof = allowance["authorization"]
        if current:
            same_request = (current["owner_thread_id"] == ident
                            and current["authorization_item_id"] == proof["item_id"])
            if current.get("finished"):
                if same_request:
                    return {"status": "already_finished", "run": public(current.get("run")), "work_allowed": False}
                data["history"].append(current)
                current = None
            elif not same_request:
                return {"status": "resume_required", "run_id": current.get("run_id"), "work_allowed": False}
        if current is None:
            current = {"request_id": str(uuid4()), "owner_token": str(uuid4()), "owner_thread_id": ident,
                       "authorization_item_id": proof["item_id"], "authorization_turn_id": proof["turn_id"],
                       "created_at_ms": lifecycle.now_ms(), "journal": []}
            data["current"] = current
            persist(config, data)  # This boundary MUST precede any network call.
        require_owner(config, ident, current)
        if not lifecycle.business_clear(config):
            raise QueueError("Business operation guards are not clear; no new snapshot may start.")
        response = api.call("start", {"request_id": current["request_id"], "owner_token": current["owner_token"],
                                      "thread_id": ident})
        record_response(config, data, response)
        return {"status": "ready", "work_allowed": True, **public(response)}


def unsettled(run):
    operations = list(run.get("operations", []))
    for item in run.get("items", []):
        operations.extend(item.get("operations", []))
    return [operation for operation in operations if operation.get("status") not in {"settled", "completed"}]


def prior_execution_terminal(config, current, ident, proof):
    prior = current["owner_thread_id"]
    if prior != ident:
        lifecycle.inspect_tree(config, prior)
    else:
        lifecycle.inspect_tree(config, ident, require_terminal=False, continuation=True)
        if current.get("authorization_turn_id") == proof["turn_id"]:
            return False  # The original owner is still executing this request.
        with lifecycle.database(config.history_db) as history:
            turn = history.execute("SELECT status,completed_at FROM thread_turns WHERE thread_id=? AND turn_id=?",
                                   (ident, current.get("authorization_turn_id"))).fetchone()
            if turn is None or turn["status"] not in lifecycle.TERMINAL or turn["completed_at"] is None:
                raise QueueError("The prior manual turn is still active or uncertain.")
    return True


def resume(config, api, ident, authorization_item_id=None, audit_path=None):
    # Verify the old execution before acquiring or changing any ownership.
    proof = lifecycle.manual_authorization(config, ident, authorization_item_id)
    with lifecycle.file_lock(config.path.parent / "manual-queue.lock"):
        data = pointer(config)
        current = data["current"]
        if not current or current.get("finished"):
            raise QueueError("There is no unfinished frozen snapshot to resume; use start.")
        prior = current["owner_thread_id"]
        terminal_prior = prior_execution_terminal(config, current, ident, proof)
        if not lifecycle.business_clear(config):
            raise QueueError("Business operation guards are not clear; unknown operations retain ownership.")
        allowance = lifecycle.start_manual(config, ident, proof["item_id"])
        if not allowance.get("work_allowed") or allowance.get("recovery_only"):
            return allowance
        if not current.get("run_id"):
            # Recover a lost start response using the ORIGINAL request and owner.
            response = api.call("start", {"request_id": current["request_id"], "owner_token": current["owner_token"],
                                          "thread_id": prior})
        else:
            response = api.call("status", {"run_id": current["run_id"]})
        record_response(config, data, response)
        if unsettled(response["run"]):
            raise QueueError("The frozen snapshot has unsettled operations; reconcile their actual outcomes before resume.")
        if response["run"].get("status") == "completed":
            audit = lifecycle.queue_completion_audit(config, ident, current, audit_path)
            if not audit["passed"]:
                return {"status": "completion_pending", "work_allowed": False, "issues": audit["issues"],
                        "reason": "The server already finished this snapshot; reconcile its local audit without research or transfer."}
            current["remote_completed_recovery"] = {"prior_thread_id": current["owner_thread_id"], "at_ms": lifecycle.now_ms()}
            current["owner_thread_id"] = ident
            current["authorization_item_id"] = proof["item_id"]
            current["authorization_turn_id"] = proof["turn_id"]
            persist(config, data)
            finished = lifecycle.finish(config, ident, audit_path)
            if finished["status"] in {"finished", "already_finished"}:
                current["finished"] = True
                persist(config, data)
            return {"status": "completed_reconciled", "work_allowed": False, "lifecycle": finished, **public(response)}
        if not terminal_prior:
            require_owner(config, ident, current)
            return {"status": "already_started", "work_allowed": True, **public(response)}
        transfer = current.get("handoff")
        if not transfer or transfer.get("thread_id") != ident or transfer.get("authorization_item_id") != proof["item_id"]:
            transfer = {"thread_id": ident, "authorization_item_id": proof["item_id"],
                        "new_owner_token": str(uuid4()), "expected_owner_token": current["owner_token"]}
            current["handoff"] = transfer
            persist(config, data)
        if response["run"].get("owner_token") == transfer["new_owner_token"] and response["run"].get("thread_id") == ident:
            pass  # A lost handoff response is reconciled from its durable token.
        else:
            response = api.call("handoff", {"run_id": current["run_id"], **{key: transfer[key] for key in ("expected_owner_token", "new_owner_token")},
                                        "reason": "Current explicit manual request; prior root and descendants verified terminal.",
                                        "thread_id": ident, "recovery_checks": {"prior_owner_terminal": True,
                                        "no_active_descendants": True, "business_operations_clear": True}})
        record_response(config, data, response)
        current["owner_token"] = transfer["new_owner_token"]
        current["owner_thread_id"] = ident
        current["authorization_item_id"] = proof["item_id"]
        current["authorization_turn_id"] = proof["turn_id"]
        current.pop("handoff", None)
        persist(config, data)
        return {"status": "resumed", "work_allowed": True, **public(response)}


def reconcile(config, api, ident, payload, receipt_path):
    """Settle one VERIFIED old operation; never authorize its execution/retry."""
    proof = lifecycle.manual_authorization(config, ident)
    with lifecycle.file_lock(config.path.parent / "manual-queue.lock"):
        data = pointer(config)
        current = data["current"]
        if not current or not current.get("run_id") or current.get("finished"):
            raise QueueError("There is no unfinished snapshot to reconcile.")
        if not prior_execution_terminal(config, current, ident, proof):
            raise QueueError("Use ordinary settle for this still-active manual owner.")
        allowance = lifecycle.start_manual(config, ident, proof["item_id"])
        if not allowance.get("work_allowed"):
            return allowance
        receipt_path = Path(receipt_path).resolve()
        if not receipt_path.is_relative_to(config.business_control.parent.resolve()):
            raise QueueError("Reconciliation receipt must be inside the business-control directory.")
        receipt = lifecycle.read_json(receipt_path)
        operation_id = lifecycle.thread_uuid(payload.get("operation_id"))
        if (receipt.get("operation_id") != operation_id or receipt.get("item_id") != payload.get("item_id")
                or receipt.get("outcome_verified") is not True or not isinstance(receipt.get("verification"), dict)
                or not all(isinstance(receipt["verification"].get(key), str) and receipt["verification"][key].strip()
                           for key in ("source", "observed_at", "observed_result"))
                or receipt.get("result") != payload.get("result")
                or "units_spent" not in payload or receipt.get("units_spent") != payload["units_spent"]):
            raise QueueError("A matching verified actual-outcome receipt and explicit usage accounting are required.")
        if any(key in payload for key in ("action", "run_id", "owner_token", "expected_owner_token", "new_owner_token")):
            raise QueueError("Reconciliation may not override identity or ownership.")
        response = api.call("status", {"run_id": current["run_id"]})
        record_response(config, data, response)
        item = next((item for item in response["run"]["items"] if item["id"] == payload.get("item_id")), None)
        if item is None or not any(op["operation_id"] == operation_id for op in item.get("operations", [])):
            raise QueueError("Reconciliation is limited to an existing operation in the frozen snapshot.")
        entry = {"action": "reconcile", "payload": copy.deepcopy(payload), "receipt_path": str(receipt_path),
                 "receipt_sha256": lifecycle.hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
                 "reconciled_by_thread_id": ident}
        if entry not in current["journal"]:
            current["journal"].append(entry)
            persist(config, data)
        prior_execution_terminal(config, current, ident, proof)
        response = api.call("settle", {"run_id": current["run_id"], "owner_token": current["owner_token"], **payload})
        record_response(config, data, response)
        return {"status": "reconciled", "operation_execution_allowed": False, **public(response)}


def stop(config, api, ident, audit_path=None):
    with lifecycle.file_lock(config.path.parent / "manual-queue.lock"):
        data = pointer(config)
        current = data["current"]
        if not current or current.get("owner_thread_id") != ident or not current.get("run_id"):
            raise QueueError("This chat does not own a confirmed snapshot to stop.")
        lifecycle.inspect_tree(config, ident, require_terminal=False, continuation=True)
        ownership = lifecycle.registry(config)
        if ownership["active_thread_id"] != ident:
            raise QueueError("The registered owner has changed; this chat cannot stop its work.")
        recorded = next((entry for entry in current["journal"] if entry.get("action") == "stop"), None)
        if recorded is not None:
            lifecycle.recorded_stop_authorization(config, current)
            payload = copy.deepcopy(recorded["payload"])
        else:
            proof = lifecycle.manual_authorization(config, ident, command="stop")
            payload = {"reason": "The current human explicitly stopped this manual queue pass.",
                       "reopening_condition": "A later explicit human queue request and verified recovery/requeue.",
                       "source_proof": {"human_stop": {"thread_id": ident, "item_id": proof["item_id"], "turn_id": proof["turn_id"]}}}
        request = {"action": "stop", "payload": payload}
        if request not in current["journal"]:
            current["journal"].append(request)
            persist(config, data)
        response = api.call("stop", {"run_id": current["run_id"], "owner_token": current["owner_token"], **payload})
        record_response(config, data, response)
        result = ({"status": "checkpoint_pending", "reason": "Unsettled queue operations retain their protections."}
                  if unsettled(response["run"]) else lifecycle.finish(config, ident, audit_path))
        current["stopped"] = True
        if result["status"] in {"finished", "already_finished"}:
            current["finished"] = True
        persist(config, data)
        return {"status": "stopped", "work_allowed": False, **public(response), "lifecycle": result}


def coordinate(config, api, ident, action, payload=None, audit_path=None):
    with lifecycle.file_lock(config.path.parent / "manual-queue.lock"):
        data = pointer(config)
        current = data["current"]
        if not current or not current.get("run_id"):
            raise QueueError("No confirmed snapshot is registered; retry the original start or resume.")
        if action == "status":
            response = api.call("status", {"run_id": current["run_id"]})
            record_response(config, data, response)
            return public(response)
        require_owner(config, ident, current, allow_settlement=action in {"settle", "finish"})
        if current.get("finished"):
            return {"status": "already_finished", "work_allowed": False}
        payload = copy.deepcopy(payload or {})
        if any(key in payload for key in ("action", "run_id", "owner_token", "expected_owner_token", "new_owner_token")):
            raise QueueError("Payload may not override queue identity or ownership.")
        if action in {"intent", "settle", "outcome", "block"}:
            if payload.get("item_id") not in {item["id"] for item in current["scope"]}:
                raise QueueError("The item is outside the frozen selected snapshot.")
        if action == "claim" and not lifecycle.business_clear(config):
            raise QueueError("Business operation guards are not clear; no next item may be claimed.")
        if action == "intent":
            comparable = {key: value for key, value in payload.items() if key != "operation_id"}
            matches = [entry for entry in current["journal"] if entry["action"] == "intent"
                       and {key: value for key, value in entry["payload"].items() if key != "operation_id"} == comparable]
            if matches and payload.get("operation_id") not in {None, matches[-1]["payload"]["operation_id"]}:
                raise QueueError("This operation already has a durable ID; preserve it rather than repeating execution.")
            if "operation_id" not in payload:
                payload["operation_id"] = matches[-1]["payload"]["operation_id"] if matches else str(uuid4())
            lifecycle.thread_uuid(payload["operation_id"])
            if not matches and not lifecycle.business_clear(config):
                raise QueueError("Business operation guards are not clear; no new operation may be authorized.")
        if action == "settle":
            lifecycle.thread_uuid(payload.get("operation_id"))
            if "units_spent" not in payload or payload["units_spent"] is None and payload.get("result", {}).get("usage_unknown") is not True:
                raise QueueError("Usage must be an explicit known decimal or null with result.usage_unknown=true.")
        if action == "finish":
            if not lifecycle.business_clear(config):
                raise QueueError("Business operation guards are not clear; finish is blocked.")
            audit = lifecycle.completion_audit(config, ident, audit_path)
            if not audit["passed"]:
                return {"status": "completion_pending", "issues": audit["issues"], "work_allowed": True}
            if audit_path is not None:
                payload["audit"] = lifecycle.read_json(audit_path)
        # Journal every write BEFORE network. Retries preserve original IDs/body.
        request = {"action": action, "payload": payload}
        replay = request in current["journal"]
        if request not in current["journal"]:
            current["journal"].append(request)
            persist(config, data)
        response = api.call(action, {"run_id": current["run_id"], "owner_token": current["owner_token"], **payload})
        record_response(config, data, response)
        if action == "intent":
            response["operation_execution_allowed"] = not replay and response.get("operation", {}).get("status") == "intent"
        if action == "finish":
            result = lifecycle.finish(config, ident, audit_path)
            if result["status"] in {"finished", "already_finished"}:
                current["finished"] = True
                persist(config, data)
            return {**public(response), "lifecycle": result}
        return public(response)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, default=lifecycle.DEFAULT_CONFIG)
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("start", "resume", "reconcile", "stop", "status", "claim", "intent", "settle", "outcome", "block", "finish"):
        command = sub.add_parser(action)
        command.add_argument("--thread-id", required=True)
        if action in {"start", "resume"}:
            command.add_argument("--authorization-item-id")
        if action in {"intent", "settle", "outcome", "block", "reconcile"}:
            command.add_argument("--payload", required=True, type=Path)
        if action == "reconcile":
            command.add_argument("--receipt", required=True, type=Path)
        if action in {"finish", "stop", "resume"}:
            command.add_argument("--audit", type=Path)
    args = parser.parse_args(argv)
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env", override=False)
        config = lifecycle.load_config(args.config)
        ident = lifecycle.thread_uuid(args.thread_id)
        api = WorkerAPI(os.environ.get("SECONDSTATE_BASE_URL", "https://secondstate.art"), os.environ.get("CATALOG_API_KEY", ""))
        if args.action in {"start", "resume"}:
            if args.action == "resume":
                result = resume(config, api, ident, args.authorization_item_id, args.audit)
            else:
                result = start(config, api, ident, args.authorization_item_id)
        elif args.action == "reconcile":
            result = reconcile(config, api, ident, lifecycle.read_json(args.payload), args.receipt)
        elif args.action == "stop":
            result = stop(config, api, ident, args.audit)
        else:
            payload = lifecycle.read_json(args.payload) if hasattr(args, "payload") else None
            result = coordinate(config, api, ident, args.action, payload, getattr(args, "audit", None))
        code = 0
    except lifecycle.LockBusy as error:
        result, code = {"status": "busy", "work_allowed": False, "reason": str(error)}, 0
    except (lifecycle.LifecycleError, OSError) as error:
        result, code = {"status": "error", "work_allowed": False,
                        "reason": str(error) if isinstance(error, lifecycle.LifecycleError) else "Local queue I/O failed."}, 1
    print(json.dumps(public(result), ensure_ascii=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
