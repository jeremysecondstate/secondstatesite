"""Read public artist bookmarks from an export or a local Chrome/Edge profile.

Browser files are opened read-only on every call. Only public auction bookmarks
and Artprice artist links leave this module; profile discovery reads labels, not
account, history, cookie, or session stores.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
import json
import os
from pathlib import Path
import re
from typing import Iterable
from urllib.parse import urlsplit

from catalogapp.artprice_artist_links import ArtpriceMatchResult, parse_artprice_artist_links
from catalogapp.bookmark_watchlist import (
    BookmarkEntry,
    DEFAULT_ALLOWED_DOMAINS,
    parse_bookmarks_html,
    parse_netscape_bookmarks,
)


_MAX_BYTES = 32 * 1024 * 1024
_MAX_NODES = 100_000
_MAX_DEPTH = 64
_PROFILE_DIRECTORY = re.compile(r"(?:Default|Profile [0-9]+)\Z")
_BROWSER_DIRECTORIES = (("Chrome", ("Google", "Chrome", "User Data")), ("Edge", ("Microsoft", "Edge", "User Data")))
_BOOKMARK_FILES = ("Bookmarks", "AccountBookmarks")


@dataclass(frozen=True, slots=True)
class BookmarkSource:
    path: Path
    browser: str
    profile_name: str
    profile_directory: str
    is_last_used: bool = False

    @property
    def label(self) -> str:
        return f"{self.browser} — {self.profile_name} ({self.profile_directory})"


def _clean_label(value: object, default: str = "") -> str:
    if not isinstance(value, str):
        return default
    label = " ".join(value.split())
    return "".join(character for character in label if ord(character) >= 32 and ord(character) != 127)[:4096] or default


def _public_bookmark_url(value: object) -> bool:
    if not isinstance(value, str) or len(value) > 8192:
        return False
    if "\\" in value or any(ord(character) < 32 or ord(character) == 127 for character in value):
        return False
    try:
        parts = urlsplit(value.strip())
        host = (parts.hostname or "").casefold().rstrip(".")
        if (
            parts.scheme.casefold() not in {"http", "https"}
            or parts.username is not None
            or parts.password is not None
            or parts.port not in ({None, 443} if parts.scheme.casefold() == "https" else {None, 80})
        ):
            return False
    except ValueError:
        return False
    return any(host == domain or host.endswith(f".{domain}") for domain in DEFAULT_ALLOWED_DOMAINS) or host in {"artprice.com", "www.artprice.com"}


def _browser_entries(payload: object) -> list[BookmarkEntry]:
    if not isinstance(payload, dict) or not isinstance(payload.get("roots"), dict):
        raise ValueError("Choose a Chrome or Edge Bookmarks file, or a bookmarks HTML export.")
    roots = payload["roots"]
    # Chromium can keep an empty account store alongside local bookmarks.
    if not roots and payload.get("version") == 1:
        return []
    folders = [node for node in roots.values() if isinstance(node, dict) and isinstance(node.get("children"), list)]
    if not folders:
        raise ValueError("The browser Bookmarks file does not contain readable bookmark folders.")
    pending = [(node, (), 0) for node in reversed(folders)]
    entries: list[BookmarkEntry] = []
    visited = 0
    while pending:
        node, folder_path, depth = pending.pop()
        visited += 1
        if visited > _MAX_NODES or depth > _MAX_DEPTH:
            raise ValueError("The bookmarks file is too large or too deeply nested to read safely.")
        if not isinstance(node, dict):
            continue
        if node.get("type") == "folder" or ("children" in node and "url" not in node):
            children = node.get("children")
            if not isinstance(children, list):
                raise ValueError("The browser Bookmarks file contains an unreadable folder. Try again after the browser saves it.")
            name = _clean_label(node.get("name"), "Unfiled")
            pending.extend((child, (*folder_path, name), depth + 1) for child in reversed(children))
        elif node.get("type") == "url" and _public_bookmark_url(node.get("url")):
            entries.append(BookmarkEntry(
                folder_path=folder_path,
                title=_clean_label(node.get("name")),
                url=node["url"].strip(),
            ))
    return entries


def _public_html(entries: Iterable[BookmarkEntry]) -> str:
    """Feed both existing parsers the same folder/title/URL representation."""

    parts = ["<!DOCTYPE NETSCAPE-Bookmark-file-1><DL>"]
    for entry in entries:
        if not _public_bookmark_url(entry.url):
            continue
        for folder in entry.folder_path:
            parts.append(f"<DT><H3>{escape(folder)}</H3><DL>")
        parts.append(f'<DT><A HREF="{escape(entry.url, quote=True)}" ADD_DATE="{escape(entry.add_date, quote=True)}">{escape(entry.title)}</A>')
        parts.extend("</DL>" for _folder in entry.folder_path)
    parts.append("</DL>")
    return "".join(parts)


def _profile_bookmark_paths(profile: Path, root: Path) -> tuple[Path, ...]:
    if not _PROFILE_DIRECTORY.fullmatch(profile.name) or not profile.is_dir() or profile.resolve().parent != root.resolve():
        return ()
    return tuple(
        candidate for name in _BOOKMARK_FILES
        if (candidate := profile / name).is_file() and candidate.resolve().parent == profile.resolve()
    )


def bookmark_source_paths(path: str | Path) -> tuple[Path, ...]:
    """Resolve a profile's plain local/account bookmark stores, or one export.

    Sibling discovery is limited to the exact Chrome/Edge profile directories
    beneath LOCALAPPDATA. An arbitrary uploaded/exported JSON file never causes
    another nearby file to be read. Encrypted and backup stores are not used.
    """

    selected = Path(path)
    local_directory = os.environ.get("LOCALAPPDATA")
    if local_directory and selected.name.casefold() in {name.casefold() for name in _BOOKMARK_FILES}:
        try:
            for _browser, relative in _BROWSER_DIRECTORIES:
                root = Path(local_directory).joinpath(*relative)
                if selected.parent.resolve().parent == root.resolve():
                    return _profile_bookmark_paths(selected.parent, root)
        except (OSError, ValueError, RuntimeError):
            return ()
    return (selected,) if selected.is_file() else ()


def _read_bookmark_entries(path: Path) -> list[BookmarkEntry]:
    with path.open("rb") as source:
        content = source.read(_MAX_BYTES + 1)
    if len(content) > _MAX_BYTES:
        raise ValueError("The bookmarks file is too large to read safely.")
    text = content.decode("utf-8-sig", errors="replace")
    if text.lstrip().startswith(("{", "[")):
        try:
            payload = json.loads(text)
        except (ValueError, RecursionError) as exc:
            raise ValueError("The browser Bookmarks file is being saved or is unreadable. Try Update Calendar again.") from exc
        return _browser_entries(payload)
    if not re.search(r"(?i)NETSCAPE-Bookmark-file|<\s*(?:dl|a)\b", text):
        raise ValueError("Choose a Chrome or Edge Bookmarks file, or a bookmarks HTML export.")
    return parse_netscape_bookmarks(text)


def load_bookmark_source(
    path: str | Path,
    *,
    artist_names: Iterable[str] | None = None,
) -> tuple[list[BookmarkEntry], ArtpriceMatchResult]:
    """Reread one local export or browser file using established artist matching.

    A selected Chrome/Edge profile includes both its plain local and account
    bookmark stores. JSON files retain their nested folders, so ``ARTPRICE`` matching
    has the same scope as an HTML export. ``artist_names`` optionally adds saved
    artists to those found in this source, so both retained and newly bookmarked
    artists can receive research links when browser additions are merged.
    Malformed or unavailable files raise rather than replacing a saved watchlist.
    """

    paths = bookmark_source_paths(path) or (Path(path),)
    raw_entries = [entry for source_path in paths for entry in _read_bookmark_entries(source_path)]
    html = _public_html(raw_entries)
    entries = parse_bookmarks_html(html)
    names = [entry.artist for entry in entries if entry.artist]
    if artist_names is not None:
        names.extend(artist_names)
    return entries, parse_artprice_artist_links(html, names)


def discover_bookmark_sources() -> list[BookmarkSource]:
    """Discover existing Chrome/Edge bookmark files from safe profile metadata."""

    local_directory = os.environ.get("LOCALAPPDATA")
    if not local_directory:
        return []
    sources: list[BookmarkSource] = []
    for browser, relative in _BROWSER_DIRECTORIES:
        user_data = Path(local_directory).joinpath(*relative)
        try:
            root = user_data.resolve()
            metadata_path = user_data / "Local State"
            information, last_used = {}, ""
            if metadata_path.is_file():
                try:
                    with metadata_path.open("rb") as source:
                        content = source.read(_MAX_BYTES + 1)
                    metadata = json.loads(content.decode("utf-8-sig")) if len(content) <= _MAX_BYTES else {}
                    profile = metadata.get("profile", {}) if isinstance(metadata, dict) else {}
                    information = profile.get("info_cache", {}) if isinstance(profile, dict) else {}
                    last_used = profile.get("last_used", "") if isinstance(profile, dict) else ""
                except (OSError, ValueError, RecursionError):
                    # Profile labels can be saved separately from Bookmarks.
                    # Existing safe profile directories remain selectable.
                    pass
            if not isinstance(information, dict):
                information = {}
            directories = {path.name for path in user_data.iterdir() if _PROFILE_DIRECTORY.fullmatch(path.name)}
            for directory in directories:
                candidate = user_data / directory
                paths = _profile_bookmark_paths(candidate, root)
                if not paths:
                    continue
                details = information.get(directory, {})
                name = _clean_label(details.get("name") if isinstance(details, dict) else None, directory)[:120]
                sources.append(BookmarkSource(paths[0], browser, name, directory, directory == last_used))
        except (OSError, ValueError, RuntimeError, RecursionError):
            continue
    return sorted(sources, key=lambda source: (not source.is_last_used, source.browser, source.profile_name.casefold(), source.profile_directory))
