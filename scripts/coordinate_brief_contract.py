"""Shared, bounded briefing shape for the isolated worker and Django server."""

from datetime import datetime
from decimal import Decimal, InvalidOperation
import re

if __package__:
    from .coordinate_evidence import _same_identity
else:
    from coordinate_evidence import _same_identity


LOT_LIMITS = {
    "label": 300, "lot_number": 80, "artist": 200, "title": 300, "medium": 300,
    "edition": 200, "dimensions": 300, "framed_dimensions": 300, "framing": 400,
    "condition": 800, "auction_house": 200, "pickup_location": 600,
    "deadline_text": 500, "release_requirements": 1200,
}
# These additions are required in newly generated strict output. The validator
# also accepts older stored briefs with none (or some) of these fields.
LOT_ADDITIONAL_LIMITS = {
    "auction_date": 120, "storage_terms": 1200, "shipping_contacts": 1200,
    "price_notes": 1200,
}
PRICE_KINDS = ("sold", "estimate", "invoice_total", "tax", "shipping", "insurance", "historical_comparison", "other")
PRICE_BASES = ("unknown", "hammer", "premium_inclusive", "estimate", "invoice_total", "tax", "shipping", "insurance", "other")
PRICE_LIMITS = {"label": 160, "amount": 24, "amount_high": 24, "currency": 3, "evidence_quote": 1500}
PLAN_LIMITS = {"notes": 4000, "pickup_deadline": 64, "deadline_basis": 500}
MAX_SOURCE_REFS = 8


def _string_schema(maximum, *, required=False):
    return {"type": "string", "maxLength": maximum, **({"minLength": 1} if required else {})}


def _refs_schema(minimum=0):
    # The CLI's strict output format does not support uniqueItems; enforce
    # uniqueness in _refs for both generated output and API submissions.
    return {"type": "array", "minItems": minimum, "maxItems": MAX_SOURCE_REFS,
            "items": _string_schema(2048, required=True)}


BRIEF_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "summary": _string_schema(1200),
        "lots": {
            "type": "array", "maxItems": 8,
            "items": {
                "type": "object", "additionalProperties": False,
                "properties": {**{key: _string_schema(limit, required=key == "label") for key, limit in {**LOT_LIMITS, **LOT_ADDITIONAL_LIMITS}.items()},
                               "prices": {"type": "array", "maxItems": 6, "items": {
                                   "type": "object", "additionalProperties": False,
                                   "properties": {
                                       **{key: _string_schema(limit, required=key in ("label", "amount", "evidence_quote")) for key, limit in PRICE_LIMITS.items()},
                                       "kind": {"type": "string", "enum": list(PRICE_KINDS)},
                                       "basis": {"type": "string", "enum": list(PRICE_BASES)},
                                       "source_refs": _refs_schema(1),
                                   },
                                   "required": [*PRICE_LIMITS, "kind", "basis", "source_refs"],
                               }},
                               "source_refs": _refs_schema(1)},
                "required": [*LOT_LIMITS, *LOT_ADDITIONAL_LIMITS, "prices", "source_refs"],
            },
        },
        "plan": {
            "type": "object", "additionalProperties": False,
            "properties": {**{key: _string_schema(limit) for key, limit in PLAN_LIMITS.items()},
                           "source_refs": _refs_schema()},
            "required": [*PLAN_LIMITS, "source_refs"],
        },
        "open_questions": {"type": "array", "maxItems": 8, "items": _string_schema(300, required=True)},
    },
    "required": ["summary", "lots", "plan", "open_questions"],
}

_CLOCK = re.compile(r"(?<![\d:+-])(?:[01]?\d|2[0-3]):[0-5]\d\b|\b(?:0?[1-9]|1[0-2])\s*[ap]\.?m\.?\b|\b(?:noon|midnight)\b", re.I)
_ZONE = re.compile(
    r"(?:[+-]\d{2}:\d{2})\b|\b(?:UTC|GMT|EST|EDT|CST|CDT|MST|MDT|PST|PDT|ET|CT|MT|PT|"
    r"AKST|AKDT|HST|BST|CET|CEST|EET|EEST|AEST|AEDT|ACST|ACDT|AWST|NZST|NZDT)\b|"
    r"\b(?:Eastern|Central|Mountain|Pacific)\s+(?:(?:Standard|Daylight)\s+)?Time\b|"
    r"\b(?:America|Europe|Asia|Australia|Africa|Pacific|Atlantic|Indian)/[A-Za-z_]+(?:/[A-Za-z_]+)?\b|"
    r"\d{2}:\d{2}(?::\d{2})?Z\b", re.I,
)


def _object(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError("Invalid briefing fields.")
    return value


def _text(value, maximum, *, required=False):
    if not isinstance(value, str) or len(value) > maximum or (required and not value.strip()):
        raise ValueError("Invalid or oversized briefing text.")
    return value.strip()


def _refs(value, *, required=False):
    if not isinstance(value, list) or len(value) > MAX_SOURCE_REFS or (required and not value):
        raise ValueError("Invalid briefing source references.")
    result = [_text(item, 2048, required=True) for item in value]
    if result != value or len(set(result)) != len(result):
        raise ValueError("Briefing source references must be exact and unique.")
    return result


def _amount(value, *, required=False):
    value = _text(value, 24, required=required)
    if value:
        try:
            if not re.fullmatch(r"\d{1,18}(?:\.\d{1,4})?", value) or Decimal(value) < 0:
                raise InvalidOperation
        except InvalidOperation:
            raise ValueError("Price amounts must be nonnegative decimal strings, without currency symbols.") from None
    return value


def _prices(value, lot_refs):
    if not isinstance(value, list) or len(value) > 6:
        raise ValueError("Too many briefing prices.")
    result = []
    for price in value:
        _object(price, [*PRICE_LIMITS, "kind", "basis", "source_refs"])
        clean = {key: _text(price[key], limit, required=key in ("label", "amount", "evidence_quote")) for key, limit in PRICE_LIMITS.items()}
        clean.update(kind=price["kind"], basis=price["basis"], source_refs=_refs(price["source_refs"], required=True))
        if clean["kind"] not in PRICE_KINDS or clean["basis"] not in PRICE_BASES:
            raise ValueError("Invalid price kind or basis.")
        clean["amount"] = _amount(clean["amount"], required=True)
        clean["amount_high"] = _amount(clean["amount_high"])
        if clean["currency"] and not re.fullmatch(r"[A-Z]{3}", clean["currency"]):
            raise ValueError("Price currency must be an explicit three-letter code or empty when unknown.")
        if clean["amount_high"] and (clean["kind"] != "estimate" or Decimal(clean["amount_high"]) < Decimal(clean["amount"])):
            raise ValueError("Only estimates may contain an ordered price range.")
        if clean["kind"] == "sold" and clean["basis"] not in ("unknown", "hammer", "premium_inclusive"):
            raise ValueError("A sold price needs an unknown, hammer, or premium-inclusive basis.")
        if clean["kind"] in ("estimate", "invoice_total", "tax", "shipping", "insurance") and clean["basis"] != clean["kind"]:
            raise ValueError("The price kind and stated basis disagree.")
        if not set(clean["source_refs"]) <= set(lot_refs):
            raise ValueError("Price citations must also be sources for the lot.")
        result.append(clean)
    return result


def validate_brief(value):
    """Return a clean briefing, or None for clients that omit the optional field."""
    if value is None:
        return None
    _object(value, BRIEF_SCHEMA["required"])
    summary = _text(value["summary"], 1200)
    lots = value["lots"]
    questions = value["open_questions"]
    if not isinstance(lots, list) or len(lots) > 8 or not isinstance(questions, list) or len(questions) > 8:
        raise ValueError("Too many briefing lots or questions.")
    cleaned_lots = []
    for lot in lots:
        if (not isinstance(lot, dict) or not {*LOT_LIMITS, "source_refs"} <= lot.keys()
                or not lot.keys() <= {*LOT_LIMITS, *LOT_ADDITIONAL_LIMITS, "prices", "source_refs"}):
            raise ValueError("Invalid briefing lot fields.")
        clean = {**{key: _text(lot[key], limit, required=key == "label") for key, limit in LOT_LIMITS.items()},
                 **{key: _text(lot[key], limit) for key, limit in LOT_ADDITIONAL_LIMITS.items() if key in lot},
                 "source_refs": _refs(lot["source_refs"], required=True)}
        if clean.get("auction_date"):
            try:
                if datetime.strptime(clean["auction_date"], "%Y-%m-%d").strftime("%Y-%m-%d") != clean["auction_date"]:
                    raise ValueError
            except ValueError:
                raise ValueError("Briefing auction dates must use YYYY-MM-DD or remain empty when unknown.") from None
        if "prices" in lot:
            clean["prices"] = _prices(lot["prices"], clean["source_refs"])
        cleaned_lots.append(clean)
    plan = _object(value["plan"], [*PLAN_LIMITS, "source_refs"])
    cleaned_plan = {**{key: _text(plan[key], limit) for key, limit in PLAN_LIMITS.items()},
                    "source_refs": _refs(plan["source_refs"])}
    if cleaned_plan["pickup_deadline"]:
        try:
            deadline = datetime.fromisoformat(cleaned_plan["pickup_deadline"].replace("Z", "+00:00"))
            if deadline.tzinfo is None or deadline.utcoffset() is None:
                raise ValueError
        except (ValueError, TypeError):
            raise ValueError("A suggested pickup deadline must include an explicit time and timezone.") from None
        basis = cleaned_plan["deadline_basis"]
        if not cleaned_plan["source_refs"] or not basis or not _CLOCK.search(basis) or not _ZONE.search(basis):
            raise ValueError("A suggested pickup deadline needs cited wording with an explicit time and timezone.")
        cleaned_plan["pickup_deadline"] = deadline.isoformat()
    return {"summary": summary, "lots": cleaned_lots, "plan": cleaned_plan,
            "open_questions": [_text(item, 300, required=True) for item in questions]}


def _normalized(value):
    return " ".join(value.split()).casefold()


def _matches_price_identity(price, lot, source):
    match = source.get("identity_match", {})
    status = match.get("status")
    if source["kind"] in ("public", "browser", "public_fetch", "public_browser", "authenticated_browser"):
        if price["kind"] == "historical_comparison":
            return status == "historical" and all(not lot.get(key) or _same_identity(key, lot[key], match.get(key, ""))
                                                   for key in ("artist", "title"))
        return (status == "exact" and bool(match.get("auction_date")) and bool(match.get("lot_number"))
                and all(not lot.get(key) or _same_identity(key, lot[key], match.get(key, ""))
                        for key in ("artist", "title", "auction_house", "auction_date", "lot_number")))
    return source["kind"] in ("message", "document", "email")


def _price_supported(price, lot, evidence):
    quote = _normalized(price["evidence_quote"])
    supporting = []
    observations = [source for ref in price["source_refs"]
                    for source in evidence[ref].get("observations", [evidence[ref]])]
    for source in observations:
        if quote not in _normalized(source["text"]) or not _matches_price_identity(price, lot, source):
            continue
        supporting.append(source)
    if not supporting:
        raise ValueError("A price needs its exact quoted wording from an opened source matching this sale.")
    label = _normalized(price["label"])
    if label not in quote:
        raise ValueError("The price label must preserve wording from its cited source.")
    after_label = quote.split(label, 1)[1][:140]
    numbers = re.findall(r"\d[\d,]*(?:\.\d+)?", after_label)
    expected = [Decimal(price["amount"])] + ([Decimal(price["amount_high"])] if price["amount_high"] else [])
    if [Decimal(item.replace(",", "")) for item in numbers[:len(expected)]] != expected:
        raise ValueError("The price amount does not follow its stated label in the cited wording.")
    # The same URL may have been observed by fetch and browser, or at different
    # times. Missing fields do not erase useful observations, but a conflicting
    # current-sale amount must never be silently selected from an older excerpt.
    amount_after_label = re.compile(re.escape(label) + r"\s*[:\-]?\s*(?:[a-z]{3}\s*|(?:[a-z]{1,2})?[$£€]\s*)?(\d[\d,]*(?:\.\d+)?)", re.I)
    if price["kind"] != "historical_comparison" and not lot.get("price_notes", "").strip():
        for source in observations:
            if _matches_price_identity(price, lot, source):
                found = amount_after_label.search(_normalized(source["text"]))
                if found and Decimal(found[1].replace(",", "")) != expected[0]:
                    raise ValueError("Conflicting observations of a cited price require a reconciliation note.")
    kind, basis = price["kind"], price["basis"]
    if kind == "sold" and (not re.search(r"\bsold\b|\b(?:price\s+)?reali[sz]ed\b|\bhammer\b", label) or "estimate" in label):
        raise ValueError("A sold price must preserve an explicit sale-result label.")
    if kind == "estimate" and "estimate" not in label:
        raise ValueError("An estimate must preserve an estimate label.")
    label_signals = {"invoice_total": r"\binvoice\b|\btotal\b", "tax": r"\btax(?:es)?\b|\bvat\b|\bgst\b",
                     "shipping": r"\bshipping\b|\bfreight\b|\btransport\b|\bdelivery\b|\bpostage\b",
                     "insurance": r"\binsurance\b|\binsured\b"}
    if kind in label_signals and not re.search(label_signals[kind], label):
        raise ValueError("The price kind must be supported by its source label.")
    if basis == "hammer" and "hammer" not in label:
        raise ValueError("A hammer basis must be explicitly stated in the cited wording.")
    if basis == "premium_inclusive":
        includes = re.search(r"(?:includ\w*|with)\s+(?:the\s+)?(?:buyer[’']?s?\s+)?premium|premium[ -]inclusive", quote)
        excludes = re.search(r"\b(?:not|exclud\w*|without)\b[^.;]{0,60}\bpremium\b|\bpremium\b[^.;]{0,40}\b(?:excluded|not included|additional|separate)\b", quote)
        if not includes or excludes:
            raise ValueError("A premium-inclusive basis must be explicitly and unambiguously stated in the cited wording.")
    currency = price["currency"]
    if currency:
        aliases = {"USD": r"US\$|U\.?S\.?\s+dollars?|United States dollars?", "GBP": r"£|pounds?\s+sterling", "EUR": r"€|euros?", "CAD": r"CA\$|C\$|Canadian dollars?", "AUD": r"AU\$|A\$|Australian dollars?"}
        pattern = rf"\b{re.escape(currency)}\b|{aliases.get(currency, '(?!)')}"
        if not re.search(pattern, quote, re.I):
            raise ValueError("A price currency must be explicitly supported; a bare dollar sign is ambiguous.")


def validate_price_evidence(brief, evidence):
    """Validate citations and price claims against a map of visible observations.

    Each reference maps to {kind, text, identity_match}. To preserve multiple
    observations of the same URL it may instead include an observations list
    of these dictionaries. Search-only results must not enter this map.
    Both the isolated worker and server use this rule before publication.
    """
    if brief is None:
        return
    refs = {ref for item in [*brief["lots"], brief["plan"]] for ref in item["source_refs"]}
    if not refs <= evidence.keys():
        raise ValueError("Briefing cites unavailable or unrelated case evidence.")
    for lot in brief["lots"]:
        lot_observations = [source for ref in lot["source_refs"]
                            for source in evidence[ref].get("observations", [evidence[ref]])]
        facts = ("artist", "title", "medium", "edition", "dimensions", "framed_dimensions", "framing",
                 "condition", "auction_date", "lot_number")
        if any(lot.get(key) for key in facts):
            current_support = []
            for source in lot_observations:
                if source["kind"] in ("public", "browser", "message", "document", "email"):
                    current_support.append(source)
                elif source["kind"] in ("public_fetch", "public_browser", "authenticated_browser"):
                    match = source.get("identity_match", {})
                    if match.get("status") == "exact" and all(
                            not lot.get(key) or not match.get(key) or _same_identity(key, lot[key], match[key])
                            for key in ("artist", "title", "auction_house", "auction_date", "lot_number")):
                        current_support.append(source)
            if not current_support:
                raise ValueError("Current lot facts need a matching opened listing or staff evidence; historical and unverified sources are insufficient.")
        for price in lot.get("prices", []):
            _price_supported(price, lot, evidence)
        current = [price for price in lot.get("prices", []) if price["kind"] == "sold"]
        identities = {(price["amount"], price["currency"], price["basis"]) for price in current}
        if len(identities) > 1 and not lot.get("price_notes", "").strip():
            raise ValueError("Different sold-price observations require an explicit reconciliation note.")
    plan = brief["plan"]
    if plan["pickup_deadline"]:
        basis = " ".join(plan["deadline_basis"].split())
        if not any(basis in " ".join(source["text"].split()) for ref in plan["source_refs"]
                   for source in evidence[ref].get("observations", [evidence[ref]])):
            raise ValueError("The suggested pickup deadline wording is absent from its cited evidence.")
