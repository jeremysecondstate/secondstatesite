"""Phillips public catalog cards and their embedded auction/session metadata."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
from typing import Iterable
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from bs4 import BeautifulSoup

from catalogapp.watchlist_adapters import BookmarkSourceAdapter
from catalogapp.watchlist_fetch import SourceAccessError
from catalogapp.watchlist_images import _saved_asset_path, normalize_saved_thumbnail
from catalogapp.watchlist_models import NormalizedLot


_SALE_PATH = re.compile(r"/auction/([A-Za-z]{2}\d+)(?:/|$)", re.I)
_LOT_PATH = re.compile(r"/detail/(?:[^/]+/)*(\d+)/?$", re.I)
_CARD = "a.pah-lot-object-tile[href], a.seldon-object-tile[href]"
_STREAM = re.compile(r'\bstreamController\.enqueue\(("(?:[^"\\]|\\.)*")\)')


def phillips_sale_code(url: str) -> str:
    match = _SALE_PATH.search(urlsplit(url).path)
    return match[1].upper() if match else ""


def _text(value: object) -> str:
    value = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m[1], 16)), str(value or ""))
    return " ".join(BeautifulSoup(value, "html.parser").get_text(" ", strip=True).split())


def _decode_router(values: list) -> object:
    """Decode JSON references from React Router's stream without evaluating JS."""
    resolved: dict[int, object] = {}
    active: set[int] = set()

    def resolve(index: object, depth: int = 0) -> object:
        if not isinstance(index, int) or isinstance(index, bool) or index < 0:
            return None
        if index >= len(values) or depth > 80 or index in active:
            raise ValueError("Invalid Phillips data reference")
        if index in resolved:
            return resolved[index]
        active.add(index)
        value = values[index]
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                name = resolve(int(key[1:]), depth + 1) if re.fullmatch(r"_\d+", key) else key
                if isinstance(name, str):
                    result[name] = resolve(item, depth + 1)
        elif isinstance(value, list):
            result = [resolve(item, depth + 1) for item in value]
        else:
            result = value
        active.remove(index)
        resolved[index] = result
        return result

    return resolve(0)


def _route_payloads(soup: BeautifulSoup) -> list[dict]:
    routes = []
    for script in soup.find_all("script"):
        for match in _STREAM.finditer(script.get_text()):
            try:
                values = json.loads(json.loads(match[1]))
                if not isinstance(values, list) or len(values) > 100_000:
                    continue
                root = _decode_router(values)
            except (ValueError, TypeError, RecursionError):
                continue
            loaders = root.get("loaderData") if isinstance(root, dict) else None
            if isinstance(loaders, dict):
                routes.extend(value for value in loaders.values() if isinstance(value, dict))
    return routes


def _auction(soup: BeautifulSoup, sale_code: str) -> tuple[dict, list[dict]]:
    routes = _route_payloads(soup)
    auctions = [route["auction"] for route in routes if isinstance(route.get("auction"), dict)]
    if auctions:
        matches = [auction for auction in auctions if str(auction.get("auctionCode", "")).upper() == sale_code]
        if not matches:
            raise SourceAccessError("The Phillips page belongs to a different auction code.")
        return matches[0], routes
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            item = json.loads(script.get_text())
        except (ValueError, TypeError):
            continue
        if not isinstance(item, dict) or item.get("@type") != "Event":
            continue
        if phillips_sale_code(str(item.get("url", ""))) != sale_code:
            raise SourceAccessError("The Phillips event belongs to a different auction code.")
        location = item.get("location") or {}
        offers = item.get("offers") or {}
        return {
            "auctionCode": sale_code,
            "auctionName": item.get("name", ""),
            "auctionLocation": location.get("name", "") if isinstance(location, dict) else "",
            "auctionStartDateTime": item.get("startDate", ""),
            "auctionEndDateTime": item.get("endDate", ""),
            "auctionCurrency": {"currencyCode": offers.get("priceCurrency", "") if isinstance(offers, dict) else ""},
        }, routes
    raise SourceAccessError("Phillips auction metadata is missing; save the sale with its session information.")


def _date(value: object, timezone_name: str = "") -> str:
    try:
        result = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        if result.tzinfo is None:
            return ""
        if timezone_name:
            result = result.astimezone(ZoneInfo(timezone_name))
        return result.isoformat()
    except (ValueError, TypeError, ZoneInfoNotFoundError):
        return ""


def _session_date(auction: dict, number: str) -> str:
    zone = str(auction.get("auctionTimezone") or "")
    sessions = auction.get("sessions") or []
    matches = []
    for session in sessions:
        if not isinstance(session, dict):
            continue
        try:
            if int(session["lotNumberStart"]) <= int(number) <= int(session["lotNumberEnd"]):
                matches.append(_date(session.get("startDateTime"), zone))
        except (ValueError, TypeError, KeyError):
            continue
    if len(matches) == 1 and matches[0]:
        return matches[0]
    if sessions:
        raise SourceAccessError(f"Phillips lot {number} does not have one verified auction session.")
    start = _date(auction.get("auctionStartDateTime"), zone)
    end = _date(auction.get("auctionEndDateTime"), zone)
    if start and (not end or start[:10] == end[:10]):
        return start
    raise SourceAccessError("Phillips has multiple sale dates but the lot session metadata is missing.")


def _image_url(value: str, sale_code: str) -> str:
    try:
        parts = urlsplit(value)
        if (
            parts.scheme == "https" and parts.hostname == "dist.phillips.com"
            and not parts.username and not parts.password and parts.port is None
            and parts.path.startswith(f"/auction-assets/{sale_code}/")
            and re.search(r"\.(?:jpe?g|png|webp)$", parts.path, re.I)
        ):
            return f"https://dist.phillips.com{parts.path}?fit=bounds&width=900&height=900"
    except ValueError:
        pass
    return ""


def _card_image(card, sale_code: str) -> str:
    image = card.find("img")
    if image is None:
        return ""
    candidates = [image.get(key, "") for key in ("id", "data-src", "src")]
    candidates.extend(item.strip().split(" ")[0] for item in image.get("srcset", "").split(","))
    return next((safe for value in candidates if (safe := _image_url(value, sale_code))), "")


def _number(value: object) -> float | None:
    try:
        result = float(str(value).replace(",", ""))
        return result if result >= 0 and result != float("inf") else None
    except (ValueError, TypeError):
        return None


def _card_lot_url(card, page_url: str) -> tuple[str, str]:
    url = urljoin(page_url, card.get("href", ""))
    parts = urlsplit(url)
    match = _LOT_PATH.fullmatch(parts.path)
    if parts.scheme != "https" or parts.hostname not in {"www.phillips.com", "phillips.com"} or not match:
        return "", ""
    return f"https://www.phillips.com{parts.path}", match[1]


class PhillipsAdapter(BookmarkSourceAdapter):
    source = "Phillips"
    domains = ("phillips.com",)

    def catalog_total(self, page: str) -> int | None:
        soup = BeautifulSoup(page, "html.parser")
        for route in _route_payloads(soup):
            auction = route.get("auction")
            if isinstance(auction, dict):
                total = auction.get("totalLotCount")
                if isinstance(total, int) and not isinstance(total, bool) and total >= 0:
                    return total
        match = re.search(r"\b([\d,]+)\s+Lots\b", soup.get_text(" ", strip=True))
        return int(match[1].replace(",", "")) if match else None

    def parse_search_page(self, page: str, page_url: str, watchlist_artist: str) -> list[NormalizedLot]:
        sale_code = phillips_sale_code(page_url)
        if not sale_code:
            raise SourceAccessError("The Phillips bookmark must identify one auction code.")
        soup = BeautifulSoup(page, "html.parser")
        auction, _routes = _auction(soup, sale_code)
        identities = {
            str(item.get("objectNumber", "")): str(item.get("lotNumberFull", ""))
            for item in auction.get("lots", []) if isinstance(item, dict)
        }
        currency = (auction.get("auctionCurrency") or {}).get("currencyCode", "")
        lots = {}
        for card in soup.select(_CARD):
            lot_url, object_number = _card_lot_url(card, page_url)
            if not object_number:
                continue
            number_node = card.select_one(".seldon-object-tile__lot-number")
            maker_node = card.select_one(".seldon-object-tile__maker")
            title_node = card.select_one(".seldon-object-tile__title")
            number = number_node.get_text(strip=True) if number_node else ""
            artist = maker_node.get_text(" ", strip=True) if maker_node else ""
            title = title_node.get_text(" ", strip=True) if title_node else ""
            if not number or not artist or not title:
                raise SourceAccessError("A Phillips lot card is missing its number, artist, or title.")
            if identities and identities.get(object_number) != number:
                raise SourceAccessError(f"Phillips lot {number} does not match this auction's lot inventory.")
            estimate_node = card.select_one(".seldon-object-tile__estimate .seldon-detail__value")
            amounts = re.findall(r"\d[\d,]*(?:\.\d+)?", estimate_node.get_text(" ", strip=True)) if estimate_node else []
            lot = NormalizedLot(
                source=self.source, source_lot_id=f"{sale_code}-{object_number}",
                artist=artist, artist_watchlist_name=artist, title=title,
                auction_house=self.source, sale_title=_text(auction.get("auctionName")),
                lot_number=number, start_at=_session_date(auction, number),
                location=_text(auction.get("auctionLocation")),
                estimate_low=_number(amounts[0]) if amounts else None,
                estimate_high=_number(amounts[1]) if len(amounts) > 1 else None,
                currency=str(currency), lot_url=lot_url,
                sale_url=f"https://www.phillips.com/auction/{sale_code}/browse",
                image_url=_card_image(card, sale_code),
            )
            if lot.cache_key in lots and lots[lot.cache_key].content_hash != lot.content_hash:
                raise SourceAccessError(f"Phillips lot {number} has conflicting catalog cards.")
            lots[lot.cache_key] = lot
        if not lots and self.catalog_total(page) != 0:
            raise SourceAccessError("No readable Phillips lot cards were found; the catalog may be incomplete or blocked.")
        return list(lots.values())

    def extract_lot_links(self, page: str, page_url: str) -> list[str]:
        return list(dict.fromkeys(url for card in BeautifulSoup(page, "html.parser").select(_CARD)
                                  if (url := _card_lot_url(card, page_url)[0])))

    def extract_next_page_url(self, page: str, page_url: str) -> str:
        total = self.catalog_total(page)
        if total is not None and len(self.extract_lot_links(page, page_url)) < total:
            raise SourceAccessError(
                "Phillips reports more catalog lots than are loaded. Save the complete catalog before importing."
            )
        return ""

    def needs_detail(self, lot: NormalizedLot) -> bool:
        # Catalog cards already carry all calendar fields. Missing medium does
        # not justify hundreds of detail requests during a whole-sale refresh.
        return not all((lot.artist, lot.title, lot.lot_number, lot.start_at))

    def parse_lot_detail(self, page: str, lot_url: str, watchlist_artist: str) -> NormalizedLot | None:
        match = _LOT_PATH.fullmatch(urlsplit(lot_url).path)
        if not match:
            return None
        soup = BeautifulSoup(page, "html.parser")
        for route in _route_payloads(soup):
            detail, auction = route.get("lot"), route.get("auction")
            if not isinstance(detail, dict) or not isinstance(auction, dict):
                continue
            if str(detail.get("objectNumber", "")) != match[1]:
                continue
            sale_code = str(auction.get("auctionCode", "")).upper()
            if not re.fullmatch(r"[A-Z]{2}\d+", sale_code):
                continue
            estimate = (detail.get("estimate") or {}).get("mainEstimate") or {}
            number = str(detail.get("lotNumberFull") or detail.get("lotNumber") or "")
            artist = _text(detail.get("makerName"))
            return NormalizedLot(
                source=self.source, source_lot_id=f"{sale_code}-{match[1]}",
                artist=artist, artist_watchlist_name=artist, title=_text(detail.get("description")),
                medium=_text(detail.get("medium")), auction_house=self.source,
                sale_title=_text(auction.get("auctionName")), lot_number=number,
                start_at=_date(detail.get("sessionStartDateTime"), str(auction.get("auctionTimezone") or ""))
                or _session_date(auction, number), location=_text(auction.get("auctionLocation")),
                estimate_low=_number(estimate.get("lowEstimate")),
                estimate_high=_number(estimate.get("highEstimate")),
                currency=str(estimate.get("currencyCode") or ""),
                lot_url=lot_url, sale_url=f"https://www.phillips.com/auction/{sale_code}/browse",
                image_url=_image_url(str(detail.get("mainImagePath") or ""), sale_code),
            )
        return None


def attach_saved_phillips_images(
    page: str, page_path: str | Path, lots: Iterable[NormalizedLot]
) -> list[str]:
    """Attach only normalized pixels from the catalog's exact companion folder."""
    path = Path(page_path)
    selected = {lot.lot_url: lot for lot in lots if lot.source == "Phillips"}
    attached = set()
    for card in BeautifulSoup(page, "html.parser").select(_CARD):
        url, _object_number = _card_lot_url(card, "https://www.phillips.com")
        if url not in selected or url in attached:
            continue
        image = card.find("img")
        asset = _saved_asset_path(path, image.get("src", "")) if image else None
        try:
            if asset is None or asset.stat().st_size > 10 * 1024 * 1024:
                continue
            with asset.open("rb") as stream:
                encoded = normalize_saved_thumbnail(stream.read(10 * 1024 * 1024 + 1))
        except (OSError, ValueError):
            continue
        lot = selected[url]
        lot.saved_image_base64 = encoded
        lot.content_hash = lot.calculate_content_hash()
        attached.add(url)
    missing = len(selected.keys() - attached)
    return [f"{missing} Phillips lots have no usable saved thumbnail; public image links remain available."] if missing else []
