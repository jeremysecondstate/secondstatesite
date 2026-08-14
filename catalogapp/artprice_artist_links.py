"""Deterministic Artprice artist-link extraction and watchlist matching."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from html import unescape
from pathlib import Path
import re
from typing import Iterable
import unicodedata
from urllib.parse import unquote_plus, urlsplit

from catalogapp.bookmark_watchlist import parse_netscape_bookmarks


_ARTPRICE_FOLDER = "artprice"
_ARTIST_PATH = re.compile(r"^/artist/(?P<artist_id>\d+)/(?P<slug>[^/?#]+)(?:/|$)", re.IGNORECASE)
_YEAR_PARENTHETICAL = re.compile(
    r"\(\s*(?:c\.?\s*)?\d{4}(?:\s*[-\u2013\u2014]\s*(?:\d{0,4})?)?\s*\)",
    re.IGNORECASE,
)
_TITLE_ENDING = re.compile(
    r"\s+(?:estimate|worth|auction\s+prices?|value|buy\b|sell\b).*$",
    re.IGNORECASE,
)
_ARTPRICE_SUFFIX = re.compile(r"\s*[-\u2013\u2014]\s*artprice(?:\.com)?\s*$", re.IGNORECASE)
_SOLD_LOTS_BY = re.compile(r"\bsold\s+lots\s+by\s+(.+?)(?:\s*[-\u2013\u2014]\s*artprice(?:\.com)?\s*)?$", re.IGNORECASE)
_LEADING_AUCTIONS_FOR = re.compile(r"^auctions?\s+for\b.*?\bby\s+", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ArtpriceBookmark:
    title: str
    url: str
    artist_id: str
    slug_name: str


@dataclass(frozen=True, slots=True)
class ArtpriceMatchResult:
    links_by_artist: dict[str, str]
    unmatched_titles: tuple[str, ...]
    ambiguous_titles: tuple[str, ...]
    extracted_count: int

    @property
    def matched_artist_count(self) -> int:
        return len(self.links_by_artist)


def _decoded_text(value: str) -> str:
    current = str(value or "")
    for _ in range(4):
        decoded = unescape(current)
        if decoded == current:
            break
        current = decoded
    return " ".join(current.replace("\xa0", " ").split()).strip()


def normalize_artist_name(value: str) -> str:
    """Normalize an artist label while retaining its readable token order."""

    label = unicodedata.normalize("NFKC", _decoded_text(value))
    label = _YEAR_PARENTHETICAL.sub(" ", label)
    label = unicodedata.normalize("NFKD", label)
    label = "".join(character for character in label if not unicodedata.combining(character))
    label = label.casefold().replace("&", " and ")
    label = re.sub(r"[^\w]+", " ", label, flags=re.UNICODE)
    return " ".join(label.split())


def artist_identity_key(value: str) -> str:
    """Return a surname-first and punctuation-tolerant artist identity key."""

    normalized = normalize_artist_name(value)
    return " ".join(sorted(normalized.split()))


def _valid_artprice_artist_url(value: str) -> tuple[str, str] | None:
    candidate = str(value or "").strip()
    if not candidate or len(candidate) > 2000:
        return None
    try:
        parsed = urlsplit(candidate)
        host = (parsed.hostname or "").casefold().rstrip(".")
        port = parsed.port
    except ValueError:
        return None
    expected_ports = {None, 443} if parsed.scheme.casefold() == "https" else {None, 80}
    if (
        parsed.scheme.casefold() not in {"http", "https"}
        or host not in {"artprice.com", "www.artprice.com"}
        or parsed.username
        or parsed.password
        or port not in expected_ports
    ):
        return None
    match = _ARTIST_PATH.match(parsed.path or "")
    if not match:
        return None
    slug_name = " ".join(unquote_plus(match.group("slug")).replace("-", " ").split())
    if not normalize_artist_name(slug_name):
        return None
    return match.group("artist_id"), slug_name


def extract_artprice_bookmarks(html: str) -> list[ArtpriceBookmark]:
    """Extract valid artist URLs only from the folder headed ``ARTPRICE``."""

    extracted: list[ArtpriceBookmark] = []
    seen: set[tuple[str, str]] = set()
    for entry in parse_netscape_bookmarks(html):
        if not any(_decoded_text(part).casefold() == _ARTPRICE_FOLDER for part in entry.folder_path):
            continue
        parsed = _valid_artprice_artist_url(entry.url)
        if parsed is None:
            continue
        artist_id, slug_name = parsed
        signature = (entry.url.strip(), _decoded_text(entry.title))
        if signature in seen:
            continue
        seen.add(signature)
        extracted.append(
            ArtpriceBookmark(
                title=_decoded_text(entry.title),
                url=entry.url.strip(),
                artist_id=artist_id,
                slug_name=slug_name,
            )
        )
    return extracted


def _title_names(title: str) -> list[tuple[str, int]]:
    clean = _decoded_text(title)
    names: list[tuple[str, int]] = []
    sold_match = _SOLD_LOTS_BY.search(clean)
    if sold_match:
        names.append((sold_match.group(1), 125))

    prefix = clean.split(":", 1)[0]
    prefix = _ARTPRICE_SUFFIX.sub("", prefix)
    prefix = _YEAR_PARENTHETICAL.sub(" ", prefix)
    prefix = _TITLE_ENDING.sub("", prefix)
    prefix = _LEADING_AUCTIONS_FOR.sub("", prefix)
    if normalize_artist_name(prefix):
        names.append((prefix, 90 if ":" in clean else 105))

    unique: dict[str, tuple[str, int]] = {}
    for name, weight in names:
        key = normalize_artist_name(name)
        if key and (key not in unique or weight > unique[key][1]):
            unique[key] = (name, weight)
    return list(unique.values())


def _candidate_signals(bookmark: ArtpriceBookmark) -> list[tuple[str, int]]:
    signals = [(bookmark.slug_name, 120)]
    signals.extend(_title_names(bookmark.title))
    return signals


def _signal_score(signal: str, weight: int, artist_name: str) -> int:
    signal_normalized = normalize_artist_name(signal)
    artist_normalized = normalize_artist_name(artist_name)
    if not signal_normalized or not artist_normalized:
        return 0
    signal_tokens = set(signal_normalized.split())
    artist_tokens = set(artist_normalized.split())
    if artist_identity_key(signal) == artist_identity_key(artist_name):
        return weight + (8 if signal_normalized == artist_normalized else 0)

    smaller, larger = sorted((signal_tokens, artist_tokens), key=len)
    if len(smaller) >= 2 and smaller < larger and len(larger) - len(smaller) <= 3:
        return min(weight - 25, 94) + len(smaller)

    if len(smaller) == 1 and next(iter(smaller)) in larger:
        token = next(iter(smaller))
        signal_parts = signal_normalized.split()
        artist_parts = artist_normalized.split()
        if len(artist_parts) == 1 and token != signal_parts[-1]:
            return 0
        if len(signal_parts) == 1 and token != artist_parts[-1]:
            return 0
        return min(weight - 45, 72)

    similarity = SequenceMatcher(None, artist_identity_key(signal), artist_identity_key(artist_name)).ratio()
    if similarity >= 0.90:
        return min(weight - 35, 82)
    return 0


def _bookmark_preference(bookmark: ArtpriceBookmark, score: int) -> tuple[int, int, int, str]:
    parsed = urlsplit(bookmark.url)
    past_lots = int("/lots/pasts" in parsed.path.casefold())
    query_fields = len([part for part in parsed.query.split("&") if part])
    return score, past_lots, query_fields, bookmark.url


def match_artprice_bookmarks(
    bookmarks: Iterable[ArtpriceBookmark],
    artist_names: Iterable[str],
) -> ArtpriceMatchResult:
    """Match extracted bookmarks conservatively against existing watchlist artists."""

    names = sorted({_decoded_text(name) for name in artist_names if normalize_artist_name(name)}, key=str.casefold)
    bookmarks = list(bookmarks)
    candidates_by_artist: dict[str, list[tuple[ArtpriceBookmark, int]]] = {name: [] for name in names}
    unmatched: list[str] = []
    ambiguous: list[str] = []

    for bookmark in bookmarks:
        scores: dict[str, int] = {}
        for artist_name in names:
            scores[artist_name] = max(
                (_signal_score(signal, weight, artist_name) for signal, weight in _candidate_signals(bookmark)),
                default=0,
            )
        best_score = max(scores.values(), default=0)
        best_names = [name for name, score in scores.items() if score == best_score and score >= 70]
        if not best_names:
            unmatched.append(bookmark.title or bookmark.url)
            continue

        best_identities = {artist_identity_key(name) for name in best_names}
        if len(best_identities) != 1:
            ambiguous.append(bookmark.title or bookmark.url)
            continue
        best_token_sets = [set(normalize_artist_name(name).split()) for name in best_names]
        for artist_name, score in scores.items():
            if score < 70 or best_score - score > 65:
                continue
            artist_tokens = set(normalize_artist_name(artist_name).split())
            related_to_best = any(
                artist_tokens <= best_tokens or best_tokens <= artist_tokens
                for best_tokens in best_token_sets
            ) or any(
                SequenceMatcher(
                    None,
                    artist_identity_key(artist_name),
                    artist_identity_key(best_name),
                ).ratio()
                >= 0.90
                for best_name in best_names
            )
            if related_to_best:
                candidates_by_artist[artist_name].append((bookmark, score))

    links: dict[str, str] = {}
    for artist_name, candidates in candidates_by_artist.items():
        if not candidates:
            continue
        best_score = max(score for _bookmark, score in candidates)
        strongest = [(bookmark, score) for bookmark, score in candidates if score == best_score]
        artist_ids = {bookmark.artist_id for bookmark, _score in strongest}
        if len(artist_ids) != 1:
            ambiguous.extend(bookmark.title or bookmark.url for bookmark, _score in strongest)
            continue
        bookmark, _score = max(strongest, key=lambda item: _bookmark_preference(item[0], item[1]))
        links[artist_name] = bookmark.url

    return ArtpriceMatchResult(
        links_by_artist=dict(sorted(links.items(), key=lambda item: item[0].casefold())),
        unmatched_titles=tuple(dict.fromkeys(unmatched)),
        ambiguous_titles=tuple(dict.fromkeys(ambiguous)),
        extracted_count=len(bookmarks),
    )


def parse_artprice_artist_links(html: str, artist_names: Iterable[str]) -> ArtpriceMatchResult:
    return match_artprice_bookmarks(extract_artprice_bookmarks(html), artist_names)


def load_artprice_artist_links(path: str | Path, artist_names: Iterable[str]) -> ArtpriceMatchResult:
    html = Path(path).read_text(encoding="utf-8", errors="replace")
    return parse_artprice_artist_links(html, artist_names)
