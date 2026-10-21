#!/usr/bin/env python3
"""Durable local handoff for the Inventory scheduled chat.

The chat researches a claimed request and edits the workbook. This helper owns
authenticated transport, claim recovery, and exact completion replay. Secrets
and staff conversation text are stored only in the ignored state directory.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from urllib import error, parse, request
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[1]
STATE_ROOT = ROOT / "private_data" / "inventory-runs"
MAX_BYTES = 1_000_000
WORKER_ID = "inventory-codex"
TERMINAL_STATUSES = {"completed", "failed", "expired", "superseded", "retry", "cancelled"}


class InventoryError(Exception):
    pass


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_origin(value):
    p = parse.urlsplit(value)
    try:
        p.port
    except ValueError as exc:
        raise InventoryError("Invalid Inventory origin port.") from exc
    if (p.scheme not in ("http", "https") or not p.hostname or p.username is not None
            or p.password is not None or p.path not in ("", "/") or p.query or p.fragment
            or (p.scheme == "http" and p.hostname not in ("localhost", "127.0.0.1", "::1"))):
        raise InventoryError("Inventory requires an HTTPS origin (HTTP allowed for loopback testing).")
    return value.rstrip("/")


class InventoryAPI:
    def __init__(self, base_url, token):
        self.base_url = validate_origin(base_url)
        if not token or any(c.isspace() for c in token):
            raise InventoryError("Inventory worker credential is not configured.")
        self.token = token
        self.opener = request.build_opener(request.ProxyHandler({}), NoRedirect())

    def post(self, path, payload):
        if not path.startswith("/inventory/api/") or "?" in path:
            raise InventoryError("Invalid Inventory endpoint.")
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if len(data) > MAX_BYTES:
            raise InventoryError("Inventory request exceeds the size limit.")
        req = request.Request(self.base_url + path, data=data, method="POST", headers={
            "Authorization": "Bearer " + self.token,
            "Content-Type": "application/json", "Accept": "application/json",
        })
        try:
            with self.opener.open(req, timeout=30) as response:
                raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise InventoryError("Inventory response exceeds the size limit.")
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except error.HTTPError as exc:
            status = exc.code
            exc.close()
            raise InventoryError(f"Inventory API returned HTTP {status}.") from None
        except (error.URLError, TimeoutError, OSError):
            raise InventoryError("Inventory transport failed; retain the handoff and retry the same operation.") from None
        except (ValueError, UnicodeError):
            raise InventoryError("Inventory API returned invalid JSON.") from None


def read_json(path):
    if path.stat().st_size > MAX_BYTES:
        raise InventoryError("Inventory state exceeds the size limit.")
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise InventoryError("Expected a JSON object.")
    return value


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


@contextmanager
def locked(root):
    root.mkdir(parents=True, exist_ok=True)
    handle = (root / ".worker.lock").open("a+b")
    try:
        handle.seek(0)
        if not handle.read(1):
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise InventoryError("Another Inventory handoff command is running.") from None
        yield
    finally:
        handle.close()


def claim_fields(state):
    try:
        job = state["claim"]["job"]
        for key in ("id", "case_id", "claim_token"):
            UUID(str(job[key]))
        if isinstance(job["message_id"], bool):
            raise ValueError()
        message_id = int(job["message_id"])
        if message_id < 1 or not isinstance(state["worker_id"], str) or not state["worker_id"]:
            raise ValueError()
    except (KeyError, ValueError, TypeError, AttributeError):
        raise InventoryError("Invalid saved Inventory claim.") from None
    return {"worker_id": state["worker_id"], "case_id": job["case_id"],
            "message_id": message_id, "claim_token": job["claim_token"]}


def endpoint(state, action):
    claim_fields(state)
    return f"/inventory/api/jobs/{state['claim']['job']['id']}/{action}/"


def response_status(response):
    job = response.get("job")
    status = job.get("status") if isinstance(job, dict) else None
    if status not in TERMINAL_STATUSES | {"processing"}:
        raise InventoryError("Inventory API returned an unrecognized job status; retain the handoff.")
    return status


def archive_terminal(state_path, active, response):
    status = response_status(response)
    write_json(state_path.with_suffix(".status.json"), response)
    active.unlink()
    return {"status": "previous_" + status, "state_file": str(state_path)}


def prepare(api, root=STATE_ROOT):
    with locked(root):
        active = root / "active.json"
        if active.exists():
            pointer = read_json(active)
            state_path = root / (str(UUID(pointer["request_id"])) + ".json")
            state = read_json(state_path)
            if state.get("base_url") != api.base_url:
                raise InventoryError("Active Inventory handoff belongs to a different site.")
            if state.get("claim", {}).get("job"):
                response = api.post(endpoint(state, "status"), claim_fields(state))
                if response_status(response) in TERMINAL_STATUSES:
                    return archive_terminal(state_path, active, response)
                return {"status": "inventory_resume_required", "state_file": str(state_path),
                        "job_id": state["claim"]["job"]["id"],
                        "completion_prepared": state_path.with_suffix(".completion.json").exists()}
        else:
            request_id = str(uuid4())
            state_path = root / (request_id + ".json")
            state = {"version": 1, "request_id": request_id, "worker_id": WORKER_ID,
                     "base_url": api.base_url, "prepared_at": datetime.now(timezone.utc).isoformat()}
            write_json(state_path, state)
            write_json(active, {"request_id": request_id})
        claim = api.post("/inventory/api/claim/", {
            "worker_id": state["worker_id"], "request_id": state["request_id"],
        })
        if "job" in claim and claim["job"] is None:
            active.unlink()
            return {"status": "idle"}
        if not isinstance(claim.get("job"), dict):
            raise InventoryError("Inventory API returned an invalid claim; retain the handoff.")
        state["claim"] = claim
        claim_fields(state)
        write_json(state_path, state)
        if response_status(claim) in TERMINAL_STATUSES:
            return archive_terminal(state_path, active, claim)
        return {"status": "inventory_work_required", "state_file": str(state_path),
                "job_id": claim["job"]["id"], "lease_expires_at": claim["job"]["lease_expires_at"]}


def saved_state(path, api):
    state = read_json(path)
    if state.get("base_url") != api.base_url:
        raise InventoryError("Saved handoff belongs to a different site.")
    claim_fields(state)
    return state


def complete(api, state_path, result_path=None):
    with locked(state_path.parent):
        state = saved_state(state_path, api)
        payload_path = state_path.with_suffix(".completion.json")
        if payload_path.exists():
            payload = read_json(payload_path)
            if (set(payload) != set(claim_fields(state)) | {"body", "result"}
                    or any(payload.get(key) != value for key, value in claim_fields(state).items())
                    or not isinstance(payload.get("body"), str) or not isinstance(payload.get("result"), dict)):
                raise InventoryError("Prepared completion does not match this Inventory claim.")
            if result_path:
                supplied = read_json(result_path)
                if supplied != {"body": payload["body"], "result": payload["result"]}:
                    raise InventoryError("A completion is already prepared; replay its exact saved content.")
        else:
            if result_path is None:
                raise InventoryError("No saved completion is available to replay.")
            supplied = read_json(result_path)
            if set(supplied) != {"body", "result"} or not isinstance(supplied["body"], str) or not isinstance(supplied["result"], dict):
                raise InventoryError("Completion needs exactly body text and a result object.")
            payload = {**claim_fields(state), **supplied}
            write_json(payload_path, payload)
        receipt = api.post(endpoint(state, "complete"), payload)
        if (not isinstance(receipt.get("already_completed"), bool)
                or not isinstance(receipt.get("reply_id"), int)
                or isinstance(receipt["reply_id"], bool) or receipt["reply_id"] < 1):
            raise InventoryError("Inventory API did not confirm completion; retain the prepared result and replay it.")
        write_json(state_path.with_suffix(".receipt.json"), receipt)
        active = state_path.parent / "active.json"
        if active.exists() and read_json(active).get("request_id") == state["request_id"]:
            active.unlink()
        return {"status": "completed", "job_id": state["claim"]["job"]["id"],
                "receipt_file": str(state_path.with_suffix(".receipt.json")),
                "reply_id": receipt.get("reply_id"), "case_url": receipt.get("case_url"),
                "body_sha256": hashlib.sha256(payload["body"].encode()).hexdigest()}


def main():
    from dotenv import load_dotenv
    load_dotenv(ROOT / "private_data" / "coordinate-production.env", override=False)
    load_dotenv(ROOT / "private_data" / "inventory-production.env", override=True)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.environ.get("INVENTORY_BASE_URL", "https://secondstate.art"))
    parser.add_argument("--state", type=Path)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--prepare", action="store_true")
    group.add_argument("--search", type=Path, help="JSON containing bounded lot lookup fields")
    group.add_argument("--purchases", type=Path, help="JSON containing exact lot identity records")
    group.add_argument("--complete", type=Path, help="JSON containing body and result")
    group.add_argument("--replay-completion", action="store_true")
    group.add_argument("--status", action="store_true")
    group.add_argument("--fail", help="Short safe error, excluding credentials or private document text")
    parser.add_argument("--output", type=Path, help="Save lookup/status JSON privately instead of printing details")
    args = parser.parse_args()
    try:
        api = InventoryAPI(args.base_url, os.environ.get("INVENTORY_WORKER_TOKEN") or os.environ.get("COORDINATE_WORKER_TOKEN", ""))
        if args.search:
            result = api.post("/inventory/api/lots/search/", {**read_json(args.search), "worker_id": WORKER_ID})
        elif args.complete or args.replay_completion:
            if not args.state:
                raise InventoryError("--state is required.")
            result = complete(api, args.state, args.complete)
        elif args.status or args.purchases or args.fail:
            if not args.state:
                raise InventoryError("--state is required.")
            state = saved_state(args.state, api)
            payload = claim_fields(state)
            if args.purchases:
                payload["lots"] = read_json(args.purchases)["lots"]
            if args.fail:
                payload.update(error=args.fail, retry=False)
            action = "purchases" if args.purchases else "fail" if args.fail else "status"
            result = api.post(endpoint(state, action), payload)
        else:
            result = prepare(api)
        if args.output:
            write_json(args.output, result)
            print(json.dumps({"status": "saved", "output_file": str(args.output)}))
        elif args.status:
            # Status includes a claim credential and private saved response text.
            # Full status is available only through an explicit private file.
            print(json.dumps({"status": response_status(result),
                              "job_id": result["job"]["id"],
                              "lease_expires_at": result["job"].get("lease_expires_at")}))
        else:
            print(json.dumps(result, ensure_ascii=False))
        return 0
    except (InventoryError, OSError, ValueError, KeyError) as exc:
        # Transport errors deliberately omit response bodies and credentials.
        message = str(exc) if isinstance(exc, InventoryError) else "Inventory local state could not be read or saved."
        print(json.dumps({"status": "error", "error": message}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
