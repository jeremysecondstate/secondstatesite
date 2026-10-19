"""Shared, bounded briefing shape for the isolated worker and Django server."""

from datetime import datetime
import re


LOT_LIMITS = {
    "label": 300, "lot_number": 80, "artist": 200, "title": 300, "medium": 300,
    "edition": 200, "dimensions": 300, "framed_dimensions": 300, "framing": 400,
    "condition": 800, "auction_house": 200, "pickup_location": 600,
    "deadline_text": 500, "release_requirements": 1200,
}
PLAN_LIMITS = {"notes": 4000, "pickup_deadline": 64, "deadline_basis": 500}


def _string_schema(maximum, *, required=False):
    return {"type": "string", "maxLength": maximum, **({"minLength": 1} if required else {})}


def _refs_schema(minimum=0):
    # The CLI's strict output format does not support uniqueItems; enforce
    # uniqueness in _refs for both generated output and API submissions.
    return {"type": "array", "minItems": minimum, "maxItems": 4,
            "items": _string_schema(2048, required=True)}


BRIEF_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "summary": _string_schema(1200),
        "lots": {
            "type": "array", "maxItems": 8,
            "items": {
                "type": "object", "additionalProperties": False,
                "properties": {**{key: _string_schema(limit, required=key == "label") for key, limit in LOT_LIMITS.items()},
                               "source_refs": _refs_schema(1)},
                "required": [*LOT_LIMITS, "source_refs"],
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
    if not isinstance(value, list) or len(value) > 4 or (required and not value):
        raise ValueError("Invalid briefing source references.")
    result = [_text(item, 2048, required=True) for item in value]
    if result != value or len(set(result)) != len(result):
        raise ValueError("Briefing source references must be exact and unique.")
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
        _object(lot, [*LOT_LIMITS, "source_refs"])
        cleaned_lots.append({**{key: _text(lot[key], limit, required=key == "label") for key, limit in LOT_LIMITS.items()},
                             "source_refs": _refs(lot["source_refs"], required=True)})
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
