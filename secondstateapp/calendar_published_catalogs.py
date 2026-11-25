"""Published catalog identities for Calendar lots with incomplete sale links."""

from dataclasses import dataclass
from datetime import datetime, timezone
import re

from .calendar_linked_sales import _drouot_catalog, _invaluable_catalog
from .calendar_sessions_2026 import drouot_url_matches


@dataclass(frozen=True)
class PublishedCatalog:
    title: str
    drouot_house: str
    drouot_id: str
    invaluable_house: str
    photo_prefix: str
    numbers: range


# The house catalog and matching numbered listings on both platforms establish
# each pairing. The three Invaluable source captures did not provide catalog URLs.
_CATALOGS = {
    # Auction 812, session I. Both catalogs include Calder 282 and Warhol 288.
    # https://www.ponteonline.com/en/lot-list/auction/812
    datetime(2026, 11, 25, 14, tzinfo=timezone.utc): PublishedCatalog(
        "Prints and Multiples · Session I", "Il Ponte", "188002",
        "Il Ponte Auction House", "/housePhotos/ilPonte/86/822386/H0611", range(202, 292),
    ),
    # The house lists Warhol 35 and Bourgeois 65 in this 67-lot sale.
    # https://www.piasa.fr/en/auctions/post-warbr-abstraction-international-figurative-art
    datetime(2026, 12, 2, 17, tzinfo=timezone.utc): PublishedCatalog(
        "Postwar Art · International Abstraction & Figuration", "Piasa", "188158",
        "Piasa", "/housePhotos/Piasa/91/818591/H0837", range(1, 68),
    ),
    # Both platforms include Vasarely 291 and Hirst 350/351 in one catalog.
    # The house publishes consecutive sections with one advertised start.
    # https://www.accademiafineart.com/auctions/2026/art/
    # https://www.accademiafineart.com/auctions/2026/13-design-moderne/
    datetime(2026, 12, 11, 15, tzinfo=timezone.utc): PublishedCatalog(
        "Art Moderne et Contemporain, followed by Design et Moderne", "Accademia Fine Art", "188578",
        "Accademia Fine Art", "/housePhotos/Accademia/60/823060/H4638", range(251, 401),
    ),
}


# Soulis publishes separate catalogs for the 11:00 and 12:30 Central sessions.
# Invaluable lot pages link each catalog to its own photo directory.
# https://soulisauctions.com/auctions/the-21st-annual-winter-art-auction/
_SOULIS_SESSIONS = {
    datetime(2026, 12, 6, 17, tzinfo=timezone.utc): (
        "/housePhotos/soulis/89/822689/H1081", "https://www.invaluable.com/catalog/P2E3A4896Q",
        "The MutualArt x Soulis Inaugural Fine Art Auction",
    ),
    datetime(2026, 12, 6, 18, 30, tzinfo=timezone.utc): (
        "/housePhotos/soulis/92/822692/H1081", "https://www.invaluable.com/catalog/PV1TQ5N75E",
        "The 21st Annual Winter Art Auction",
    ),
}


def published_catalog(lot):
    """Resolve a source observation only within its published sale and session."""
    if lot.is_all_day:
        return None
    session = _SOULIS_SESSIONS.get(lot.event_at)
    if session and lot.source == "Invaluable" and lot.auction_house == "Soulis Auctions" and not lot.sale_url:
        prefix, url, title = session
        if lot.sale_title in ("", title) and _invaluable_catalog(lot) == ((lot.auction_house, lot.event_at, prefix), ""):
            return {"identity": "sale:" + url, "catalog_url": url, "session_title": title, "starts_at": lot.event_at}

    catalog = _CATALOGS.get(lot.event_at)
    if not catalog or not re.fullmatch(r"[0-9]{1,4}", lot.lot_number or ""):
        return None
    if int(lot.lot_number) not in catalog.numbers:
        return None
    if lot.source == "Drouot":
        if (lot.auction_house != catalog.drouot_house or _drouot_catalog(lot) != catalog.drouot_id
                or not re.fullmatch(r"[0-9]+", lot.source_lot_id or "")
                or not drouot_url_matches(lot.lot_url, "l", lot.source_lot_id)):
            return None
    elif lot.source == "Invaluable":
        evidence = _invaluable_catalog(lot)
        if evidence != ((catalog.invaluable_house, lot.event_at, catalog.photo_prefix), ""):
            return None
    else:
        return None
    url = f"https://drouot.com/en/v/{catalog.drouot_id}"
    return {"identity": "linked:" + url, "catalog_url": url,
            "session_title": catalog.title, "starts_at": lot.event_at}
