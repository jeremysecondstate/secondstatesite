"""Conservative cleanup of inventory notes before they become public copy."""

from __future__ import annotations

import re


_SENTENCES = re.compile(r"(?<=[.!?])\s+|[\r\n]+")
_CLAUSES = re.compile(r"\s*;\s*|\s*\|\s*")
_INTERNAL = re.compile(
    r"\b(?:invoice(?:\s+(?:no\.?|number))?|"
    r"(?:USD|EUR|GBP|currency|FX)\s+conversion|exchange\s+rate|FX\s*[:=]|"
    r"buyer(?:[’']s|s[’']?)?\s+premium|"
    r"(?:Drouot|auction(?:eer)?|platform)\s+fees?|"
    r"hammer(?:\s+price)?(?=\s*[:=]|\s+(?:USD|EUR|GBP|CHF|CAD|AUD|JPY|[$€£]|\d))|"
    r"VAT(?=\s*[:=]|\s+(?:USD|EUR|GBP|CHF|CAD|AUD|JPY|[$€£]|\d))|"
    r"(?:paid|payment)(?=\s*[:=]|\s+(?:on\b|in\s+full\b|date\b|USD|EUR|GBP|CHF|CAD|AUD|JPY|[$€£]|\d))|"
    r"(?:purchase|acquisition|landed|total)\s+(?:cost|price)|"
    r"(?:shipping|postage)(?=\s*[:=]|\s+(?:costs?|charges?|fees?|invoice|paid|USD|EUR|GBP|[$€£]|\d))|"
    r"(?:tax(?:es)?|fees?)\s*[:=])",
    re.IGNORECASE,
)
_COST_SUFFIX = re.compile(
    r"\s+(?:for|at)\s+(?:(?:USD|EUR|GBP|CHF|CAD|AUD|JPY)\s*\d|[$€£]\s*\d)",
    re.IGNORECASE,
)
_MISSING_FIELD = (
    r"(?:year|date|edition(?:\s+(?:size|details))?|signature|signing|shipping|framing|condition|"
    r"provenance|printer|publisher|paper(?:\s+type)?|image\s+size|sheet\s+size)"
)
_MISSING_INFO = re.compile(
    rf"\b{_MISSING_FIELD}(?:\s*(?:,|/|&|\band\b|\bor\b)\s*{_MISSING_FIELD})*"
    r"\s*[:=-]?\s*(?:(?:is|are|was|were)\s+)?"
    r"(?:not\s+(?:stated|provided|specified|known|available)|unknown)\b",
    re.IGNORECASE,
)


def clean_public_notes(text: object) -> str:
    """Remove clear accounting/admin clauses while retaining factual art notes.

    This deliberately does not rewrite condition, signatures, measurements, or
    provenance. Unrecognized prose is retained for review rather than guessed at.
    """
    if text is None:
        return ""
    sentences = []
    for sentence in _SENTENCES.split(str(text).strip()):
        kept = []
        for clause in _CLAUSES.split(sentence):
            clause = clause.strip()
            if not clause:
                continue
            # Remove only the missing-field phrase. Condition or signature facts
            # can follow it in the same comma-delimited clause.
            clause = _MISSING_INFO.sub("", clause)
            clause = re.sub(r"(?:,\s*){2,}", ", ", clause).strip(" ,")
            clause = re.sub(r",\s*([.!?])", r"\1", clause)
            if not re.search(r"\w", clause):
                continue
            # A comma can separate a public fact from internal purchase details.
            marker = _INTERNAL.search(clause)
            if marker:
                clause = clause[:marker.start()].rstrip(" ,:–—-")
            cost = _COST_SUFFIX.search(clause)
            if cost:
                clause = clause[:cost.start()].rstrip(" ,:–—-")
            if not clause or re.fullmatch(r"(?:purchased|acquired|bought)", clause, re.I):
                continue
            if clause:
                kept.append(clause)
        if kept:
            sentence = "; ".join(kept)
            if sentence[-1:] not in ".!?":
                sentence += "."
            sentences.append(sentence)
    return " ".join(sentences)
