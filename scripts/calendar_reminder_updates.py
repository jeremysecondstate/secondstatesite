"""Durable live-catalog changes and rolling owner/countdown Gmail draft plans.

This module performs no external mail operations. Normal live scans call
``scan_updates(lots, now, ledger_path)`` after fetching a complete snapshot.
Before a connector draft mutation, use ``draft-claim``; acknowledge the returned
immutable operation with ``draft-record`` only after confirming its draft ID.
Uncertain mutations stay reserved for reconciliation by the stable subject.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timedelta, timezone
from html import escape
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import uuid
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
UTC = timezone.utc
FIELDS = (
    "source", "source_lot_id", "lot_url", "artist", "artist_watchlist_name",
    "title", "lot_number", "auction_house", "sale_title", "sale_url",
    "start_at", "end_at", "estimate_low", "estimate_high", "current_bid",
    "bid_count", "currency", "medium", "status", "sold_price", "sold_currency",
)
NUMERIC_FIELDS = {"estimate_low", "estimate_high", "current_bid", "bid_count", "sold_price"}


def _helper():
    # Lazy import also supports the main planner invoking us as a script.
    from scripts import calendar_sale_reminders
    return calendar_sale_reminders


def _stamp(now):
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("A timezone-aware scan timestamp is required.")
    return now.astimezone(UTC).isoformat()


def _connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE IF NOT EXISTS reminder_update_state (
            singleton INTEGER PRIMARY KEY CHECK(singleton=1), last_scan_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS reminder_update_snapshots (
            lot_key TEXT PRIMARY KEY, payload TEXT NOT NULL, present INTEGER NOT NULL,
            first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS reminder_update_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT NOT NULL,
            lot_key TEXT NOT NULL, kind TEXT NOT NULL, changed_fields TEXT NOT NULL,
            before_payload TEXT, after_payload TEXT, observed_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS reminder_update_events_owner
            ON reminder_update_events(owner,event_id);
        CREATE TABLE IF NOT EXISTS reminder_update_drafts (
            owner TEXT NOT NULL, days INTEGER NOT NULL CHECK(days BETWEEN 1 AND 5),
            draft_id TEXT, target_date TEXT, through_event_id INTEGER NOT NULL DEFAULT 0,
            revision TEXT, updated_at TEXT, operation_token TEXT,
            operation_payload TEXT, operation_state TEXT, operation_reason TEXT,
            PRIMARY KEY(owner,days));
        CREATE TABLE IF NOT EXISTS reminder_update_draft_recoveries (
            recovery_id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner TEXT NOT NULL, days INTEGER NOT NULL, operation_token TEXT NOT NULL UNIQUE,
            operation_payload TEXT NOT NULL, previous_state TEXT NOT NULL,
            missing_draft INTEGER NOT NULL, proof_reason TEXT NOT NULL, released_at TEXT NOT NULL);
    """)
    return db


def _snapshot(row):
    snapshot = {}
    for field in FIELDS:
        value = row.get(field, None if field in NUMERIC_FIELDS else "")
        if isinstance(value, str):
            value = value.strip()
        snapshot[field] = value
    snapshot["source"] = str(snapshot["source"]).casefold()
    snapshot["currency"] = str(snapshot["currency"]).upper()
    snapshot["sold_currency"] = str(snapshot["sold_currency"]).upper()
    # new/changed/unchanged describe collection runs, not a lot's sale status.
    snapshot["status"] = "ended" if snapshot["status"] == "ended" else "listed"
    for field in ("start_at", "end_at"):
        value = snapshot[field]
        if value and len(value) > 10:
            try:
                snapshot[field] = _helper().aware(value).astimezone(UTC).isoformat()
            except (ValueError, TypeError):
                pass
    return snapshot


def _key(row):
    source, identity = row.get("source"), row.get("source_lot_id") or row.get("lot_url")
    if not source or not identity:
        raise ValueError("A source and scoped lot identity are required for change tracking.")
    return f"{source}:{identity}"


def _details(row, owner):
    if not row:
        return None
    try:
        return _helper().event_details(row, ZoneInfo(_helper().OWNERS[owner]["zone"]))
    except (ValueError, TypeError, OverflowError):
        return None


def _belongs(row, owner):
    return bool(row) and (owner == "jeremy" or _helper().is_oliver_house(row.get("auction_house", "")))


def _in_window(row, owner, now):
    details = _details(row, owner)
    today = now.astimezone(ZoneInfo(_helper().OWNERS[owner]["zone"])).date()
    return _belongs(row, owner) and details is not None and 0 <= (details[0] - today).days <= 5


def _sold(row):
    return bool(row) and (row.get("sold_price") or 0) > 0


def _future_active(row, owner, now):
    if not _in_window(row, owner, now) or row.get("status") == "ended" or _sold(row):
        return False
    raw = row.get("end_at") or row.get("start_at") or ""
    if len(raw) == 10:
        return True
    try:
        return _helper().aware(raw) > now
    except (TypeError, ValueError):
        return False


def _event_dict(row):
    result = dict(row)
    for field in ("before_payload", "after_payload", "changed_fields"):
        result[field] = json.loads(result[field]) if result[field] else None
    return result


def _target_events(db, owner, target):
    result = []
    for record in db.execute("SELECT * FROM reminder_update_events WHERE owner=? ORDER BY event_id", (owner,)):
        event = _event_dict(record)
        if any(_belongs(row, owner) and (details := _details(row, owner)) and details[0].isoformat() == target
               for row in (event["before_payload"], event["after_payload"])):
            result.append(event)
    return result


def _draft_payload(owner, days, target, events, now, draft_id):
    helper = _helper()
    config = helper.OWNERS[owner]
    reference = f"SS-CALENDAR-UPDATES-{owner.upper()}-{days}D"
    subject = helper.category_subject(days, owner, target, reference, kind="UPDATE DRAFT")
    local = now.astimezone(ZoneInfo(config["zone"]))
    html = [helper.category_banner(days, owner, target, kind="UPDATE DRAFT"),
            f"<p>Sales on <strong>{target}</strong>. Updated {escape(local.strftime('%B %d, %Y at %I:%M %p %Z'))}.</p>",
            "<p>This rolling draft records observed catalog changes. Scheduled reminder emails are prepared separately from current sales.</p>"]
    if not events:
        html.append("<p>No recorded catalog changes for this sale date.</p>")
    for event in events:
        before, after = event["before_payload"], event["after_payload"]
        row = after or before
        title = row.get("title") or "Untitled lot"
        artist = row.get("artist_watchlist_name") or row.get("artist") or "Artist unspecified"
        labels = {"added": "New listing", "changed": "Listing updated", "sold": "Sold result recorded",
                  "ended": "Listing ended", "no_longer_present": "No longer present in the live catalog",
                  "reappeared": "Listing present again", "scope_changed": "Calendar membership changed"}
        observed = helper.aware(event["observed_at"]).astimezone(ZoneInfo(config["zone"]))
        html.append(f"<h3>{escape(labels.get(event['kind'], event['kind']))}: {escape(artist)} — {escape(title)}</h3>")
        html.append(f"<p>Observed {escape(observed.strftime('%b %d, %Y at %I:%M %p %Z'))}<br>"
                    f"{escape(row.get('auction_house') or 'Auction house unspecified')} · "
                    f"{escape(row.get('sale_title') or 'Sale title unspecified')}<br>"
                    f"Lot {escape(str(row.get('lot_number') or row.get('source_lot_id') or 'unspecified'))}</p>")
        for label, snapshot in (("Previous", before), ("Current", after)):
            details = _details(snapshot, owner)
            if details:
                html.append(f"<p>{label} sale: {details[0].isoformat()} at {escape(details[1])}</p>")
        if event["kind"] == "no_longer_present":
            html.append("<p>The listing was absent from the latest complete catalog scan. This does not establish cancellation.</p>")
        if event["changed_fields"]:
            html.append("<ul>")
            for field in event["changed_fields"]:
                old = (before or {}).get(field)
                new = (after or {}).get(field)
                html.append(f"<li>{escape(field.replace('_', ' ').title())}: "
                            f"{escape(str(old) if old not in (None, '') else 'Unavailable')} → "
                            f"{escape(str(new) if new not in (None, '') else 'Unavailable')}</li>")
            html.append("</ul>")
        currency = row.get("currency") or "Currency unspecified"
        html.append(f"<p>Estimate: {escape(str(row.get('estimate_low') or 'Unavailable'))}–"
                    f"{escape(str(row.get('estimate_high') or 'Unavailable'))} {escape(currency)}; "
                    f"current bid: {escape(str(row.get('current_bid') if row.get('current_bid') is not None else 'Unavailable'))}; "
                    f"bid count: {escape(str(row.get('bid_count') if row.get('bid_count') is not None else 'Unavailable'))}</p>")
        for label, value in (("Auction lot", row.get("lot_url", "")), ("Auction sale", row.get("sale_url", ""))):
            if url := helper.public_url(value):
                html.append(f'<p><a href="{escape(url, quote=True)}">{label}</a></p>')
    html.append(f"<p>Reference: {reference}</p>")
    gmail = {"link_id": config["link_id"], "from_address": owner + "@secondstate.art",
             "to": ", ".join(config["to"]), "subject": subject,
             "payload": {"mime_type": "text/html", "charset": "UTF-8", "body": {"content": "\n".join(html)}}}
    if draft_id:
        gmail["draft_id"] = draft_id
    return {"kind": "update" if draft_id else "create", "owner": owner, "days_away": days,
            "target_date": target, "through_event_id": events[-1]["event_id"] if events else 0,
            "reference": reference, "gmail": gmail}


def _group(db, owner, days, now):
    target = (now.astimezone(ZoneInfo(_helper().OWNERS[owner]["zone"])).date() + timedelta(days=days)).isoformat()
    events = _target_events(db, owner, target)
    through = events[-1]["event_id"] if events else 0
    revision = hashlib.sha256(f"{owner}|{days}|{target}|{through}".encode()).hexdigest()
    row = db.execute("SELECT * FROM reminder_update_drafts WHERE owner=? AND days=?", (owner, days)).fetchone()
    state = dict(row) if row else {}
    same_date = state.get("target_date") == target
    pending = [event for event in events if not same_date or event["event_id"] > state.get("through_event_id", 0)]
    needs_action = state.get("revision") != revision and (bool(events) or bool(state.get("draft_id")))
    action = _draft_payload(owner, days, target, events, now, state.get("draft_id")) if needs_action else None
    operation = None
    if state.get("operation_token"):
        operation = {"claim_token": state["operation_token"], "state": state["operation_state"],
                     "reason": state.get("operation_reason"), "payload": json.loads(state["operation_payload"])}
    return {"days_away": days, "target_date": target, "through_event_id": through,
            "pending_event_count": len(pending), "pending_events": pending,
            "draft_id": state.get("draft_id"), "draft_action": action,
            "operation": operation, "revision": revision}


def _status(db, now):
    return [{"owner": owner, "groups": [_group(db, owner, days, now) for days in range(1, 6)]}
            for owner in _helper().OWNERS]


def scan_updates(lots, now, ledger_path):
    stamp = _stamp(now)
    incoming = {}
    for row in lots:
        snapshot = _snapshot(row)
        key = _key(snapshot)
        if key in incoming:
            raise ValueError("Duplicate lot identity in the complete change-tracking snapshot.")
        incoming[key] = snapshot
    counts = {owner: 0 for owner in _helper().OWNERS}
    with closing(_connect(ledger_path)) as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            previous = db.execute("SELECT last_scan_at FROM reminder_update_state WHERE singleton=1").fetchone()
            baseline = previous is None
            stale = previous is not None and stamp <= previous["last_scan_at"]
            if not stale:
                stored = {row["lot_key"]: row for row in db.execute("SELECT * FROM reminder_update_snapshots")}

                def emit(owner, key, kind, before, after, changed):
                    db.execute("""INSERT INTO reminder_update_events
                        (owner,lot_key,kind,changed_fields,before_payload,after_payload,observed_at)
                        VALUES (?,?,?,?,?,?,?)""", (owner, key, kind, json.dumps(changed),
                           json.dumps(before, ensure_ascii=False) if before else None,
                           json.dumps(after, ensure_ascii=False) if after else None, stamp))
                    counts[owner] += 1

                for key, after in incoming.items():
                    old = stored.get(key)
                    before = json.loads(old["payload"]) if old else None
                    changed = [field for field in FIELDS if before and before.get(field) != after.get(field)]
                    if not baseline and (not old or not old["present"] or changed):
                        for owner in counts:
                            old_scope, new_scope = _in_window(before, owner, now), _in_window(after, owner, now)
                            if not (old_scope or new_scope):
                                continue
                            if not old:
                                kind = "added"
                            elif not old["present"]:
                                kind = "reappeared"
                            elif _sold(after) and not _sold(before):
                                kind = "sold"
                            elif after["status"] == "ended" and before["status"] != "ended":
                                kind = "ended"
                            elif _belongs(before, owner) != _belongs(after, owner):
                                kind = "scope_changed"
                            else:
                                kind = "changed"
                            emit(owner, key, kind, before, after, changed)
                    db.execute("""INSERT INTO reminder_update_snapshots
                        (lot_key,payload,present,first_seen_at,last_seen_at) VALUES (?,?,1,?,?)
                        ON CONFLICT(lot_key) DO UPDATE SET payload=excluded.payload,present=1,last_seen_at=excluded.last_seen_at""",
                               (key, json.dumps(after, ensure_ascii=False), stamp, stamp))
                for key, old in stored.items():
                    if key in incoming or not old["present"]:
                        continue
                    before = json.loads(old["payload"])
                    for owner in counts:
                        if _future_active(before, owner, now):
                            emit(owner, key, "no_longer_present", before, None, [])
                    db.execute("UPDATE reminder_update_snapshots SET present=0 WHERE lot_key=?", (key,))
                db.execute("INSERT INTO reminder_update_state VALUES (1,?) ON CONFLICT(singleton) DO UPDATE SET last_scan_at=excluded.last_scan_at", (stamp,))
            result = {"baseline_created": baseline, "ignored_stale_scan": stale,
                      "scanned_at": stamp, "new_event_count": sum(counts.values()),
                      "owner_event_counts": counts,
                      "owners": _status(db, _helper().aware(previous["last_scan_at"]) if stale else now)}
            db.commit()
            return result
        except BaseException:
            db.rollback()
            raise


def draft_status(ledger_path, now=None):
    now = now or datetime.now(UTC)
    with closing(_connect(ledger_path)) as db:
        return {"owners": _status(db, now)}


def claim_draft(ledger_path, owner, days, target_date, through_event_id, now=None):
    now = now or datetime.now(UTC)
    if owner not in _helper().OWNERS or days not in range(1, 6):
        raise ValueError("Choose a configured owner and a 1–5 day category.")
    with closing(_connect(ledger_path)) as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            group = _group(db, owner, days, now)
            if group["operation"]:
                db.commit()
                return {"claimed": False, "reason": "Reconcile the reserved draft operation before another mutation.",
                        "operation": group["operation"]}
            if group["target_date"] != target_date or group["through_event_id"] != through_event_id:
                raise ValueError("The draft plan changed; refresh draft-status before claiming.")
            if not group["draft_action"]:
                db.commit()
                return {"claimed": False, "reason": "The draft is current or there are no changes to draft."}
            token = uuid.uuid4().hex
            action = {**group["draft_action"], "revision": group["revision"]}
            db.execute("""INSERT INTO reminder_update_drafts
                (owner,days,operation_token,operation_payload,operation_state)
                VALUES (?,?,?,?,'claimed') ON CONFLICT(owner,days) DO UPDATE SET
                operation_token=excluded.operation_token,operation_payload=excluded.operation_payload,
                operation_state='claimed',operation_reason=NULL""", (owner, days, token, json.dumps(action, ensure_ascii=False)))
            db.commit()
            return {"claimed": True, "claim_token": token, **action}
        except BaseException:
            db.rollback()
            raise


def record_draft(ledger_path, owner, days, draft_id, through_event_id, claim_token):
    if not draft_id.strip():
        raise ValueError("A verified Gmail draft ID is required.")
    with closing(_connect(ledger_path)) as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            row = db.execute("SELECT * FROM reminder_update_drafts WHERE owner=? AND days=?", (owner, days)).fetchone()
            if not row or row["operation_token"] != claim_token:
                raise ValueError("No matching reserved draft operation.")
            action = json.loads(row["operation_payload"])
            if action["through_event_id"] != through_event_id:
                raise ValueError("The acknowledged change ID must match the immutable draft operation.")
            if action["kind"] == "update" and action["gmail"]["draft_id"] != draft_id:
                raise ValueError("An update must acknowledge the same existing draft ID.")
            db.execute("""UPDATE reminder_update_drafts SET draft_id=?,target_date=?,through_event_id=?,
                revision=?,updated_at=?,operation_token=NULL,operation_payload=NULL,
                operation_state=NULL,operation_reason=NULL WHERE owner=? AND days=?""",
                       (draft_id, action["target_date"], through_event_id, action["revision"],
                        datetime.now(UTC).isoformat(), owner, days))
            db.commit()
        except BaseException:
            db.rollback()
            raise
    return {"recorded": True, "owner": owner, "days_away": days, "draft_id": draft_id,
            "through_event_id": through_event_id}


def unknown_draft(ledger_path, owner, days, claim_token, reason):
    with closing(_connect(ledger_path)) as db:
        changed = db.execute("""UPDATE reminder_update_drafts SET operation_state='unknown',operation_reason=?
            WHERE owner=? AND days=? AND operation_token=?""", (reason, owner, days, claim_token)).rowcount
        if not changed:
            raise ValueError("No matching reserved draft operation.")
    return {"owner": owner, "days_away": days, "state": "unknown"}


def release_draft(ledger_path, owner, days, claim_token, *, confirmed_not_applied=False,
                  reason="", missing_draft=False):
    """Release only an externally verified non-application, retaining its audit.

    A missing draft requires a definitive provider 404 plus reconciliation.
    An empty draft listing alone does not establish either required fact.
    """
    if not confirmed_not_applied:
        raise ValueError("Explicit confirmation that the operation was not applied is required; ambiguous outcomes stay reserved.")
    if not reason.strip():
        raise ValueError("Record the definitive provider rejection or verified 404 and reconciliation evidence.")
    with closing(_connect(ledger_path)) as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            row = db.execute("SELECT * FROM reminder_update_drafts WHERE owner=? AND days=?", (owner, days)).fetchone()
            if not row or not claim_token or row["operation_token"] != claim_token:
                raise ValueError("No matching reserved draft operation.")
            action = json.loads(row["operation_payload"])
            if missing_draft and (not row["draft_id"] or action["kind"] != "update"):
                raise ValueError("A missing-draft reset requires a reserved update of an existing draft.")
            db.execute("""INSERT INTO reminder_update_draft_recoveries
                (owner,days,operation_token,operation_payload,previous_state,missing_draft,proof_reason,released_at)
                VALUES (?,?,?,?,?,?,?,?)""", (owner, days, claim_token, row["operation_payload"],
                    json.dumps(dict(row), ensure_ascii=False), int(missing_draft), reason.strip(), datetime.now(UTC).isoformat()))
            db.execute("""UPDATE reminder_update_drafts SET operation_token=NULL,operation_payload=NULL,
                operation_state=NULL,operation_reason=NULL WHERE owner=? AND days=?""", (owner, days))
            if missing_draft:
                db.execute("""UPDATE reminder_update_drafts SET draft_id=NULL,target_date=NULL,
                    through_event_id=0,revision=NULL WHERE owner=? AND days=?""", (owner, days))
            db.commit()
        except BaseException:
            db.rollback()
            raise
    return {"released": True, "owner": owner, "days_away": days,
            "missing_draft_reset": bool(missing_draft), "reason": reason.strip()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, default=_helper().LEDGER)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("draft-status")
    for name in ("draft-claim", "draft-record", "draft-unknown", "draft-release"):
        command = commands.add_parser(name)
        command.add_argument("--owner", choices=tuple(_helper().OWNERS), required=True)
        command.add_argument("--days", type=int, choices=range(1, 6), required=True)
        if name in {"draft-claim", "draft-record"}:
            command.add_argument("--through-event-id", type=int, required=True)
        if name == "draft-claim":
            command.add_argument("--target-date", required=True)
        else:
            command.add_argument("--claim-token", required=True)
            command.add_argument("--draft-id" if name == "draft-record" else "--reason", required=True)
            if name == "draft-release":
                command.add_argument("--confirmed-not-applied", action="store_true")
                command.add_argument("--missing-draft", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "draft-status":
            result = draft_status(args.ledger)
        elif args.command == "draft-claim":
            result = claim_draft(args.ledger, args.owner, args.days, args.target_date, args.through_event_id)
        elif args.command == "draft-record":
            result = record_draft(args.ledger, args.owner, args.days, args.draft_id, args.through_event_id, args.claim_token)
        elif args.command == "draft-release":
            result = release_draft(args.ledger, args.owner, args.days, args.claim_token,
                                   confirmed_not_applied=args.confirmed_not_applied,
                                   reason=args.reason, missing_draft=args.missing_draft)
        else:
            result = unknown_draft(args.ledger, args.owner, args.days, args.claim_token, args.reason)
        # Windows pipe stdout can be cp1252; JSON escapes preserve emoji without
        # failing after a durable draft claim has already been committed.
        print(json.dumps(result))
        return 0
    except (ValueError, KeyError, TypeError, OSError, sqlite3.Error) as exc:
        print(f"Calendar update drafts: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
