"""Offline artist links shared by whole-sale and watchlist Calendar lots."""

from functools import lru_cache
import json
from pathlib import Path
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
    return tuple(records)


def _name_matches(name: str, alias: str) -> bool:
    key, alias_key = artist_identity_key(name), artist_identity_key(alias)
    if not key or not alias_key:
        return False
    if key == alias_key:
        return True
    # Catalogs sometimes omit a middle initial (Charles R. Sheeler).
    words, alias_words = key.split(), alias_key.split()
    if len(words) >= 2 and len(alias_words) >= 2:
        smaller, larger = sorted((set(words), set(alias_words)), key=len)
        extra = larger - smaller
        return smaller < larger and len(extra) == 1 and len(next(iter(extra))) == 1
    # A supplied surname is usable only if it identifies one artist in the
    # entire registry; the caller rejects multiple distinct artist IDs.
    if len(words) == 1:
        surname = alias.split(",", 1)[0] if "," in alias else alias.split()[-1]
        return key == normalize_artist_name(surname)
    return False


@lru_cache(maxsize=4096)
def _lookup(name, bookmarks_signature, generated_signature):
    matches = {"artprice": {}, "invaluable": {}, "generated_artprice": {}}
    for provider, url, aliases in _registry(bookmarks_signature, generated_signature):
        if any(_name_matches(name, alias) for alias in aliases):
            identity = _valid_artprice_artist_url(url)[0] if "artprice" in provider else artist_identity_key(_invaluable_name(url))
            matches[provider].setdefault(identity, url)
    if len(artist_identity_key(name).split()) == 1:
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
