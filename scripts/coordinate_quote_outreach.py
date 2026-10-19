"""Dispatch bounded, explicitly authorized initial inquiries through the server.

Recipient selection, test routing and immutable send receipts are server-owned.
This script cannot supply email content, a destination or new permission.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time
from uuid import uuid4

if __package__:
    from .coordinate_worker import CoordinateAPI, WorkerError
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from coordinate_worker import CoordinateAPI, WorkerError


def dispatch(api, directory, limit=2):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + 85
    results = []
    pending = sorted(directory.glob("*.pending.json"))
    for _ in range(min(max(limit, 1), 3)):
        # Reserve a complete transport window before starting a request. A short
        # timeout must not interrupt an in-flight server/Gmail send operation.
        if deadline - time.monotonic() < 40:
            break
        if pending:
            path = pending.pop(0)
            data = json.loads(path.read_text(encoding="utf-8"))
        else:
            data = {"worker_id": "manual-codex", "request_id": str(uuid4())}
            path = directory / (data["request_id"] + ".pending.json")
            path.write_text(json.dumps(data), encoding="utf-8")
        # Transport ambiguity retains the same request for the next run. The
        # server never dispatches a saved request or a provider inquiry twice.
        result = api.post("/coordinate/api/quote-inquiries/dispatch/", data, timeout=40)
        done = path.with_name(path.name.replace(".pending.json", ".completed.json"))
        done.write_text(json.dumps({"request": data, "result": result}), encoding="utf-8")
        path.unlink()
        results.append(result)
        if result.get("status") in ("outreach_idle", "unknown", "sending"):
            break
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.environ.get("COORDINATE_BASE_URL", "https://secondstate.art"))
    parser.add_argument("--limit", type=int, choices=[1, 2, 3], default=2)
    parser.add_argument("--state-dir", default="private_data/coordinate-outreach-runs")
    args = parser.parse_args()
    try:
        results = dispatch(CoordinateAPI(args.base_url, os.environ.get("COORDINATE_WORKER_TOKEN", "")), args.state_dir, args.limit)
    except (WorkerError, ValueError, OSError):
        print(json.dumps({"status": "outreach_failed", "error": "Dispatch not confirmed; retain the pending request and reconcile. Never resend manually."}))
        return 1
    print(json.dumps({"results": results}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
