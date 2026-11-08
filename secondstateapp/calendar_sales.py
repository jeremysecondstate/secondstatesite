"""Verified sale metadata for Calendar display; imported lots stay unchanged."""

import re
from datetime import date, datetime, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo


# Invaluable search captures for all 196 watched lots in catalog 821739
# agree on dateTimeUTCUnix=1794164400 (2026-11-08 19:00 UTC). Their
# different endTimeUTCUnix values were imported as event_at. Without this
# sale identity, each closing time becomes a separate Calendar auction.
# Scope this evidence to the verified house, catalog and day; do not infer
# that arbitrary same-house lots or reused photographs belong to one sale.
_ALYES_START = datetime(2026, 11, 8, 19, tzinfo=timezone.utc)
_ALYES_IMAGE = re.compile(r"/housePhotos/Alyes/39/821739/H21147-[A-Za-z0-9_-]+\.jpg")


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
