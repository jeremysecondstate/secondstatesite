"""Read-only public Calendar verification for a Drouot Worker run.

Run before/after to fetch the authenticated public watchlist projection, then
compare. The API has a date horizon: pass --dom with root-saved public monthly
Calendar rows to verify accepted observations outside it. No source requests,
Calendar writes, research fields, purchase flags or credentials are retained.
Preexisting superseded records may use explicit public database proof plus
historical DOM identities; this readback is counted separately from API/DOM.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
import json
import math
import os
from pathlib import Path
import re
import sys
import unicodedata
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from catalogapp.bookmark_watchlist import canonicalize_bookmark_url
from secondstateapp.lot_presentation import artist_display_name, clean_display_text

PUBLIC_FIELDS = (
    "source", "source_lot_id", "artist", "artist_watchlist_name", "title", "medium",
    "auction_house", "sale_title", "lot_number", "start_at", "end_at", "location",
    "estimate_low", "estimate_high", "currency", "current_bid", "bid_count",
    "sold_price", "sold_currency", "lot_url", "sale_url", "image_url",
    "first_seen_at", "last_seen_at", "status",
)
NUMBERS = {"estimate_low", "estimate_high", "current_bid", "sold_price"}
READBACK_FIELDS = tuple(field for field in PUBLIC_FIELDS if field not in {
    "source", "source_lot_id", "start_at", "first_seen_at", "status",
})
MEANINGFUL_FIELDS = tuple(field for field in READBACK_FIELDS if field != "last_seen_at")
DOM_FIELDS = (
    "artist", "title", "auction_house", "sale_title", "lot_number", "medium", "location",
    "estimate_low", "estimate_high", "current_bid", "bid_count", "currency", "sold_price",
    "sold_currency", "lot_url", "sale_url", "image_urls", "event_at", "date", "ended",
)


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def key(row: dict) -> str:
    source, identity = row.get("source"), row.get("source_lot_id")
    if not isinstance(source, str) or not isinstance(identity, str) or not source.strip() or not identity.strip():
        raise ValueError("Public Calendar rows require source and source_lot_id strings.")
    return f"{source.casefold()}:{identity.strip()}"


def stamp(value):
    if not value:
        return None
    text = str(value).strip()
    if len(text) == 10:
        return text
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Calendar observation timestamps must include a timezone.")
    return parsed.astimezone(timezone.utc).isoformat()


def canonical(field, value):
    if field in NUMBERS and value is not None:
        return str(Decimal(str(value)).quantize(Decimal("0.01")))
    if field in {"end_at", "last_seen_at", "first_seen_at", "event_at"}:
        return stamp(value)
    if field in {"lot_url", "sale_url"}:
        return canonicalize_bookmark_url(value or "")
    if field == "image_url":
        path = urlsplit(str(value or "")).path
        return path if path.startswith("/media/calendar-lots/") else value
    if field == "image_urls" and isinstance(value, list):
        return [canonical("image_url", image) for image in value]
    return value


def differences(before, after, fields=MEANINGFUL_FIELDS):
    return {field: {"before": before.get(field), "after": after.get(field)} for field in fields
            if canonical(field, before.get(field)) != canonical(field, after.get(field))}


def indexed(rows):
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("Expected an array of public lot objects.")
    result = {key(row): row for row in rows}
    if len(result) != len(rows):
        raise ValueError("Duplicate public source lot identities.")
    return result


def public_row(row):
    values = {field: row.get(field) for field in PUBLIC_FIELDS}
    if any(value is not None and not isinstance(value, (str, int, float, bool)) for value in values.values()):
        raise RuntimeError("Calendar public lot fields contain unsupported nested metadata.")
    if any(isinstance(value, float) and not math.isfinite(value) for value in values.values()):
        raise RuntimeError("Calendar public lot fields contain invalid numbers.")
    return values


def fetch_snapshot(run_dir: Path, phase: str, calendar_zone: str):
    import requests
    from dotenv import load_dotenv
    from catalogapp.watchlist_sync import _validated_base_url

    load_dotenv(ROOT / ".env", override=False)
    credential = os.environ.get("CATALOG_API_KEY", "").strip()
    if not credential:
        raise RuntimeError("Local Calendar API credential is unavailable.")
    endpoint = _validated_base_url(os.environ.get("SECONDSTATE_BASE_URL", "https://secondstate.art")) + "/calendar/watchlist/"
    fetched_at = datetime.now(timezone.utc)
    zone = ZoneInfo(calendar_zone)
    today = fetched_at.astimezone(zone).date()
    cursor, cursors, identities, lots, page_counts = "0", set(), set(), [], []
    for _page in range(1000):
        try:
            response = requests.get(endpoint, params={"cursor": cursor, "page_size": 500, "horizon_days": 7},
                                    headers={"X-API-KEY": credential, "Accept": "application/json"},
                                    timeout=(10, 60), allow_redirects=False)
        except requests.RequestException as exc:
            raise RuntimeError("The public Calendar watchlist could not be read.") from exc
        if response.status_code != 200:
            raise RuntimeError(f"Calendar public watchlist GET returned HTTP {response.status_code}.")
        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError("Calendar public watchlist GET returned invalid JSON.") from exc
        if not isinstance(payload, dict) or payload.get("ok") is not True or not isinstance(payload.get("lots"), list):
            raise RuntimeError("Calendar public watchlist response is invalid.")
        if any(not isinstance(row, dict) for row in payload["lots"]):
            raise RuntimeError("Calendar public lot records are invalid.")
        public_keys = payload.get("calendar_lot_keys")
        if not isinstance(public_keys, list) or any(not isinstance(value, str) for value in public_keys):
            raise RuntimeError("Calendar global source identity keys are invalid.")
        identities.update(public_keys)
        # Access only these public fields. Exclude entries, staff research,
        # email selections, purchase flags, account state and other metadata.
        rows = [public_row(row) for row in payload["lots"]]
        indexed(rows)
        lots.extend(rows)
        page_counts.append(len(rows))
        cursor = payload.get("next_cursor")
        if cursor is None:
            break
        if not isinstance(cursor, str) or not cursor.isdecimal() or cursor in cursors:
            raise RuntimeError("Calendar cursor is invalid or repeated.")
        cursors.add(cursor)
    else:
        raise RuntimeError("Calendar public watchlist exceeded the audit page limit.")
    indexed(lots)
    data = {
        "phase": phase, "fetched_at": fetched_at.isoformat(), "endpoint": endpoint,
        "http_method": "GET", "horizon_days": 7, "page_counts": page_counts,
        "coverage": {
            "calendar_time_zone": calendar_zone,
            "time_zone_evidence": "Configured audit timezone; confirm against the Calendar UI header.",
            "event_start_inclusive": datetime.combine(today - timedelta(days=7), time.min, zone).isoformat(),
            "event_end_exclusive": datetime.combine(today + timedelta(days=8), time.min, zone).isoformat(),
            "undated_lots_included": True,
            "limitation": "API public fields cover this date horizon only. Global identity keys include every nonsuperseded saved lot. Supply public monthly DOM rows for accepted lots outside the horizon.",
        },
        "calendar_lot_keys": sorted(identities), "lot_count": len(lots),
        "source_counts": dict(Counter(row["source"] for row in lots)), "lots": lots,
    }
    save(run_dir / f"calendar-{phase}.json", data)
    return {field: data[field] for field in ("phase", "fetched_at", "page_counts", "lot_count", "source_counts")}


def expected_record(incoming, before=None):
    result = {field: incoming.get(field) for field in PUBLIC_FIELDS}
    result["end_at"] = incoming.get("end_at") or incoming.get("start_at") or ""
    result["title"] = str(incoming.get("title") or "").strip() or "Untitled lot"
    for field in ("currency", "sold_currency"):
        result[field] = str(result.get(field) or "").upper()
    if before:
        if before.get("sold_price") and not result.get("sold_price"):
            result["sold_price"] = before["sold_price"]
            result["sold_currency"] = before.get("sold_currency") or before.get("currency")
        if urlsplit(str(before.get("image_url") or "")).path.startswith("/media/calendar-lots/"):
            result["image_url"] = before["image_url"]
    if result.get("sold_price") and not result.get("sold_currency"):
        result["sold_currency"] = result.get("currency")
    return result


def projected_dom(lot, calendar_zone):
    event = lot.get("end_at") or lot.get("start_at") or ""
    zone = ZoneInfo(calendar_zone)
    when = datetime.fromisoformat(event.replace("Z", "+00:00")) if event else None
    if when and when.tzinfo is None:
        when = when.replace(tzinfo=zone)
    image = lot.get("image_url") or ""
    return {
        "artist": artist_display_name(lot.get("artist_watchlist_name") or lot.get("artist") or "Unknown artist"),
        "title": clean_display_text(lot.get("title"), strip_lot_markers=True) or "Untitled lot",
        "auction_house": clean_display_text(lot.get("auction_house") or lot.get("source") or "Auction"),
        "sale_title": clean_display_text(lot.get("sale_title")), "lot_number": lot.get("lot_number"),
        "medium": clean_display_text(lot.get("medium")), "location": clean_display_text(lot.get("location")),
        **{field: lot.get(field) for field in ("estimate_low", "estimate_high", "current_bid", "bid_count")},
        "currency": (lot.get("currency") or "").upper(), "sold_price": lot.get("sold_price"),
        "sold_currency": (lot.get("sold_currency") or "").upper(), "lot_url": lot.get("lot_url"),
        "sale_url": lot.get("sale_url"), "image_urls": [image] if image else [],
        "event_at": None if len(event) == 10 else event or None,
        "date": when.astimezone(zone).date().isoformat() if when else None,
        "ended": bool(lot.get("sold_price") or lot.get("status") == "ended"),
    }


def read_dom(paths):
    result = {}
    for path in paths:
        rows = load(path)
        if not isinstance(rows, list):
            raise ValueError("--dom files must contain public Calendar row arrays.")
        for raw in rows:
            if not isinstance(raw, dict):
                raise ValueError("Public DOM rows must be objects.")
            parts = urlsplit(str(raw.get("lot_url") or ""))
            match = re.match(r"^/en/l/([1-9][0-9]*)(?:-|/|$)", parts.path)
            if parts.scheme != "https" or parts.hostname != "drouot.com" or parts.username or parts.password:
                continue
            if not match:
                continue
            database_id = raw.get("id")
            if type(database_id) is not int or database_id < 1:
                raise ValueError("Drouot DOM rows need their public Calendar database ID.")
            identity = f"drouot:{match[1]}"
            row = {field: raw.get(field) for field in DOM_FIELDS}
            row["calendar_id"] = database_id
            prior = result.get(identity)
            if prior and (prior["calendar_id"] != database_id or differences(prior, row, DOM_FIELDS)):
                raise ValueError(f"Public monthly DOM rows disagree for {identity}.")
            result[identity] = row
    return result


def inside_horizon(row, coverage):
    event = row.get("end_at") or row.get("start_at")
    if not event:
        return True
    when = datetime.fromisoformat(str(event).replace("Z", "+00:00"))
    if when.tzinfo is None:
        when = when.replace(tzinfo=ZoneInfo(coverage["calendar_time_zone"]))
    return (datetime.fromisoformat(coverage["event_start_inclusive"]) <= when
            < datetime.fromisoformat(coverage["event_end_exclusive"]))


def normalized(value):
    value = unicodedata.normalize("NFKD", str(value or "")).casefold()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", "".join(c for c in value if not unicodedata.combining(c))).split())


def cross_listing_candidates(accepted, existing):
    grouped = defaultdict(list)
    for row in existing.values():
        number = normalized(row.get("lot_number"))
        event = row.get("end_at") or row.get("start_at")
        if not number or not event or not normalized(row.get("auction_house")):
            continue
        day = datetime.fromisoformat(str(event).replace("Z", "+00:00"))
        if day.tzinfo is None:
            day = day.replace(tzinfo=ZoneInfo("America/Los_Angeles"))
        signature = (normalized(row["auction_house"]), day.astimezone(ZoneInfo("America/New_York")).date().isoformat(), number.lstrip("0") or "0")
        grouped[signature].append(row)
    results = []
    for row in accepted.values():
        event = row.get("end_at") or row.get("start_at")
        if not event:
            continue
        day = datetime.fromisoformat(str(event).replace("Z", "+00:00"))
        if day.tzinfo is None:
            day = day.replace(tzinfo=ZoneInfo("America/New_York"))
        number = normalized(row.get("lot_number"))
        signature = (normalized(row.get("auction_house")), day.astimezone(ZoneInfo("America/New_York")).date().isoformat(), number.lstrip("0") or "0")
        for other in grouped.get(signature, []):
            if other["source"].casefold() != row["source"].casefold():
                results.append({"drouot_key": key(row), "other_key": key(other), "auction_house": row.get("auction_house"),
                                "sale_day_new_york": signature[1], "lot_number": row.get("lot_number"),
                                "drouot_url": row.get("lot_url"), "other_url": other.get("lot_url"),
                                "action": "Review possible cross-listing; no merge or hiding performed."})
    return results


def superseded_records(proof, historical_dom, before, after, accepted, dom):
    """Accept only proven preexisting supersessions, never infer a merge."""
    if proof is None:
        return {}
    if (not isinstance(proof, dict) or proof.get("format") != "secondstate-drouot-superseded-db-readback"
            or proof.get("version") != 1 or not isinstance(proof.get("rows"), list)
            or not proof["rows"] or any(not isinstance(proof.get(field), str) or not proof[field].strip()
                                      for field in ("provider", "workspace_id", "postgres_id", "sql"))):
        raise ValueError("Superseded DB evidence requires its read-only source envelope.")
    observed, readback = stamp(proof.get("captured_at")), stamp(after.get("fetched_at"))
    if not observed or not readback or observed < readback:
        raise ValueError("Superseded DB evidence must postdate the after-sync readback.")
    original_keys, current_keys = set(before["calendar_lot_keys"]), set(after["calendar_lot_keys"])
    prior_public, current_public = indexed(before["lots"]), indexed(after["lots"])
    fields = set(READBACK_FIELDS) - {"end_at", "last_seen_at"}
    required = fields | {"id", "source", "source_lot_id", "active", "superseded_by_id", "event_at",
                         "source_last_seen_at", "replacement_id", "replacement_source",
                         "replacement_source_lot_id", "replacement_lot_url"}
    result = {}
    for row in proof["rows"]:
        if not isinstance(row, dict) or set(row) != required:
            raise ValueError("Superseded DB rows must contain exactly the public fields and identity proof.")
        identity = key(row)
        if identity not in accepted or identity in result:
            raise ValueError("Superseded DB row is unaccepted or duplicated.")
        if identity in original_keys or identity in current_keys or identity in prior_public or identity in current_public or identity in dom:
            raise ValueError("Supersession exception requires absence before and after synchronization.")
        database_id, replacement_id = row["id"], row["replacement_id"]
        if (type(database_id) is not int or database_id < 1 or type(replacement_id) is not int or replacement_id < 1
                or database_id == replacement_id or row["superseded_by_id"] != replacement_id
                or row["active"] is not False):
            raise ValueError("Superseded DB row needs an inactive record and a distinct real replacement.")
        if historical_dom.get(identity, {}).get("calendar_id") != database_id:
            raise ValueError("Superseded DB ID does not match historical public Calendar evidence.")
        replacement_key = key({"source": row["replacement_source"], "source_lot_id": row["replacement_source_lot_id"]})
        if (replacement_key == identity or replacement_key not in original_keys or replacement_key not in current_keys
                or replacement_key not in prior_public or replacement_key not in current_public
                or any(canonical("lot_url", records[replacement_key].get("lot_url")) != canonical("lot_url", row["replacement_lot_url"])
                       for records in (prior_public, current_public))):
            raise ValueError("Superseded replacement lacks matching before/after public identity and URL proof.")
        public = {field: row[field] for field in fields}
        public.update(end_at=row["event_at"], last_seen_at=row["source_last_seen_at"])
        result[identity] = {"public": public, "calendar_id": database_id,
                            "superseded_by_id": replacement_id, "replacement_key": replacement_key}
    return result


def compare_snapshots(before, after, preview, sync, dom=None, superseded_db=None, historical_dom=None):
    old, saved, accepted = indexed(before["lots"]), indexed(after["lots"]), indexed(preview["lots"])
    if any(not identity.startswith("drouot:") for identity in accepted):
        raise ValueError("The Drouot preview includes another source.")
    synchronized = indexed(sync.get("lots", []))
    errors = []
    if preview.get("summary", {}).get("errors") or sync.get("summary", {}).get("errors"):
        errors.append("Preview or synchronization report contains errors.")
    if set(accepted) != set(synchronized) or any(differences(row, synchronized[identity], MEANINGFUL_FIELDS)
                                                for identity, row in accepted.items() if identity in synchronized):
        errors.append("Preview and synchronization accepted observations differ.")
    receipt = str(sync.get("summary", {}).get("calendar_result") or "")
    confirmed = re.search(r"Website calendar synced: ([0-9]+) lots", receipt)
    if accepted and (sync.get("summary", {}).get("mode") != "synced" or not confirmed or int(confirmed[1]) != len(accepted)):
        errors.append("Synchronization receipt does not confirm every accepted observation.")
    global_before, global_after = set(before["calendar_lot_keys"]), set(after["calendar_lot_keys"])
    absent_global, lost = sorted(set(accepted) - global_after), sorted(global_before - global_after)
    mismatches, verified_api, verified_dom, unavailable, stale = [], [], [], [], []
    verified_superseded, absent_public = [], []
    actual_changes, unchanged_drouot, concurrent, unreverified_drouot = [], [], [], []
    dom = dom or {}
    superseded = superseded_records(superseded_db, historical_dom or {}, before, after, accepted, dom)
    for identity, incoming in accepted.items():
        prior = old.get(identity)
        is_stale = prior and stamp(prior.get("last_seen_at")) and (not stamp(incoming.get("last_seen_at"))
                      or stamp(incoming["last_seen_at"]) < stamp(prior["last_seen_at"]))
        expected = prior if is_stale else expected_record(incoming, prior)
        if is_stale:
            stale.append(identity)
        if identity in saved:
            delta = differences(expected, saved[identity], READBACK_FIELDS)
            if expected.get("sold_price") and saved[identity].get("status") != "ended":
                delta["status"] = {"before": "ended", "after": saved[identity].get("status")}
            if delta:
                mismatches.append({"key": identity, "surface": "API", "differences": delta})
            else:
                verified_api.append(identity)
        if identity in dom:
            delta = differences(projected_dom(expected, after["coverage"]["calendar_time_zone"]), dom[identity], DOM_FIELDS)
            if delta:
                mismatches.append({"key": identity, "surface": "DOM", "calendar_id": dom[identity]["calendar_id"], "differences": delta})
            else:
                verified_dom.append({"key": identity, "calendar_id": dom[identity]["calendar_id"]})
        if identity not in saved and identity not in dom:
            absent_public.append(identity)
            if identity in superseded:
                evidence = superseded[identity]
                delta = differences(expected, evidence["public"], READBACK_FIELDS)
                if delta:
                    mismatches.append({"key": identity, "surface": "superseded database", "differences": delta})
                    unavailable.append(identity)
                else:
                    verified_superseded.append({"key": identity, "calendar_id": evidence["calendar_id"],
                                                "surface": "superseded database", "superseded_by_id": evidence["superseded_by_id"],
                                                "replacement_key": evidence["replacement_key"]})
            else:
                unavailable.append(identity)
        if prior and identity in saved:
            delta = differences(prior, saved[identity])
            if delta:
                actual_changes.append({"key": identity, "artist": incoming.get("artist"), "title": incoming.get("title"), "changes": delta})
    for identity, row in old.items():
        if identity in accepted:
            continue
        if identity not in saved:
            if row["source"].casefold() == "drouot":
                if identity in dom:
                    delta = differences(projected_dom(row, after["coverage"]["calendar_time_zone"]), dom[identity], DOM_FIELDS)
                    if delta:
                        mismatches.append({"key": identity, "surface": "unobserved DOM", "differences": delta})
                    else:
                        unchanged_drouot.append(identity)
                elif inside_horizon(row, after["coverage"]):
                    mismatches.append({"key": identity, "surface": "unobserved API", "missing_expected_record": True})
                else:
                    unreverified_drouot.append(identity)
            continue
        delta = differences(row, saved[identity], PUBLIC_FIELDS)
        if row["source"].casefold() == "drouot":
            if delta:
                mismatches.append({"key": identity, "surface": "unobserved API", "differences": delta})
            else:
                unchanged_drouot.append(identity)
        elif delta:
            concurrent.append({"key": identity, "changes": delta})
    missing = sorted(set(absent_global) - {row["key"] for row in verified_superseded})
    if missing:
        errors.append("Accepted Drouot source identities are missing from global Calendar keys.")
    if lost:
        errors.append("Previously saved global Calendar identities disappeared.")
    if mismatches:
        errors.append("Saved public fields or preserved Drouot observations differ from the expected values.")
    if unavailable:
        errors.append("Some accepted observations have no public field readback; supply monthly DOM evidence outside the API horizon.")
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(), "passed": not errors, "errors": errors,
        "accepted_observations": len(accepted), "sync_receipt": receipt,
        "new_global_source_ids": sorted((set(accepted) - global_before) & global_after),
        "all_accepted_source_ids_saved": not missing, "missing_accepted_global_ids": missing,
        "accepted_absent_from_public_global_keys": absent_global,
        "prior_global_identity_keys_lost": lost, "accepted_api_fields_verified": len(verified_api),
        "accepted_dom_fields_verified": len(verified_dom), "verified_calendar_ids": verified_dom + verified_superseded,
        "accepted_superseded_db_fields_verified": len(verified_superseded), "verified_superseded_records": verified_superseded,
        "accepted_without_api_or_dom_readback": absent_public,
        "accepted_without_public_field_readback": unavailable, "public_field_mismatches": mismatches,
        "newer_observations_preserved": stale, "unobserved_drouot_public_records_preserved": len(unchanged_drouot),
        "unobserved_drouot_outside_public_readback": unreverified_drouot,
        "different_source_concurrent_updates": concurrent, "meaningful_drouot_changes": actual_changes,
        "suspected_cross_listings": cross_listing_candidates(accepted, old),
        "coverage": after["coverage"], "dom_evidence_provided": bool(dom),
        "research_preservation": "Public-field audit and reviewed sync code path only; private research, email selections and purchase flags were intentionally not read.",
        "supersession_preservation": "Optional read-only database evidence verifies preexisting inactive superseded identities separately from API/DOM. No supersession is inferred or created.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--dom", action="append", default=[], type=Path, help="Public after-sync Calendar DOM JSON row array; repeat for multiple months.")
    parser.add_argument("--superseded-db", type=Path, help="Read-only public database proof for preexisting inactive superseded observations.")
    parser.add_argument("--prior-dom", action="append", default=[], type=Path, help="Earlier public monthly DOM evidence for original Calendar database IDs; used only with --superseded-db.")
    parser.add_argument("--calendar-time-zone", default="America/Los_Angeles", help="Confirm this timezone against the Calendar UI header.")
    parser.add_argument("mode", choices=("before", "after", "compare"))
    args = parser.parse_args(argv)
    if not args.run_dir.is_dir():
        parser.error("--run-dir must identify an existing Drouot evidence directory.")
    if args.mode in {"before", "after"}:
        result = fetch_snapshot(args.run_dir, args.mode, args.calendar_time_zone)
    else:
        result = compare_snapshots(load(args.run_dir / "calendar-before.json"), load(args.run_dir / "calendar-after.json"),
                                   load(args.run_dir / "preview-report.json"), load(args.run_dir / "sync-report.json"), read_dom(args.dom),
                                   load(args.superseded_db) if args.superseded_db else None, read_dom(args.prior_dom))
        if args.superseded_db:
            result["superseded_db_evidence"] = str(args.superseded_db.resolve())
            result["historical_identity_evidence"] = [str(path.resolve()) for path in args.prior_dom]
        save(args.run_dir / "calendar-audit.json", result)
    summary = {field: result[field] for field in (
        "phase", "fetched_at", "lot_count", "source_counts", "passed", "accepted_observations",
        "accepted_api_fields_verified", "accepted_dom_fields_verified", "accepted_superseded_db_fields_verified", "errors",
    ) if field in result}
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    return 0 if result.get("passed", True) else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, RuntimeError, ZoneInfoNotFoundError) as exc:
        print(f"Drouot Calendar audit failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
