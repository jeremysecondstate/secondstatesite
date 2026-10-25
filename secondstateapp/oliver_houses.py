"""House membership for Oliver's Calendar, independent of lot identity or state."""

from __future__ import annotations

import json
from pathlib import Path
import unicodedata

from .lot_presentation import clean_display_text


def _house_key(value: str) -> str:
    # Keep every letter and number. Do not drop house-name words or use fuzzy
    # matching: a separately named affiliate is not automatically a partner.
    normalized = unicodedata.normalize("NFKC", clean_display_text(value)).casefold().replace("\u02bc", "'")
    return "".join(character for character in normalized if character.isalnum())


_DATA_PATH = Path(__file__).with_name("data") / "oliver_auction_houses.json"
_REGISTRY = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
_HOUSE_NAMES = tuple(house["name"] for house in _REGISTRY["houses"])
_HOUSE_KEYS = frozenset(
    _house_key(name)
    for house in _REGISTRY["houses"]
    for name in (house["name"], *house["aliases"])
)


def is_oliver_house(name: str) -> bool:
    """Match one supplied house name or an explicit, verified display alias."""

    return isinstance(name, str) and bool(name.strip()) and _house_key(name) in _HOUSE_KEYS


def oliver_house_names() -> tuple[str, ...]:
    """Return the workbook's house labels in their original row order."""

    return _HOUSE_NAMES
