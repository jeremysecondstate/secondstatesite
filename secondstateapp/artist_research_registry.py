"""Offline artist links shared by whole-sale and watchlist Calendar lots."""

from collections import defaultdict
from functools import lru_cache
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, urlsplit

from django.conf import settings

from catalogapp.artprice_artist_links import (
    _valid_artprice_artist_url,
    artist_identity_key,
    extract_artprice_bookmarks,
    normalize_artist_name,
)
from catalogapp.bookmark_watchlist import parse_netscape_bookmarks, repeatedly_decode
from catalogapp.artprice_link_backfill import _validate_records

from .liveart_artist import liveart_artist_search_name


# Complete source credits audited against Forum's November 4, 2026 catalogue.
# Keep qualifiers on the lot; only the offline bookmark lookup uses these names.
# In particular, Jacques Villon is the printmaker in these explicit After credits,
# and a collaborative credit must not silently resolve to just one contributor.
_FORUM_CREDIT_ALIASES = {
    normalize_artist_name(credit): artist
    for credit, artist in (
        ("Lucio Fontana after.", "Lucio Fontana"),
        ("Roy Lichtenstein after.", "Roy Lichtenstein"),
        ("Marc Chagall after.", "Marc Chagall"),
        ("Gaston Bernheim de Villers after. Jacques Villon", "Gaston Bernheim de Villers"),
        ("Marcel Duchamp after. Jacques Villon", "Marcel Duchamp"),
        ("Marcel Gromaire after. Jacques Villon", "Marcel Gromaire"),
        ("Marie Laurencin after. Jacques Villon", "Marie Laurencin"),
        ("Joan Miró after.", "Joan Miró"),
        ("Pablo Picasso after.", "Pablo Picasso"),
        ("Pablo Picasso after. Jacques Villon", "Pablo Picasso"),
        ("Pierre-Auguste Renoir after. Jacques Villon", "Pierre-Auguste Renoir"),
        ("Rembrandt Harmensz. van Rijn", "Rembrandt van Rijn"),
    )
}


def _signature(path: Path) -> tuple[str, int, int]:
    try:
        stat = path.stat()
        return str(path), stat.st_mtime_ns, stat.st_size
    except OSError:
        return str(path), 0, 0


def _read_text(signature: tuple[str, int, int]) -> str:
    try:
        return Path(signature[0]).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def _invaluable_name(url: str) -> str:
    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in {"invaluable.com", "www.invaluable.com"}
            or parsed.username or parsed.password or parsed.port not in {None, 443}
            or parsed.path.rstrip("/") != "/search"
        ):
            return ""
        return repeatedly_decode(parse_qs(parsed.query).get("artistName", [""])[0])
    except ValueError:
        return ""


def _liveart_artist(value: str) -> tuple[str, str] | None:
    if (
        not value or value != value.strip() or len(value) > 2000
        or "\\" in value or any(character.isspace() or ord(character) < 32 for character in value)
    ):
        return None
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https" or parsed.hostname != "www.liveart.ai"
            or parsed.username is not None or parsed.password is not None
            or parsed.port not in {None, 443} or parsed.query or parsed.fragment
        ):
            return None
    except ValueError:
        return None
    match = re.fullmatch(r"/artists/([A-Za-z0-9]+)/([A-Za-z0-9][A-Za-z0-9-]*)/?", parsed.path)
    if match is None:
        return None
    return match.group(1), match.group(2).replace("-", " ")


def _without_initials(words):
    """Each form with exactly one single-letter word omitted."""
    return (words - {word} for word in words if len(word) == 1)


def _alias_index(records, *, liveart=False):
    index = defaultdict(list)
    for position, (provider_or_id, url, aliases) in enumerate(records):
        keys = set()
        for alias in aliases:
            if liveart:
                alias = liveart_artist_search_name(alias)
            name = artist_identity_key(alias)
            if not name:
                continue
            keys.add(name)
            surname = alias.split(",", 1)[0] if "," in alias else alias.split()[-1]
            surname = normalize_artist_name(surname)
            if len(surname.split()) == 1:
                keys.add(surname)
            # LiveArt full names require exact or explicitly verified aliases.
            # Other providers also allow one missing middle initial in either direction.
            if not liveart and len(name.split()) >= 2:
                words = frozenset(name.split())
                keys.add(("full", words))
                keys.update(("shortened", shorter) for shorter in _without_initials(words))
        for key in keys:
            index[key].append((position, provider_or_id, url))
    return index


@lru_cache(maxsize=8)
def _liveart_registry(bookmarks_signature):
    records = []
    for bookmark in parse_netscape_bookmarks(_read_text(bookmarks_signature)):
        if not any(folder.casefold() == "liveart" for folder in bookmark.folder_path):
            continue
        parsed = _liveart_artist(bookmark.url)
        if parsed is None:
            continue
        title = re.sub(r"\s*[-\u2013\u2014]\s*LiveArt\s*$", "", bookmark.title, flags=re.IGNORECASE)
        records.append((parsed[0], bookmark.url, (title, parsed[1])))
    return _alias_index(records, liveart=True)


@lru_cache(maxsize=8)
def _registry(bookmarks_signature, generated_signature):
    html = _read_text(bookmarks_signature)
    records = []
    for bookmark in extract_artprice_bookmarks(html):
        records.append(("artprice", bookmark.url, (
            bookmark.title.split(":", 1)[0], bookmark.slug_name,
        )))
    for bookmark in parse_netscape_bookmarks(html):
        if not any(folder.casefold() == "artists invaluable" for folder in bookmark.folder_path):
            continue
        name = _invaluable_name(bookmark.url)
        if name:
            records.append(("invaluable", bookmark.url, (name, bookmark.title.split(":", 1)[0])))

    # Generated links are secondary to curated bookmarks. They never trigger a
    # network request here; discovery is an explicit management command.
    try:
        generated = json.loads(_read_text(generated_signature))
    except (ValueError, TypeError):
        generated = {}
    if isinstance(generated, dict) and generated.get("version") == 1:
        rows = generated.get("artists", [])
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict) or not isinstance(row.get("name"), str):
                continue
            url = row.get("url", "")
            if not isinstance(url, str):
                continue
            try:
                _validate_records([row])
            except ValueError:
                continue
            parsed = _valid_artprice_artist_url(url)
            records.append(("generated_artprice", url, (row["name"], parsed[1])))
    return _alias_index(records)


@lru_cache(maxsize=4096)
def _lookup(name, bookmarks_signature, generated_signature):
    name = _FORUM_CREDIT_ALIASES.get(normalize_artist_name(name), name)
    key = artist_identity_key(name)
    words = key.split()
    index = _registry(bookmarks_signature, generated_signature)
    candidates = set(index.get(key, ()))
    if len(words) >= 2:
        word_set = frozenset(words)
        candidates.update(index.get(("shortened", word_set), ()))
        for shorter in _without_initials(word_set):
            candidates.update(index.get(("full", shorter), ()))

    matches = {"artprice": {}, "invaluable": {}, "generated_artprice": {}}
    # A bookmark can match through several aliases. Keep its original position
    # so the first URL for each provider identity retains precedence.
    for _, provider, url in sorted(candidates):
        identity = _valid_artprice_artist_url(url)[0] if "artprice" in provider else artist_identity_key(_invaluable_name(url))
        matches[provider].setdefault(identity, url)
    if len(words) == 1:
        # A surname must identify one artist across both sources, even when
        # one candidate was curated and the other was discovered later.
        artprice = {**matches["generated_artprice"], **matches["artprice"]}
    else:
        artprice = matches["artprice"] or matches["generated_artprice"]
    invaluable = matches["invaluable"]
    return (
        next(iter(artprice.values())) if len(artprice) == 1 else "",
        next(iter(invaluable.values())) if len(invaluable) == 1 else "",
    )


def artist_research_urls(name: str) -> tuple[str, str]:
    """Return Artprice and Invaluable bookmarks without changing any lot data."""
    docs = Path(settings.BASE_DIR) / "docs"
    return _lookup(
        str(name or "").strip(),
        _signature(docs / "artist-links.html"),
        _signature(docs / "artprice-artist-links.json"),
    )


@lru_cache(maxsize=4096)
def _liveart_lookup(name, bookmarks_signature):
    matches = {}
    name = liveart_artist_search_name(name)
    key = artist_identity_key(name)
    if not key:
        return ""
    for _, identity, url in _liveart_registry(bookmarks_signature).get(key, ()):
        matches.setdefault(identity, url)
    return next(iter(matches.values())) if len(matches) == 1 else ""


def artist_liveart_url(name: str) -> str:
    """Return one unambiguous saved LiveArt artist URL without a provider lookup."""
    return _liveart_lookup(
        str(name or "").strip(),
        _signature(Path(settings.BASE_DIR) / "docs" / "artist-links.html"),
    )
