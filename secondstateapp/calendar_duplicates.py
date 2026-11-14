"""Reviewable Calendar duplicate audit and reversible display suppression.

No source records or saved work are deleted. Candidate evidence is intentionally
conservative, and callers must explicitly review a plan before applying it.
"""

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
from itertools import combinations
import json
import re
import unicodedata
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from catalogapp.artprice_artist_links import artist_identity_key
from catalogapp.bookmark_watchlist import canonicalize_bookmark_url
from .oliver_houses import is_oliver_house, oliver_house_name


PUBLIC_FIELDS = (
    "id", "source", "source_lot_id", "artist", "artist_watchlist_name", "title",
    "medium", "auction_house", "sale_title", "lot_number", "event_at", "is_all_day",
    "currency", "estimate_low", "estimate_high", "lot_url", "sale_url", "image_url",
    "active", "superseded_by_id",
)


def snapshot(lot):
    values = {field: getattr(lot, field) for field in PUBLIC_FIELDS}
    for key, value in values.items():
        if isinstance(value, datetime):
            values[key] = value.astimezone(timezone.utc).isoformat()
        elif isinstance(value, Decimal):
            values[key] = str(value)
    for field in ("estimate_low", "estimate_high"):
        if values[field] is not None:
            values[field] = format(Decimal(str(values[field])), ".2f")
    return values


def fingerprint(lot):
    return sha256(json.dumps(snapshot(lot), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _text_key(value):
    value = unicodedata.normalize("NFKD", value or "").casefold()
    return "".join(char for char in value if char.isalnum())


def _house_key(value):
    return _text_key(oliver_house_name(value) or value)


def _lot_number(value):
    value = re.sub(r"^lot\s*", "", (value or "").strip(), flags=re.I)
    return re.sub(r"^0+(?=\d)", "", _text_key(value))


def _url_key(value):
    try:
        canonical = canonicalize_bookmark_url(value)
        parts = urlsplit(canonical)
    except ValueError:
        return ""
    if not canonical:
        return ""
    host = (parts.hostname or "").removeprefix("www.")
    # Invaluable can change the title slug while retaining the same lot token.
    if host == "invaluable.com":
        match = re.fullmatch(r"/auction-lot/[^/]+-c-([a-f0-9]+)/?", parts.path)
        if match:
            return f"invaluable:{match[1]}"
    return canonical


def _preferred(first, second):
    """The survivor is always Invaluable when either listing is Invaluable."""
    return sorted((first, second), key=lambda lot: (lot.source.casefold() != "invaluable", lot.pk))


def audit_lots(lots, *, timezone_name="America/Los_Angeles"):
    lots = list(lots)
    zone = ZoneInfo(timezone_name)
    visible = [lot for lot in lots if lot.superseded_by_id is None]
    dates, identities, numbers = defaultdict(list), defaultdict(list), defaultdict(list)
    for lot in visible:
        day = lot.event_at.astimezone(zone).date().isoformat() if lot.event_at else "undated"
        dates[day].append(lot)
        url = _url_key(lot.lot_url)
        if url:
            identities[(lot.source.casefold(), url)].append(lot)
        number = _lot_number(lot.lot_number)
        if number and day != "undated":
            numbers[(day, number)].append(lot)
    matches = {}
    for group in identities.values():
        for first, second in combinations(group, 2):
            matches[tuple(sorted((first.pk, second.pk)))] = (first, second, "same_source_lot_url", True)
    for group in numbers.values():
        for first, second in combinations(group, 2):
            key = tuple(sorted((first.pk, second.pk)))
            if key in matches:
                continue
            artist = artist_identity_key(first.artist_watchlist_name or first.artist)
            if not artist or artist != artist_identity_key(second.artist_watchlist_name or second.artist):
                continue
            house = _house_key(first.auction_house)
            same_house = bool(house) and house == _house_key(second.auction_house)
            title = _text_key(first.title)
            same_title = bool(title) and title == _text_key(second.title)
            same_estimates = (
                first.estimate_low is not None and first.estimate_high is not None
                and first.estimate_low > 0 and first.estimate_high > 0
                and bool(first.currency) and first.currency.upper() == second.currency.upper()
                and first.estimate_low == second.estimate_low and first.estimate_high == second.estimate_high
            )
            if same_house or same_title or same_estimates:
                evidence = ["same_day_lot_number_artist"]
                evidence += [label for label, present in (
                    ("same_house", same_house), ("same_title", same_title),
                    ("same_native_estimates", same_estimates),
                ) if present]
                matches[key] = (first, second, "+".join(evidence),
                                first.source.casefold() != second.source.casefold() and same_house and (same_title or same_estimates))
    # A row with multiple possible survivors needs human review of the whole set.
    neighbors = defaultdict(set)
    for first, second, _reason, _strong in matches.values():
        neighbors[first.pk].add(second.pk)
        neighbors[second.pk].add(first.pk)
    pairs = []
    for first, second, reason, strong in matches.values():
        keep, remove = _preferred(first, second)
        pairs.append({
            "keep_id": keep.pk, "remove_id": remove.pk, "reason": reason,
            "confidence": "strong" if strong and len(neighbors[remove.pk]) == 1 and len(neighbors[keep.pk]) == 1 else "review",
            "keep_fingerprint": fingerprint(keep), "remove_fingerprint": fingerprint(remove),
            "keep": snapshot(keep), "remove": snapshot(remove),
        })
    return {
        "format": "secondstate-calendar-duplicate-audit-v1",
        "timezone": timezone_name, "total_records": len(lots), "visible_records": len(visible),
        "superseded_records": len(lots) - len(visible),
        "dated_days": len([day for day in dates if day != "undated"]),
        "days": [{"day": day, "jeremy_lots": len(rows), "oliver_lots": sum(is_oliver_house(row.auction_house) for row in rows)}
                 for day, rows in sorted(dates.items())],
        "pairs": sorted(pairs, key=lambda pair: (pair["remove"]["event_at"] or "", pair["remove_id"])),
        "limitations": "Candidates are review aids, not identity proof. Missing dates, lot numbers, artist labels or divergent provider metadata require source review. Nothing is changed by an audit.",
    }


def apply_pairs(pairs):
    """Apply an explicitly reviewed plan atomically; reject stale or chained plans."""
    from django.db import transaction
    from .models import AuctionWatchLot

    remove_ids = [pair["remove_id"] for pair in pairs]
    keep_ids = [pair["keep_id"] for pair in pairs]
    if len(set(remove_ids)) != len(remove_ids) or set(remove_ids) & set(keep_ids):
        raise ValueError("A duplicate may appear only once and may not also be a survivor.")
    changes = []
    with transaction.atomic():
        rows = {lot.pk: lot for lot in AuctionWatchLot.objects.select_for_update().filter(pk__in=remove_ids + keep_ids)}
        for pair in pairs:
            old, keep = rows.get(pair["remove_id"]), rows.get(pair["keep_id"])
            if old is None or keep is None or old.pk == keep.pk:
                raise ValueError("A reviewed lot no longer exists or refers to itself.")
            if old.superseded_by_id is not None or keep.superseded_by_id is not None:
                raise ValueError("A reviewed lot has already been superseded.")
            if old.source.casefold() == "invaluable" and keep.source.casefold() != "invaluable":
                raise ValueError("An Invaluable listing must be kept in preference to another provider.")
            if not pair.get("reason", "").strip():
                raise ValueError("Every reviewed pair requires its supporting reason.")
            if fingerprint(old) != pair.get("remove_fingerprint") or fingerprint(keep) != pair.get("keep_fingerprint"):
                raise ValueError(f"Lot {old.pk} or {keep.pk} changed since review; audit again.")
            if AuctionWatchLot.objects.filter(superseded_by_id=old.pk).exists():
                raise ValueError(f"Lot {old.pk} already has retained duplicates; resolve its children explicitly.")
            changes.append({"remove_id": old.pk, "keep_id": keep.pk, "active_before": old.active,
                            "reason": pair["reason"], "before": snapshot(old)})
        for change in changes:
            AuctionWatchLot.objects.filter(pk=change["remove_id"]).update(superseded_by_id=change["keep_id"], active=False)
    return {"format": "secondstate-calendar-duplicate-receipt-v1", "changes": changes}


def rollback_receipt(receipt):
    """Restore only suppression flags, leaving later source updates/saved work intact."""
    from django.db import transaction
    from .models import AuctionWatchLot

    if receipt.get("format") != "secondstate-calendar-duplicate-receipt-v1":
        raise ValueError("Not a Calendar duplicate receipt.")
    changes = receipt["changes"]
    with transaction.atomic():
        rows = {lot.pk: lot for lot in AuctionWatchLot.objects.select_for_update().filter(pk__in=[row["remove_id"] for row in changes])}
        for change in changes:
            old = rows.get(change["remove_id"])
            if old is None or old.superseded_by_id != change["keep_id"] or old.active:
                raise ValueError("A suppression link changed; rollback requires another review.")
            # A newer sale result must not be reactivated by an old receipt.
            active = change["active_before"] and old.sold_price is None and old.source_status != "ended"
            AuctionWatchLot.objects.filter(pk=old.pk).update(superseded_by_id=None, active=active)
    return len(changes)
