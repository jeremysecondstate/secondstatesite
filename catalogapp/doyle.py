"""Parse Doyle sale catalogs, including complete browser-saved catalog pages."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Iterable
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from catalogapp.watchlist_adapters import BookmarkSourceAdapter
from catalogapp.watchlist_fetch import SourceAccessError
from catalogapp.watchlist_images import _saved_asset_path, normalize_saved_thumbnail
from catalogapp.watchlist_models import NormalizedLot


_LIFE_DATES = re.compile(r"\s*\((?:b\.?\s*)?\d{4}(?:\s*[-–—]\s*\d{4})?\)\s*$", re.I)
_NUMBER = re.compile(r"\bLot\s+(\d+[A-Za-z]?)\b", re.I)


def _text(node) -> str:
    return " ".join(node.get_text(" ", strip=True).split()) if node is not None else ""


def _public_url(value: str, page_url: str, *, image: bool = False) -> str:
    if not value or "\\" in value or any(ord(char) < 32 for char in value):
        return ""
    # Saved companion paths must never be mistaken for remote artwork URLs.
    if image and ("_files/" in value or value.startswith("data:")):
        return ""
    try:
        parts = urlsplit(urljoin(page_url, value))
        host = (parts.hostname or "").lower()
        allowed = host in {"doyle.com", "www.doyle.com"}
        if image:
            allowed = allowed or host == "goauctiondoyle.blob.core.windows.net"
        if not allowed or parts.scheme not in {"https", "http"} or parts.username or parts.password or parts.port not in {None, 80, 443}:
            return ""
    except ValueError:
        return ""
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


def doyle_sale_id(url: str) -> str:
    """Return the one explicitly identified public Doyle sale, or an empty ID."""
    safe = _public_url(url, "https://doyle.com/")
    values = parse_qs(urlsplit(safe).query).get("au", [])
    return values[0] if len(values) == 1 and values[0].isdigit() else ""


def _lot_url(value: str, page_url: str) -> tuple[str, str, str]:
    safe = _public_url(value, page_url)
    parts = urlsplit(safe)
    values = parse_qs(parts.query).get("lot", [])
    sale_id = doyle_sale_id(safe)
    if not parts.path.startswith("/auction/lot/") or not sale_id or len(values) != 1 or not values[0].isdigit():
        return "", "", ""
    # Remove page/sort/filter state so the same lot has one stable public URL.
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode({"lot": values[0], "au": sale_id}), "")), sale_id, values[0]


def _money(text: str) -> tuple[float | None, float | None, str]:
    amounts = re.findall(r"(?<!\w)[\d,]+(?:\.\d{1,2})?", text)
    numbers = [float(value.replace(",", "")) for value in amounts]
    currency = "USD" if "$" in text or "USD" in text else ""
    return (numbers[0] if numbers else None, numbers[1] if len(numbers) > 1 else None, currency)


def _sale_metadata(soup: BeautifulSoup, page_url: str) -> tuple[str, str, str]:
    sale_id = doyle_sale_id(page_url)
    title = _text(soup.select_one(".auction-details-title"))
    sale_url = f"https://doyle.com/auction/search/?au={sale_id}" if sale_id else ""
    for node in soup.select(".auction-details-buttons a[href]"):
        if doyle_sale_id(node["href"]) == sale_id and "details" in _text(node).lower():
            sale_url = _public_url(node["href"], page_url)
            break
    date = ""
    # Match by auction ID, never take another auction's date from this dropdown.
    option = soup.select_one(f'#Filter_AuctionId option[value="{sale_id}"]') if sale_id else None
    match = re.search(r"\b(\d{1,2}/\d{1,2}/\d{4})\b", _text(option))
    if match:
        title = title or _text(option)[:match.start()].strip()
        try:
            date = datetime.strptime(match[1], "%m/%d/%Y").date().isoformat()
        except ValueError:
            pass
    return title, sale_url, date


class DoyleAdapter(BookmarkSourceAdapter):
    source = "Doyle"
    domains = ("doyle.com",)

    @staticmethod
    def snapshot_observed_at(page: str) -> datetime | None:
        """Read the catalog's load timestamp, never its auction/event timestamp."""
        stamps = set()
        for script in BeautifulSoup(page, "html.parser").select("script:not([src])"):
            for match in re.finditer(r"\bvar\s+pageLoadTimeStamp\s*=\s*(\d{9,11})\s*;", script.get_text()):
                try:
                    stamp = datetime.fromtimestamp(int(match[1]), timezone.utc)
                except (ValueError, OverflowError, OSError):
                    continue
                if 2000 <= stamp.year <= 2100:
                    stamps.add(stamp)
        # Conflicting load times cannot establish one snapshot observation.
        return next(iter(stamps)) if len(stamps) == 1 else None

    @staticmethod
    def catalog_total(page: str) -> int | None:
        soup = BeautifulSoup(page, "html.parser")
        node = soup.select_one(".auction-tab-current")
        match = re.search(r"Current\s+lots\s*\(([\d,]+)\)", _text(node), re.I)
        return int(match[1].replace(",", "")) if match else None

    def parse_search_page(self, page: str, page_url: str, watchlist_artist: str) -> list[NormalizedLot]:
        sale_id = doyle_sale_id(page_url)
        if not sale_id:
            raise SourceAccessError("The Doyle catalog URL must identify one auction with au.")
        soup = BeautifulSoup(page, "html.parser")
        title, sale_url, date = _sale_metadata(soup, page_url)
        observed: dict[str, NormalizedLot] = {}
        for card in soup.select(".auction-grid-lot, .auction-list-lot"):
            link = card.select_one(".auction-lot-title a[href], a[href*='/auction/lot/']")
            url, card_sale, lot_id = _lot_url(link.get("href", "") if link else "", page_url)
            if not lot_id:
                raise SourceAccessError("A Doyle lot card is missing its verified lot identity.")
            if card_sale != sale_id:
                raise SourceAccessError("The Doyle catalog contains lots from a different auction number.")
            label = _text(card.select_one(".lot-title, .auction-lot-title"))
            number_match = _NUMBER.search(label)
            number = str(card.get("data-lotwithsuffix") or (number_match[1] if number_match else ""))
            artist = _LIFE_DATES.sub("", _NUMBER.sub("", label, count=1)).strip(" :-–—")
            if not artist or not number:
                raise SourceAccessError("A Doyle lot card is missing its number or artist.")
            if number_match and number_match[1].upper() != number.upper():
                raise SourceAccessError("A Doyle lot card has conflicting lot numbers.")
            estimate_low, estimate_high, currency = _money(_text(card.select_one(".estimate")))
            image = card.select_one(".auction-lot-image img")
            image_url = ""
            if image is not None:
                image_url = _public_url(image.get("src", ""), page_url, image=True) or _public_url(image.get("data-src", ""), page_url, image=True)
            artwork_title = _text(card.select_one(".lot-artwork-title, .artwork-title")) or f"Lot {number}"
            lot = NormalizedLot(
                source=self.source, source_lot_id=f"{sale_id}-{lot_id}", artist=artist,
                artist_watchlist_name=artist, title=artwork_title,
                medium=_text(card.select_one(".lot-medium")), auction_house="Doyle",
                sale_title=title, lot_number=number, start_at=date,
                estimate_low=estimate_low, estimate_high=estimate_high, currency=currency,
                lot_url=url, sale_url=sale_url, image_url=image_url,
            )
            if lot.cache_key in observed and observed[lot.cache_key].content_hash != lot.content_hash:
                raise SourceAccessError(f"Doyle lot {number} has conflicting catalog cards.")
            observed[lot.cache_key] = lot
        if not observed and self.catalog_total(page) != 0:
            raise SourceAccessError("Doyle returned no readable catalog lots. Save the catalog with its lot cards visible.")
        return list(observed.values())

    def extract_lot_links(self, page: str, page_url: str) -> list[str]:
        return [lot.lot_url for lot in self.parse_search_page(page, page_url, "")]

    def extract_next_page_url(self, page: str, page_url: str) -> str:
        soup = BeautifulSoup(page, "html.parser")
        current = parse_qs(urlsplit(page_url).query).get("pn", ["1"])[0]
        if not current.isdigit() or int(current) < 1:
            raise SourceAccessError("Doyle returned an invalid catalog page number.")
        current_number = int(current)
        sale_id = doyle_sale_id(page_url)
        for option in soup.select('.pagination option[selected][value*="/auction/"]'):
            selected_url = _public_url(option.get("value", ""), page_url)
            selected_number = parse_qs(urlsplit(selected_url).query).get("pn", ["1"])[0]
            if doyle_sale_id(selected_url) != sale_id or selected_number != str(current_number):
                raise SourceAccessError("Doyle returned a different catalog page than requested.")
        next_urls = set()
        for arrow in soup.select(".pagination .fa-chevron-right"):
            link = arrow.find_parent("a", href=True)
            if link is None or link.has_attr("disabled") or "disabled" in link.get("class", []):
                continue
            url = _public_url(link["href"], page_url)
            next_page = parse_qs(urlsplit(url).query).get("pn", ["1"])[0]
            if doyle_sale_id(url) != sale_id or not next_page.isdigit() or int(next_page) != current_number + 1:
                raise SourceAccessError("Doyle catalog pagination skipped or repeated a page.")
            next_urls.add(url)
        if len(next_urls) > 1:
            raise SourceAccessError("Doyle catalog pagination contains conflicting next pages.")
        next_url = next(iter(next_urls), "")
        total = self.catalog_total(page)
        per_page_option = soup.select_one(".auction-results-per-page option[selected]")
        per_page = per_page_option.get("value", "") if per_page_option else ""
        count = len({_lot_url(link.get("href", ""), page_url)[0]
                     for link in soup.select(".auction-lot-title a[href]")})
        if total is not None and per_page.isdigit() and int(per_page) > 0:
            size = int(per_page)
            expected = max(0, min(size, total - (current_number - 1) * size))
            if count != expected:
                raise SourceAccessError("Doyle returned an incomplete catalog page; existing lots were retained.")
            should_have_next = current_number * size < total
            if bool(next_url) != should_have_next:
                raise SourceAccessError("Doyle pagination does not cover the advertised catalog total.")
        elif total is not None and count < total and not next_url:
            raise SourceAccessError("Doyle reports more catalog lots than are loaded; existing lots were retained.")
        return next_url

    def needs_detail(self, lot: NormalizedLot) -> bool:
        return lot.title == f"Lot {lot.lot_number}" or super().needs_detail(lot)

    def parse_lot_detail(self, page: str, lot_url: str, watchlist_artist: str) -> NormalizedLot | None:
        """Read explicit structured artwork metadata when a detail page supplies it.

        Catalog-only saves intentionally retain the honest ``Lot N`` title. No
        artwork title, date, time, or medium is inferred from the artist's name.
        """
        url, sale_id, lot_id = _lot_url(lot_url, lot_url)
        if not lot_id:
            return None
        soup = BeautifulSoup(page, "html.parser")
        sale_title, sale_url, date = _sale_metadata(soup, lot_url)
        number_match = re.search(r"/lot-(\d+[a-z]?)-", urlsplit(url).path, re.I)
        number = number_match[1].upper() if number_match else ""
        objects = []
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                payload = json.loads(script.string or script.get_text())
            except (TypeError, ValueError):
                continue
            values = payload if isinstance(payload, list) else [payload]
            for value in values:
                if isinstance(value, dict):
                    objects.extend(value.get("@graph", []) if isinstance(value.get("@graph"), list) else [value])
        for item in objects:
            if not isinstance(item, dict) or not isinstance(item.get("@type"), str) or item["@type"] not in {"VisualArtwork", "Product"}:
                continue
            title = item.get("name")
            if not isinstance(title, str) or not title.strip():
                continue
            artist = item.get("artist") or item.get("creator")
            if isinstance(artist, dict):
                artist = artist.get("name")
            artist = artist if isinstance(artist, str) else watchlist_artist
            if not artist:
                continue
            image = item.get("image")
            if isinstance(image, list):
                image = image[0] if image else ""
            if isinstance(image, dict):
                image = image.get("url", "")
            return NormalizedLot(
                source=self.source, source_lot_id=f"{sale_id}-{lot_id}", artist=artist,
                artist_watchlist_name=artist, title=title.strip(),
                medium=item.get("artMedium", "") if isinstance(item.get("artMedium", ""), str) else "",
                auction_house="Doyle", sale_title=sale_title, lot_number=number,
                start_at=date, lot_url=url, sale_url=sale_url,
                image_url=_public_url(image, lot_url, image=True) if isinstance(image, str) else "",
            )
        return None


def attach_saved_doyle_images(page: str, page_path: str | Path, lots: Iterable[NormalizedLot]) -> list[str]:
    """Attach sanitized primary thumbnails from this HTML's companion folder."""
    selected = {lot.source_lot_id: lot for lot in lots if lot.source == "Doyle"}
    attached: set[str] = set()
    for card in BeautifulSoup(page, "html.parser").select(".auction-grid-lot, .auction-list-lot"):
        link = card.select_one(".auction-lot-title a[href], a[href*='/auction/lot/']")
        _url, sale_id, lot_id = _lot_url(link.get("href", "") if link else "", "https://doyle.com/")
        identity = f"{sale_id}-{lot_id}"
        if identity not in selected or identity in attached:
            continue
        image = card.select_one(".auction-lot-image img")
        asset = _saved_asset_path(Path(page_path), image.get("src", "")) if image is not None else None
        if asset is None:
            continue
        try:
            if asset.stat().st_size > 10 * 1024 * 1024:
                continue
            with asset.open("rb") as stream:
                encoded = normalize_saved_thumbnail(stream.read(10 * 1024 * 1024 + 1))
        except (OSError, ValueError):
            continue
        lot = selected[identity]
        lot.saved_image_base64 = encoded
        lot.content_hash = lot.calculate_content_hash()
        attached.add(identity)
    missing = len(selected.keys() - attached)
    return [f"{missing} Doyle lots have no usable saved thumbnail. Save the catalog as Webpage, Complete with its matching _files folder to include their images."] if missing else []
