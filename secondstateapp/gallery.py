"""Technique groups derived from the inventory's recorded medium."""

import re


GALLERY_CATEGORIES = (
    {
        "key": "intaglio",
        "label": "Etchings & engravings",
        "description": "Explore etchings, engravings, aquatints, drypoints, and mezzotints.",
    },
    {
        "key": "lithograph",
        "label": "Lithographs",
        "description": "Explore works recorded as lithographs in the collection.",
    },
    {
        "key": "screenprint",
        "label": "Screenprints",
        "description": "Explore screenprints and serigraphs from the collection.",
    },
    {
        "key": "other",
        "label": "Other techniques",
        "description": "Explore further techniques and works with an unspecified medium.",
    },
)

_TECHNIQUE_PATTERNS = (
    ("intaglio", re.compile(r"\b(?:etch\w*|engrav\w*|aquatint\w*|dry\s*point\w*|mezzotint\w*|intaglio)\b")),
    ("lithograph", re.compile(r"\b(?:litho\w*|chromolitho\w*)\b")),
    ("screenprint", re.compile(r"\b(?:screen[\s-]*print\w*|silk[\s-]*screen\w*|serigraph\w*)\b")),
)


def gallery_category_for_medium(medium):
    """Assign each work once, using a stable priority for mixed techniques."""
    value = (medium or "").casefold()
    for category, pattern in _TECHNIQUE_PATTERNS:
        if pattern.search(value):
            return category
    return "other"
