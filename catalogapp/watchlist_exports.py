"""Agenda rendering and local Markdown, CSV, and RFC 5545 exports."""

from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
import hashlib
from io import StringIO
from itertools import groupby
from typing import Iterable

from catalogapp.watchlist_models import NormalizedLot, parse_lot_datetime


def agenda_date(lot: NormalizedLot) -> str:
    parsed, _all_day = parse_lot_datetime(lot.relevant_at)
    return parsed.date().isoformat() if parsed else "Date unverified"


def render_markdown(lots: Iterable[NormalizedLot]) -> str:
    ordered = sorted(lots, key=_sort_key)
    lines = ["# Artist Watchlist Agenda", ""]
    if not ordered:
        return "\n".join(lines + ["No watched lots are currently in this horizon.", ""])
    for day, day_items in groupby(ordered, key=agenda_date):
        lines.extend((f"## {day}", ""))
        day_lots = list(day_items)
        for artist, artist_items in groupby(day_lots, key=lambda lot: lot.artist_watchlist_name or lot.artist):
            lines.extend((f"### {artist}", ""))
            for lot in artist_items:
                house_sale = " — ".join(value for value in (lot.auction_house, lot.sale_title) if value) or lot.source
                lot_label = f"Lot {lot.lot_number}" if lot.lot_number else "Lot"
                money = _money_label(lot)
                marker = f" **[{lot.status.upper()}]**" if lot.status in {"new", "changed", "ended"} else ""
                link = f" ([source]({lot.lot_url}))" if lot.lot_url else ""
                lines.append(f"- {house_sale} — {lot_label} — {lot.title or 'Untitled'}{money}{marker}{link}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_csv(lots: Iterable[NormalizedLot]) -> str:
    output = StringIO(newline="")
    fields = [
        "date",
        "artist",
        "source",
        "auction_house",
        "sale_title",
        "lot_number",
        "title",
        "medium",
        "estimate_low",
        "estimate_high",
        "currency",
        "current_bid",
        "status",
        "lot_url",
        "sale_url",
    ]
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for lot in sorted(lots, key=_sort_key):
        writer.writerow(
            {
                "date": agenda_date(lot),
                "artist": lot.artist_watchlist_name or lot.artist,
                "source": lot.source,
                "auction_house": lot.auction_house,
                "sale_title": lot.sale_title,
                "lot_number": lot.lot_number,
                "title": lot.title,
                "medium": lot.medium,
                "estimate_low": "" if lot.estimate_low is None else lot.estimate_low,
                "estimate_high": "" if lot.estimate_high is None else lot.estimate_high,
                "currency": lot.currency,
                "current_bid": "" if lot.current_bid is None else lot.current_bid,
                "status": lot.status,
                "lot_url": lot.lot_url,
                "sale_url": lot.sale_url,
            }
        )
    return output.getvalue()


def render_ics(
    lots: Iterable[NormalizedLot],
    *,
    event_per_lot: bool = False,
    include_reminders: bool = False,
    generated_at: datetime | None = None,
) -> str:
    dated = [lot for lot in lots if parse_lot_datetime(lot.relevant_at)[0] is not None and lot.status != "ended"]
    groups: dict[tuple[str, ...], list[NormalizedLot]] = {}
    for lot in dated:
        key = (lot.cache_key,) if event_per_lot else _sale_key(lot)
        groups.setdefault(key, []).append(lot)
    stamp = (generated_at or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//SecondState//Artist Watchlist//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]
    for key, group in sorted(groups.items(), key=lambda item: _sort_key(item[1][0])):
        group.sort(key=lambda lot: ((lot.artist_watchlist_name or lot.artist).casefold(), lot.lot_number.casefold()))
        first = group[0]
        parsed, all_day = parse_lot_datetime(first.relevant_at)
        if parsed is None:
            continue
        uid_seed = "|".join(key)
        uid = hashlib.sha256(uid_seed.encode("utf-8")).hexdigest()[:32] + "@secondstate.watchlist"
        source = first.source or "Auction"
        summary = (
            f"{source} — {first.artist_watchlist_name or first.artist} — {first.title or 'watched lot'}"
            if event_per_lot
            else f"{source} — {len(group)} watched print lot{'s' if len(group) != 1 else ''}"
        )
        lines.extend(("BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{stamp}", f"SUMMARY:{_ics_escape(summary)}"))
        if all_day:
            lines.append(f"DTSTART;VALUE=DATE:{parsed.strftime('%Y%m%d')}")
            lines.append(f"DTEND;VALUE=DATE:{(parsed + timedelta(days=1)).strftime('%Y%m%d')}")
        else:
            utc_start = parsed.astimezone(timezone.utc)
            lines.append(f"DTSTART:{utc_start.strftime('%Y%m%dT%H%M%SZ')}")
            lines.append(f"DTEND:{(utc_start + timedelta(hours=1)).strftime('%Y%m%dT%H%M%SZ')}")
        lines.append(f"DESCRIPTION:{_ics_escape(_calendar_description(group, all_day))}")
        official_url = first.sale_url or first.lot_url
        if official_url:
            lines.append(f"URL:{_ics_escape(official_url)}")
        if include_reminders and not all_day:
            for trigger, label in (("-PT24H", "Auction in 24 hours"), ("-PT1H", "Auction in 1 hour")):
                lines.extend(
                    (
                        "BEGIN:VALARM",
                        f"TRIGGER:{trigger}",
                        "ACTION:DISPLAY",
                        f"DESCRIPTION:{label}",
                        "END:VALARM",
                    )
                )
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold_ics_line(line) for line in lines) + "\r\n"


def render_calendar_preview(lots: Iterable[NormalizedLot]) -> str:
    dated = [lot for lot in sorted(lots, key=_sort_key) if lot.status != "ended"]
    if not dated:
        return "No calendar events in the selected horizon."
    groups: dict[tuple[str, ...], list[NormalizedLot]] = {}
    for lot in dated:
        groups.setdefault(_sale_key(lot), []).append(lot)
    lines: list[str] = []
    for group in sorted(groups.values(), key=lambda items: _sort_key(items[0])):
        first = group[0]
        lines.append(f"{agenda_date(first)}  {first.auction_house or first.source} — {first.sale_title or 'Auction sale'}")
        for lot in group:
            lines.append(f"    {lot.artist_watchlist_name or lot.artist} — Lot {lot.lot_number or '?'} — {lot.title}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _calendar_description(group: list[NormalizedLot], all_day: bool) -> str:
    lines = ["Auction time is unverified; source supplied a date only."] if all_day else []
    current_artist = None
    for lot in group:
        artist = lot.artist_watchlist_name or lot.artist or "Unknown artist"
        if artist != current_artist:
            lines.append(artist)
            current_artist = artist
        line = f"  Lot {lot.lot_number or '?'} — {lot.title or 'Untitled'}"
        if lot.lot_url:
            line += f" — {lot.lot_url}"
        lines.append(line)
    return "\n".join(lines)


def _sale_key(lot: NormalizedLot) -> tuple[str, ...]:
    parsed, _all_day = parse_lot_datetime(lot.relevant_at)
    if lot.sale_url:
        return (lot.source.casefold(), lot.sale_url)
    day = parsed.date().isoformat() if parsed else ""
    return (
        lot.source.casefold(),
        lot.auction_house.casefold(),
        lot.sale_title.casefold(),
        day,
    )


def _money_label(lot: NormalizedLot) -> str:
    code = f" {lot.currency}" if lot.currency else ""
    if lot.estimate_low is not None or lot.estimate_high is not None:
        low = "?" if lot.estimate_low is None else f"{lot.estimate_low:,.0f}"
        high = "?" if lot.estimate_high is None else f"{lot.estimate_high:,.0f}"
        return f" — estimate {low}–{high}{code}"
    if lot.current_bid is not None:
        return f" — bid {lot.current_bid:,.0f}{code}"
    return ""


def _sort_key(lot: NormalizedLot) -> tuple[str, str, str, str]:
    parsed, _all_day = parse_lot_datetime(lot.relevant_at)
    when = parsed.isoformat() if parsed else "9999-12-31T23:59:59+00:00"
    return (
        when,
        (lot.artist_watchlist_name or lot.artist).casefold(),
        lot.auction_house.casefold(),
        lot.lot_number.casefold(),
    )


def _ics_escape(value: str) -> str:
    return (
        (value or "")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def _fold_ics_line(line: str) -> str:
    if len(line.encode("utf-8")) <= 75:
        return line
    chunks: list[str] = []
    current = ""
    limit = 75
    for char in line:
        candidate = current + char
        if current and len(candidate.encode("utf-8")) > limit:
            chunks.append(current)
            current = char
            limit = 74  # Continuation lines begin with one space.
        else:
            current = candidate
    if current:
        chunks.append(current)
    return "\r\n ".join(chunks)
