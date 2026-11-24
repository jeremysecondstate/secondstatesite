"""Resolve credited artists against the active Invaluable and Drouot intake."""

from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
import re
from types import MappingProxyType

from .artprice_artist_links import artist_identity_key
from .bookmark_watchlist import (
    INVALUABLE_INTAKE_BULK_TITLES, invaluable_search_artists, parse_netscape_bookmarks,
    select_invaluable_intake_entries,
)
from .watchlist_drouot_pages import _SOURCE_CREDIT_ALIASES, select_drouot_entries


# Confirmed alternate names seen on sale records. Enable each alias only
# while the corresponding artist is present in the current intake.
_ALIASES = {
    "Romare Howard Bearden": ("Romare Bearden",),
    "Will Barnet": ("Will R. Barnet", "Will Barnett"),
    "LeRoy Neiman": ("LeRoy Neimann",),
    "Friedensreich Hundertwasser": ("Friedrich Hundertwasser",),
    "Albrecht Dürer": ("Albrecht Duerer",),
    "Pierre-Auguste Renoir": ("Auguste Renoir",),
    "Francisco de Goya": ("Goya",),
    "Giovanni Battista Piranesi": ("Giovanni Battista Piranèse", "Jean-Baptiste Piranèse"),
    "Rembrandt": ("Rembrandt Harmensz. van Rijn",),
    "Alphonse Mucha": ("Alfons Mucha",),
}
_QUALIFIER = re.compile(
    r"^\(?(?:after|attributed to|d['’]après|attribuée? à|based on(?: (?:a work|works) by)?|according to)\)?\s+", re.I
)
_END_QUALIFIER = re.compile(r"(?:[, ]+|\s*\()(?:after|attributed to|d['’]après|attribué[e]? à)[.)]*$", re.I)
_CONTRIBUTORS = re.compile(r"\s*;\s*|\s+(?:and|et|und|&|\+|×|/|with|after|d['’]après)\s+", re.I)
_NATIONALITY = (
    r"American|Argentine|Australian|Austrian|Belgian|Brazilian|British|Canadian|Chilean|Chinese|"
    r"Colombian|Cuban|Czech|Danish|Dutch|Egyptian|English|Finnish|French|German|Greek|Hungarian|"
    r"Indian|Irish|Israeli|Italian|Japanese|Korean|Mexican|Norwegian|Polish|Portuguese|Romanian|"
    r"Russian|Scottish|South African|Spanish|Swedish|Swiss|Turkish|Ukrainian|Uruguayan|Venezuelan|Welsh"
)
_LIFESPAN = re.compile(
    rf"\s*\(\s*(?:(?:{_NATIONALITY})(?:[- /]+(?:{_NATIONALITY}))?[,\s]+)?"
    r"(?:(?:b\.|born)\s*\d{4}|(?:c\.\s*)?\d{4}\s*[-–—]\s*(?:\d{4})?)\s*\)$", re.I
)
_REFERENCE_ONLY = re.compile(
    r"\b(?:inspired by|(?:in (?:the )?)?(?:style|manner|taste) of|school of|circle of|follower of|"
    r"homage to|hommage à|portrait of|subject of|depicting|dans (?:le style|la manière) de)\b", re.I
)


def tracked_artist_keys(bookmark_path: Path) -> frozenset[str]:
    return frozenset(tracked_artist_names(bookmark_path))


def tracked_artist_names(bookmark_path: Path) -> Mapping[str, str]:
    path = Path(bookmark_path)
    stat = path.stat()
    return _load_names(path, stat.st_mtime_ns, stat.st_size)


@lru_cache(maxsize=4)
def _load_names(path: Path, modified_ns: int, size: int) -> Mapping[str, str]:
    html = path.read_text(encoding="utf-8-sig")
    entries = select_invaluable_intake_entries(parse_netscape_bookmarks(html))
    bulk = [entry for entry in entries if entry.title.strip().upper() in INVALUABLE_INTAKE_BULK_TITLES]
    if not bulk:
        raise ValueError("The four active Invaluable bulk bookmarks are missing.")
    drouot = select_drouot_entries(html)
    if not drouot:
        raise ValueError("The active Drouot print bookmarks are missing.")
    names = {artist_identity_key(name): name for entry in bulk for name in invaluable_search_artists(entry.url)}
    names.update((artist_identity_key(entry.artist), entry.artist) for entry in drouot)
    aliases = dict(_SOURCE_CREDIT_ALIASES)
    for name, variants in _ALIASES.items():
        key = artist_identity_key(name)
        aliases[key] = (*aliases.get(key, ()), *variants)
    for key, name in list(names.items()):
        for alias in aliases.get(key, ()):
            names.setdefault(artist_identity_key(alias), name)
    return MappingProxyType(names)


@lru_cache(maxsize=16384)
def _credit_keys(credit: str) -> tuple[str, ...]:
    def identity(value):
        value = _LIFESPAN.sub("", value.strip())
        return artist_identity_key(_END_QUALIFIER.sub("", _QUALIFIER.sub("", value)))

    # An inspiration or subject clause can name several artists. Its scope
    # extends over those names even when they are joined by "and".
    credit = _REFERENCE_ONLY.split(credit, maxsplit=1)[0].rstrip(" ,;-(")
    keys = [identity(credit)]
    for part in _CONTRIBUTORS.split(credit):
        keys.append(identity(part))
        # A comma also occurs in surname-first names. Only accept a component
        # of a comma-separated list when it supplies a whole multi-word name.
        if "," in part:
            keys.extend(key for name in part.split(",") if " " in (key := identity(name)))
    return tuple(dict.fromkeys(filter(None, keys)))


def is_tracked_credit(credit: str, tracked_keys: frozenset[str]) -> bool:
    return bool(credit) and not tracked_keys.isdisjoint(_credit_keys(credit))


def allows_watchlist_credit(source_credit: str) -> bool:
    """Use a retained intake attribution for an empty, qualified or group credit.

    A different standalone creator or an explicit reference to a subject or
    influence cannot be overridden by a historical search label.
    """
    if not source_credit:
        return True
    source_credit = _LIFESPAN.sub("", source_credit.strip())
    return not _REFERENCE_ONLY.search(source_credit) and bool(
        _CONTRIBUTORS.search(source_credit) or _QUALIFIER.match(source_credit)
        or _END_QUALIFIER.search(source_credit) or "(" in source_credit
        or " - " in source_credit or "plusieurs artistes" in source_credit.casefold()
    )


def tracked_artist_match(credit: str, roster: Mapping[str, str]) -> str:
    return next((roster[key] for key in _credit_keys(credit or "") if key in roster), "")
