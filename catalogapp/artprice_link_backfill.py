"""Persist public, conservatively matched Artprice artist URL evidence."""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Iterable

from artpricelinkgen.artist_id_resolver import ArtistIdCandidate, ArtpriceArtistIdResolver
from catalogapp.artprice_artist_links import (
    _valid_artprice_artist_url,
    artist_identity_key,
    extract_artprice_bookmarks,
    match_artprice_bookmarks,
)


def resolution_record(artist: str, candidate: ArtistIdCandidate) -> dict[str, str]:
    """Build a print-history link only from the observed, matched artist URL."""
    checked = ArtpriceArtistIdResolver.candidate_from_url(artist, candidate.url)
    if (not candidate.is_high_confidence or checked is None or not checked.is_high_confidence
            or candidate.artist_id != checked.artist_id):
        raise ValueError(f"No unambiguous Artprice artist URL evidence for {artist}.")
    return {
        "name": artist,
        "url": checked.url + "/lots/pasts?idcategory=2&p=1&sort=datesale_desc",
        "source_url": checked.url,
        "source": candidate.source,
        "resolved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def load_resolution_records(path: str | Path) -> list[dict[str, str]]:
    """Read strictly before a write, so malformed existing data is never replaced."""
    source = Path(path)
    if not source.exists():
        return []
    if source.stat().st_size > 2_000_000:
        raise ValueError("The Artprice artist registry exceeds 2 MB.")
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("version") != 1 or not isinstance(payload.get("artists"), list):
        raise ValueError("Invalid Artprice artist registry; expected version 1 and an artists list.")
    records = payload["artists"]
    _validate_records(records)
    return records


def _validate_records(records: Iterable[dict[str, str]]) -> None:
    seen: dict[str, str] = {}
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("Artprice artist registry records must be objects.")
        name = record.get("name")
        if not isinstance(name, str) or not name.strip() or len(name) > 255:
            raise ValueError("Invalid artist name in Artprice artist registry.")
        url = record.get("url")
        source = record.get("source_url")
        parsed = _valid_artprice_artist_url(url) if isinstance(url, str) else None
        source_parsed = _valid_artprice_artist_url(source) if isinstance(source, str) else None
        if not parsed or not source_parsed or parsed[0] != source_parsed[0]:
            raise ValueError(f"Invalid or conflicting Artprice URL evidence for {name}.")
        candidate = ArtpriceArtistIdResolver.candidate_from_url(name, url)
        source_candidate = ArtpriceArtistIdResolver.candidate_from_url(name, source)
        if (not candidate or not source_candidate or not candidate.is_high_confidence
                or not source_candidate.is_high_confidence or candidate.url != source_candidate.url):
            raise ValueError(f"Artprice URL evidence does not match the complete artist name for {name}.")
        key = artist_identity_key(name)
        if key in seen and seen[key] != parsed[0]:
            raise ValueError(f"Conflicting Artprice IDs for {name}.")
        seen[key] = parsed[0]


def atomic_write_text(path: str | Path, text: str) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="",
                                         dir=destination.parent, prefix="artprice-", suffix=".tmp",
                                         delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(text)
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def save_resolution_records(path: str | Path, additions: Iterable[dict[str, str]]) -> int:
    records = load_resolution_records(path)
    additions = list(additions)
    _validate_records([*records, *additions])
    seen = {artist_identity_key(record["name"]) for record in records}
    added = 0
    for record in additions:
        key = artist_identity_key(record["name"])
        if key not in seen:
            records.append(record)
            seen.add(key)
            added += 1
    if added:
        records.sort(key=lambda record: record["name"].casefold())
        atomic_write_text(path, json.dumps({"version": 1, "artists": records}, ensure_ascii=False, indent=2) + "\n")
    return added


def add_resolution_bookmarks(html: str, records: Iterable[dict[str, str]]) -> tuple[str, int]:
    """Insert only new Artprice bookmarks without rewriting the user's export."""
    records = list(records)
    _validate_records(records)
    known = match_artprice_bookmarks(extract_artprice_bookmarks(html), [record["name"] for record in records])
    additions = {artist_identity_key(record["name"]): record for record in records
                 if record["name"] not in known.links_by_artist}
    if not additions:
        return html, 0
    folder = re.search(r"<H3\b[^>]*>\s*ARTPRICE\s*</H3>\s*<DL\b[^>]*>(?:<p>)?", html, re.I)
    if folder is None:
        raise ValueError("The bookmarks file must contain an ARTPRICE folder.")
    depth = 1
    close_at = None
    for tag in re.finditer(r"</?DL\b[^>]*>", html[folder.end():], re.I):
        depth += -1 if tag.group().startswith("</") else 1
        if depth == 0:
            close_at = folder.end() + tag.start()
            break
    if close_at is None:
        raise ValueError("The bookmarks ARTPRICE folder is not closed.")
    line_start = html.rfind("\n", 0, close_at) + 1
    indentation = html[line_start:close_at]
    if indentation.strip():
        indentation = ""
        line_start = close_at
    newline = "\r\n" if "\r\n" in html else "\n"
    lines = [
        f'{indentation}    <DT><A HREF="{escape(record["url"], quote=True)}">'
        f'{escape(record["name"])}: Artprice — Prints, past lots</A>{newline}'
        for record in sorted(additions.values(), key=lambda record: record["name"].casefold())
    ]
    return html[:line_start] + "".join(lines) + html[line_start:], len(lines)
