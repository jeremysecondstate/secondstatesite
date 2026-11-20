"""Read and save market assessments using the configured SecondState Calendar API."""

import argparse
import json
import os
from pathlib import Path
import sys

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from catalogapp.watchlist_sync import CalendarSyncError, _validated_base_url


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    pending = commands.add_parser("pending", help="Get current and future Calendar lots in auction order.")
    pending.add_argument("--limit", type=int, default=50, help="Number of lots to return (1–200).")
    inspect = commands.add_parser("inspect", help="Read current catalog facts and saved assessments by ID.")
    inspect.add_argument("--ids", required=True, help="Up to 200 comma-separated Calendar IDs.")
    apply = commands.add_parser("apply", help="Atomically record a batch of assessed lots.")
    apply.add_argument("file", type=Path, help="UTF-8 JSON file containing a reviews array.")
    for command in (pending, inspect, apply):
        command.add_argument("--output", type=Path, help="Write the response as UTF-8 JSON.")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env", override=False)
    key = os.environ.get("CATALOG_API_KEY", "").strip()
    if not key:
        raise ValueError("The Calendar API key is unavailable in this workspace.")
    base = _validated_base_url(os.environ.get("SECONDSTATE_BASE_URL", "https://secondstate.art"))
    endpoint = f"{base}/calendar/market-review/"
    options = {"headers": {"X-API-KEY": key, "Accept": "application/json"}, "timeout": (10, 90), "allow_redirects": False}
    if args.command == "apply":
        plan = json.loads(args.file.read_text(encoding="utf-8-sig"))
        response = requests.post(endpoint, json=plan, **options)
    else:
        params = {"ids": args.ids} if args.command == "inspect" else {"limit": args.limit}
        response = requests.get(endpoint, params=params, **options)
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if (response.status_code != 200 or not isinstance(payload, dict)
            or payload.get("ok") is not True or payload.get("version") != 1):
        error = payload.get("error", "") if isinstance(payload, dict) and response.status_code in (400, 401, 409, 413) else ""
        raise RuntimeError(f"Calendar returned HTTP {response.status_code}. {error}".strip())
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        fields = ("pending_count", "eligible_count", "upcoming_pending_count", "archive_pending_count",
                  "oldest_pending_day", "oldest_pending_day_count", "reviews")
        summary = {key: payload[key] for key in fields if key in payload}
        print(json.dumps({"output": str(args.output), "rows": len(payload.get("lots", [])), **summary}))
    else:
        print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    try:
        main()
    except requests.RequestException as exc:
        print(f"Calendar request failed ({type(exc).__name__}). Inspect IDs before retrying a write.", file=sys.stderr)
        raise SystemExit(1)
    except (OSError, ValueError, RuntimeError, CalendarSyncError) as exc:
        print(f"Calendar market review failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
