"""Pure matching, comparable review, and bid scenarios for LiveArt lots.

The transport layer supplies bounded, authenticated API results.  This module
never fetches data, and never treats premiums or LiveArt Estimate values as
realized comparable-sale hammers.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from statistics import median
from typing import Any, Mapping
from urllib.parse import urlsplit

from catalogapp.artprice_artist_links import artist_identity_key

from .artprice_max_bid import ArtpriceAnalysisError, calculate_bid_rows
from .liveart_client import verify_sold_hammer_usd


MONEY = Decimal("0.01")
MAX_MONEY = Decimal("1000000000000")
DEFAULT_ASSUMPTIONS = {
    "inbound_shipping": "200.00",
    "other_buying_costs": "0.00",
    "target_profit": "100.00",
    "seller_commission_pct": "0.00",
    "outbound_shipping": "0.00",
    "other_resale_costs": "0.00",
    "premium_min": 23,
    "premium_max": 35,
    # Explicit sensitivity factors.  They add a downside/upside even when the
    # selected sample has only one sale, and are estimates, not forecasts.
    "downside_factor": "0.80",
    "upside_factor": "1.10",
}


def _value(obj: Any, key: str, default: Any = None) -> Any:
    return obj.get(key, default) if isinstance(obj, Mapping) else getattr(obj, key, default)


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _safe_url(value: Any) -> str | None:
    candidate = _text(value)
    if not candidate or len(candidate) > 2000:
        return None
    try:
        parsed = urlsplit(candidate)
        if parsed.scheme.lower() in {"http", "https"} and parsed.hostname and not parsed.username and not parsed.password:
            return candidate
    except ValueError:
        pass
    return None


def _key(value: Any) -> str:
    value = unicodedata.normalize("NFKD", _text(value))
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = value.casefold().replace("&", " and ")
    return " ".join(re.sub(r"[^\w]+", " ", value).split())


def artwork_search_title(title: Any, artist: Any) -> str:
    """Drop a matching artist heading from a Calendar artwork title."""

    title_text = _text(title)
    for separator in (", ", ": ", " - ", " – ", " — "):
        if separator not in title_text:
            continue
        heading, work = title_text.split(separator, 1)
        if work.strip() and artist_identity_key(heading) == artist_identity_key(_text(artist)):
            return work.strip()
    return title_text


def _title_forms(value: Any) -> set[str]:
    """Keep complete titles and distinctive bilingual parenthetical forms."""

    title = _text(value)
    forms = {_key(title)}
    if title.endswith(")") and "(" in title:
        base, translation = title.rsplit("(", 1)
        translation = translation[:-1]
        for part in (base, translation):
            key = _key(part)
            if len(key.split()) >= 3:
                forms.add(key)
    return forms - {""}


def _title_identity(expected: Any, candidate: Any) -> bool:
    common = _title_forms(expected) & _title_forms(candidate)
    return any(key not in {"untitled", "composition", "abstract", "study"} for key in common)


def _sale(raw: Mapping[str, Any]) -> Mapping[str, Any]:
    sale = raw.get("sale")
    return sale if isinstance(sale, Mapping) else {}


def _artwork(raw: Mapping[str, Any]) -> Mapping[str, Any]:
    artwork = raw.get("artwork")
    return artwork if isinstance(artwork, Mapping) else {}


def _description(artwork: Mapping[str, Any]) -> Mapping[str, Any]:
    description = artwork.get("description")
    return description if isinstance(description, Mapping) else artwork


def _artist_id(artwork: Mapping[str, Any]) -> Any:
    description = _description(artwork)
    artist = description.get("artist") or artwork.get("artist")
    nested_id = artist.get("id") if isinstance(artist, Mapping) else None
    return artwork.get("artist_id") or description.get("artist_id") or nested_id


def _artist_name(artwork: Mapping[str, Any]) -> str:
    description = _description(artwork)
    for artist in (description.get("artist"), artwork.get("artist")):
        if isinstance(artist, Mapping) and artist.get("name"):
            return _text(artist["name"])
        if isinstance(artist, str) and artist.strip():
            return artist.strip()
    return ""


def _category_id(artwork: Mapping[str, Any]) -> Any:
    description = _description(artwork)
    category = description.get("category") or artwork.get("category")
    nested_id = category.get("id") if isinstance(category, Mapping) else None
    return description.get("category_id") or artwork.get("category_id") or nested_id


def _medium(artwork: Mapping[str, Any]) -> str | None:
    description = _description(artwork)
    return _text(description.get("materials") or artwork.get("materials")) or None


def _markings(artwork: Mapping[str, Any]) -> str:
    description = _description(artwork)
    return _text(description.get("markings") or artwork.get("markings"))


def _artwork_edition(artwork: Mapping[str, Any], notes: str = "") -> str | None:
    description = _description(artwork)
    current = _text(description.get("edition_current"))
    size = _text(description.get("edition_size"))
    if current.isdecimal() and size.isdecimal():
        return f"{int(current)}/{int(size)}"
    if size.isdecimal():
        return f"edition of {int(size)}"
    return _edition(" ".join((_markings(artwork), notes)))


def _artist(raw: Mapping[str, Any]) -> str:
    return _artist_name(_artwork(raw))


def _raw_date(raw: Mapping[str, Any]) -> str:
    source = _sale(raw).get("start_datetime") or raw.get("sale_datetime")
    if not source:
        return ""
    if isinstance(source, (datetime, date)):
        return source.date().isoformat() if isinstance(source, datetime) else source.isoformat()
    match = re.match(r"\d{4}-\d{2}-\d{2}", _text(source))
    return match.group() if match else ""


def _subject_fields(raw: Mapping[str, Any]) -> dict[str, Any]:
    artwork = _artwork(raw)
    sale = _sale(raw)
    lot_id = raw.get("id")
    markings = _markings(artwork)
    notes = _text(raw.get("catalog_notes"))
    evidence = " ".join((markings, notes))
    return {
        "id": _text(lot_id),
        "lot_id": lot_id,
        "sale_id": raw.get("sale_id") or sale.get("id"),
        "artwork_id": raw.get("artwork_id") or artwork.get("id"),
        "artist_id": _artist_id(artwork),
        "category_id": _category_id(artwork),
        "house": _text(raw.get("auction_house_name")),
        "date": _raw_date(raw),
        "lot": _text(raw.get("lot_num")),
        "artist": _artist(raw),
        "title": _text(_description(artwork).get("name") or artwork.get("name")),
        "lot_url": _safe_url(raw.get("lot_url")),
        "medium": _medium(artwork),
        "edition": _artwork_edition(artwork, notes),
        "signature": _signature(evidence),
        "size": _size(_description(artwork)),
        "condition": _condition(notes),
        "markings": markings or None,
        "catalog_notes": notes or None,
    }


def artwork_matches(
    lot: Any, raw_artworks: list[Mapping[str, Any]], *, artist_id: Any, artist_name: str,
    title_aliases: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    """Rank artwork identities by artist and title, independent of the auction."""

    expected_artist = _text(artist_name or _value(lot, "artist") or _value(lot, "artist_watchlist_name"))
    expected_title = artwork_search_title(_value(lot, "title"), expected_artist)
    options: list[dict[str, Any]] = []
    for raw in raw_artworks:
        if not isinstance(raw, Mapping):
            continue
        artwork_id = _text(raw.get("id"))
        if not artwork_id:
            continue
        description = _description(raw)
        markings = _markings(raw)
        candidate_artist_id = _artist_id(raw)
        candidate_artist = _artist_name(raw)
        candidate_title = _text(description.get("name") or raw.get("name"))
        artist_name_matches = bool(
            expected_artist and candidate_artist
            and artist_identity_key(expected_artist) == artist_identity_key(candidate_artist)
        )
        artist_matches = bool(
            artist_id is not None and candidate_artist_id is not None
            and _text(artist_id) == _text(candidate_artist_id)
        ) if artist_id is not None else artist_name_matches
        title_matches = _title_identity(expected_title, candidate_title)
        variant_matches = any(_title_identity(title, candidate_title) for title in title_aliases)
        matched_title = expected_title if title_matches else next(
            (title for title in title_aliases if _title_identity(title, candidate_title)), None
        )
        matches = {
            "artist": artist_matches,
            "title": title_matches,
        }
        missing = [name for name, value in (("artist", candidate_artist), ("title", candidate_title), ("medium", _medium(raw)), ("edition", _artwork_edition(raw)), ("signature", _signature(markings)), ("size", _size(description))) if not value]
        if not candidate_artist_id:
            missing.append("artist_id")
        score = sum(matches.values()) + int(variant_matches and not title_matches)
        notes = []
        if artist_id is not None and candidate_artist_id is not None and not artist_matches:
            notes.append("Artist ID differs")
        elif not artist_name_matches:
            notes.append("Artist name differs or is missing")
        if not title_matches:
            notes.append("Artwork title differs from the Calendar title; verify this work before using its history")
        if variant_matches and not title_matches:
            notes.append("The supplied title variant matched; choose this artwork only if it is the same work")
        option = {
            "id": artwork_id,
            "artwork_id": artwork_id,
            "artist_id": candidate_artist_id,
            "category_id": _category_id(raw),
            "artist": candidate_artist,
            "title": candidate_title,
            "matched_title": matched_title,
            "title_variant_matches": variant_matches,
            "medium": _medium(raw),
            "edition": _artwork_edition(raw),
            "signature": _signature(markings),
            "size": _size(description),
            "condition": None,
            "markings": markings or None,
            "matches": matches,
            "score": score,
            "verified": artist_matches and title_matches,
            "can_choose": artist_matches and (title_matches or variant_matches),
            "missing_data": missing,
            "match_notes": notes,
            "provider_url": f"https://api.liveart.ai/v1/artworks?id={artwork_id}&limit=1" if artwork_id.isdecimal() else None,
        }
        options.append(option)
    return sorted(options, key=lambda item: (-int(item["verified"]), -item["score"], item["id"]))


def subject_matches(lot: Any, raw_artworks: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Compatibility wrapper for artwork identity matching."""

    return artwork_matches(lot, raw_artworks, artist_id=None, artist_name="")


_EDITION_RE = re.compile(r"\b(?:edition\s+(?:of\s+)?|numbered\s+)?(\d{1,4})\s*/\s*(\d{1,4})\b", re.I)
_EDITION_SIZE_RE = re.compile(r"\b(?:edition\s+of|edition\s*:)\s*(\d{1,4})\b", re.I)
_CONDITION_RE = re.compile(r"\bcondition\s*[:\-]\s*([^.;\n]{3,100})", re.I)


def _edition(text: Any) -> str | None:
    match = _EDITION_RE.search(_text(text))
    if match:
        return f"{match.group(1)}/{match.group(2)}"
    match = _EDITION_SIZE_RE.search(_text(text))
    return f"edition of {match.group(1)}" if match else None


def _signature(text: Any) -> str | None:
    note = _key(text)
    if re.search(r"\bunsigned\b|\bnot signed\b", note):
        return "unsigned"
    if re.search(r"\bfacsimile signature\b|\bfacsimile signed\b", note):
        return "facsimile signature"
    if re.search(r"\bplate signed\b|\bsigned in the plate\b|\bin the plate\b|\bprinted signature\b", note):
        return "plate signed"
    if re.search(r"\bstamp(?:ed)? signature\b|\bstamp(?:ed)? signed\b|\bsignature stamp\b", note):
        return "stamped signature"
    if re.search(r"\bpencil signed\b|\bsigned in pencil\b|\bsigned and numbered in pencil\b", note):
        return "pencil signed"
    if re.search(r"\bink signed\b|\bsigned in ink\b", note):
        return "ink signed"
    if re.search(r"\bhand signed\b|\bsigned by the artist\b", note):
        return "hand signed"
    if re.search(r"\bsigned\b", note):
        return "signed (method unspecified)"
    if re.search(r"\bsignature\b", note):
        return "signature mentioned; verify"
    return None


def _condition(text: Any) -> str | None:
    match = _CONDITION_RE.search(_text(text))
    return match.group(1).strip() if match else None


def _size(artwork: Mapping[str, Any]) -> str | None:
    parts = []
    for dimension in ("height", "width", "depth"):
        raw = artwork.get(f"measurements_{dimension}_cm")
        if raw is None or isinstance(raw, bool):
            continue
        try:
            value = Decimal(str(raw))
        except (InvalidOperation, ValueError):
            continue
        if value.is_finite() and value > 0:
            parts.append(format(value.normalize(), "f"))
    return " × ".join(parts) + " cm" if len(parts) >= 2 else None


def _comparison(subject: str | None, comp: str | None) -> dict[str, str | None]:
    if not subject or not comp:
        status = "missing"
    else:
        status = "same" if _key(subject) == _key(comp) else "different"
    return {"subject": subject, "comp": comp, "status": status}


_MEDIUM_TERMS = (
    "screenprint", "serigraph", "lithograph", "etching", "aquatint",
    "woodcut", "linocut", "giclee", "pigment print", "digital print",
    "photograph", "oil", "acrylic", "watercolor", "gouache", "bronze",
)


_SPECIFIC_MEDIUM_ALIASES = (
    ("screenprint", "screenprint"), ("screen print", "screenprint"),
    ("silkscreen", "screenprint"), ("serigraph", "screenprint"),
    ("lithograph", "lithograph"), ("lithography", "lithograph"),
    ("etching", "etching"), ("aquatint", "aquatint"),
    ("woodcut", "woodcut"), ("linocut", "linocut"),
    ("giclee", "giclee"), ("pigment print", "pigment print"),
    ("digital print", "digital print"), ("photograph", "photograph"),
    ("oil", "oil"), ("acrylic", "acrylic"),
    ("watercolor", "watercolor"), ("gouache", "gouache"),
    ("bronze", "bronze"),
)


def _specific_medium(value: Any) -> str | None:
    key = _key(value)
    for phrase, canonical in _SPECIFIC_MEDIUM_ALIASES:
        if re.search(rf"\b{re.escape(phrase)}\b", key):
            return canonical
    return None


def _medium_comparison(subject: str | None, comp: str | None) -> dict[str, str | None]:
    comparison = _comparison(subject, comp)
    if not subject or not comp:
        return comparison
    subject_specific, comp_specific = _specific_medium(subject), _specific_medium(comp)
    if subject_specific and subject_specific == comp_specific:
        comparison["status"] = "same"
        return comparison
    subject_key, comp_key = _key(subject), _key(comp)
    subject_terms = {term for term in _MEDIUM_TERMS if term in subject_key}
    comp_terms = {term for term in _MEDIUM_TERMS if term in comp_key}
    if subject_terms and comp_terms and subject_terms & comp_terms:
        comparison["status"] = "same"
    return comparison


def _edition_size(edition: str | None) -> int | None:
    if not edition:
        return None
    match = re.search(r"/(\d+)$|edition of (\d+)$", edition)
    return int(match.group(1) or match.group(2)) if match else None


def _size_from_text(text: Any) -> str | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)(?:\s*[x×]\s*(\d+(?:\.\d+)?))?\s*cm\b", _text(text), re.I)
    if not match:
        return None
    return " × ".join(part for part in match.groups() if part) + " cm"


def normalize_candidate(raw: Mapping[str, Any], subject: Mapping[str, Any] | None, calendar_lot: Any) -> dict[str, Any]:
    """Build one reviewable comp, retaining missing data and mismatches."""

    reference = subject if isinstance(subject, Mapping) else {}
    if isinstance(reference.get("artwork"), Mapping):
        reference = _subject_fields(reference)
    artwork = _artwork(raw)
    description = _description(artwork)
    price = raw.get("price") if isinstance(raw.get("price"), Mapping) else {}
    markings = _markings(artwork)
    notes = _text(raw.get("catalog_notes"))
    evidence = " ".join((markings, notes))
    medium = _medium(artwork)
    edition = _artwork_edition(artwork, notes)
    signature = _signature(evidence)
    size = _size(description)
    condition = _condition(notes)
    calendar_medium = _text(_value(calendar_lot, "medium")) or None
    subject_medium = _text(reference.get("medium")) or calendar_medium
    subject_edition = _text(reference.get("edition")) or _edition(calendar_medium)
    subject_signature = _text(reference.get("signature")) or _signature(calendar_medium)
    subject_size = _text(reference.get("size")) or _size_from_text(calendar_medium)
    subject_condition = _text(reference.get("condition")) or _condition(calendar_medium)
    differences = {
        "medium": _medium_comparison(subject_medium, medium),
        "edition": _comparison(subject_edition, edition),
        "signature": _comparison(subject_signature, signature),
        "size": _comparison(subject_size, size),
        "condition": _comparison(subject_condition, condition),
    }
    hammer = verify_sold_hammer_usd(raw)
    candidate_artist = _artist(raw)
    candidate_artist_id = _artist_id(artwork)
    expected_artist = _text(reference.get("artist") or _value(calendar_lot, "artist") or _value(calendar_lot, "artist_watchlist_name"))
    if candidate_artist and expected_artist:
        artist_matches = artist_identity_key(candidate_artist) == artist_identity_key(expected_artist)
    else:
        artist_matches = bool(
            reference.get("artist_id") and candidate_artist_id
            and _text(reference["artist_id"]) == _text(candidate_artist_id)
        )
    candidate_title = _text(description.get("name") or artwork.get("name"))
    expected_title = _text(reference.get("title") or _value(calendar_lot, "title"))
    candidate_artwork_id = raw.get("artwork_id") or artwork.get("id")
    same_artwork = bool(
        reference.get("artwork_id") and candidate_artwork_id
        and _text(reference["artwork_id"]) == _text(candidate_artwork_id)
    )
    title_matches = _title_identity(expected_title, candidate_title)
    exact_work = artist_matches and (same_artwork or title_matches)
    match_type = "exact_work" if exact_work else "related_work"
    candidate_category_id = _category_id(artwork)
    reference_category_id = reference.get("category_id")
    same_category = bool(
        reference_category_id and candidate_category_id
        and _text(reference_category_id) == _text(candidate_category_id)
    )
    subject_specific_medium = _specific_medium(subject_medium)
    candidate_specific_medium = _specific_medium(medium)
    same_specific_medium = bool(
        subject_specific_medium and candidate_specific_medium
        and subject_specific_medium == candidate_specific_medium
    )
    related_compatible = same_category or same_specific_medium
    medium_differs = differences["medium"]["status"] == "different"
    edition_differs = differences["edition"]["status"] == "different"
    edition_incompatible = edition_differs and _edition_size(subject_edition) != _edition_size(edition)
    signature_differs = differences["signature"]["status"] == "different"
    size_differs = differences["size"]["status"] == "different"
    condition_differs = differences["condition"]["status"] == "different"
    sale_date = _raw_date(raw)
    try:
        date_is_past_or_today = bool(sale_date and date.fromisoformat(sale_date) <= datetime.now(timezone.utc).date())
    except ValueError:
        date_is_past_or_today = False
    credible = bool(
        hammer is not None and artist_matches and (exact_work or related_compatible)
        and (not sale_date or date_is_past_or_today)
    )
    selected = bool(
        credible and exact_work and same_specific_medium and date_is_past_or_today
        and not any((medium_differs, edition_incompatible, signature_differs, size_differs, condition_differs))
    )
    reasons = []
    if hammer is None:
        reasons.append("No verified sold USD hammer price")
    if not artist_matches:
        reasons.append("Artist does not match")
    if not title_matches:
        reasons.append("Title differs")
    if not exact_work and not related_compatible:
        reasons.append("Related work has no matching category or specific medium")
    if exact_work and not same_specific_medium:
        reasons.append("Specific medium differs or is not reported; review before using")
    if medium_differs:
        reasons.append("Medium differs")
    if edition_differs:
        reasons.append("Edition impression differs" if not edition_incompatible else "Edition size differs")
    if signature_differs:
        reasons.append("Signature type differs")
    if size_differs:
        reasons.append("Size differs")
    if condition_differs:
        reasons.append("Condition differs")
    if sale_date and not date_is_past_or_today:
        reasons.append("Sale date is invalid or in the future")
    missing = [name for name, value in (("artist", candidate_artist), ("title", candidate_title), ("auction_house", raw.get("auction_house_name")), ("lot_number", raw.get("lot_num")), ("medium", medium), ("edition", edition), ("signature", signature), ("size", size), ("condition", condition), ("original_hammer", price.get("hammer")), ("original_currency", price.get("currency")), ("sale_date", sale_date)) if value is None or value == ""]
    if hammer is None:
        missing.append("hammer_usd")
    raw_hammer = price.get("hammer")
    original_hammer = _text(raw_hammer) if raw_hammer is not None else None
    candidate_id = _text(raw.get("id"))
    if not candidate_id.isdecimal():
        missing.extend(("provider_id", "provider_url"))
    return {
        "id": candidate_id,
        "provider": "LiveArt",
        "provider_id": candidate_id,
        # The documented exact-ID filter gives a stable provider record URL.
        # It exposes only the public response in a browser; never a key.
        "provider_url": f"https://api.liveart.ai/v1/lots?id={candidate_id}&limit=1" if candidate_id.isdecimal() else None,
        "lot_url": _safe_url(raw.get("lot_url")),
        "sale_id": raw.get("sale_id") or _sale(raw).get("id"),
        "artwork_id": candidate_artwork_id,
        "artist_id": candidate_artist_id,
        "category_id": candidate_category_id,
        "match_type": match_type,
        "auction_house": _text(raw.get("auction_house_name")),
        "sale_date": sale_date,
        "lot_number": _text(raw.get("lot_num")),
        "artist": candidate_artist,
        "title": candidate_title,
        "status": _text(raw.get("status")),
        "hammer_usd": f"{hammer:.2f}" if hammer is not None else None,
        "original_hammer": original_hammer,
        "hammer_original": original_hammer,
        "original_currency": _text(price.get("currency")) or None,
        "currency": _text(price.get("currency")) or None,
        "medium": medium,
        "edition": edition,
        "signature": signature,
        "size": size,
        "condition": condition,
        "markings": markings or None,
        "catalog_notes": notes or None,
        "differences": differences,
        "missing_data": missing,
        "credible": credible,
        "selected": selected,
        "exclusion_reasons": reasons,
        "match_notes": reasons,
        "retrieved_at": raw.get("_retrieved_at"),
    }


def _money(value: Any, name: str) -> Decimal:
    if isinstance(value, bool):
        raise ArtpriceAnalysisError(f"{name} must be a number.")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ArtpriceAnalysisError(f"{name} must be a number.") from None
    if not amount.is_finite() or amount < 0 or amount > MAX_MONEY or amount.as_tuple().exponent < -2:
        raise ArtpriceAnalysisError(f"{name} must be a nonnegative amount with at most two decimals.")
    return amount


def _factor(value: Any, name: str, minimum: Decimal, maximum: Decimal) -> Decimal:
    try:
        factor = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ArtpriceAnalysisError(f"{name} must be a valid factor.") from None
    if not factor.is_finite() or not minimum <= factor <= maximum:
        raise ArtpriceAnalysisError(f"{name} is outside the supported range.")
    return factor


def _display_money(value: Decimal) -> str:
    return f"{value.quantize(MONEY, rounding=ROUND_HALF_UP):.2f}"


def _rows(resale: Decimal, assumptions: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    common = {
        "expected_resale_hammer": resale,
        "premium_min": assumptions["premium_min"],
        "premium_max": assumptions["premium_max"],
        # Artprice's calculator has one fixed acquisition-cost slot.  Combine
        # shipping with tax, insurance, and other user-entered buying costs.
        "inbound_shipping": Decimal(assumptions["inbound_shipping"]) + Decimal(assumptions["other_buying_costs"]),
        "seller_commission_pct": assumptions["seller_commission_pct"],
        "outbound_shipping": assumptions["outbound_shipping"],
        "other_resale_costs": assumptions["other_resale_costs"],
    }
    net = resale * (Decimal("1") - Decimal(assumptions["seller_commission_pct"]) / 100) - Decimal(assumptions["outbound_shipping"]) - Decimal(assumptions["other_resale_costs"])
    try:
        _, break_even = calculate_bid_rows(**common, target_profit=0)
    except ArtpriceAnalysisError as exc:
        if "No positive bid" not in str(exc):
            raise
        break_even = []
    try:
        _, target = calculate_bid_rows(**common, target_profit=assumptions["target_profit"])
    except ArtpriceAnalysisError as exc:
        if "No positive bid" not in str(exc):
            raise
        target = []
    by_break_even = {row["premium_pct"]: row for row in break_even}
    by_target = {row["premium_pct"]: row for row in target}
    rows = [
        {
            "premium_pct": premium,
            "break_even_max_bid": _display_money(by_break_even[premium]["max_bid"]) if premium in by_break_even else None,
            "target_profit_max_bid": _display_money(by_target[premium]["max_bid"]) if premium in by_target else None,
        }
        for premium in range(assumptions["premium_min"], assumptions["premium_max"] + 1)
    ]
    return _display_money(net), rows


def _comparable_date(value: Any) -> date | None:
    text = _text(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass
    for format_string in ("%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(text, format_string).date()
        except ValueError:
            continue
    return None


def _same_sale(artprice: Mapping[str, Any], liveart: Mapping[str, Any]) -> bool:
    """Require a matching date plus strong sale details before dropping an overlap."""

    artprice_date = _comparable_date(artprice.get("sale_date"))
    if artprice_date is None or artprice_date != _comparable_date(liveart.get("sale_date")):
        return False
    house = _key(artprice.get("auction_house"))
    if not house or house != _key(liveart.get("auction_house")):
        return False
    lot = _key(artprice.get("lot_number"))
    liveart_lot = _key(liveart.get("lot_number"))
    if lot and liveart_lot:
        return lot == liveart_lot
    title = _key(artprice.get("title"))
    if not title or title in {"untitled", "composition", "abstract"} or title != _key(liveart.get("title")):
        return False
    try:
        artprice_hammer = Decimal(str(artprice.get("hammer_usd")))
        liveart_hammer = Decimal(str(liveart.get("hammer_usd")))
    except (InvalidOperation, TypeError, ValueError):
        return False
    if not (artprice_hammer.is_finite() and liveart_hammer.is_finite()):
        return False
    return abs(artprice_hammer - liveart_hammer) <= max(artprice_hammer, liveart_hammer) * Decimal("0.02")


def build_scenarios(
    candidates: list[Mapping[str, Any]], selected_ids: list[str | int], assumptions: Mapping[str, Any] | None
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    normalized, scenarios, _summary = build_scenarios_with_sources(candidates, selected_ids, assumptions)
    return normalized, scenarios


def build_scenarios_with_sources(
    candidates: list[Mapping[str, Any]],
    selected_ids: list[str | int],
    assumptions: Mapping[str, Any] | None,
    *,
    artprice_sold_count: int | None = None,
    artprice_source_filename: str | None = None,
    artprice_sources: list[Mapping[str, Any]] | None = None,
    artprice_analysis_updated_at: str | None = None,
    allow_unestimable: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """Calculate scenario maximum hammer bids from selected verified sales.

    A selected candidate may have a visible medium/edition mismatch, but it
    still must be a sold result with a positive USD hammer and the same artist.
    """

    supplied = dict(assumptions or {})
    unknown = set(supplied) - set(DEFAULT_ASSUMPTIONS)
    if unknown:
        raise ArtpriceAnalysisError(f"Unsupported assumption: {', '.join(sorted(unknown))}.")
    merged = {**DEFAULT_ASSUMPTIONS, **supplied}
    for field in ("inbound_shipping", "other_buying_costs", "target_profit", "seller_commission_pct", "outbound_shipping", "other_resale_costs"):
        merged[field] = _display_money(_money(merged[field], field.replace("_", " ")))
    if Decimal(merged["seller_commission_pct"]) >= 100:
        raise ArtpriceAnalysisError("Seller commission must be less than 100%.")
    try:
        premium_min = int(merged["premium_min"])
        premium_max = int(merged["premium_max"])
    except (TypeError, ValueError):
        raise ArtpriceAnalysisError("Buyer premium range must be whole percentages.") from None
    if str(premium_min) != str(merged["premium_min"]) or str(premium_max) != str(merged["premium_max"]):
        raise ArtpriceAnalysisError("Buyer premium range must be whole percentages.")
    if not 0 <= premium_min <= premium_max <= 100 or premium_max - premium_min > 100:
        raise ArtpriceAnalysisError("Buyer premium range is invalid.")
    merged["premium_min"], merged["premium_max"] = premium_min, premium_max
    downside = _factor(merged["downside_factor"], "Downside factor", Decimal("0.25"), Decimal("1"))
    upside = _factor(merged["upside_factor"], "Upside factor", Decimal("1"), Decimal("2"))
    merged["downside_factor"] = str(downside)
    merged["upside_factor"] = str(upside)

    selected = {str(item) for item in selected_ids}
    values: list[Decimal] = []
    liveart_sales: list[Mapping[str, Any]] = []
    artprice_sales: list[tuple[Mapping[str, Any], Decimal]] = []
    for candidate in candidates:
        if str(candidate.get("id")) not in selected or candidate.get("status") != "sold":
            continue
        if candidate.get("credible") is not True:
            continue
        try:
            hammer = Decimal(str(candidate.get("hammer_usd")))
        except (InvalidOperation, TypeError, ValueError):
            continue
        if hammer.is_finite() and 0 < hammer <= MAX_MONEY:
            if candidate.get("provider") == "Artprice":
                artprice_sales.append((candidate, hammer))
            else:
                values.append(hammer)
                liveart_sales.append(candidate)
    artprice_included_count = 0
    artprice_duplicate_count = 0
    included_artprice_sales = []
    for candidate, hammer in artprice_sales:
        if any(_same_sale(candidate, liveart) for liveart in liveart_sales):
            artprice_duplicate_count += 1
            continue
        values.append(hammer)
        artprice_included_count += 1
        included_artprice_sales.append(candidate)
    source_details = []
    for source in artprice_sources or []:
        source_id = source["id"]
        belongs = lambda candidate: source_id in (candidate.get("source_ids") or [])
        source_details.append({
            "id": source_id,
            "filename": source["filename"],
            "ingested_count": source["sold_records_count"],
            "eligible_count": sum(
                1 for candidate in candidates if candidate.get("provider") == "Artprice" and belongs(candidate)
                and candidate.get("status") == "sold" and candidate.get("credible") is True
                and bool(_text(candidate.get("artist")))
            ),
            "selected_count": sum(1 for candidate, _hammer in artprice_sales if belongs(candidate)),
            "included_count": sum(1 for candidate in included_artprice_sales if belongs(candidate)),
        })
    source_summary = {
        "liveart_selected_count": len(liveart_sales),
        "artprice_sold_count": artprice_sold_count if artprice_sold_count is not None else sum(
            1 for item in candidates if item.get("provider") == "Artprice"
        ),
        "artprice_eligible_count": sum(
            1 for item in candidates
            if item.get("provider") == "Artprice" and item.get("status") == "sold"
            and item.get("credible") is True and bool(_text(item.get("artist")))
        ),
        "artprice_selected_count": len(artprice_sales),
        "artprice_included_count": artprice_included_count,
        "artprice_duplicate_count": artprice_duplicate_count,
        "artprice_source_filename": artprice_source_filename,
        "artprice_source_filenames": [source["filename"] for source in artprice_sources or []]
        or ([artprice_source_filename] if artprice_source_filename else []),
        "artprice_sources": source_details,
        "artprice_source_count": len(source_details),
        "artprice_ingested_count": sum(source["ingested_count"] for source in source_details),
        "artprice_file_duplicate_count": max(0, sum(source["ingested_count"] for source in source_details) - (
            artprice_sold_count or sum(1 for item in candidates if item.get("provider") == "Artprice")
        )),
        "artprice_analysis_updated_at": artprice_analysis_updated_at,
        "combined_comp_count": len(values),
    }
    if not values:
        return merged, [], source_summary

    if artprice_included_count and liveart_sales:
        source_label = "selected LiveArt and saved Artprice sold USD hammers"
    elif artprice_included_count:
        source_label = "saved Artprice sold USD hammers"
    else:
        source_label = "selected LiveArt sold USD hammers"
    estimates = (
        ("downside", min(values) * downside, f"{downside:.0%} of the lowest {source_label}"),
        ("typical", Decimal(str(median(values))), f"Median of {source_label}"),
        ("upside", max(values) * upside, f"{upside:.0%} of the highest {source_label}"),
    )
    if any(resale > MAX_MONEY for _name, resale, _basis in estimates):
        message = "Combined resale estimate exceeds the supported range."
        if allow_unestimable:
            source_summary["calculation_error"] = message
            return merged, [], source_summary
        raise ArtpriceAnalysisError(message)
    scenarios = []
    for name, resale, basis in estimates:
        net, rows = _rows(resale, merged)
        scenarios.append(
            {
                "name": name,
                "key": name,
                "label": name.title(),
                "basis": basis,
                "resale_hammer": _display_money(resale),
                "expected_resale_hammer": _display_money(resale),
                "net_resale_proceeds": net,
                "bid_rows": rows,
                "selected_comp_count": len(values),
                "estimate_notice": "Resale and maximum hammer bids are estimates, not guaranteed profit.",
            }
        )
    return merged, scenarios, source_summary
