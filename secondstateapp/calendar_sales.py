"""Verified sale times and catalog identities for the Calendar."""

import re
from datetime import date, datetime, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from .calendar_sessions_2026 import SESSION_TIMES, corrected_session_time, drouot_url_matches


# Invaluable search captures for all 196 watched lots in catalog 821739
# agree on dateTimeUTCUnix=1794164400 (2026-11-08 19:00 UTC). Their
# different endTimeUTCUnix values were imported as event_at. Without this
# sale identity, each closing time becomes a separate Calendar auction.
# Scope this evidence to the verified house, catalog and day; do not infer
# that arbitrary same-house lots or reused photographs belong to one sale.
_ALYES_START = datetime(2026, 11, 8, 19, tzinfo=timezone.utc)
_ALYES_IMAGE = re.compile(r"/housePhotos/Alyes/39/821739/H21147-[A-Za-z0-9_-]+\.jpg")


def calendar_event_at(event_at, *, source, auction_house, sale_url, is_all_day, source_lot_id="", lot_number="",
                      lot_url="", image_url=""):
    # Drouot catalog 188631 supplied 03:00 CET. Templum publishes 15:00
    # in Barcelona for this live sale, also confirmed by the Invaluable lots.
    # https://templumauctions.com/auction/312-gran-subasta-de-es/
    if (
        event_at == datetime(2026, 12, 3, 2, tzinfo=timezone.utc)
        and not is_all_day
        and source == "Drouot"
        and auction_house == "Templum Fine art Auction"
        and drouot_url_matches(sale_url, "v", "188631")
    ):
        return datetime(2026, 12, 3, 14, tzinfo=timezone.utc)
    return corrected_session_time(
        event_at, source=source, auction_house=auction_house, sale_url=sale_url,
        is_all_day=is_all_day, source_lot_id=source_lot_id, lot_number=lot_number,
        lot_url=lot_url, image_url=image_url,
    )


def combined_catalog_starts(lots):
    """Return both represented starts when one Drouot catalog covers two sessions."""
    first = lots[0]
    if first.source != "Drouot" or not first.sale_url or len(lots) < 2:
        return ()
    for rule in SESSION_TIMES:
        if rule.reported_by != "Drouot" or rule.lot_numbers is None or rule.house != first.auction_house:
            continue
        if not drouot_url_matches(first.sale_url, "v", rule.drouot_catalog):
            continue
        if any(lot.is_all_day or lot.source != first.source or lot.auction_house != rule.house for lot in lots):
            return ()
        by_time = {lot.event_at: lot for lot in lots}
        if by_time.keys() == {rule.reported, rule.published}:
            return tuple(by_time[start] for start in sorted(by_time))
    return ()


def verified_sale(lot):
    """Return presentation metadata only for the corroborated missing sale."""
    if (lot.sale_url or lot.source != "Invaluable"
            or " ".join(lot.auction_house.split()).casefold() != "alyes auctions"
            or not lot.event_at or lot.event_at.tzinfo is None or lot.is_all_day):
        return None
    if lot.event_at.astimezone(ZoneInfo("America/Los_Angeles")).date() != date(2026, 11, 8):
        return None
    try:
        image = urlsplit(lot.image_url)
        link = urlsplit(lot.lot_url)
        if (image.scheme != "https" or image.netloc != "image.invaluable.com"
                or not _ALYES_IMAGE.fullmatch(image.path)
                or link.scheme != "https" or link.netloc not in {"www.invaluable.com", "invaluable.com"}
                or not re.fullmatch(r"/auction-lot/[^/]+-\d+-c-[a-f0-9]+/?", link.path)):
            return None
    except ValueError:
        return None
    return {"identity": "invaluable:821739", "starts_at": _ALYES_START}
