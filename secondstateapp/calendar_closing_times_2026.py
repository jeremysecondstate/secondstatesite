"""Two published lot closes checked against the catalog and live lot countdown."""

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class PublishedClose:
    house: str
    number: str
    lot_url: str
    image_url: str
    catalog_url: str
    previous: datetime
    published: datetime


UTC = timezone.utc
VERIFIED_AT = datetime(2026, 11, 22, 0, 14, 17, tzinfo=UTC)
# The photo URL binds legacy observations with an empty sale URL to the exact
# catalog. Keep these two historical rules stable for migration 0057.
PUBLISHED_CLOSES = {
    # https://www.auctionzip.com/auction-lot/lot_c739ffc328
    "207710805": PublishedClose(
        house="Weschler's",
        number="528",
        lot_url=("https://www.invaluable.com/auction-lot/after-marc-chagall-russian-french-1887-1985-"
                 "plate-from-vitraux-pour-jerusalem-andre-sauret-monte-carlo-framed-26-x-22-in-66-x-55-9-cm-528-c-c739ffc328"),
        image_url="https://image.invaluable.com/housePhotos/weschlers/51/820351/H0143-LFskgYM2Olmh6j.JPG",
        catalog_url="https://www.invaluable.com/catalog/2vsj20nczp",
        previous=datetime(2026, 11, 24, 17, 12, tzinfo=UTC),
        published=datetime(2026, 11, 24, 17, 11, 45, tzinfo=UTC),
    ),
    # https://www.auctionzip.com/auction-lot/lot_f094cfaf9d
    "207575415": PublishedClose(
        house="Ripley Auctions",
        number="70",
        lot_url=("https://www.invaluable.com/auction-lot/after-georges-braque-french-1882-1963-"
                 "le-gueridon-noir-cubist-still-life-with-fruit-and-guitar-aquatint-etching-"
                 "15-1-2-h-x-25-w-sight-26-1-4-h-x-36-w-frame-70-c-f094cfaf9d"),
        image_url="https://image.invaluable.com/housePhotos/ripleyauctions/52/822652/H0071-LbKUizBe7Vsf98.JPG",
        catalog_url="https://www.invaluable.com/catalog/qs77vvq8yd",
        previous=datetime(2026, 12, 2, 20, 34, 30, tzinfo=UTC),
        published=datetime(2026, 12, 2, 20, 37, 30, tzinfo=UTC),
    ),
}


def corrected_lot_close(event_at, *, source, auction_house, sale_url, is_all_day,
                        source_lot_id, lot_number, lot_url, image_url, observed_at):
    rule = PUBLISHED_CLOSES.get(source_lot_id)
    if (rule is None or source != "Invaluable" or is_all_day or event_at != rule.previous
            or auction_house != rule.house or lot_number != rule.number or lot_url != rule.lot_url
            or (observed_at is not None and observed_at >= VERIFIED_AT)):
        return event_at
    if sale_url and sale_url.rstrip("/") != rule.catalog_url:
        return event_at
    if image_url != rule.image_url and (image_url or not sale_url):
        return event_at
    return rule.published
