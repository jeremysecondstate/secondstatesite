"""Published session times shared by the importer and data migration 0056.

Keep these historical rules stable when adding corrections for later sales.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit


def drouot_url_matches(url, kind, identity):
    try:
        parsed = urlsplit(url or "")
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.netloc in {"drouot.com", "www.drouot.com"}
        and re.fullmatch(r"/[a-z]{2}/" + kind + "/" + identity + r"(?:-[^/]+)?/?", parsed.path) is not None
    )


def invaluable_image_catalog_matches(*, sale_url, lot_url, image_url, lot_number, catalog_path):
    """Identify a missing catalog from its provider-hosted image and numbered lot link."""
    if sale_url or not re.fullmatch(r"[0-9]+", str(lot_number)):
        return False
    try:
        image = urlsplit(image_url or "")
        link = urlsplit(lot_url or "")
    except ValueError:
        return False
    directory, _, filename = image.path.rpartition("/")
    return (
        image.scheme == "https" and image.netloc == "image.invaluable.com"
        and directory == catalog_path and re.fullmatch(r"H[0-9]+-[A-Za-z0-9_-]+\.jpg", filename) is not None
        and link.scheme == "https" and link.netloc in {"www.invaluable.com", "invaluable.com"}
        and re.fullmatch(rf"/auction-lot/[^/]+-{lot_number}-c-[a-f0-9]+/?", link.path) is not None
    )


@dataclass(frozen=True)
class SessionTime:
    house: str
    reported: datetime | None
    published: datetime
    drouot_catalog: str = ""
    lot_numbers: range | None = None
    invaluable_catalog_path: str = ""
    invaluable_lots: tuple[tuple[str, str], ...] = ()  # (source_lot_id, catalog lot number)
    reported_by: str = "Drouot"


UTC = timezone.utc
PUBLISHED_SESSIONS = (
    # The entire Fine Pictures, Prints & Sculptures auction starts at 11:00 GMT.
    # https://www.dawsonsauctions.co.uk/auction/details/dawson10279-fine-pictures-prints--sculptures/?au=360
    SessionTime("Dawson's Auctioneers", datetime(2026, 11, 26, 9, 30, tzinfo=UTC),
                datetime(2026, 11, 26, 11, tzinfo=UTC), drouot_catalog="187924"),
    # The Milan catalog combines two sessions. Lots 201–278 open at 16:00 CET.
    # https://www.krusoart.com/?page_id=466&codAsta=0139B&project=dettaglio-asta
    SessionTime("Kruso Art", datetime(2026, 11, 25, 10, tzinfo=UTC),
                datetime(2026, 11, 25, 15, tzinfo=UTC), drouot_catalog="188068", lot_numbers=range(201, 279),
                invaluable_catalog_path="/housePhotos/ArtRite/41/822741"),
    # https://www.lempertz.com/en/catalogues/detail/1303-1-day-sale-modern-art.html
    SessionTime("Lempertz", None, datetime(2026, 12, 5, 10, tzinfo=UTC), drouot_catalog="187112",
                lot_numbers=range(100, 318), invaluable_catalog_path="/housePhotos/Lempertz/82/821482"),
    # Cologne's Contemporary Day Sale starts at 14:00 CET, after the Modern session.
    # https://www.lempertz.com/en/catalogues/detail/1303-2-day-sale-contemporary-art.html
    SessionTime("Lempertz", datetime(2026, 12, 5, 10, tzinfo=UTC),
                datetime(2026, 12, 5, 13, tzinfo=UTC), drouot_catalog="187112", lot_numbers=range(400, 586),
                invaluable_catalog_path="/housePhotos/Lempertz/83/821483"),
    # Tokyo's regular sale #261210 starts at 15:00 JST. M-Live opens at noon.
    # https://mallet.co.jp/news/detail/571
    # https://mallet-i.com/auction
    SessionTime("Mallet Auction", datetime(2026, 12, 10, 3, tzinfo=UTC),
                datetime(2026, 12, 10, 6, tzinfo=UTC), drouot_catalog="188574", lot_numbers=range(1, 91)),
    SessionTime("Mallet Auction", None, datetime(2026, 12, 10, 3, tzinfo=UTC), drouot_catalog="188574",
                lot_numbers=range(1001, 1092), invaluable_catalog_path="/housePhotos/malletauctionjapan/47/823047"),
    # These Invaluable observations lack catalog URLs. Match stable source IDs
    # and lot numbers verified in the house's two separate Munich day sales.
    # https://auktionen.karlundfaber.de/en/auction/41/lots (11:00 CET)
    SessionTime("Karl & Faber", datetime(2026, 12, 4, 13, tzinfo=UTC),
                datetime(2026, 12, 4, 10, tzinfo=UTC), reported_by="Invaluable", drouot_catalog="187125",
                invaluable_catalog_path="/housePhotos/Karl-Faber/34/821434", lot_numbers=range(600, 735),
                invaluable_lots=(("207499898", "644"), ("207499957", "703"))),
    # https://auktionen.karlundfaber.de/en/auction/40/lots (14:00 CET)
    SessionTime("Karl & Faber", datetime(2026, 12, 4, 15, tzinfo=UTC),
                datetime(2026, 12, 4, 13, tzinfo=UTC), reported_by="Invaluable", drouot_catalog="188024",
                invaluable_catalog_path="/housePhotos/Karl-Faber/35/821435", lot_numbers=range(800, 880),
                invaluable_lots=(("207500014", "814"), ("207500019", "819"), ("207500041", "841"),
                                 ("207500042", "842"), ("207500051", "851"), ("207500069", "869"))),
)
SESSION_TIMES = tuple(session for session in PUBLISHED_SESSIONS if session.reported is not None)
NUMBERED_SESSIONS = {
    (session.house, session.published): session for session in PUBLISHED_SESSIONS
    if session.lot_numbers is not None and session.lot_numbers.start > 1
}


def corrected_session_time(event_at, *, source, auction_house, sale_url, lot_number, source_lot_id, is_all_day,
                           lot_url="", image_url=""):
    if is_all_day:
        return event_at
    for rule in SESSION_TIMES:
        if source != rule.reported_by or auction_house != rule.house or event_at != rule.reported:
            continue
        if source == "Invaluable" and not sale_url and (source_lot_id, lot_number) in rule.invaluable_lots:
            return rule.published
        if rule.lot_numbers is not None and (
            not re.fullmatch(r"[0-9]+", lot_number or "") or int(lot_number) not in rule.lot_numbers
        ):
            continue
        if source == "Drouot" and rule.drouot_catalog and drouot_url_matches(sale_url, "v", rule.drouot_catalog):
            return rule.published
        if source == "Invaluable" and rule.invaluable_catalog_path and invaluable_image_catalog_matches(
            sale_url=sale_url, lot_url=lot_url, image_url=image_url,
            lot_number=lot_number, catalog_path=rule.invaluable_catalog_path,
        ):
            return rule.published
    return event_at
