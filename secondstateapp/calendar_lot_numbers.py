"""Verified Calendar display numbers without changing imported lot identities."""

from datetime import date, datetime
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo


def _drouot_identity(url, kind, identity):
    try:
        parsed = urlsplit(url or "")
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.netloc in {"drouot.com", "www.drouot.com"}
        and re.fullmatch(r"/[a-z]{2}/" + kind + "/" + identity + r"(?:-[^/]+)?/?", parsed.path) is not None
    )


def calendar_lot_number(lot):
    """Return a narrowly verified display correction, otherwise the raw number."""
    number = lot.lot_number
    event_at = lot.event_at
    # Verified November 16, 2026 from the visible lot heading and sale link:
    # https://drouot.com/fr/l/36007953
    # https://drouot.com/fr/v/187811-arts-decoratifs-du-xxe-design
    # Leger's Couple, edition 482/600, is 97-1; Miro's El Innocente is 97.
    # The search observation supplied only 97. Preserve that source value.
    if (
        lot.source.casefold() == "drouot"
        and lot.source_lot_id == "36007953"
        and lot.auction_house == "Quai des Enchères"
        and number == "97"
        and isinstance(event_at, datetime) and event_at.tzinfo is not None
        and event_at.astimezone(ZoneInfo("Europe/Paris")).date() == date(2026, 11, 20)
        and _drouot_identity(lot.sale_url, "v", "187811")
        and _drouot_identity(lot.lot_url, "l", "36007953")
    ):
        return "97-1"
    # The house's December 12 sale publishes The Lion, edition 115/195,
    # as 601-1; the separate Pantagruel's Humorous Dreams remains lot 601.
    # https://www.interencheres.com/art-decoration/tableaux-anciens-et-modernes-estampes-sculptures-et-tapis-693682/lot-89946549.html
    # https://www.interencheres.com/art-decoration/tableaux-anciens-et-modernes-estampes-sculptures-et-tapis-693682/lot-89946548.html
    if (
        lot.source.casefold() == "drouot"
        and lot.source_lot_id == "36035570"
        and lot.auction_house == "Les Andelys Enchères"
        and number == "601"
        and isinstance(event_at, datetime) and event_at.tzinfo is not None
        and event_at.astimezone(ZoneInfo("Europe/Paris")).date() == date(2026, 12, 12)
        and _drouot_identity(lot.sale_url, "v", "188346")
        and _drouot_identity(lot.lot_url, "l", "36035570")
    ):
        return "601-1"
    return number
