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

    Search results provide public URL evidence, not direct page verification.
    Only unambiguous complete name matches are accepted automatically.
    """

    def __init__(self, timeout_seconds: int = 8):
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def clean_artist_name(value: str) -> str:
        value = unicodedata.normalize("NFKD", str(value or ""))
        value = "".join(ch for ch in value if not unicodedata.combining(ch))
        value = re.sub(r"\(\s*\d{4}(?:\s*[-–—]\s*\d{0,4})?\s*\)", " ", value)
        value = value.lower().replace("&", " and ")
        value = re.sub(r"[^a-z0-9]+", " ", value)
        return re.sub(r"\s+", " ", value).strip()

    @classmethod
    def tokens_for_name(cls, value: str) -> set[str]:
        return set(cls.clean_artist_name(value).split())

    @classmethod
    def tokens_for_slug(cls, slug: str) -> set[str]:
        return cls.tokens_for_name(slug.replace("-", " "))

    @staticmethod
    def build_search_url(artist_name: str) -> str:
        query = quote_plus(f"site:artprice.com/artist/ {artist_name}")
        return f"https://duckduckgo.com/html/?q={query}"

    def resolve(self, artist_name: str) -> ArtistIdCandidate | None:
        urls = self.search_candidate_urls(artist_name)
        return self.resolve_candidates(artist_name, urls)

    @classmethod
    def resolve_candidates(cls, artist_name: str, urls: list[str]) -> ArtistIdCandidate | None:
        """Apply the same identity checks to supplied public result URLs offline."""
        candidates = cls.candidates_from_urls(artist_name, urls)
        high_confidence = [candidate for candidate in candidates if candidate.is_high_confidence]
        if high_confidence and len({candidate.artist_id for candidate in high_confidence}) == 1:
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
            raw_body = response.read(2_000_001)
        if len(raw_body) > 2_000_000:
            raise ValueError("Artist search response exceeds the size limit.")
        body = raw_body.decode("utf-8", errors="ignore")
        if "anomaly.js" in body or "challenge-form" in body:
            raise ValueError("Artist search requires a browser challenge; no result was accepted.")
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
        url = str(url or "").strip()
        if len(url) > 2000 or "\\" in url or any(ord(character) < 32 for character in url):
            return None
        try:
            parsed = urlparse(url)
            if (parsed.scheme.lower() not in {"http", "https"}
                    or (parsed.hostname or "").lower() not in {"artprice.com", "www.artprice.com"}
                    or parsed.username or parsed.password
                    or parsed.port not in ({None, 443} if parsed.scheme.lower() == "https" else {None, 80})):
                return None
        except ValueError:
            return None
        match = re.match(r"^/artist/(\d+)/([a-z0-9]+(?:-[a-z0-9]+)*)(?:/|$)", parsed.path, flags=re.I)
        if not match:
            return None

        artist_id, slug = match.group(1), match.group(2)
        artist_tokens = cls.tokens_for_name(artist_name)
        slug_tokens = cls.tokens_for_slug(slug)
        if not artist_tokens or not slug_tokens:
            return None

        overlap = artist_tokens & slug_tokens
        score = len(overlap) / max(len(artist_tokens | slug_tokens), 1)

        confidence = "low"
        # Keep surname-only queries, junior/senior variants, extra first names,
        # and approximate spelling matches out of automatic persistence. One
        # middle initial may be omitted, provided both full name tokens agree.
        smaller, larger = sorted((artist_tokens, slug_tokens), key=len)
        initial_only = (len(smaller) >= 2 and smaller < larger
                        and len(larger - smaller) == 1
                        and all(len(token) == 1 for token in larger - smaller))
        if artist_tokens == slug_tokens or initial_only:
            confidence = "high"
        elif score >= 0.50:
            confidence = "medium"

        return ArtistIdCandidate(
            artist=artist_name,
            artist_id=artist_id,
            url=f"https://www.artprice.com/artist/{artist_id}/{slug.lower()}",
            source="duckduckgo",
            confidence=confidence,
            score=score,
        )
