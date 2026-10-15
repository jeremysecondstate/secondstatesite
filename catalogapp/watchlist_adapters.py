"""Deterministic source adapters for bookmarked auction pages."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from copy import copy
import json
import math
import re
from typing import Any, Iterable, Protocol
import unicodedata
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, Comment, NavigableString

from catalogapp.bookmark_watchlist import canonicalize_bookmark_url
from catalogapp.watchlist_models import NormalizedLot
from catalogapp.watchlist_fetch import SourceAccessError
from catalogapp.watchlist_images import heritage_preview_url


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
        "soldPrice",
        "soldCurrencyCode",
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
        if not normalized:
            return None
        canonical = canonicalize_bookmark_url(lot_url)
        canonical_node = soup.find("link", rel="canonical")
        page_canonical = canonicalize_bookmark_url(canonical_node.get("href", "")) if canonical_node else ""
        detail = next((lot for lot in normalized if lot.lot_url in {canonical, page_canonical}), None)
        if detail is None:
            # Related-lot metadata alone must not become this page's lot.
            detail = self._normalize(self._raw_from_detail(soup, lot_url), lot_url, watchlist_artist)
        if detail is None:
            return None
        if not detail.title:
            # Current Invaluable metadata can carry only a URL and bid. Its
            # visible heading supplies the title; an empty application shell
            # must not count as a successfully refreshed lot detail.
            detail.title = self._node_text(soup, ("h1", "[data-testid='lot-title']", ".lot-title"))
        if not detail.title or re.fullmatch(
            r"(?:JavaScript is disabled|Access denied|Verify you are human|Just a moment(?:\.{3})?)",
            detail.title,
            re.I,
        ):
            return None
        # The public metadata can omit the result while the visible detail
        # contains "Sold: $11,000 USD". Read that label independently of JSON.
        sold = self._sold_from_html(soup)
        if sold.low is not None:
            detail.sold_price = sold.low
            detail.sold_currency = sold.currency or detail.currency
        elif any(
            re.fullmatch(r"Sold(?:\s+(?:for|price))?\s*:\s*(?:Log\s*in|Sign\s*in)\s+to\s+view\b.*", text, re.I)
            for text in self._sold_label_texts(soup)
        ):
            detail.ambiguities.append("sold_price_login")
        detail.content_hash = detail.calculate_content_hash()
        return detail

    def merge_detail(self, card: NormalizedLot, detail: NormalizedLot) -> NormalizedLot:
        merged = super().merge_detail(card, detail)
        # Catalog objectID and URL-derived detail IDs need not be identical.
        merged.source_lot_id = card.source_lot_id
        merged.lot_url = card.lot_url or detail.lot_url
        merged.content_hash = merged.calculate_content_hash()
        return merged

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
        sold = self._sold_money(hit)
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
            "soldPrice": sold.low,
            "soldCurrency": sold.currency,
            "bidCount": self._value(hit, "bidCount"),
            "currency": self._text_value(hit, "currencyCode"),
            "endAt": self._catalog_datetime(hit),
            "location": location,
            "saleUrl": urljoin(page_url, f"/catalog/{catalog_ref}") if catalog_ref else "",
            "imageUrl": self._catalog_image_url(hit),
        }

    @classmethod
    def _catalog_image_url(cls, hit: dict[str, Any]) -> str:
        """Expand Invaluable's CDN-relative primary image path."""

        photo_path = cls._text_value(hit, "photoPath", "imageUrl", "image")
        if not photo_path:
            return ""
        parsed = urlsplit(photo_path)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return photo_path
        if photo_path.startswith("//"):
            return f"https:{photo_path}"
        relative_path = photo_path.lstrip("/")
        if relative_path.casefold().startswith("housephotos/"):
            relative_path = relative_path[len("housePhotos/") :]
        return urljoin("https://image.invaluable.com/housePhotos/", relative_path)

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
        seen: dict[str, NormalizedLot] = {}
        for raw in raw_lots:
            lot = self._normalize(raw, page_url, watchlist_artist)
            if not lot:
                continue
            if lot.cache_key in seen:
                existing = seen[lot.cache_key]
                if lot.sold_price is not None:
                    # Public JSON can omit a result present on its DOM card.
                    existing.sold_price = lot.sold_price
                    existing.sold_currency = lot.sold_currency
                    existing.content_hash = existing.calculate_content_hash()
                continue
            seen[lot.cache_key] = lot
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
        current_bid_value = self._value(raw, "currentBid", "bid", "price")
        current = self._money(current_bid_value, None, None, estimate.currency)
        sold = self._sold_money(raw)
        bid_count = self._bid_count(self._value(raw, "bidCount", "numberOfBids"))
        if bid_count is None:
            bid_count = self._bid_count(current_bid_value, require_label=True)
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
            sold_price=sold.low,
            sold_currency=sold.currency if sold.low is not None else "",
            bid_count=bid_count,
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
        sold = self._sold_from_html(node)
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
            "soldPrice": sold.low,
            "soldCurrency": sold.currency,
            "bidCount": self._node_text(node, (".bid-count", "[data-bid-count]", "[data-testid='bid-count']")),
            "endAt": self._node_attr(node, ("time[datetime]", "[data-end-at]"), ("datetime", "data-end-at")),
            "startAt": self._node_attr(node, ("[data-start-at]",), ("data-start-at",)),
            "image": (node.find("img").get("src", "") if hasattr(node, "find") and node.find("img") else ""),
            "saleUrl": self._node_attr(node, ("a.sale-link",), ("href",)),
            "pageUrl": page_url,
        }

    def _raw_from_detail(self, soup: BeautifulSoup, lot_url: str) -> dict[str, Any]:
        canonical = soup.find("link", rel="canonical")
        sold = self._sold_from_html(soup)
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
            "soldPrice": sold.low,
            "soldCurrency": sold.currency,
            "bidCount": self._node_text(soup, (".bid-count", "[data-bid-count]", "[data-testid='bid-count']")),
            "endAt": self._node_attr(soup, ("time[datetime]", "[data-end-at]"), ("datetime", "data-end-at")),
        }

    @staticmethod
    def _posted_sold_money(value: Any, currency: Any = "") -> _Money:
        """Accept a single explicit result amount, never bids or an estimate.

        Text must start with the amount (after an optional Sold: label), so a
        login prompt or an unavailable result cannot consume a later number.
        Currency printed alongside the result takes precedence over estimates.
        """

        if value is None or isinstance(value, bool):
            return _Money()
        text = " ".join(str(value).split())
        text = re.sub(r"^Sold(?:\s+(?:for|price))?\s*:\s*", "", text, flags=re.I)
        match = re.fullmatch(
            r"(?:(?P<prefix>[A-Z]{3})\s*)?"
            r"(?P<symbol>US\$|C\$|A\$|HK\$|NZ\$|[$€£])?\s*"
            r"(?P<amount>\d[\d,]*(?:\.\d{1,2})?)\s*"
            r"(?P<suffix>[A-Z]{3})?",
            text,
            flags=re.I,
        )
        if not match:
            return _Money()
        amount = float(match["amount"].replace(",", ""))
        if amount <= 0 or not math.isfinite(amount):
            return _Money()
        symbol_codes = {"US$": "USD", "C$": "CAD", "A$": "AUD", "HK$": "HKD", "NZ$": "NZD", "$": "USD", "€": "EUR", "£": "GBP"}
        explicit_code = match["suffix"] or match["prefix"]
        # A supplied source currency disambiguates the generic dollar symbol.
        code = explicit_code or (symbol_codes.get((match["symbol"] or "").upper()) if match["symbol"] != "$" else "")
        code = code or str(currency or "").upper().strip() or symbol_codes.get(match["symbol"] or "", "")
        return _Money(amount, currency=code.upper())

    @classmethod
    def _sold_money(cls, raw: dict[str, Any]) -> _Money:
        folded = {str(key).casefold(): value for key, value in raw.items()}
        source_currency = cls._value(raw, "soldCurrency", "soldCurrencyCode", "currencyCode", "currency", "priceCurrency")
        for key in ("soldPrice", "soldFor", "priceRealized", "realizedPrice", "hammerPrice"):
            value = folded.get(key.casefold())
            currency = source_currency
            if isinstance(value, dict):
                currency = cls._value(value, "currency", "currencyCode", "priceCurrency") or currency
                value = cls._value(value, "amount", "value", "price")
            sold = cls._posted_sold_money(value, currency)
            if sold.low is not None:
                return sold
        return _Money()

    @classmethod
    def _sold_node_excluded(cls, candidate: Any, root: Any) -> bool:
        for ancestor in (candidate, *candidate.parents):
            if ancestor.has_attr("hidden") or ancestor.get("aria-hidden") == "true":
                return True
            if root.name == "[document]" and (
                re.search(r"\b(?:lot-card|lot-item|related-lots|recommended-lots|recommendations)\b", " ".join(ancestor.get("class", [])))
                or "related" in str(ancestor.get("data-testid", "")).casefold()
            ):
                return True
        return False

    @classmethod
    def _sold_label_texts(cls, node: Any) -> Iterable[str]:
        """Read only the Sold label and its immediately adjacent inline value.

        Invaluable's closed-bid-lot-detail places the strong label beside the
        amount, with title, estimate, house and date in the same parent. Parsing
        that entire parent either misses the result or risks borrowing another
        number. Stop at the next block, field label, or hidden element.
        """

        label_pattern = r"Sold(?:\s+(?:for|price))?\s*:"
        for label in node.find_all(string=re.compile(r"^\s*" + label_pattern, re.I)):
            parent = label.parent
            if isinstance(label, Comment) or parent.name in {"script", "style", "template"}:
                continue
            if cls._sold_node_excluded(parent, node):
                continue
            for candidate in (parent, parent.parent):
                if candidate is not None:
                    yield candidate.get_text(" ", strip=True)
            for origin in (label, parent):
                origin_text = str(origin).strip() if isinstance(origin, NavigableString) else origin.get_text(" ", strip=True)
                if not re.fullmatch(label_pattern, origin_text, re.I):
                    continue
                parts = [origin_text]
                for sibling in origin.next_siblings:
                    if isinstance(sibling, Comment):
                        continue
                    if isinstance(sibling, NavigableString):
                        value = str(sibling).strip()
                    else:
                        if sibling.name not in {"span", "b", "i", "em", "small", "button", "a"}:
                            break
                        if cls._sold_node_excluded(sibling, node):
                            break
                        value = sibling.get_text(" ", strip=True)
                    if value:
                        parts.append(value)
                    if len(parts) > 8:
                        break
                yield " ".join(parts)

    @classmethod
    def _sold_from_html(cls, node: Any) -> _Money:
        if not hasattr(node, "select"):
            return _Money()
        # DOM selectors are explicitly about the result; generic price and bid
        # elements carry no evidence that the lot was sold.

        for candidate in node.select("[data-sold-price], .sold-price, .lot-sold-price, [data-testid='sold-price']"):
            if cls._sold_node_excluded(candidate, node):
                continue
            value = candidate.get("data-sold-price") or candidate.get_text(" ", strip=True)
            currency = candidate.get("data-sold-currency") or candidate.get("data-currency") or ""
            sold = cls._posted_sold_money(value, currency)
            if sold.low is not None:
                return sold
        for text in cls._sold_label_texts(node):
            sold = cls._posted_sold_money(text)
            if sold.low is not None:
                return sold
        return _Money()

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
                value = next(
                    (
                        value[child_key]
                        for child_key in ("name", "value", "url")
                        if child_key in value and value[child_key] not in (None, "")
                    ),
                    None,
                )
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
    def _bid_count(value: Any, *, require_label: bool = False) -> int | None:
        if value in (None, "") or isinstance(value, bool):
            return None
        normalized = " ".join(str(value).split())
        if re.search(r"\bno\s+bids?\b", normalized, re.IGNORECASE):
            return 0
        labelled = re.search(r"(\d[\d,]*)\s+bids?\b", normalized, re.IGNORECASE)
        if labelled:
            return int(labelled.group(1).replace(",", ""))
        if require_label:
            return None
        if re.fullmatch(r"\d[\d,]*", normalized):
            return int(normalized.replace(",", ""))
        return None

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


class HeritageAdapter(BookmarkSourceAdapter):
    """Read Heritage's public catalog cards, including whole-sale bookmarks.

    A starting bid is not a current bid. Catalog dates are kept date-only unless
    a lot detail explicitly supplies its session's time and timezone.
    """

    source = "Heritage"
    domains = ("ha.com",)
    _lot_path = re.compile(r"/a/(\d+)-(\d+)\.s(?:/|$)", re.I)

    @staticmethod
    def _text(node) -> str:
        return " ".join(node.get_text(" ", strip=True).split()) if node else ""

    @classmethod
    def _identity(cls, url: str) -> tuple[str, str] | None:
        match = cls._lot_path.search(urlsplit(url).path)
        return (match[1], match[2]) if match else None

    @staticmethod
    def _clean_url(url: str) -> str:
        parts = urlsplit(url)
        query = [(k, v) for k, v in parse_qsl(parts.query) if not re.fullmatch(r"ic\d+", k, re.I)]
        return canonicalize_bookmark_url(urlunsplit(parts._replace(query=urlencode(query))))

    @staticmethod
    def _sale_filter(url: str) -> str:
        values = {k.casefold(): v for k, v in parse_qsl(urlsplit(url).query)}
        return values.get("auction_name") or values.get("saleno") or ""

    @classmethod
    def _description(cls, node) -> tuple[str, str, str]:
        if node is None:
            return "", "", ""
        artist = cls._text(node.select_one("b, strong"))
        # Birth/death years belong to the source description, not artist identity.
        artist = re.sub(r"\s*\((?:b\.?\s*)?\d{4}[^)]*\)\s*$", "", artist, flags=re.I).strip()
        description = copy(node)
        for br in description.find_all("br"):
            br.replace_with("\n")
        lines = [" ".join(line.split()) for line in description.get_text().splitlines() if line.strip()]
        if artist and len(lines) >= 2:
            return artist, lines[1], lines[2] if len(lines) >= 3 else ""
        return artist, cls._text(node.select_one("i, em")) or cls._text(node), ""

    @staticmethod
    def _date(text: str) -> str:
        # Gallery cards omit dates; the selected sale heading uses year-first
        # dates, e.g. "2026 October 22 Prints & Multiples Signature Auction".
        heading = re.search(r"\b(20\d{2})\s+([A-Za-z]+)\s+(\d{1,2})\b(?!\s*[-–/]\s*\d)", text)
        if heading:
            text = f"{heading[2]} {heading[3]}, {heading[1]}"
        match = re.search(r"\b([A-Za-z]+\s+\d{1,2},?\s+\d{4})\b", text)
        if not match:
            return ""
        for fmt in ("%b %d, %Y", "%B %d, %Y", "%b %d %Y", "%B %d %Y"):
            try:
                return datetime.strptime(match[1], fmt).date().isoformat()
            except ValueError:
                pass
        return ""

    @staticmethod
    def _image_url(node, page_url: str) -> str:
        """Use Heritage product previews and retain other allowed public images."""

        if node is None:
            return ""
        for name in ("data-src", "src"):
            value = str(node.get(name) or "").strip()
            if not value.startswith(("https://", "//", "/")):
                continue
            url = urljoin(page_url, value)
            parts = urlsplit(url)
            host = (parts.hostname or "").casefold()
            if parts.scheme == "https" and not parts.username and not parts.password and any(
                host == domain or host.endswith(f".{domain}") for domain in ("ha.com", "heritagestatic.com")
            ):
                return heritage_preview_url(url) or url
        return ""

    @classmethod
    def _bid(cls, node) -> tuple[float | None, int | None]:
        text = cls._text(node)
        match = re.search(r"\bCurrent\s+Bid\s*:\s*\$([\d,]+(?:\.\d+)?)", text, re.I)
        if match:
            return float(match[1].replace(",", "")), None
        # Heritage explicitly distinguishes 'Starting Bid' from money bid.
        if re.search(r"\bStarting Bid\s*:", text, re.I):
            return None, 0
        return None, None

    @classmethod
    def _estimate(cls, node) -> _Money:
        match = re.search(r"Estimate\s*:\s*(\$[\d,]+(?:\.\d+)?(?:\s*[-–]\s*\$?[\d,]+(?:\.\d+)?)?)", cls._text(node), re.I)
        return InvaluableAdapter._money(match[1] if match else "", None, None, "USD")

    @classmethod
    def _sale_title(cls, soup: BeautifulSoup, sale: str) -> str:
        home = soup.select_one(".auction-home-link")
        if home:
            title = cls._text(home).split("(go to Auction Home page)")[0].strip()
            if title:
                return title
        for node in soup.select("a.trigger, a[href*='auction-home.zx']"):
            title = cls._text(node)
            if re.search(r"\b20\d{2}\b", title) and "auction" in title.casefold():
                return title
        return f"Heritage Auction {sale}"

    def extract_lot_links(self, page: str, page_url: str) -> list[str]:
        soup = BeautifulSoup(page, "html.parser")
        return list(dict.fromkeys(
            self._clean_url(urljoin(page_url, node["href"]))
            for node in soup.select(".item-block a.item-title[href]")
            if self.supports(urljoin(page_url, node["href"])) and self._identity(node["href"])
        ))

    def parse_search_page(self, page: str, page_url: str, watchlist_artist: str) -> list[NormalizedLot]:
        soup = BeautifulSoup(page, "html.parser")
        if self._identity(page_url):
            detail = self.parse_lot_detail(page, page_url, watchlist_artist)
            return [detail] if detail else []
        nodes = soup.select(".item-block")
        if not nodes:
            text = self._text(soup)
            if re.search(r"\b(?:no (?:items|results) (?:found|match)|0 available items)\b", text, re.I):
                return []
            raise SourceAccessError(
                "Heritage did not return readable catalog lots. Open the bookmarked sale in your browser "
                "and use Import Saved Heritage Pages, or configure the optional watchlist browser profile."
            )
        lots: dict[str, NormalizedLot] = {}
        expected_sale = self._sale_filter(page_url)
        for node in nodes:
            link = node.select_one("a.item-title[href]")
            url = self._clean_url(urljoin(page_url, link["href"])) if link else ""
            identity = self._identity(url)
            if not identity or not self.supports(url):
                raise SourceAccessError("A Heritage catalog card was incomplete; existing lots have been retained.")
            sale, number = identity
            if expected_sale and sale != expected_sale:
                raise SourceAccessError("The Heritage catalog does not match the bookmarked auction number.")
            artist, title, medium = self._description(link)
            estimate = self._estimate(node)
            bid, count = self._bid(node.select_one(".item-value, .current-amount .bid-value"))
            sale_title = self._sale_title(soup, sale)
            date_node = node.select_one(".live-auction-date")
            when = self._date(self._text(date_node))
            if not when:
                when = self._date(self._text(node.select_one(".auction-date, .closing-date")))
            if not when and expected_sale:
                when = self._date(sale_title)
            image = node.select_one("a.photo-holder img[src], img.thumbnail[src]")
            sale_link = node.select_one(".item-info a[href*='search.zx'], .lotno a[href*='search.zx']")
            sale_url = self._clean_url(urljoin(page_url, sale_link["href"])) if sale_link else ""
            lot = NormalizedLot(
                source=self.source, source_lot_id=f"{sale}-{number}", artist=artist,
                artist_watchlist_name=watchlist_artist or artist, title=title, medium=medium,
                auction_house="Heritage Auctions", sale_title=sale_title,
                lot_number=number, start_at=when, currency="USD",
                estimate_low=estimate.low, estimate_high=estimate.high,
                current_bid=bid, bid_count=count, lot_url=url, sale_url=sale_url,
                image_url=self._image_url(image, page_url),
                ambiguities=[] if artist else ["artist"],
            )
            lots[lot.cache_key] = lot
        return list(lots.values())

    def parse_lot_detail(self, page: str, lot_url: str, watchlist_artist: str) -> NormalizedLot | None:
        identity = self._identity(lot_url)
        soup = BeautifulSoup(page, "html.parser")
        description = soup.select_one('#auction-description [itemprop="description"]')
        if not identity or description is None:
            raise SourceAccessError("Heritage did not return a readable lot detail page.")
        sale, number = identity
        artist, title, medium = self._description(description)
        sale_title = self._sale_title(soup, sale)
        info = soup.select_one("#auction-info")
        # Use the actual session time, never the earlier proxy bidding deadline.
        session = self._text(info.select_one(".additional-info .left")) if info else ""
        match = re.search(
            r"(\d{1,2}:\d{2}\s*[AP]M)\s+(Central Time|CT|CST|CDT|Eastern Time|ET|EST|EDT|Pacific Time|PT|PST|PDT),\s*(?:\w+,\s*)?([A-Za-z]+ \d{1,2}, \d{4})",
            session, re.I,
        )
        when = ""
        if match:
            zone = "America/Chicago" if match[2].upper().startswith("C") else "America/New_York" if match[2].upper().startswith("E") else "America/Los_Angeles"
            day = self._date(match[3])
            if day:
                local_time = datetime.strptime(re.sub(r"\s+", " ", match[1]).upper(), "%I:%M %p").time()
                when = datetime.combine(datetime.fromisoformat(day).date(), local_time, tzinfo=ZoneInfo(zone)).isoformat()
        if not when:
            match_date = re.search(r"\b(20\d{2}) ([A-Za-z]+) (\d{1,2})\b", sale_title)
            when = self._date(f"{match_date[2]} {match_date[3]}, {match_date[1]}") if match_date else ""
        estimate = self._estimate(soup.select_one("#auction-description"))
        bid, count = self._bid(soup.select_one("#bidBlockTop"))
        # Positive 'Bids + Registered Phone Bidders' is not a bid count.
        bid_node = soup.select_one("#number-bids")
        if self._text(bid_node) == "0":
            count = 0
        image = soup.select_one('img[src*="heritagestatic.com"][src*="it=product"]')
        sale_link = soup.select_one(".auction-home-link a[href]")
        return NormalizedLot(
            source=self.source, source_lot_id=f"{sale}-{number}", artist=artist,
            artist_watchlist_name=watchlist_artist or artist, title=title, medium=medium,
            auction_house="Heritage Auctions", sale_title=sale_title, lot_number=number,
            start_at=when, currency="USD", estimate_low=estimate.low, estimate_high=estimate.high,
            current_bid=bid, bid_count=count, lot_url=self._clean_url(lot_url),
            sale_url=self._clean_url(urljoin(lot_url, sale_link["href"])) if sale_link else "",
            image_url=self._image_url(image, lot_url),
            ambiguities=[] if artist else ["artist"],
        )

    def extract_next_page_url(self, page: str, page_url: str) -> str:
        if self._identity(page_url):
            return ""
        soup = BeautifulSoup(page, "html.parser")
        def page_number(url: str) -> int:
            value = dict(parse_qsl(urlsplit(url).query)).get("page", "25~1")
            match = re.fullmatch(r"\d+~(\d+)", value)
            return int(match[1]) if match else 1
        current = page_number(page_url)
        current_node = soup.select_one(".items-pagination .pageindex.current")
        if current_node and self._text(current_node).isdigit() and int(self._text(current_node)) != current:
            raise SourceAccessError("Heritage returned a different catalog page; refresh is incomplete.")
        candidates: list[tuple[int, str]] = []
        for link in soup.select("a.pageindex[href], a[rel='next'][href]"):
            url = self._clean_url(urljoin(page_url, link["href"]))
            if (not self.supports(url) or urlsplit(url).path != urlsplit(page_url).path
                    or self._sale_filter(url) != self._sale_filter(page_url)):
                raise SourceAccessError("Heritage pagination left the bookmarked catalog; refresh is incomplete.")
            number = page_number(url)
            if number > current:
                candidates.append((number, url))
        if candidates:
            number, url = min(candidates)
            if number != current + 1:
                raise SourceAccessError("Heritage skipped a catalog page; refresh is incomplete.")
            return url
        total_text = self._text(soup.select_one(".number-bid-buy-results")).replace(",", "")
        page_value = dict(parse_qsl(urlsplit(page_url).query)).get("page", "25~1")
        size = re.fullmatch(r"(\d+)~\d+", page_value)
        if total_text.isdigit() and size:
            accounted = (current - 1) * int(size[1]) + len(soup.select(".item-block"))
            if accounted < int(total_text):
                raise SourceAccessError("Heritage has more catalog lots but no next page; refresh is incomplete.")
        return ""


ADAPTERS: tuple[BookmarkSourceAdapter, ...] = (InvaluableAdapter(), HeritageAdapter())


def adapter_for_url(url: str) -> BookmarkSourceAdapter | None:
    return next((adapter for adapter in ADAPTERS if adapter.supports(url)), None)
