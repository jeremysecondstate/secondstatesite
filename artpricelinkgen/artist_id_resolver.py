from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import parse_qs, quote_plus, unquote, urlparse
from urllib.request import Request, urlopen


@dataclass
class ArtistIdCandidate:
    artist: str
    artist_id: str
    url: str
    source: str
    confidence: str
    score: float

    @property
    def is_high_confidence(self) -> bool:
        return self.confidence == "high"


class ArtpriceArtistIdResolver:
    """Resolve missing Artprice artist IDs from search-result URLs.

    The resolver only auto-accepts candidates that look like real Artprice artist
    pages and whose URL slug strongly matches the cleaned artist name.
    """

    ARTPRICE_ARTIST_URL_RE = re.compile(
        r"https?://(?:www\.)?artprice\.com/artist/(\d+)/([A-Za-z0-9\-]+)",
        flags=re.I,
    )

    def __init__(self, timeout_seconds: int = 8):
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def clean_artist_name(value: str) -> str:
        value = unicodedata.normalize("NFKD", str(value or ""))
        value = "".join(ch for ch in value if not unicodedata.combining(ch))
        value = value.lower().replace("&", " and ")
        value = re.sub(
            r"\b(?:after|attributed to|attr\.?|school of|manner of|circle of|follower of)\b",
            "",
            value,
            flags=re.I,
        )
        value = re.sub(r"[^a-z0-9]+", " ", value)
        return re.sub(r"\s+", " ", value).strip()

    @classmethod
    def tokens_for_name(cls, value: str) -> set[str]:
        stopwords = {"the", "of", "de", "da", "di", "la", "le", "van", "von", "der", "den", "du"}
        return {token for token in cls.clean_artist_name(value).split() if token and token not in stopwords}

    @classmethod
    def tokens_for_slug(cls, slug: str) -> set[str]:
        return cls.tokens_for_name(slug.replace("-", " "))

    @staticmethod
    def build_search_url(artist_name: str) -> str:
        query = quote_plus(f"{artist_name} artprice")
        return f"https://duckduckgo.com/html/?q={query}"

    def resolve(self, artist_name: str) -> ArtistIdCandidate | None:
        urls = self.search_candidate_urls(artist_name)
        candidates = self.candidates_from_urls(artist_name, urls)
        high_confidence = [candidate for candidate in candidates if candidate.is_high_confidence]
        if high_confidence:
            return sorted(high_confidence, key=lambda c: c.score, reverse=True)[0]
        return None

    def search_candidate_urls(self, artist_name: str) -> list[str]:
        search_url = self.build_search_url(artist_name)
        request = Request(
            search_url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; ArtpriceLinkGenerator/1.0)",
            },
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            body = response.read().decode("utf-8", errors="ignore")
        return self.extract_urls_from_search_html(body)

    @classmethod
    def extract_urls_from_search_html(cls, body: str) -> list[str]:
        body = html.unescape(body or "")
        urls: list[str] = []

        # DuckDuckGo result links often wrap the destination as a uddg query param.
        for raw_href in re.findall(r'href=["\']([^"\']+)["\']', body, flags=re.I):
            href = html.unescape(raw_href)
            parsed = urlparse(href)
            query = parse_qs(parsed.query)
            if "uddg" in query and query["uddg"]:
                href = unquote(query["uddg"][0])
            urls.append(href)

        # Also catch direct Artprice URLs that appear as text in the page.
        urls.extend(match.group(0) for match in cls.ARTPRICE_ARTIST_URL_RE.finditer(body))

        deduped = []
        seen = set()
        for url in urls:
            if url not in seen:
                deduped.append(url)
                seen.add(url)
        return deduped

    @classmethod
    def candidates_from_urls(cls, artist_name: str, urls: list[str]) -> list[ArtistIdCandidate]:
        candidates = []
        for url in urls:
            candidate = cls.candidate_from_url(artist_name, url)
            if candidate:
                candidates.append(candidate)
        return candidates

    @classmethod
    def candidate_from_url(cls, artist_name: str, url: str) -> ArtistIdCandidate | None:
        match = cls.ARTPRICE_ARTIST_URL_RE.search(url)
        if not match:
            return None

        artist_id, slug = match.group(1), match.group(2)
        artist_tokens = cls.tokens_for_name(artist_name)
        slug_tokens = cls.tokens_for_slug(slug)
        if not artist_tokens or not slug_tokens:
            return None

        overlap = artist_tokens & slug_tokens
        score = len(overlap) / max(len(artist_tokens), 1)

        confidence = "low"
        if score >= 0.80 or artist_tokens.issubset(slug_tokens):
            confidence = "high"
        elif score >= 0.50:
            confidence = "medium"

        return ArtistIdCandidate(
            artist=artist_name,
            artist_id=artist_id,
            url=match.group(0),
            source="duckduckgo",
            confidence=confidence,
            score=score,
        )
