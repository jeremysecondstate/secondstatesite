"""Prepare Calendar reminder digests; Gmail delivery is performed by the scheduled agent.

This script never sends mail or changes the website. A durable claim must precede
Gmail send_email; record its returned ID with ``sent``. An uncertain send stays
claimed/unknown until the agent reconciles the sender's Sent mailbox.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import date, datetime, time, timedelta, timezone
from html import escape
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from secondstateapp.oliver_houses import is_oliver_house

UTC = timezone.utc
BASE_URL = "https://secondstate.art"
LEDGER = ROOT / "private_data" / "calendar-reminders" / "deliveries.sqlite3"
SCHEDULE = {
    5: ("10:00",),
    4: ("12:00", "18:00"),
    3: ("09:00", "13:00", "18:00"),
    2: ("07:00", "11:00", "15:00", "18:00"),
    1: ("06:00", "09:00", "12:00", "15:00", "18:00"),
}
OWNERS = {
    "jeremy": {"zone": "America/Los_Angeles", "view": "catalog",
               "link_id": "link_6ad41eae32d081918462849699f226a2",
               "to": ["jeremy@secondstate.art", "alex@secondstate.art"]},
    "oliver": {"zone": "America/New_York", "view": "oliver",
               "link_id": "link_6aeb8f025d2081918f927770c4dd0a06",
               "to": ["oliver@secondstate.art", "alex@secondstate.art", "OliverGDonson@gmail.com", "oliver1@vt.edu"]},
}
GRACE = timedelta(hours=1)
CATEGORY_STYLES = {
    5: {"emoji": "🟦", "background": "#1D4ED8", "foreground": "#FFFFFF"},
    4: {"emoji": "🟪", "background": "#6D28D9", "foreground": "#FFFFFF"},
    3: {"emoji": "🟨", "background": "#FACC15", "foreground": "#1F2937"},
    2: {"emoji": "🟧", "background": "#9A3412", "foreground": "#FFFFFF"},
    1: {"emoji": "🟥", "background": "#B42318", "foreground": "#FFFFFF"},
}


def category_date_label(sale_date: date | str) -> str:
    day = date.fromisoformat(sale_date) if isinstance(sale_date, str) else sale_date
    return f"{day:%b} {day.day}, {day.year}"


def category_subject(days_away: int, owner: str, sale_date: date | str, reference: str,
                     *, kind: str = "REMINDER", no_sales: bool = False) -> str:
    style = CATEGORY_STYLES[days_away]
    empty = " · No sales" if no_sales else ""
    return (f"{style['emoji']} {days_away}-DAY {kind.upper()} · {owner.title()} · "
            f"{category_date_label(sale_date)}{empty} [{reference}]")


def category_banner(days_away: int, owner: str, sale_date: date | str,
                    *, kind: str = "REMINDER") -> str:
    style = CATEGORY_STYLES[days_away]
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
            f'style="width:100%;border-collapse:collapse;background-color:{style["background"]};'
            f'color:{style["foreground"]};"><tr><td style="padding:22px 24px;'
            f'color:{style["foreground"]};font-family:Arial,Helvetica,sans-serif;">'
            f'<div style="font-size:22px;line-height:1.35;font-weight:bold;">'
            f'{style["emoji"]} {days_away}-DAY {escape(kind.upper())}</div>'
            f'<div style="margin-top:8px;font-size:16px;line-height:1.5;">'
            f'{escape(owner.title())}\'s Calendar · {escape(category_date_label(sale_date))}'
            '</div></td></tr></table>')


def aware(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("A timezone-aware timestamp is required.")
    return parsed


def public_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme in {"https", "http"} and parsed.hostname
                 and not parsed.username and not parsed.password
                 and parsed.port in {None, 80, 443} and "\\" not in value
                 and not any(ord(char) < 32 for char in value))
        return value if valid else ""
    except ValueError:
        return ""


def validate_record(row: object) -> dict:
    if not isinstance(row, dict):
        raise ValueError("Invalid Calendar lot record.")
    fields = ("source", "source_lot_id", "lot_url", "auction_house", "sale_title",
              "sale_url", "end_at", "start_at", "status", "artist", "artist_watchlist_name",
              "title", "lot_number", "currency", "sold_currency", "medium")
    result = {}
    for field in fields:
        value = row.get(field, "")
        if not isinstance(value, str) or len(value) > 20000 or "\x00" in value:
            raise ValueError("Invalid Calendar lot field.")
        result[field] = value
    if not result["source"] or not (result["source_lot_id"] or result["lot_url"]):
        raise ValueError("Missing Calendar lot identity.")
    if result["status"] not in {"new", "changed", "unchanged", "ended"}:
        raise ValueError("Invalid Calendar lot status.")
    for field in ("sold_price", "estimate_low", "estimate_high", "current_bid"):
        value = row.get(field)
        if value is not None and (type(value) not in {int, float} or not math.isfinite(value) or value < 0):
            raise ValueError(f"Invalid Calendar {field}.")
        result[field] = value
    bids = row.get("bid_count")
    if bids is not None and (type(bids) is not int or bids < 0):
        raise ValueError("Invalid Calendar bid count.")
    result["bid_count"] = bids
    return result


def fetch_lots(session=None) -> tuple[list[dict], dict]:
    import requests
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)
    key = os.environ.get("CATALOG_API_KEY", "").strip()
    if not key:
        raise ValueError("CATALOG_API_KEY is unavailable.")
    session = session or requests
    cursor, cursors, identities, inventory, lots, counts = "0", {"0"}, set(), set(), [], []
    for _ in range(200):
        try:
            response = session.get(BASE_URL + "/calendar/watchlist/",
                                   params={"cursor": cursor, "page_size": 500, "horizon_days": 7},
                                   headers={"X-API-KEY": key, "Accept": "application/json"},
                                   timeout=(10, 60), allow_redirects=False)
        except requests.RequestException:
            raise ValueError("The live Calendar could not be read.") from None
        if response.status_code != 200:
            raise ValueError(f"Live Calendar returned HTTP {response.status_code}.")
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("Live Calendar returned invalid JSON.") from None
        if not isinstance(payload, dict) or payload.get("ok") is not True or payload.get("version") != 1:
            raise ValueError("Invalid live Calendar response.")
        records = payload.get("lots")
        keys = payload.get("calendar_lot_keys")
        if not isinstance(records, list) or len(records) > 500:
            raise ValueError("Invalid Calendar page.")
        if not isinstance(keys, list) or any(not isinstance(k, str) or ":" not in k for k in keys):
            raise ValueError("Invalid Calendar inventory.")
        inventory.update(keys)
        for record in records:
            row = validate_record(record)
            identity = row["source"].casefold() + ":" + (row["source_lot_id"] or row["lot_url"])
            if identity in identities:
                raise ValueError("Duplicate Calendar record; no partial reminder will be prepared.")
            identities.add(identity)
            lots.append(row)
        counts.append(len(records))
        cursor = payload.get("next_cursor")
        if cursor is None:
            if not identities.issubset(inventory):
                raise ValueError("Incomplete Calendar inventory.")
            return lots, {"fetched_at": datetime.now(UTC).isoformat(), "page_counts": counts,
                          "lot_count": len(lots), "endpoint": BASE_URL + "/calendar/watchlist/"}
        if not isinstance(cursor, str) or not cursor.isdecimal() or len(cursor) > 30 or cursor in cursors or not records:
            raise ValueError("Invalid Calendar pagination; no partial reminder will be prepared.")
        cursors.add(cursor)
    raise ValueError("Calendar page limit exceeded; no partial reminder will be prepared.")


def event_details(row: dict, zone: ZoneInfo) -> tuple[date, str, date]:
    raw = row.get("end_at") or row.get("start_at") or ""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        day = date.fromisoformat(raw)
        return day, "Time TBA (date-only listing)", day
    event = aware(raw)
    local = event.astimezone(zone)
    # Calendar links use the site's Pacific date even when the email uses ET.
    calendar_day = event.astimezone(ZoneInfo("America/Los_Angeles")).date()
    return local.date(), local.strftime("%I:%M %p %Z").lstrip("0"), calendar_day


def due_slots(owner: str, now: datetime) -> list[tuple[datetime, set[int]]]:
    zone = ZoneInfo(OWNERS[owner]["zone"])
    local = now.astimezone(zone)
    by_slot = {}
    for days, times in SCHEDULE.items():
        for label in times:
            scheduled = datetime.combine(local.date(), time.fromisoformat(label), zone)
            elapsed = now.astimezone(UTC) - scheduled.astimezone(UTC)
            if timedelta(0) <= elapsed < GRACE:
                by_slot.setdefault(scheduled, set()).add(days)
    return sorted(by_slot.items())


def compose(owner: str, scheduled: datetime, lead_days: set[int], lots: list[dict]) -> tuple[dict, int]:
    if len(lead_days) != 1:
        raise ValueError("Each reminder must contain exactly one days-away category.")
    days_away = next(iter(lead_days))
    if days_away not in SCHEDULE:
        raise ValueError("Unsupported days-away category.")
    config, groups, ambiguous = OWNERS[owner], {}, 0
    zone = ZoneInfo(config["zone"])
    for row in lots:
        if row.get("status") == "ended" or (row.get("sold_price") or 0) > 0:
            continue
        if owner == "oliver" and not is_oliver_house(row.get("auction_house", "")):
            continue
        try:
            day, label, calendar_day = event_details(row, zone)
        except (TypeError, ValueError, OverflowError):
            ambiguous += 1
            continue
        lead = (day - scheduled.date()).days
        if lead not in lead_days:
            continue
        house = row.get("auction_house") or "Auction house unspecified"
        title = row.get("sale_title") or house
        sale_url = public_url(row.get("sale_url", ""))
        fallback = "|".join((row.get("source", ""), house, row.get("sale_title", ""),
                              row.get("end_at") or row.get("start_at") or ""))
        identity = (day.isoformat(), sale_url or fallback)
        group = groups.setdefault(identity, {"sale_date": day.isoformat(), "days_away": lead,
                                            "house": house, "title": title, "sale_url": sale_url,
                                            "lot_url": public_url(row.get("lot_url", "")),
                                            "times": set(), "calendar_dates": set(), "lot_count": 0})
        group["times"].add(label)
        group["calendar_dates"].add(calendar_day.isoformat())
        group["lot_count"] += 1
    slot = scheduled.isoformat()
    key = f"{owner}|{config['zone']}|{slot}|days:{days_away}"
    token = "SSR-" + hashlib.sha256(key.encode()).hexdigest()[:16].upper()
    target_date = scheduled.date() + timedelta(days=days_away)
    subject = category_subject(days_away, owner, target_date, token, no_sales=not groups and not ambiguous)
    html = ['<div style="max-width:760px;margin:0 auto;font-family:Arial,Helvetica,sans-serif;'
            'font-size:15px;line-height:1.6;color:#1F2937;background-color:#FFFFFF;">',
            category_banner(days_away, owner, target_date),
            '<div style="padding:8px 24px 24px;">',
            f"<p>Reminder for {escape(scheduled.strftime('%B %d, %Y at %I:%M %p %Z'))}. "
            "Current sales are grouped below; follow the catalog links for the latest lots and saved research.</p>"]
    sales, lead_status = [], []
    for lead in sorted(lead_days):
        target = (scheduled.date() + timedelta(days=lead)).isoformat()
        count = sum(1 for group in groups.values() if group["days_away"] == lead)
        state = "sales_found" if count else "dates_unavailable" if ambiguous else "no_sales"
        lead_status.append({"days_away": lead, "sale_date": target, "sale_count": count, "state": state})
        if not count:
            if ambiguous:
                html.append(f"<p>No confirmed dated sales found in {lead} days ({target}). "
                            f"{ambiguous} catalog lot(s) have unavailable or ambiguous dates; "
                            "a no-sales result cannot be confirmed.</p>")
            else:
                html.append(f"<p>No sales on {escape(owner.title())}'s Calendar in {lead} days ({target}).</p>")
    if ambiguous and groups:
        html.append(f"<p>Date check incomplete: {ambiguous} catalog lot(s) have unavailable or ambiguous "
                    "dates and cannot be assigned to the reminder dates below.</p>")
    for identity, group in sorted(groups.items()):
        group["times"] = sorted(group["times"])
        group["calendar_dates"] = sorted(group["calendar_dates"])
        group["catalog_links"] = [BASE_URL + "/calendar/?" + urlencode({"view": config["view"],
                                  "month": day[:7], "day": day}) for day in group["calendar_dates"]]
        title = escape(group["title"])
        link = group["sale_url"] or group["lot_url"]
        if link:
            title = f'<a href="{escape(link, quote=True)}">{title}</a>'
        html.append(f'<h3 style="font-size:18px;line-height:1.4;margin:24px 0 8px;'
                    f'padding-bottom:8px;border-bottom:1px solid #D1D5DB;">{title}</h3>'
                    f"<p>{escape(group['house'])}<br>"
                    f"{group['sale_date']} — {group['days_away']} day(s) away<br>"
                    f"{escape('; '.join(group['times']))}<br>{group['lot_count']} catalog lot(s)</p><p>")
        html.extend(f'<a href="{escape(url, quote=True)}">Open {escape(owner.title())}\'s catalog ({day})</a><br>'
                    for day, url in zip(group["calendar_dates"], group["catalog_links"]))
        html.append("</p>")
        sales.append(group)
    html.append(f'<p style="margin-top:28px;font-size:12px;color:#4B5563;">Reference: {token}</p></div></div>')
    return {"key": key, "owner": owner, "scheduled_at": slot, "zone": config["zone"],
            "reference": token, "days_away": days_away, "sale_date": str(target_date),
            "sales": sales, "lead_status": lead_status,
            "ambiguous_date_count": ambiguous,
            "gmail": {"link_id": config["link_id"], "from_address": owner + "@secondstate.art",
                      "to": ", ".join(config["to"]), "subject": subject,
                      "payload": {"mime_type": "text/html", "charset": "UTF-8",
                                  "body": {"content": "\n".join(html)}}}}, ambiguous


def make_plan(lots: list[dict], now: datetime) -> dict:
    messages, ambiguous = [], {}
    for owner in OWNERS:
        for scheduled, lead_days in due_slots(owner, now):
            for days_away in sorted(lead_days):
                message, count = compose(owner, scheduled, {days_away}, lots)
                ambiguous[owner] = max(ambiguous.get(owner, 0), count)
                messages.append(message)
    return {"version": 1, "planned_at": now.astimezone(UTC).isoformat(),
            "grace_minutes": int(GRACE.total_seconds() / 60),
            "delivery_window": "Current scheduled local hour, ending before the next hour",
            "ambiguous_date_counts": ambiguous, "messages": messages}


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("""CREATE TABLE IF NOT EXISTS deliveries (
        key TEXT PRIMARY KEY, owner TEXT NOT NULL, scheduled_at TEXT NOT NULL,
        state TEXT NOT NULL, payload TEXT NOT NULL, claimed_at TEXT NOT NULL,
        updated_at TEXT NOT NULL, message_id TEXT, reason TEXT)""")
    db.commit()
    return db


def claim(db: sqlite3.Connection, message: dict, now: datetime) -> bool:
    scheduled = aware(message["scheduled_at"])
    owner = message["owner"]
    days_away = message.get("days_away")
    if (owner not in OWNERS or type(days_away) is not int or days_away not in SCHEDULE
            or message["key"] != f"{owner}|{OWNERS[owner]['zone']}|{scheduled.isoformat()}|days:{days_away}"):
        raise ValueError("Invalid reminder key.")
    zone = ZoneInfo(OWNERS[owner]["zone"])
    local_slot = scheduled.astimezone(zone)
    if (local_slot.strftime("%H:%M") not in SCHEDULE[days_away] or local_slot.second or local_slot.microsecond
            or scheduled.utcoffset() != local_slot.utcoffset()
            or not timedelta(0) <= now.astimezone(UTC) - scheduled.astimezone(UTC) < GRACE):
        raise ValueError("Reminder must belong to the current scheduled local hour.")
    expected = OWNERS[owner]
    gmail = message["gmail"]
    if (gmail["link_id"] != expected["link_id"] or gmail["from_address"] != owner + "@secondstate.art"
            or gmail["to"] != ", ".join(expected["to"])):
        raise ValueError("Reminder sender or recipients do not match the configured stream.")
    stamp = now.astimezone(UTC).isoformat()
    with db:
        inserted = db.execute("""INSERT OR IGNORE INTO deliveries
            (key, owner, scheduled_at, state, payload, claimed_at, updated_at)
            VALUES (?, ?, ?, 'claimed', ?, ?, ?)""",
                              (message["key"], owner, message["scheduled_at"],
                               json.dumps(message, ensure_ascii=False), stamp, stamp)).rowcount
    return inserted == 1


def mark(db: sqlite3.Connection, key: str, state: str, *, message_id: str = "", reason: str = "") -> None:
    if state == "sent" and not message_id.strip():
        raise ValueError("A returned or reconciled Gmail message ID is required.")
    if state not in {"sent", "unknown"}:
        raise ValueError("Unsupported delivery state.")
    with db:
        changed = db.execute("""UPDATE deliveries SET state=?, updated_at=?, message_id=?, reason=?
            WHERE key=? AND state IN ('claimed', 'unknown')""",
                             (state, datetime.now(UTC).isoformat(), message_id or None, reason or None, key)).rowcount
    if not changed:
        raise ValueError("No unresolved claim matched; sent reminders cannot be overwritten.")


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=path.name + ".", suffix=".tmp", delete=False) as output:
            temporary = Path(output.name)
            json.dump(value, output, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, default=LEDGER)
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan", help="Fetch live Calendar and write due Gmail payloads; never sends or claims.")
    plan.add_argument("--output", type=Path, required=True)
    plan.add_argument("--at", help="Timezone-aware timestamp for a non-delivery preview; default is now.")
    reserve = commands.add_parser("claim", help="Atomically reserve one due reminder, printing its Gmail payload once.")
    reserve.add_argument("--plan", type=Path, required=True)
    reserve.add_argument("--key", required=True)
    for command in ("sent", "unknown"):
        action = commands.add_parser(command)
        action.add_argument("--key", required=True)
        action.add_argument("--message-id" if command == "sent" else "--reason", required=True)
    commands.add_parser("status", help="List durable delivery state and unresolved claims.")
    show = commands.add_parser("show", help="Read an immutable claim including subject/reference for Sent reconciliation.")
    show.add_argument("--key", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            lots, source = fetch_lots()
            now = aware(args.at) if args.at else datetime.now(UTC)
            result = make_plan(lots, now)
            result["source"] = source
            result["preview_only"] = bool(args.at)
            if args.at:
                result["updates"] = {"preview_only": True, "tracking_unchanged": True}
            else:
                from scripts.calendar_reminder_updates import scan_updates
                result["updates"] = scan_updates(lots, now, args.ledger)
            atomic_json(args.output, result)
            print(json.dumps({"output": str(args.output.resolve()), "source": source,
                              "message_count": len(result["messages"]),
                              "ambiguous_date_counts": result["ambiguous_date_counts"],
                              "preview_only": result["preview_only"]}))
            return 0
        with closing(connect(args.ledger)) as db:
            if args.command == "claim":
                plan = json.loads(args.plan.read_text(encoding="utf-8"))
                if plan.get("preview_only") or plan.get("version") != 1:
                    raise ValueError("Preview or invalid plans cannot be claimed.")
                matched = [message for message in plan["messages"] if message["key"] == args.key]
                if len(matched) != 1:
                    raise ValueError("Exactly one matching reminder is required.")
                message = matched[0]
                if claim(db, message, datetime.now(UTC)):
                    print(json.dumps({"claimed": True, **message}, ensure_ascii=True))
                else:
                    print(json.dumps({"claimed": False, "key": args.key,
                                      "reason": "Already reserved; reconcile unresolved claims instead of sending again."}))
            elif args.command in {"sent", "unknown"}:
                mark(db, args.key, args.command, message_id=getattr(args, "message_id", ""),
                     reason=getattr(args, "reason", ""))
                print(json.dumps({"key": args.key, "state": args.command}))
            elif args.command == "show":
                stored = db.execute("SELECT * FROM deliveries WHERE key=?", (args.key,)).fetchone()
                if stored is None:
                    raise ValueError("Reminder key was not found.")
                result = dict(stored)
                result["payload"] = json.loads(result["payload"])
                print(json.dumps(result, ensure_ascii=True))
            else:
                rows = db.execute("SELECT key,owner,scheduled_at,state,claimed_at,updated_at,message_id,reason "
                                  "FROM deliveries ORDER BY scheduled_at DESC").fetchall()
                print(json.dumps([dict(row) for row in rows], ensure_ascii=True))
        return 0
    except (ValueError, KeyError, TypeError, OSError, sqlite3.Error) as exc:
        print(f"Calendar reminders: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
