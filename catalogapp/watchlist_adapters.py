"""Deterministic source adapters for bookmarked auction pages."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
from typing import Any, Iterable, Protocol
import unicodedata
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from catalogapp.bookmark_watchlist import canonicalize_bookmark_url
from catalogapp.watchlist_models import NormalizedLot


class PageFetcher(Protocol):
    def fetch(self, url: str) -> str: ...

    def post_json(self, url: str, payload: object, *, referer: str = "") -> object: ...


class BookmarkSourceAdapter(ABC):
    source = ""
    domains: tuple[str, ...] = ()

    def supports(self, url: str) -> bool:
        host = (urlsplit(url).hostname or "").casefold()
        return any(host == domain or host.endswith(f".{domain}") for domain in self.domains)

    def fetch_search_page(self, url: str, fetcher: PageFetcher) -> str:
        return fetcher.fetch(url)

    def fetch_lot_detail(self, url: str, fetcher: PageFetcher) -> str:
        return fetcher.fetch(url)

    @abstractmethod
    def extract_lot_links(self, page: str, page_url: str) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def parse_search_page(self, page: str, page_url: str, watchlist_artist: str) -> list[NormalizedLot]:
        raise NotImplementedError

    @abstractmethod
    def parse_lot_detail(self, page: str, lot_url: str, watchlist_artist: str) -> NormalizedLot | None:
        raise NotImplementedError

    @abstractmethod
    def extract_next_page_url(self, page: str, page_url: str) -> str:
        raise NotImplementedError

    def needs_detail(self, lot: NormalizedLot) -> bool:
        return not all((lot.title, lot.auction_house, lot.lot_number, lot.relevant_at, lot.medium))

    def merge_detail(self, card: NormalizedLot, detail: NormalizedLot) -> NormalizedLot:
        payload = card.to_dict()
        for key, value in detail.to_dict().items():
            if key in {"first_seen_at", "last_seen_at", "status", "content_hash"}:
                continue
            if value not in (None, "", []):
                payload[key] = value
        payload["content_hash"] = ""
        return NormalizedLot.from_dict(payload)


@dataclass(frozen=True, slots=True)
class _Money:
    low: float | None = None
    high: float | None = None
    currency: str = ""


@dataclass(frozen=True, slots=True)
class BatchedSearchPage:
    page: str
    complete: bool = True


class InvaluableAdapter(BookmarkSourceAdapter):
    source = "Invaluable"
    domains = ("invaluable.com",)
    _catalog_path = "/catResults"
    _catalog_filters = (
        "banned:false AND channelIDs:1 AND unlotted:false AND onlineOnly:false "
        "AND closed:false AND NOT subcategoryRef:7IA742QGM5"
    )
    _catalog_attributes = (
        "artistName",
        "bidCount",
        "catalogRef",
        "countryName",
        "currencyCode",
        "currencySymbol",
        "currentBid",
        "dateTimeLocal",
        "dateTimeUTCUnix",
        "endTimeUTCUnix",
        "estimateHigh",
        "estimateLow",
        "houseName",
        "location",
        "lotDescription",
        "lotNumber",
        "lotRef",
        "lotTitle",
        "objectID",
        "photoPath",
        "stateName",
        "subcategoryName",
        "supercategoryName",
    )
    _sort_indexes = {
        "enddateasc": "upcoming_lots_dateTimeUTCUnix_asc_prod",
        "newlylisted": "upcoming_lots_postDateTime_desc_prod",
        "postdatetimedesc": "upcoming_lots_postDateTime_desc_prod",
        "priceasc": "upcoming_lots_currentBid_asc_prod",
        "pricedesc": "upcoming_lots_currentBid_desc_prod",
        "bidcountasc": "upcoming_lots_bidCount_asc_prod",
        "bidcountdesc": "upcoming_lots_bidCount_desc_prod",
    }
    _category_facets = frozenset(
        {
            "asian art",
            "collectibles",
            "decorative art",
            "fine art",
            "furniture",
            "jewelry",
        }
    )
    _lot_href = re.compile(r"/(?:auction-lot|lot)/", re.IGNORECASE)
    _print_terms = re.compile(
        r"\b(etching|engraving|lithograph|linocut|screenprint|serigraph|woodcut|woodblock|"
        r"aquatint|mezzotint|monotype|print|multiple|mixograf\w*|gicl(?:ee|ée))\b",
        re.IGNORECASE,
    )

    def fetch_search_page(self, url: str, fetcher: PageFetcher) -> str:
        """Use the same public JSON feed as Invaluable's JavaScript search page.

        A normal GET of ``/search`` now returns an empty application shell. The
        catalog feed is both smaller and deterministic, and does not need browser
        cookies or a logged-in profile. Fixture/browser fetchers without
        ``post_json`` retain the HTML parsing fallback.
        """

        post_json = getattr(fetcher, "post_json", None)
        if urlsplit(url).path.rstrip("/").casefold() != "/search" or not callable(post_json):
            return super().fetch_search_page(url, fetcher)
        parts = urlsplit(url)
        endpoint = urlunsplit((parts.scheme, parts.netloc, self._catalog_path, "", ""))
        payload = post_json(endpoint, self._catalog_request_payload(url), referer=url)
        if self._catalog_result(payload) is None:
            raise RuntimeError("Invaluable returned an unexpected catalog-search response.")
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    def fetch_search_batch(
        self,
        searches: Iterable[tuple[str, str]],
        fetcher: PageFetcher,
        *,
        max_pages: int = 10,
    ) -> dict[str, BatchedSearchPage]:
        """Fetch compatible artist searches with one OR-facet request per page.

        Invaluable accepts an Algolia-style OR group for artist facets. Combining
        selected artists avoids a burst of near-identical requests while keeping
        each bookmark's cache membership separate after the response is split.
        """

        items = [(url, artist) for url, artist in searches if url and artist]
        post_json = getattr(fetcher, "post_json", None)
        if len(items) < 2 or not callable(post_json):
            return {}
        if any(urlsplit(url).path.rstrip("/").casefold() != "/search" for url, _artist in items):
            return {}

        grouped: dict[str, list[tuple[str, str, str]]] = {}
        request_templates: dict[str, dict[str, Any]] = {}
        for url, watchlist_artist in items:
            artist_name = self._catalog_artist_name(url) or watchlist_artist
            request = self._catalog_request_payload(url)["requests"][0]
            params = dict(request["params"])
            params["page"] = 0
            params["facetFilters"] = [
                list(group)
                for group in params.get("facetFilters", [])
                if not self._is_artist_facet_group(group)
            ]
            template = {
                "indexName": self._sort_indexes["enddateasc"],
                "params": params,
            }
            signature = json.dumps(template, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            request_templates[signature] = template
            grouped.setdefault(signature, []).append((url, watchlist_artist, artist_name))

        pages: dict[str, BatchedSearchPage] = {}
        page_limit = max(1, min(int(max_pages), 25))
        for signature, group in grouped.items():
            if len(group) < 2:
                continue
            template = request_templates[signature]
            artist_names = list(dict.fromkeys(item[2] for item in group))
            params_template = dict(template["params"])
            params_template["facetFilters"] = [
                [f"artistName:{artist_name}" for artist_name in artist_names],
                *params_template.get("facetFilters", []),
            ]
            first_url = group[0][0]
            parts = urlsplit(first_url)
            endpoint = urlunsplit((parts.scheme, parts.netloc, self._catalog_path, "", ""))
            hits: list[dict[str, Any]] = []
            seen_hits: set[str] = set()
            complete = True
            page_index = 0
            result_template: dict[str, Any] = {}

            while page_index < page_limit:
                page_params = dict(params_template)
                page_params["page"] = page_index
                payload = post_json(
                    endpoint,
                    {
                        "requests": [{"indexName": template["indexName"], "params": page_params}],
                        "isCatalogPageRequest": False,
                    },
                    referer=first_url,
                )
                catalog_result = self._catalog_result(payload)
                if catalog_result is None:
                    raise RuntimeError("Invaluable returned an unexpected batched catalog-search response.")
                result_template = {
                    key: value
                    for key, value in catalog_result.items()
                    if key not in {"hits", "page", "nbPages", "nbHits", "hitsPerPage"}
                }
                for hit in catalog_result.get("hits", []):
                    if not isinstance(hit, dict):
                        continue
                    identity = self._text_value(hit, "objectID", "lotRef")
                    identity = identity or json.dumps(hit, ensure_ascii=False, sort_keys=True, default=str)
                    if identity in seen_hits:
                        continue
                    seen_hits.add(identity)
                    hits.append(hit)
                try:
                    page_count = max(0, int(catalog_result.get("nbPages", 0)))
                except (TypeError, ValueError):
                    page_count = 0
                if page_index + 1 >= page_count:
                    break
                page_index += 1
            else:
                complete = False

            if page_index + 1 < page_count:
                complete = False
            hits_by_artist: dict[str, list[dict[str, Any]]] = {}
            for hit in hits:
                key = self._artist_match_key(self._text_value(hit, "artistName", "artist"))
                if key:
                    hits_by_artist.setdefault(key, []).append(hit)
            for url, _watchlist_artist, artist_name in group:
                artist_hits = hits_by_artist.get(self._artist_match_key(artist_name), [])
                per_artist_result = {
                    **result_template,
                    "hits": artist_hits,
                    "page": 0,
                    "nbPages": 1,
                    "nbHits": len(artist_hits),
                    "hitsPerPage": max(1, len(artist_hits)),
                }
                pages[url] = BatchedSearchPage(
                    json.dumps(
                        {"results": [per_artist_result]},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    complete=complete,
                )
        return pages

    def extract_lot_links(self, page: str, page_url: str) -> list[str]:
        catalog_result = self._catalog_result(page)
        if catalog_result is not None:
            links: list[str] = []
            for hit in catalog_result.get("hits", []):
                if not isinstance(hit, dict):
                    continue
                lot_url = self._catalog_lot_url(hit, page_url)
                if lot_url and lot_url not in links:
                    links.append(lot_url)
            return links
        soup = BeautifulSoup(page or "", "html.parser")
        links: list[str] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            if not self._lot_href.search(anchor["href"]):
                continue
            canonical = canonicalize_bookmark_url(urljoin(page_url, anchor["href"]))
            if canonical and canonical not in seen:
                seen.add(canonical)
                links.append(canonical)
        for raw in self._embedded_lot_dicts(soup):
            href = self._value(raw, "lotUrl", "url", "canonicalUrl")
            canonical = canonicalize_bookmark_url(urljoin(page_url, str(href or "")))
            if canonical and self._lot_href.search(urlsplit(canonical).path) and canonical not in seen:
                seen.add(canonical)
                links.append(canonical)
        return links

    def parse_search_page(self, page: str, page_url: str, watchlist_artist: str) -> list[NormalizedLot]:
        catalog_result = self._catalog_result(page)
        if catalog_result is not None:
            raw_lots = [
                self._raw_from_catalog_hit(hit, page_url, watchlist_artist)
                for hit in catalog_result.get("hits", [])
                if isinstance(hit, dict)
            ]
            return self._normalize_and_deduplicate(raw_lots, page_url, watchlist_artist)
        soup = BeautifulSoup(page or "", "html.parser")
        raw_lots: list[dict[str, Any]] = list(self._embedded_lot_dicts(soup))
        selectors = (
            "[data-lot-id]",
            "article.lot-card",
            ".lot-card",
            ".lot-item",
            "[data-testid*='lot-card']",
        )
        nodes = []
        seen_nodes: set[int] = set()
        for selector in selectors:
            for node in soup.select(selector):
                if id(node) not in seen_nodes:
                    seen_nodes.add(id(node))
                    nodes.append(node)
        if not nodes:
            nodes = [anchor.parent for anchor in soup.find_all("a", href=self._lot_href)]
        raw_lots.extend(self._raw_from_card(node, page_url) for node in nodes if node)
        return self._normalize_and_deduplicate(raw_lots, page_url, watchlist_artist)

    def parse_lot_detail(self, page: str, lot_url: str, watchlist_artist: str) -> NormalizedLot | None:
        soup = BeautifulSoup(page or "", "html.parser")
        raw_lots = list(self._embedded_lot_dicts(soup))
        if not raw_lots:
            raw_lots.append(self._raw_from_detail(soup, lot_url))
        normalized = self._normalize_and_deduplicate(raw_lots, lot_url, watchlist_artist)
        return normalized[0] if normalized else None

    def extract_next_page_url(self, page: str, page_url: str) -> str:
        catalog_result = self._catalog_result(page)
        if catalog_result is not None:
            try:
                page_index = int(catalog_result.get("page", 0))
                page_count = int(catalog_result.get("nbPages", 0))
            except (TypeError, ValueError):
                return ""
            if page_index + 1 >= page_count:
                return ""
            current = urlsplit(page_url)
            query = [(key, value) for key, value in parse_qsl(current.query, keep_blank_values=True) if key.casefold() != "page"]
            query.append(("page", str(page_index + 2)))
            return canonicalize_bookmark_url(
                urlunsplit((current.scheme, current.netloc, current.path, urlencode(query), ""))
            )
        soup = BeautifulSoup(page or "", "html.parser")
        candidates = [
            soup.find("link", rel=lambda value: value and "next" in value),
            soup.find("a", rel=lambda value: value and "next" in value),
            soup.find("a", attrs={"aria-label": re.compile(r"next", re.I)}),
            soup.select_one(".pagination .next a"),
        ]
        for node in candidates:
            href = node.get("href") if node else ""
            if not href:
                continue
            if href and href.startswith("?"):
                current = urlsplit(page_url)
                combined = dict(parse_qsl(current.query, keep_blank_values=True))
                combined.update(dict(parse_qsl(href[1:], keep_blank_values=True)))
                resolved = urlunsplit((current.scheme, current.netloc, current.path, urlencode(combined), ""))
            else:
                resolved = urljoin(page_url, href or "")
            canonical = canonicalize_bookmark_url(resolved)
            if canonical and self.supports(canonical):
                return canonical
        return ""

    def _catalog_request_payload(self, page_url: str) -> dict[str, Any]:
        query_items = parse_qsl(urlsplit(page_url).query, keep_blank_values=True)
        folded: dict[str, list[str]] = {}
        for key, value in query_items:
            folded.setdefault(key.casefold(), []).append(value)

        def first(*keys: str) -> str:
            for key in keys:
                values = folded.get(key.casefold(), [])
                if values and values[0].strip():
                    return values[0].strip()
            return ""

        artist_name = first("artistName", "artist")
        search_text = first("query", "keyword", "q")
        sort_value = first("sort").casefold()
        index_name = self._sort_indexes.get(sort_value, "upcoming_lots_prod")
        try:
            page_number = max(1, int(first("page") or "1"))
        except ValueError:
            page_number = 1

        facet_filters: list[list[str]] = []
        if artist_name:
            facet_filters.append([f"artistName:{artist_name}"])
        for key, value in query_items:
            if key.casefold() in self._category_facets and value.strip():
                facet_filters.append([f"{key}:{value.strip()}"])

        return {
            "requests": [
                {
                    "indexName": index_name,
                    "params": {
                        "analytics": False,
                        "attributesToRetrieve": list(self._catalog_attributes),
                        "clickAnalytics": False,
                        "facetFilters": facet_filters,
                        "facets": [],
                        "filters": self._catalog_filters,
                        "getRankingInfo": False,
                        "hitsPerPage": 96,
                        "page": page_number - 1,
                        "query": search_text,
                    },
                }
            ],
            "isCatalogPageRequest": False,
        }

    @staticmethod
    def _is_artist_facet_group(group: object) -> bool:
        return isinstance(group, list) and bool(group) and all(
            str(value).casefold().startswith("artistname:") for value in group
        )

    @staticmethod
    def _catalog_artist_name(page_url: str) -> str:
        for key, value in parse_qsl(urlsplit(page_url).query, keep_blank_values=True):
            if key.casefold() in {"artistname", "artist"} and value.strip():
                return value.strip()
        return ""

    @staticmethod
    def _artist_match_key(value: str) -> str:
        return " ".join(unicodedata.normalize("NFKC", value or "").casefold().split())

    @staticmethod
    def _catalog_result(payload: object) -> dict[str, Any] | None:
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (TypeError, ValueError):
                return None
        if not isinstance(payload, dict):
            return None
        results = payload.get("results")
        if not isinstance(results, list) or not results or not isinstance(results[0], dict):
            return None
        if not isinstance(results[0].get("hits"), list):
            return None
        return results[0]

    def _raw_from_catalog_hit(
        self,
        hit: dict[str, Any],
        page_url: str,
        watchlist_artist: str,
    ) -> dict[str, Any]:
        title = self._text_value(hit, "lotTitle", "title")
        description = self._text_value(hit, "lotDescription", "description")
        medium_match = self._print_terms.search(f"{title} {description}")
        medium = medium_match.group(0).capitalize() if medium_match else "Print"
        catalog_ref = self._text_value(hit, "catalogRef")
        location = self._text_value(hit, "location")
        if not location:
            location = ", ".join(
                value for value in (self._text_value(hit, "stateName"), self._text_value(hit, "countryName")) if value
            )
        return {
            "lotId": self._text_value(hit, "objectID", "lotRef"),
            "lotUrl": self._catalog_lot_url(hit, page_url),
            "title": title,
            "artist": self._text_value(hit, "artistName") or watchlist_artist,
            "medium": medium,
            "auctionHouse": self._text_value(hit, "houseName"),
            "lotNumber": self._text_value(hit, "lotNumber"),
            "estimateLow": self._value(hit, "estimateLow"),
            "estimateHigh": self._value(hit, "estimateHigh"),
            "currentBid": self._value(hit, "currentBid"),
            "currency": self._text_value(hit, "currencyCode"),
            "endAt": self._catalog_datetime(hit),
            "location": location,
            "saleUrl": urljoin(page_url, f"/catalog/{catalog_ref}") if catalog_ref else "",
        }

    @classmethod
    def _catalog_lot_url(cls, hit: dict[str, Any], page_url: str) -> str:
        lot_ref = cls._text_value(hit, "lotRef")
        if not lot_ref:
            return ""
        title_slug = cls._slugify(cls._text_value(hit, "lotTitle", "title")) or "lot"
        number_slug = cls._slugify(cls._text_value(hit, "lotNumber"))
        suffix = "-".join(value for value in (title_slug, number_slug, "c", lot_ref.casefold()) if value)
        return canonicalize_bookmark_url(urljoin(page_url, f"/auction-lot/{suffix}"))

    @staticmethod
    def _slugify(value: str) -> str:
        ascii_value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")
        return re.sub(r"[^a-z0-9]+", "-", ascii_value.casefold()).strip("-")

    @classmethod
    def _catalog_datetime(cls, hit: dict[str, Any]) -> str:
        for key in ("endTimeUTCUnix", "dateTimeUTCUnix"):
            value = cls._value(hit, key)
            try:
                timestamp = float(value)
            except (TypeError, ValueError):
                continue
            if timestamp <= 0:
                continue
            if timestamp > 10_000_000_000:
                timestamp /= 1000
            try:
                return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
            except (OverflowError, OSError, ValueError):
                continue
        return ""

    def _normalize_and_deduplicate(
        self,
        raw_lots: Iterable[dict[str, Any]],
        page_url: str,
        watchlist_artist: str,
    ) -> list[NormalizedLot]:
        lots: list[NormalizedLot] = []
        seen: set[str] = set()
        for raw in raw_lots:
            lot = self._normalize(raw, page_url, watchlist_artist)
            if not lot or lot.cache_key in seen:
                continue
            seen.add(lot.cache_key)
            lots.append(lot)
        return lots

    def _normalize(self, raw: dict[str, Any], page_url: str, watchlist_artist: str) -> NormalizedLot | None:
        lot_url = canonicalize_bookmark_url(
            urljoin(page_url, str(self._value(raw, "lotUrl", "url", "canonicalUrl") or ""))
        )
        source_id = str(self._value(raw, "lotId", "source_lot_id", "id", "lot_id") or "").strip()
        if not source_id and lot_url:
            source_id = self._source_id_from_url(lot_url)
        if not source_id and not lot_url:
            return None
        title = self._text_value(raw, "title", "name", "lotTitle")
        artist = self._text_value(raw, "artist", "artistName", "creator") or watchlist_artist
        medium = self._text_value(raw, "medium", "mediumText", "description")
        estimate = self._money(
            self._value(raw, "estimate", "estimateText"),
            self._value(raw, "estimateLow", "lowEstimate", "lowPrice"),
            self._value(raw, "estimateHigh", "highEstimate", "highPrice"),
            self._value(raw, "currency", "priceCurrency"),
        )
        current = self._money(self._value(raw, "currentBid", "bid", "price"), None, None, estimate.currency)
        start_at = self._date_value(raw, "startAt", "startDate", "saleStart", "start_at")
        end_at = self._date_value(raw, "endAt", "endDate", "saleEnd", "closeDate", "end_at")
        ambiguities: list[str] = []
        if not self._text_value(raw, "artist", "artistName", "creator"):
            ambiguities.append("artist")
        combined_medium = f"{title} {medium}"
        if combined_medium.strip() and not self._print_terms.search(combined_medium):
            ambiguities.append("print_classification")
        if not end_at and not start_at:
            ambiguities.append("date")
        return NormalizedLot(
            source=self.source,
            source_lot_id=source_id,
            artist=artist,
            artist_watchlist_name=watchlist_artist,
            title=title,
            medium=medium,
            auction_house=self._text_value(raw, "auctionHouse", "auctioneer", "seller", "house"),
            sale_title=self._text_value(raw, "saleTitle", "auctionTitle", "eventName"),
            lot_number=self._text_value(raw, "lotNumber", "lotNo", "lot_number"),
            start_at=start_at,
            end_at=end_at,
            location=self._text_value(raw, "location", "saleLocation"),
            estimate_low=estimate.low,
            estimate_high=estimate.high,
            currency=estimate.currency or current.currency,
            current_bid=current.low,
            lot_url=lot_url,
            sale_url=(
                urljoin(page_url, str(self._value(raw, "saleUrl", "auctionUrl", "eventUrl")))
                if self._value(raw, "saleUrl", "auctionUrl", "eventUrl")
                else ""
            ),
            image_url=(
                urljoin(page_url, str(self._value(raw, "imageUrl", "image", "thumbnail")))
                if self._value(raw, "imageUrl", "image", "thumbnail")
                else ""
            ),
            ambiguities=ambiguities,
        )

    def _raw_from_card(self, node: Any, page_url: str) -> dict[str, Any]:
        anchor = node.find("a", href=self._lot_href) if hasattr(node, "find") else None
        return {
            "lotId": node.get("data-lot-id", "") if hasattr(node, "get") else "",
            "url": anchor.get("href", "") if anchor else "",
            "title": self._node_text(node, ("[data-title]", ".lot-title", ".title", "h2", "h3")),
            "artist": self._node_text(node, ("[data-artist]", ".artist", ".lot-artist")),
            "medium": self._node_text(node, (".medium", ".lot-medium")),
            "auctionHouse": self._node_text(node, (".auction-house", ".house", "[data-auction-house]")),
            "saleTitle": self._node_text(node, (".sale-title", ".auction-title")),
            "lotNumber": self._node_text(node, (".lot-number", "[data-lot-number]")),
            "estimate": self._node_text(node, (".estimate", "[data-estimate]")),
            "currentBid": self._node_text(node, (".current-bid", ".bid")),
            "endAt": self._node_attr(node, ("time[datetime]", "[data-end-at]"), ("datetime", "data-end-at")),
            "startAt": self._node_attr(node, ("[data-start-at]",), ("data-start-at",)),
            "image": (node.find("img").get("src", "") if hasattr(node, "find") and node.find("img") else ""),
            "saleUrl": self._node_attr(node, ("a.sale-link",), ("href",)),
            "pageUrl": page_url,
        }

    def _raw_from_detail(self, soup: BeautifulSoup, lot_url: str) -> dict[str, Any]:
        canonical = soup.find("link", rel="canonical")
        return {
            "url": canonical.get("href", lot_url) if canonical else lot_url,
            "title": self._node_text(soup, ("h1", "[data-testid='lot-title']", ".lot-title")),
            "artist": self._node_text(soup, (".artist", "[data-testid='artist']", ".lot-artist")),
            "medium": self._node_text(soup, (".medium", ".lot-description", "[data-testid='description']")),
            "auctionHouse": self._node_text(soup, (".auction-house", "[data-testid='auction-house']")),
            "saleTitle": self._node_text(soup, (".sale-title", "[data-testid='sale-title']")),
            "lotNumber": self._node_text(soup, (".lot-number", "[data-testid='lot-number']")),
            "estimate": self._node_text(soup, (".estimate", "[data-testid='estimate']")),
            "currentBid": self._node_text(soup, (".current-bid", "[data-testid='current-bid']")),
            "endAt": self._node_attr(soup, ("time[datetime]", "[data-end-at]"), ("datetime", "data-end-at")),
        }

    def _embedded_lot_dicts(self, soup: BeautifulSoup) -> Iterable[dict[str, Any]]:
        for script in soup.find_all("script"):
            script_type = (script.get("type") or "").casefold()
            if "json" not in script_type and script.get("id") not in {"__NEXT_DATA__", "__NUXT_DATA__"}:
                continue
            try:
                payload = json.loads(script.string or script.get_text() or "")
            except (TypeError, ValueError):
                continue
            for value in self._walk_dicts(payload):
                href = str(self._value(value, "lotUrl", "url", "canonicalUrl") or "")
                has_identity = bool(self._value(value, "lotId", "lotNumber", "lotNo"))
                has_title = bool(self._value(value, "title", "name", "lotTitle"))
                if (href and self._lot_href.search(href)) or (has_identity and has_title):
                    yield value

    def _walk_dicts(self, value: Any) -> Iterable[dict[str, Any]]:
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from self._walk_dicts(child)
        elif isinstance(value, list):
            for child in value:
                yield from self._walk_dicts(child)

    @staticmethod
    def _value(raw: dict[str, Any], *keys: str) -> Any:
        folded = {str(key).casefold(): value for key, value in raw.items()}
        for key in keys:
            value = folded.get(key.casefold())
            if isinstance(value, dict):
                value = value.get("name") or value.get("value") or value.get("url")
            if value not in (None, ""):
                return value
        return None

    @classmethod
    def _text_value(cls, raw: dict[str, Any], *keys: str) -> str:
        value = cls._value(raw, *keys)
        if isinstance(value, list):
            value = ", ".join(str(item) for item in value)
        return " ".join(str(value or "").split()).strip()

    @classmethod
    def _date_value(cls, raw: dict[str, Any], *keys: str) -> str:
        value = str(cls._value(raw, *keys) or "").strip()
        if not value:
            return ""
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return value
        normalized = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return value
        return parsed.isoformat()

    @staticmethod
    def _source_id_from_url(url: str) -> str:
        slug = urlsplit(url).path.rstrip("/").split("/")[-1]
        match = re.search(r"(?:^|-)(\d{2,})(?:-|$)", slug)
        return match.group(1) if match else slug

    @staticmethod
    def _money(text: Any, low: Any, high: Any, currency: Any) -> _Money:
        combined = " ".join(str(value) for value in (text, low, high, currency) if value not in (None, ""))
        currency_code = str(currency or "").upper().strip()
        if not currency_code:
            if "$" in combined:
                currency_code = "USD"
            elif "€" in combined:
                currency_code = "EUR"
            elif "£" in combined:
                currency_code = "GBP"
        numbers = [float(value.replace(",", "")) for value in re.findall(r"\d[\d,]*(?:\.\d+)?", combined)]
        if low not in (None, ""):
            try:
                low_value = float(str(low).replace(",", ""))
            except ValueError:
                low_value = numbers[0] if numbers else None
        else:
            low_value = numbers[0] if numbers else None
        if high not in (None, ""):
            try:
                high_value = float(str(high).replace(",", ""))
            except ValueError:
                high_value = numbers[1] if len(numbers) > 1 else None
        else:
            high_value = numbers[1] if len(numbers) > 1 else None
        return _Money(low_value, high_value, currency_code)

    @staticmethod
    def _node_text(node: Any, selectors: Iterable[str]) -> str:
        for selector in selectors:
            found = node.select_one(selector) if hasattr(node, "select_one") else None
            if found:
                value = found.get("data-title") or found.get("data-artist") or found.get_text(" ", strip=True)
                if value:
                    return " ".join(str(value).split())
        return ""

    @staticmethod
    def _node_attr(node: Any, selectors: Iterable[str], attrs: Iterable[str]) -> str:
        for selector in selectors:
            found = node.select_one(selector) if hasattr(node, "select_one") else None
            if not found:
                continue
            for attr in attrs:
                if found.get(attr):
                    return str(found.get(attr))
        return ""


ADAPTERS: tuple[BookmarkSourceAdapter, ...] = (InvaluableAdapter(),)


def adapter_for_url(url: str) -> BookmarkSourceAdapter | None:
    return next((adapter for adapter in ADAPTERS if adapter.supports(url)), None)
