"""Keep the curated watchlist usable when its original bookmark export moves."""

from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path
import tempfile
from typing import Iterable, Mapping
from urllib.parse import urlsplit

from catalogapp.artprice_artist_links import _valid_artprice_artist_url
from catalogapp.bookmark_watchlist import BookmarkEntry, canonicalize_bookmark_url, source_for_url


def _entry(value: object) -> BookmarkEntry | None:
    if not isinstance(value, dict):
        return None
    raw_url = value.get("url")
    if not isinstance(raw_url, str) or len(raw_url) > 8000 or "\\" in raw_url:
        return None
    try:
        parsed = urlsplit(raw_url)
        if (parsed.scheme not in {"http", "https"} or parsed.username or parsed.password
                or parsed.port not in {None, 80, 443}
                or any(ord(character) < 32 for character in raw_url)):
            return None
        url = canonicalize_bookmark_url(raw_url)
        source = source_for_url(url)
    except ValueError:
        return None
    if not source:
        return None
    folders = value.get("folder_path", [])
    if (not isinstance(folders, (list, tuple)) or len(folders) > 30
            or any(not isinstance(folder, str) or len(folder) > 512 for folder in folders)):
        return None
    fields = {}
    for name in ("title", "artist", "add_date"):
        text = value.get(name, "")
        if not isinstance(text, str) or len(text) > 2000:
            return None
        fields[name] = text
    return BookmarkEntry(folder_path=tuple(folders), url=url, source=source, **fields)


def _normalize(entries: Iterable[object], links: object) -> tuple[list[BookmarkEntry], dict[str, str]]:
    accepted = {}
    for value in entries:
        entry = _entry(asdict(value) if isinstance(value, BookmarkEntry) else value)
        if entry is not None:
            accepted.setdefault(entry.url, entry)
    artists = {entry.artist for entry in accepted.values() if entry.artist}
    valid_links = {}
    if isinstance(links, dict):
        for name, url in links.items():
            if (name in artists and isinstance(url, str) and not any(ord(c) < 32 for c in url)
                    and _valid_artprice_artist_url(url)):
                valid_links[name] = url.strip()
    return list(accepted.values()), valid_links


def load_watchlist(path: str | Path) -> tuple[list[BookmarkEntry], dict[str, str]]:
    """Return validated entries and public artist links, or an empty registry."""
    try:
        source = Path(path)
        if source.stat().st_size > 8_000_000:
            return [], {}
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], {}
    if not isinstance(payload, dict) or payload.get("version") != 1:
        return [], {}
    entries = payload.get("entries")
    if not isinstance(entries, list) or len(entries) > 10000:
        return [], {}
    return _normalize(entries, payload.get("artist_artprice_links"))


def save_watchlist(
    path: str | Path, entries: Iterable[BookmarkEntry], artist_artprice_links: Mapping[str, str],
) -> None:
    """Atomically save normalized entries, never original HTML or browser state."""
    entries, links = _normalize(entries, dict(artist_artprice_links))
    if len(entries) > 10000:
        raise ValueError("The saved watchlist exceeds 10,000 entries.")
    payload = json.dumps({
        "version": 1, "entries": [asdict(entry) for entry in entries], "artist_artprice_links": links,
    }, ensure_ascii=False, indent=2)
    if len(payload.encode("utf-8")) > 8_000_000:
        raise ValueError("The saved watchlist is too large.")
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=destination.parent,
                                         prefix="watchlist-", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
