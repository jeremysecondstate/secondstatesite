"""Read public Calendar state or apply an explicitly reviewed duplicate plan.

Loads the existing local Calendar configuration. Never selects pairs, retries a
POST automatically, or prints credentials. Receipt paths must be new files.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import requests
from dotenv import load_dotenv

from catalogapp.watchlist_sync import _validated_base_url
from secondstateapp.calendar_duplicates import PUBLIC_FIELDS


ROW_FIELDS = (*PUBLIC_FIELDS, "current_bid", "bid_count", "sold_price", "sold_currency", "location",
              "source_first_seen_at", "source_last_seen_at", "source_status", "fingerprint")
PAIR_FIELDS = ("keep_id", "remove_id", "keep_fingerprint", "remove_fingerprint", "reason")


def now():
    return datetime.now(timezone.utc).isoformat()


def connection():
    load_dotenv(ROOT / ".env", override=False)
    key = os.environ.get("CATALOG_API_KEY", "").strip()
    if not key:
        raise ValueError("CATALOG_API_KEY is unavailable in the existing local configuration.")
    base = _validated_base_url(os.environ.get("SECONDSTATE_BASE_URL", "https://secondstate.art"))
    return base + "/calendar/reconciliation/", {"X-API-KEY": key, "Accept": "application/json"}


def public_row(row):
    if not isinstance(row, dict):
        raise ValueError("Calendar returned a non-object lot.")
    public = {field: row.get(field) for field in ROW_FIELDS}
    if any(value is not None and type(value) not in (str, int, float, bool) for value in public.values()):
        raise ValueError("Calendar returned nested public lot data.")
    if any(type(value) is float and not math.isfinite(value) for value in public.values()):
        raise ValueError("Calendar returned a non-finite lot value.")
    if type(public["id"]) is not int or public["id"] <= 0 or str(public["source"]).casefold() not in {"invaluable", "drouot"}:
        raise ValueError("Calendar returned an invalid source identity.")
    if not isinstance(public["source_lot_id"], str) or not public["source_lot_id"]:
        raise ValueError("Calendar returned an empty source lot ID.")
    if not isinstance(public["fingerprint"], str) or not re.fullmatch(r"[0-9a-f]{64}", public["fingerprint"]):
        raise ValueError("Calendar returned an invalid review fingerprint.")
    return public


def get_json(endpoint, headers, params, *, session=requests):
    response = session.get(endpoint, params=params, headers=headers, timeout=(10, 60), allow_redirects=False)
    if response.status_code != 200:
        raise RuntimeError(f"Calendar GET returned HTTP {response.status_code}; no data was accepted.")
    payload = response.json()
    if not isinstance(payload, dict) or payload.get("ok") is not True or payload.get("version") != 1:
        raise ValueError("Calendar returned an invalid API response.")
    return payload


def fetch_snapshot(endpoint, headers, filters, *, session=requests):
    started = now()
    cursor, seen, identities, lots, page_times = "0", set(), set(), [], []
    for _ in range(1000):
        payload = get_json(endpoint, headers, {**filters, "cursor": cursor, "page_size": 500}, session=session)
        page = payload.get("lots")
        if not isinstance(page, list) or len(page) > 500:
            raise ValueError("Calendar returned an invalid lot page.")
        last_id = int(cursor)
        for raw in page:
            row = public_row(raw)
            identity = (row["source"].casefold(), row["source_lot_id"])
            if row["id"] <= last_id or row["id"] in seen or identity in identities:
                raise ValueError("Calendar pagination repeated or reordered a lot.")
            seen.add(row["id"]); identities.add(identity); lots.append(row)
            last_id = row["id"]
        page_times.append(payload.get("observed_at"))
        following = payload.get("next_cursor")
        if following is None:
            return {"format": "secondstate-calendar-public-snapshot-v1", "endpoint": endpoint,
                    "started_at": started, "completed_at": now(), "filters": filters,
                    "page_observed_at": page_times, "lot_count": len(lots), "lots": lots}
        if not page or not isinstance(following, str) or following != str(last_id):
            raise ValueError("Calendar returned a non-advancing page cursor.")
        cursor = following
    raise ValueError("Calendar pagination exceeded the safety limit; snapshot was not completed.")


def reviewed_plan(path):
    raw = path.read_bytes()
    if len(raw) > 1_000_000:
        raise ValueError("Reviewed plan exceeds 1 MB.")
    payload = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(payload, dict) or set(payload) != {"version", "operation", "reviewed", "pairs"}:
        raise ValueError("Plan needs version, operation, reviewed and pairs only.")
    if type(payload["version"]) is not int or payload["version"] != 1 or payload["reviewed"] is not True:
        raise ValueError("An explicitly reviewed version 1 plan is required.")
    if not isinstance(payload["operation"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,75}", payload["operation"]):
        raise ValueError("Plan operation identifier is invalid.")
    pairs = payload["pairs"]
    if not isinstance(pairs, list) or not 1 <= len(pairs) <= 200:
        raise ValueError("Plan requires 1 to 200 reviewed pairs.")
    for pair in pairs:
        if not isinstance(pair, dict) or set(pair) != set(PAIR_FIELDS):
            raise ValueError("Each reviewed pair needs IDs, fingerprints and a reason.")
        if any(type(pair[key]) is not int or not 0 < pair[key] <= 2**63 - 1 for key in ("keep_id", "remove_id")):
            raise ValueError("Reviewed pair IDs must be positive Calendar IDs.")
        if any(not isinstance(pair[key], str) or not re.fullmatch(r"[0-9a-f]{64}", pair[key])
               for key in ("keep_fingerprint", "remove_fingerprint")):
            raise ValueError("Reviewed pair fingerprints are invalid.")
        if not isinstance(pair["reason"], str) or not pair["reason"].strip() or len(pair["reason"]) > 4000:
            raise ValueError("Reviewed pairs require specific supporting reasons.")
        pair["reason"] = pair["reason"].strip()
    pairs.sort(key=lambda pair: (pair["remove_id"], pair["keep_id"]))
    digest = sha256(json.dumps(pairs, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return payload, digest


def _save_handle(handle, data):
    handle.seek(0)
    json.dump(data, handle, ensure_ascii=False, indent=2)
    handle.write("\n")
    handle.truncate()
    handle.flush()
    os.fsync(handle.fileno())


def apply_plan(endpoint, headers, plan, digest, receipt_path, *, session=requests):
    # Reserve and persist intent before any mutation. A collision never sends POST.
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    attempt = {"format": "secondstate-calendar-reconciliation-attempt-v1", "endpoint": endpoint,
               "operation": plan["operation"], "request_hash": digest, "started_at": now(),
               "outcome": "unknown", "note": "Do not assume success or retry with a new operation ID."}
    with receipt_path.open("x", encoding="utf-8") as handle:
        _save_handle(handle, attempt)
        try:
            response = session.post(endpoint, json=plan, headers=headers, timeout=(10, 60), allow_redirects=False)
            attempt["http_status"] = response.status_code
            attempt["completed_at"] = now()
            try:
                payload = response.json()
            except ValueError:
                payload = None
            if response.status_code == 200 and isinstance(payload, dict) and payload.get("ok") is True:
                receipt = payload.get("receipt")
                if (not isinstance(receipt, dict) or receipt.get("format") != "secondstate-calendar-duplicate-receipt-v1"
                        or receipt.get("operation") != plan["operation"] or receipt.get("request_hash") != digest
                        or not isinstance(receipt.get("changes"), list)
                        or len(receipt["changes"]) != len(plan["pairs"])):
                    raise ValueError("Calendar response did not contain the expected operation receipt.")
                attempt.update(outcome="applied", replayed=payload.get("replayed") is True)
                result = {**receipt, "attempt": attempt}
                _save_handle(handle, result)
                return result
            # Auth/validation/conflict responses are known rejections. Other status
            # codes or malformed responses can follow a committed write.
            rejected = (response.status_code in {400, 401, 409, 413}
                        and isinstance(payload, dict) and payload.get("ok") is False)
            attempt["outcome"] = "rejected" if rejected else "unknown"
            if rejected and isinstance(payload.get("error"), str):
                attempt["error"] = payload["error"][:1000]
            _save_handle(handle, attempt)
            raise RuntimeError(f"Calendar POST returned HTTP {response.status_code}; outcome {attempt['outcome']}. Inspect the saved attempt before recovery.")
        except (requests.RequestException, ValueError) as exc:
            attempt.update(completed_at=now(), exception_type=type(exc).__name__)
            _save_handle(handle, attempt)
            raise RuntimeError("Calendar POST outcome is unknown. Saved recovery metadata; no automatic retry was made.") from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--audit", action="store_true", help="Read duplicate candidates for a bounded date window or --ids.")
    modes.add_argument("--apply", type=Path, help="Explicitly reviewed JSON plan to POST once.")
    modes.add_argument("--operation", help="Read a prior operation receipt after an uncertain request.")
    parser.add_argument("--output", type=Path, help="New JSON file for a read-only snapshot, audit or operation response.")
    parser.add_argument("--receipt", type=Path, help="Required new file for an --apply receipt or uncertain-attempt metadata.")
    parser.add_argument("--start", help="Inclusive Calendar date YYYY-MM-DD.")
    parser.add_argument("--end", help="Inclusive Calendar date YYYY-MM-DD.")
    parser.add_argument("--ids", help="Comma-separated Calendar IDs, at most 500.")
    args = parser.parse_args(argv)
    filters = {name: getattr(args, name) for name in ("start", "end", "ids") if getattr(args, name) is not None}
    if args.apply:
        if not args.receipt or args.output or filters:
            parser.error("--apply requires --receipt and cannot use read-only output/filter options.")
        plan, digest = reviewed_plan(args.apply)
        endpoint, headers = connection()
        result = apply_plan(endpoint, headers, plan, digest, args.receipt)
        print(json.dumps({"operation": plan["operation"], "changes": len(result["changes"]),
                          "replayed": result["attempt"]["replayed"], "receipt": str(args.receipt)}))
        return 0
    if not args.output or args.receipt or (args.operation and filters):
        parser.error("Read-only modes require --output; --receipt is for --apply and --operation takes no filters.")
    if args.audit and not args.ids and not (args.start and args.end):
        parser.error("--audit needs --ids or both --start and --end.")
    if args.output.exists():
        raise FileExistsError("Output already exists; choose a new path.")
    endpoint, headers = connection()
    if args.audit or args.operation:
        params = {**filters, "mode": "audit"} if args.audit else {"operation": args.operation}
        result = get_json(endpoint, headers, params)
        # These two API projections contain only reviewed public evidence.
        allowed = ("ok", "version", "observed_at", "audit") if args.audit else (
            "ok", "version", "operation", "request_hash", "receipt", "created_at")
        result = {key: result[key] for key in allowed if key in result}
    else:
        result = fetch_snapshot(endpoint, headers, filters)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        _save_handle(handle, result)
    print(json.dumps({"output": str(args.output), "lots": result.get("lot_count"),
                      "candidates": len(result["audit"]["pairs"]) if "audit" in result else None}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, requests.RequestException) as exc:
        # Transport details and response bodies can contain sensitive data.
        message = str(exc) if not isinstance(exc, requests.RequestException) else type(exc).__name__
        print(f"Calendar reconciliation failed: {message}", file=sys.stderr)
        raise SystemExit(1)
