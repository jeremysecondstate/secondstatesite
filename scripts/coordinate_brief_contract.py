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
SHIPPING_TOPICS = ("pickup", "storage", "third_party_release", "house_recommended", "nearby_ups", "fine_art_packers")
SHIPPING_SERVICES = ("unknown", "packing", "fine_art_transport", "full_service", "parcel_shipping", "other")
SHIPPING_CHECK_STATUSES = ("found", "not_found_in_checked_pages", "access_failed", "not_checked")
OPENED_KINDS = ("public", "browser", "public_fetch", "public_browser", "authenticated_browser")


def _string_schema(maximum, *, required=False):
    return {"type": "string", "maxLength": maximum, **({"minLength": 1} if required else {})}


def _refs_schema(minimum=0):
    # The CLI's strict output format does not support uniqueItems; enforce
    # uniqueness in _refs for both generated output and API submissions.
    return {"type": "array", "minItems": minimum, "maxItems": MAX_SOURCE_REFS,
            "items": _string_schema(2048, required=True)}


def _record_schema(properties):
    return {"type": "object", "additionalProperties": False, "properties": properties, "required": list(properties)}


SHIPPING_SCHEMA = _record_schema({
    "working_currency": _record_schema({"code": _string_schema(3),
        "basis": {"type": "string", "enum": ["unknown", "inferred", "staff", "source"]},
        "note": _string_schema(500), "source_refs": _refs_schema()}),
    "quote_readiness": _record_schema({"status": {"type": "string", "enum": [
        "not_assessed", "conditional_ready", "needs_public_research", "needs_destination"]}, "note": _string_schema(600)}),
    "actions": {"type": "array", "maxItems": 8, "items": _record_schema({
        "owner": {"type": "string", "enum": ["provider", "auction_house", "staff"]},
        "stage": {"type": "string", "enum": ["quote", "release", "booking"]},
        "text": _string_schema(600, required=True), "source_refs": _refs_schema()})},
    "providers": {"type": "array", "maxItems": 6, "items": _record_schema({
        "name": _string_schema(200, required=True), "email": _string_schema(254),
        "service_type": {"type": "string", "enum": list(SHIPPING_SERVICES)},
        "published_capability": _string_schema(1000), "contact_quote": _string_schema(1200, required=True),
        "source_refs": _refs_schema(1)})},
    "site_checks": {"type": "array", "maxItems": 8, "items": _record_schema({
        "topic": {"type": "string", "enum": list(SHIPPING_TOPICS)},
        "status": {"type": "string", "enum": list(SHIPPING_CHECK_STATUSES)},
        "note": _string_schema(600), "source_refs": _refs_schema()})},
})


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
        "shipping": SHIPPING_SCHEMA,
    },
    "required": ["summary", "lots", "plan", "open_questions", "shipping"],
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


def _shipping(value):
    def clean_record(record, schema):
        _object(record, schema["required"])
        cleaned = {}
        for name, spec in schema["properties"].items():
            item = record[name]
            if name == "source_refs":
                cleaned[name] = _refs(item, required=spec.get("minItems", 0) > 0)
            elif "enum" in spec:
                if not isinstance(item, str) or item not in spec["enum"]:
                    raise ValueError("Invalid shipping brief classification.")
                cleaned[name] = item
            elif spec["type"] == "object":
                cleaned[name] = clean_record(item, spec)
            elif spec["type"] == "array":
                if not isinstance(item, list) or len(item) > spec["maxItems"]:
                    raise ValueError("Too many shipping brief entries.")
                cleaned[name] = [clean_record(entry, spec["items"]) for entry in item]
            else:
                cleaned[name] = _text(item, spec["maxLength"], required=spec.get("minLength", 0) > 0)
        return cleaned

    result = clean_record(value, SHIPPING_SCHEMA)
    currency = result["working_currency"]
    if currency["code"] and not re.fullmatch(r"[A-Z]{3}", currency["code"]):
        raise ValueError("shipping.working_currency.code: Use a three-letter code or remain empty.")
    if currency["basis"] == "unknown":
        if currency["code"]:
            raise ValueError("shipping.working_currency.code: An unknown working currency cannot contain an assumed code.")
    elif not currency["code"] or not currency["note"] or not currency["source_refs"]:
        raise ValueError("shipping.working_currency: A known or inferred currency needs code, note and cited context.")
    if currency["basis"] == "inferred" and currency["code"] != "USD":
        raise ValueError("shipping.working_currency.code: Only the supported US-location working currency inference is enabled.")
    seen = set()
    for index, provider in enumerate(result["providers"]):
        path = f"shipping.providers[{index}]"
        email = provider["email"]
        if email and (not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+", email)
                      or ".." in email or any(c in email for c in "\r\n")):
            raise ValueError(f"{path}.email: Use one valid published email address, or leave it empty when unknown.")
        key = (provider["name"].casefold(), email.casefold())
        if key in seen:
            raise ValueError(f"{path}: Duplicate shipping provider.")
        seen.add(key)
        if provider["service_type"] != "unknown" and not provider["published_capability"]:
            raise ValueError(f"{path}.service_type: A service classification needs published capability wording; use unknown when absent.")
    for index, check in enumerate(result["site_checks"]):
        path = f"shipping.site_checks[{index}]"
        if check["status"] != "not_checked" and (not check["note"] or not check["source_refs"]):
            raise ValueError(f"{path}: A completed site check needs a note and scoped supporting source_refs; omit an unsupported check.")
        if check["status"] == "not_checked" and check["source_refs"]:
            raise ValueError(f"{path}.source_refs: An unchecked topic cannot claim checked sources.")
    return result


def brief_source_refs(brief):
    records = [*brief["lots"], brief["plan"]]
    if "shipping" in brief:
        shipping = brief["shipping"]
        records += [shipping["working_currency"], *shipping["actions"], *shipping["providers"], *shipping["site_checks"]]
    return {ref for item in records for ref in item["source_refs"]}


def validate_brief(value):
    """Return a clean briefing, or None for clients that omit the optional field."""
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) not in (
            set(BRIEF_SCHEMA["required"]), set(BRIEF_SCHEMA["required"]) - {"shipping"}):
        raise ValueError("Invalid briefing fields.")
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
    result = {"summary": summary, "lots": cleaned_lots, "plan": cleaned_plan,
              "open_questions": [_text(item, 300, required=True) for item in questions]}
    if "shipping" in value:
        result["shipping"] = _shipping(value["shipping"])
    return result


def _normalized(value):
    return " ".join(value.split()).casefold()


def _currency_stated(code, text):
    aliases = {"USD": r"US\$|U\.?S\.?\s+dollars?|United States dollars?", "GBP": r"£|pounds?\s+sterling",
               "EUR": r"€|euros?", "CAD": r"CA\$|C\$|Canadian dollars?", "AUD": r"AU\$|A\$|Australian dollars?"}
    return bool(re.search(rf"\b{re.escape(code)}\b|{aliases.get(code, '(?!)')}", text, re.I))


def _observations(refs, evidence):
    return [source for ref in refs for source in evidence[ref].get("observations", [evidence[ref]])]


def _available(source):
    return (not source.get("error") and bool(source.get("text", "").strip())
            and source.get("kind") in (*OPENED_KINDS, "message", "document", "email"))


def _current_shipping_source(source, *, opened_only=False):
    if not _available(source):
        return False
    kind = source.get("kind")
    if kind not in OPENED_KINDS:
        return not opened_only
    status = source.get("identity_match", {}).get("status")
    return status in ("exact", "context") or kind in ("public", "browser") and not status


def _shipping_evidence(shipping, evidence):
    def supporting(refs, *, path, opened_only=False):
        # Each displayed citation must actually support the relevant source class.
        for index, ref in enumerate(refs):
            if not any(_current_shipping_source(source, opened_only=opened_only)
                       for source in _observations([ref], evidence)):
                raise ValueError(f"{path}.source_refs[{index}]: Shipping facts need current, visible source evidence; search leads are insufficient.")
        return [source for source in _observations(refs, evidence)
                if _current_shipping_source(source, opened_only=opened_only)]

    def validate_currency(currency):
        sources = supporting(currency["source_refs"], path="shipping.working_currency")
        if currency["basis"] == "inferred":
            # This is a labeled planning assumption, never a sale-price currency fact.
            us_location = re.compile(r"\b(?:United States|USA|U\.S\.A?\.?|Arizona|California|New York|Scottsdale|Phoenix)\b|\b(?:AZ|CA|NY)\s+\d{5}(?:-\d{4})?\b", re.I)
            if not any(us_location.search(source["text"]) for source in sources):
                raise ValueError("shipping.working_currency.source_refs: A working USD inference needs cited US location context; otherwise keep the currency unknown.")
        elif currency["basis"] in ("source", "staff"):
            if not any((currency["basis"] != "staff" or source["kind"] == "message")
                       and _currency_stated(currency["code"], source["text"]) for source in sources):
                raise ValueError("shipping.working_currency.source_refs: The stated working currency is absent from its cited basis.")

    def validate_provider(provider, path):
        sources = supporting(provider["source_refs"], path=path, opened_only=True)
        quote = _normalized(provider["contact_quote"])
        # Bind the name/address together, so a nearby unrelated address cannot
        # be silently assigned to a provider from another part of a catalog.
        if (not any(quote in _normalized(source["text"]) for source in sources)
                or _normalized(provider["name"]) not in quote
                or provider["email"] and not re.search(
                    r"(?<![\w.!#$%&'*+/=?^`{|}~@-])" + re.escape(provider["email"].casefold())
                    + r"(?![\w.@-])", quote)):
            raise ValueError(f"{path}.contact_quote: Use one contiguous opened excerpt containing this exact provider name and its email when supplied; omit this provider if no supported contact quote exists.")
        capability = _normalized(provider["published_capability"])
        if capability and (_normalized(provider["name"]) not in capability
                           or not any(capability in _normalized(source["text"]) for source in sources)):
            raise ValueError(f"{path}.published_capability: Use an exact opened excerpt naming this same provider, without combining aliases; otherwise set published_capability=\"\" and service_type=\"unknown\".")
        packing = bool(re.search(r"\bpack\w*|\bcrat\w*", capability))
        transport = bool(re.search(r"\bship\w*|\btransport\w*|\bdeliver\w*|\bmov(?:e|ing)\b", capability))
        service = provider["service_type"]
        if ((service == "packing" and not packing)
                or (service == "full_service" and not (packing and transport))
                or (service == "fine_art_transport" and not (transport and re.search(r"\bfine art\b|\bartwork\b|\bart transport", capability)))
                or (service == "parcel_shipping" and not re.search(r"\bparcel\b|\bUPS\b|\bFedEx\b|\bDHL\b", capability, re.I))):
            raise ValueError(f"{path}.service_type: The service type is not supported by its published wording; use unknown instead of inferring a capability.")
    def validate_check(check, path):
        status = check["status"]
        if status in ("found", "not_found_in_checked_pages"):
            sources = supporting(check["source_refs"], path=path, opened_only=True)
            if status == "found" and not any(_normalized(check["note"]) in _normalized(source["text"]) for source in sources):
                raise ValueError(f"{path}.note: Entire note must be one exact contiguous excerpt from cited opened text, without added quotation marks, prefixes, suffixes, commentary or combined excerpts. shipping_research_notes.detail is a summary, not a quote. Put explanations in actions/summary/plan, or omit this check.")
        elif status == "access_failed":
            for ref_index, ref in enumerate(check["source_refs"]):
                if not any(source.get("error") and any(
                        attempt.get("method") in ("public_fetch", "public_browser", "authenticated_browser")
                        and attempt.get("status") in ("unavailable", "timeout", "challenge", "login_required")
                        for attempt in source.get("attempts", [])) for source in _observations([ref], evidence)):
                    raise ValueError(f"{path}.source_refs[{ref_index}]: An access failure needs a recorded page-access attempt, not a failed browser launch; omit an unsupported failure claim.")

    errors = []

    def collect(validator, *args, **kwargs):
        try:
            validator(*args, **kwargs)
        except ValueError as exc:
            errors.append(str(exc))

    # A bounded correction sees every independently invalid shipping entry at
    # once. Keep each predicate intact, and never accept a partially valid brief.
    collect(validate_currency, shipping["working_currency"])
    for index, action in enumerate(shipping["actions"]):
        collect(supporting, action["source_refs"], path=f"shipping.actions[{index}]")
    for index, provider in enumerate(shipping["providers"]):
        collect(validate_provider, provider, f"shipping.providers[{index}]")
    for index, check in enumerate(shipping["site_checks"]):
        collect(validate_check, check, f"shipping.site_checks[{index}]")
    if errors:
        # Preserve every indexed path even at the schema's maximum entry count;
        # trim only explanatory wording when the combined diagnostic is large.
        if len("\n".join(errors)) > 4000:
            limit = (4000 - len(errors) + 1) // len(errors)
            errors = [error if len(error) <= limit else error[:limit - 3] + "..." for error in errors]
        raise ValueError("\n".join(errors))


def _matches_price_identity(price, lot, source):
    if source.get("error"):
        return False
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
    if currency and not _currency_stated(currency, quote):
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
    refs = brief_source_refs(brief)
    if not refs <= evidence.keys():
        raise ValueError("Briefing cites unavailable or unrelated case evidence.")
    for item in [*brief["lots"], brief["plan"]]:
        if any(not any(_available(source) for source in _observations([ref], evidence)) for ref in item["source_refs"]):
            raise ValueError("Lot and plan citations require readable evidence, not failed page observations.")
    for lot in brief["lots"]:
        lot_observations = [source for ref in lot["source_refs"]
                            for source in evidence[ref].get("observations", [evidence[ref]]) if _available(source)]
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
                   for source in evidence[ref].get("observations", [evidence[ref]]) if _available(source)):
            raise ValueError("The suggested pickup deadline wording is absent from its cited evidence.")
    if "shipping" in brief:
        _shipping_evidence(brief["shipping"], evidence)
