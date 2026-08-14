"""Local, privacy-preserving browser bookmark import for artist watchlists."""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
import re
from typing import Iterable, Sequence
from urllib.parse import parse_qsl, urlencode, unquote_plus, urlsplit, urlunsplit


DEFAULT_ALLOWED_DOMAINS = (
    "invaluable.com",
    "liveauctioneers.com",
    "drouot.com",
)
_TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "referrer",
}
_ARTIST_QUERY_KEYS = {
    "artist",
    "artistname",
    "keyword",
    "keywords",
    "q",
    "query",
    "querystring",
    "search",
    "searchterm",
}


@dataclass(frozen=True, slots=True)
class BookmarkEntry:
    folder_path: tuple[str, ...]
    title: str
    url: str
    add_date: str = ""
    artist: str = ""
    source: str = ""

    @property
    def folder(self) -> str:
        return self.folder_path[-1] if self.folder_path else "Unfiled"


class _NetscapeBookmarkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.entries: list[BookmarkEntry] = []
        self.folder_stack: list[str] = []
        self.pending_folder = ""
        self._capture: str | None = None
        self._text: list[str] = []
        self._anchor: dict[str, str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        name = tag.casefold()
        values = {key.casefold(): value or "" for key, value in attrs}
        if name == "h3":
            self._capture = "folder"
            self._text = []
        elif name == "a":
            self._capture = "anchor"
            self._text = []
            # ICON data is deliberately never retained.
            self._anchor = {
                "href": values.get("href", ""),
                "add_date": values.get("add_date", ""),
            }
        elif name == "dl" and self.pending_folder:
            self.folder_stack.append(self.pending_folder)
            self.pending_folder = ""

    def handle_endtag(self, tag: str) -> None:
        name = tag.casefold()
        if name == "h3" and self._capture == "folder":
            self.pending_folder = _clean_text("".join(self._text)) or "Unfiled"
            self._capture = None
            self._text = []
        elif name == "a" and self._capture == "anchor":
            values = self._anchor or {}
            href = values.get("href", "").strip()
            if href:
                self.entries.append(
                    BookmarkEntry(
                        folder_path=tuple(self.folder_stack),
                        title=_clean_text("".join(self._text)),
                        url=href,
                        add_date=values.get("add_date", ""),
                    )
                )
            self._anchor = None
            self._capture = None
            self._text = []
        elif name == "dl" and self.folder_stack:
            self.folder_stack.pop()

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._text.append(data)


def parse_netscape_bookmarks(html: str) -> list[BookmarkEntry]:
    """Parse a Netscape bookmark export without applying source-domain filters."""

    parser = _NetscapeBookmarkParser()
    parser.feed(html or "")
    parser.close()
    return parser.entries


def _clean_text(value: str) -> str:
    return " ".join((value or "").replace("\xa0", " ").split()).strip()


def repeatedly_decode(value: str, max_rounds: int = 6) -> str:
    """Decode nested URL encoding without allowing an unbounded decode loop."""

    current = value or ""
    for _ in range(max_rounds):
        decoded = unquote_plus(current)
        if decoded == current:
            break
        current = decoded
    return _clean_text(current)


def _allowed_host(hostname: str, allowed_domains: Sequence[str]) -> bool:
    host = (hostname or "").casefold().rstrip(".")
    return any(host == domain.casefold() or host.endswith(f".{domain.casefold()}") for domain in allowed_domains)


def source_for_url(url: str) -> str:
    host = (urlsplit(url).hostname or "").casefold()
    if host == "invaluable.com" or host.endswith(".invaluable.com"):
        return "Invaluable"
    if host == "liveauctioneers.com" or host.endswith(".liveauctioneers.com"):
        return "LiveAuctioneers"
    if host == "drouot.com" or host.endswith(".drouot.com"):
        return "Drouot"
    return ""


def canonicalize_bookmark_url(url: str) -> str:
    parts = urlsplit((url or "").strip())
    if parts.scheme.casefold() not in {"http", "https"} or not parts.hostname:
        return ""
    scheme = parts.scheme.casefold()
    host = parts.hostname.casefold().rstrip(".")
    try:
        port = parts.port
    except ValueError:
        return ""
    netloc = host if port is None or (scheme == "https" and port == 443) or (scheme == "http" and port == 80) else f"{host}:{port}"
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query_items: list[tuple[str, str]] = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key.casefold().startswith("utm_") or key.casefold() in _TRACKING_QUERY_KEYS:
            continue
        query_items.append((key, repeatedly_decode(value)))
    query_items.sort(key=lambda item: (item[0].casefold(), item[1].casefold()))
    return urlunsplit((scheme, netloc, path, urlencode(query_items, doseq=True), ""))


def normalize_artist_label(value: str) -> str:
    label = repeatedly_decode(value)
    label = re.sub(r"\s+", " ", label).strip(" -|–—:_")
    label = re.split(
        r"(?i)\s*(?:\||—|–| - )\s*(?:invaluable|liveauctioneers|drouot).*$",
        label,
        maxsplit=1,
    )[0]
    label = re.sub(
        r"(?i)\s+(?:artworks?|art|prints?|works?)\s+(?:for\s+sale\s+)?(?:at\s+)?auction.*$",
        "",
        label,
    )
    label = re.sub(r"(?i)^search(?:ing)?\s+(?:for\s+)?", "", label)
    return _clean_text(label).strip(" -|–—:_")


def artist_from_bookmark(title: str, url: str) -> str:
    query = parse_qsl(urlsplit(url).query, keep_blank_values=False)
    for key, value in query:
        if key.casefold() in _ARTIST_QUERY_KEYS:
            candidate = normalize_artist_label(value)
            if candidate:
                return candidate
    path = repeatedly_decode(urlsplit(url).path)
    match = re.search(r"(?i)/(?:artist|artists)/([^/]+)", path)
    if match:
        candidate = normalize_artist_label(match.group(1).replace("-", " "))
        candidate = re.sub(r"\s+\d+$", "", candidate).strip()
        if candidate:
            return candidate
    return normalize_artist_label(title)


def _folder_selected(path: tuple[str, ...], selected_folders: set[str] | None) -> bool:
    if selected_folders is None:
        return True
    folded = {item.casefold() for item in selected_folders}
    full_path = "/".join(path).casefold()
    return full_path in folded or any(part.casefold() in folded for part in path)


def parse_bookmarks_html(
    html: str,
    *,
    selected_folders: Iterable[str] | None = None,
    allowed_domains: Sequence[str] = DEFAULT_ALLOWED_DOMAINS,
) -> list[BookmarkEntry]:
    selected = set(selected_folders) if selected_folders is not None else None
    entries: list[BookmarkEntry] = []
    seen: set[str] = set()
    for raw in parse_netscape_bookmarks(html):
        if not _folder_selected(raw.folder_path, selected):
            continue
        canonical = canonicalize_bookmark_url(raw.url)
        if not canonical:
            continue
        parts = urlsplit(canonical)
        if not _allowed_host(parts.hostname or "", allowed_domains) or canonical in seen:
            continue
        seen.add(canonical)
        entries.append(
            BookmarkEntry(
                folder_path=raw.folder_path,
                title=raw.title,
                url=canonical,
                add_date=raw.add_date,
                artist=artist_from_bookmark(raw.title, canonical),
                source=source_for_url(canonical),
            )
        )
    return entries


def load_bookmarks_file(
    path: str | Path,
    *,
    selected_folders: Iterable[str] | None = None,
    allowed_domains: Sequence[str] = DEFAULT_ALLOWED_DOMAINS,
) -> list[BookmarkEntry]:
    # Only local parsing occurs here. Callers must never forward this text to OpenAI.
    html = Path(path).read_text(encoding="utf-8", errors="replace")
    return parse_bookmarks_html(html, selected_folders=selected_folders, allowed_domains=allowed_domains)


def folder_counts(entries: Iterable[BookmarkEntry]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in entries:
        name = entry.folder
        counts[name] = counts.get(name, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: item[0].casefold()))


def artist_source_counts(entries: Iterable[BookmarkEntry]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for entry in entries:
        artist_counts = counts.setdefault(entry.artist or entry.title or "Unknown artist", {})
        artist_counts[entry.source or "Unsupported"] = artist_counts.get(entry.source or "Unsupported", 0) + 1
    return dict(sorted(counts.items(), key=lambda item: item[0].casefold()))
