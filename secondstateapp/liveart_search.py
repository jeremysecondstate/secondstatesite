"""Bounded search parsing and result merging without provider requests."""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping
from typing import Any


MAX_SEARCH_CHARACTERS = 200
MAX_SEARCH_TERMS = 5
MAX_SEARCH_LOTS = 20
# LiveArt /v1/categories, verified 2026-10-12: prints-and-multiples.
PRINTS_AND_MULTIPLES_CATEGORY_ID = 2
PRINTS_AND_MULTIPLES_LABEL = "Prints & Multiples"


def _term_key(term: str) -> str:
    normalized = unicodedata.normalize("NFKD", term).casefold()
    return "".join(char for char in normalized if not unicodedata.combining(char)).replace("\u2019", "'")


def parse_search_terms(value: Any) -> tuple[str, ...]:
    """Split words as alternatives; double quotes preserve a complete phrase."""

    if not isinstance(value, str) or len(value) > MAX_SEARCH_CHARACTERS:
        raise ValueError("LiveArt search terms must be text of at most 200 characters.")
    value = value.replace("\u201c", '"').replace("\u201d", '"')
    terms: list[str] = []
    seen: set[str] = set()
    token: list[str] = []
    quoted = False
    closed_phrase = False

    def append_term() -> None:
        term = " ".join("".join(token).split())
        token.clear()
        if not term or not any(char.isalnum() for char in term):
            raise ValueError("Enter a word or phrase between the LiveArt search separators.")
        key = _term_key(term)
        if key not in seen:
            terms.append(term)
            seen.add(key)
        if len(terms) > MAX_SEARCH_TERMS:
            raise ValueError("Search for at most 5 different LiveArt words or phrases at a time.")

    for char in value:
        if char == '"':
            if quoted:
                append_term()
                quoted = False
                closed_phrase = True
            else:
                if token or closed_phrase:
                    raise ValueError("Separate quoted LiveArt phrases with a space, comma, or semicolon.")
                quoted = True
        elif quoted:
            token.append(char)
        elif char.isspace() or char in ",;":
            if token:
                append_term()
            closed_phrase = False
        else:
            if closed_phrase:
                raise ValueError("Separate quoted LiveArt phrases with a space, comma, or semicolon.")
            token.append(char)
    if quoted:
        raise ValueError("Close each quoted LiveArt phrase with a double quote.")
    if token:
        append_term()
    if not terms and value.strip():
        raise ValueError("Enter at least one LiveArt search word or phrase.")
    return tuple(terms)


def search_query_limits(term_count: int) -> tuple[int, ...]:
    """Share the twenty-result allowance fairly among all search terms."""

    if not 1 <= term_count <= MAX_SEARCH_TERMS:
        raise ValueError("A LiveArt search needs between 1 and 5 terms.")
    count, extra = divmod(MAX_SEARCH_LOTS, term_count)
    return tuple(count + int(index < extra) for index in range(term_count))


def merge_search_lots(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep each sale once, carrying every query that returned it.

    Either an identical provider lot ID or sale ID plus lot number establishes
    overlap. Retain aliases across duplicates so later rows can bridge groups.
    Equal titles, dates, or prices alone do not establish the same sale.
    """

    groups: list[dict[str, Any]] = []
    for raw in rows:
        identifier = str(raw.get("id") or "").strip()
        if not identifier:
            continue
        sale = raw.get("sale") if isinstance(raw.get("sale"), Mapping) else {}
        sale_key = (str(raw.get("sale_id") or sale.get("id") or "").strip(), str(raw.get("lot_num") or "").strip())
        keys = {("id", identifier)}
        if all(sale_key):
            keys.add(("sale", *sale_key))
        overlapping = [group for group in groups if group["keys"] & keys]
        if overlapping:
            target = overlapping[0]
            for group in overlapping[1:]:
                target["keys"].update(group["keys"])
                target["terms"].extend(term for term in group["terms"] if term not in target["terms"])
                groups.remove(group)
        else:
            target = {"raw": raw, "keys": set(), "terms": []}
            groups.append(target)
        target["keys"].update(keys)
        target["terms"].extend(term for term in raw.get("_search_terms", []) if term not in target["terms"])
    return [{**group["raw"], "_search_terms": group["terms"]} for group in groups]
