"""Bounded staff transcription of LiveArt web evidence; never calls an API."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.parse import urlsplit

from .liveart_artist import liveart_artist_names_match
from .liveart_resale import MAX_MONEY, _comparison, _key, manual_review_eligible, normalize_candidate, same_liveart_sale
from .liveart_search import PRINTS_AND_MULTIPLES_CATEGORY_ID


MAX_MANUAL_SALES = 50
MANUAL_CATEGORIES = {
    "prints_and_multiples": "Prints & Multiples",
    "works_on_paper": "Drawings / Works on paper",
}
ENTRY_FIELDS = {
    "artist", "title", "sale_date", "auction_house", "lot_number", "hammer_usd",
    "provider_url", "evidence_note", "original_hammer", "original_currency", "lot_url",
    "medium", "edition", "size", "signature", "condition", "price_basis", "currency",
    "category", "status",
    "source_kind", "price_mode", "fx_rate", "fx_direction", "fx_date", "fx_source_url",
}


def is_manual_web(candidate: object) -> bool:
    return isinstance(candidate, dict) and candidate.get("provider") in {"LiveArt", "Auction archive"} and candidate.get("entry_method") == "manual_web"


def _text(entry: dict, field: str, *, required: bool = False, limit: int = 300) -> str:
    value = entry.get(field, "")
    if not isinstance(value, str):
        raise ValueError(f"{field.replace('_', ' ').title()} must be text.")
    value = value.strip()
    if (required and not value) or len(value) > limit or any(ord(char) < 32 and char not in "\n\r\t" for char in value):
        raise ValueError(f"Enter a valid {field.replace('_', ' ')} (up to {limit} characters).")
    return value


def _money(value: object, field: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError(f"{field} must be a positive amount with at most two decimals.")
    # Accept the common web display format, without guessing decimal separators.
    text = str(value).strip()
    if re.fullmatch(r"(?:USD\s*|\$\s*)?(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]{1,2})?", text, re.IGNORECASE):
        text = re.sub(r"^(?:USD\s*|\$\s*)", "", text, flags=re.IGNORECASE).replace(",", "")
    else:
        raise ValueError(f"{field} must be a positive amount with at most two decimals.")
    try:
        amount = Decimal(text)
    except InvalidOperation:
        raise ValueError(f"Enter a valid {field.lower()}.") from None
    if not amount.is_finite() or not 0 < amount <= MAX_MONEY:
        raise ValueError(f"{field} is outside the supported range.")
    return f"{amount:.2f}"


def _source_url(value: str, *, liveart: bool) -> str:
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower()
        valid = (
            len(value) <= 2000 and parsed.scheme == "https" and bool(host)
            and bool(parsed.path.strip("/")) and not parsed.username and not parsed.password
            and parsed.port in (None, 443) and not any(char.isspace() for char in value)
            and "\\" not in value
        )
        if liveart:
            valid = valid and (host == "liveart.ai" or host.endswith(".liveart.ai")) and host != "api.liveart.ai"
        if not valid:
            raise ValueError
    except ValueError:
        label = "LiveArt website record" if liveart else "original auction lot"
        raise ValueError(f"Enter a complete HTTPS {label} link.") from None
    return value


def normalize_manual_entry(entry: object, *, confirmed: object, calendar_lot, user_id: int) -> dict:
    if not isinstance(entry, dict) or set(entry) - ENTRY_FIELDS:
        raise ValueError("Manual sale must contain only the supported evidence fields.")
    if confirmed is not True:
        raise ValueError("Confirm that you checked the source, artwork category and sold USD hammer.")
    category = _text(entry, "category", required=True)
    if category not in MANUAL_CATEGORIES:
        raise ValueError("Choose Prints & Multiples or Drawings / Works on paper, as verified on the source.")
    source_kind = entry.get("source_kind", "liveart_web")
    price_mode = entry.get("price_mode", "source_usd")
    if not isinstance(source_kind, str) or not isinstance(price_mode, str) or source_kind not in {"liveart_web", "auction_archive"} or price_mode not in {"source_usd", "historical_fx"}:
        raise ValueError("Choose a supported evidence source and USD price basis.")
    archive = source_kind == "auction_archive"
    if price_mode == "historical_fx" and not archive:
        raise ValueError("Historical currency conversion belongs to an auction archive source.")
    required_facts = {"price_basis": "hammer", "currency": "USD", "status": "sold"}
    if any(entry.get(field) != expected for field, expected in required_facts.items()):
        raise ValueError("Only completed sales with a documented hammer can be entered.")
    fields = {field: _text(entry, field, required=True, limit=limit) for field, limit in (
        ("artist", 300), ("title", 500), ("sale_date", 10), ("auction_house", 300),
        ("lot_number", 80), ("provider_url", 2000), ("evidence_note", 4000),
    )}
    expected_artist = calendar_lot.artist or calendar_lot.artist_watchlist_name
    if not liveart_artist_names_match(fields["artist"], expected_artist):
        raise ValueError("The comparable artist must match this Calendar lot.")
    try:
        sale_date = date.fromisoformat(fields["sale_date"])
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", fields["sale_date"]) or sale_date > datetime.now(timezone.utc).date():
            raise ValueError
    except ValueError:
        raise ValueError("Enter a completed sale date as YYYY-MM-DD; future sales are not eligible.") from None
    fields["provider_url"] = _source_url(fields["provider_url"], liveart=not archive)
    if price_mode == "source_usd":
        fields["hammer_usd"] = _money(entry.get("hammer_usd"), "USD hammer")
    fields.update({field: _text(entry, field, limit=1000 if field == "condition" else 500 if field in {"medium", "signature"} else 300) for field in (
        "medium", "edition", "size", "signature", "condition",
    )})
    lot_url = _text(entry, "lot_url", limit=2000)
    fields["lot_url"] = _source_url(lot_url, liveart=False) if lot_url else None
    original_currency = _text(entry, "original_currency", limit=3).upper()
    original_value = entry.get("original_hammer", "")
    if bool(original_currency) != (original_value not in (None, "")):
        raise ValueError("Supply the original hammer and its currency together, or leave both blank.")
    if original_currency and not re.fullmatch(r"[A-Z]{3}", original_currency):
        raise ValueError("Original currency must be a three-letter currency code.")
    if original_currency and original_currency != "USD" and isinstance(original_value, str) and re.match(r"^(?:USD|\$)", original_value.strip(), re.IGNORECASE):
        raise ValueError("Enter the original hammer as a number in its stated currency, without a USD prefix.")
    original_hammer = _money(original_value, "Original hammer") if original_currency else None
    conversion = None
    if price_mode == "historical_fx":
        if not original_hammer or original_currency == "USD":
            raise ValueError("A historical conversion requires the original non-USD hammer and currency.")
        rate_text = _text(entry, "fx_rate", required=True, limit=30)
        if not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,12})?", rate_text):
            raise ValueError("Enter a positive historical exchange rate with up to 12 decimal places.")
        rate = Decimal(rate_text)
        direction = entry.get("fx_direction")
        if not rate.is_finite() or not 0 < rate <= MAX_MONEY or not isinstance(direction, str) or direction not in {"usd_per_original", "original_per_usd"}:
            raise ValueError("Choose a valid exchange-rate direction and positive rate.")
        rate_date_text = _text(entry, "fx_date", required=True, limit=10)
        try:
            rate_date = date.fromisoformat(rate_date_text)
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", rate_date_text) or not 0 <= (sale_date - rate_date).days <= 7:
                raise ValueError
        except ValueError:
            raise ValueError("Use the sale-date exchange rate or a published rate from the preceding seven days.") from None
        rate_source = _source_url(_text(entry, "fx_source_url", required=True, limit=2000), liveart=False)
        converted = Decimal(original_hammer) * rate if direction == "usd_per_original" else Decimal(original_hammer) / rate
        if not converted.is_finite() or not 0 < converted <= MAX_MONEY:
            raise ValueError("Converted USD hammer is outside the supported range.")
        fields["hammer_usd"] = f"{converted.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}"
        if entry.get("hammer_usd") not in (None, "") and _money(entry["hammer_usd"], "USD hammer") != fields["hammer_usd"]:
            raise ValueError("The entered USD hammer does not agree with the sourced historical conversion.")
        operator = "*" if direction == "usd_per_original" else "/"
        conversion = {"rate": str(rate), "direction": direction, "rate_date": rate_date_text, "source_url": rate_source,
                      "original_hammer": original_hammer, "original_currency": original_currency, "sale_date": fields["sale_date"],
                      "calculation": f"{original_hammer} {original_currency} {operator} {rate} = {fields['hammer_usd']} USD (rounded half up)",
                      "hammer_usd": fields["hammer_usd"]}
    elif any(entry.get(field) not in (None, "") for field in ("fx_rate", "fx_date", "fx_source_url")):
        raise ValueError("Choose historical conversion to supply exchange-rate evidence.")
    if original_currency == "USD" and original_hammer != fields["hammer_usd"]:
        raise ValueError("An original USD hammer must agree with the entered USD hammer.")
    identity = [_key(fields[key]) for key in ("artist", "auction_house", "sale_date", "lot_number")]
    identifier = ("archive-web:" if archive else "liveart-web:") + hashlib.sha256(json.dumps(identity).encode()).hexdigest()[:24]
    now = datetime.now(timezone.utc).isoformat()
    candidate = normalize_candidate({
        "id": identifier, "status": "sold", "lot_num": fields["lot_number"],
        "auction_house_name": fields["auction_house"], "sale_datetime": fields["sale_date"],
        "lot_url": fields["lot_url"], "_retrieved_at": now,
        "price": {"hammer_usd": fields["hammer_usd"], "hammer": original_hammer, "currency": original_currency or None},
        "artwork": {"artist": fields["artist"], "name": fields["title"], "materials": fields["medium"],
                    "category_id": PRINTS_AND_MULTIPLES_CATEGORY_ID if category == "prints_and_multiples" else None},
    }, None, calendar_lot)
    candidate.update({
        **fields, "provider_id": None, "entry_method": "manual_web", "match_type": "liveart_web",
        "provider": "Auction archive" if archive else "LiveArt", "source_kind": source_kind,
        "price_mode": price_mode, "fx_conversion": conversion,
        "price_basis": "hammer", "hammer_currency": "USD", "category": category,
        "category_label": MANUAL_CATEGORIES[category],
        "original_hammer": original_hammer, "hammer_original": original_hammer,
        "original_currency": original_currency or None, "currency": original_currency or None,
        "entered_by": user_id, "entered_at": now, "source_confirmed": True,
        "credible": False, "selected": False,
        "match_notes": ["Manually transcribed from an auction archive; review the documented hammer and artwork details before selecting." if archive else "Manually transcribed from LiveArt's website; review the source and artwork details before selecting.", *candidate.get("match_notes", [])],
        "exclusion_reasons": [],
    })
    if archive:
        candidate["match_type"] = "auction_archive"
    for field in ("edition", "size", "signature", "condition"):
        candidate["differences"][field] = _comparison(candidate["differences"][field]["subject"], fields[field] or None)
    candidate["missing_data"] = [field for field in candidate["missing_data"] if field not in {"provider_id", "provider_url"} and not candidate.get(field)]
    candidate["manual_selectable"] = manual_review_eligible(candidate, calendar_lot)
    if not candidate["manual_selectable"]:
        raise ValueError("This manual sale does not meet the verified sold-evidence requirements.")
    return candidate


def find_existing_sale(candidates: list[dict], candidate: dict) -> dict | None:
    """Recognize a repeated transcription without overwriting prior evidence."""
    for existing in candidates:
        if existing.get("provider") not in {"LiveArt", "Auction archive"}:
            continue
        if str(existing.get("id")) != candidate["id"] and not same_liveart_sale(existing, candidate):
            continue
        existing_category = existing.get("category") if is_manual_web(existing) else (
            "prints_and_multiples" if str(existing.get("category_id")) == str(PRINTS_AND_MULTIPLES_CATEGORY_ID) else None
        )
        if existing_category != candidate["category"]:
            raise ValueError("This sale already exists with a different artwork category. Review the saved source before adding it again.")
        raw_hammer = existing.get("hammer_usd")
        if raw_hammer is None:
            continue
        try:
            old_hammer = Decimal(str(raw_hammer))
        except InvalidOperation:
            continue
        if old_hammer != Decimal(candidate["hammer_usd"]):
            raise ValueError("This sale already exists with a different USD hammer. Review the saved source before adding it again.")
        return existing
    return None


def retained_manual_candidates(*candidate_groups: object) -> list[dict]:
    retained = {}
    for candidates in candidate_groups:
        if isinstance(candidates, list):
            for candidate in candidates:
                if is_manual_web(candidate):
                    retained[str(candidate.get("id"))] = candidate
    return list(retained.values())
