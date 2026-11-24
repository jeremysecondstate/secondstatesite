"""Verified Calendar display numbers without changing imported lot identities."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from .calendar_sales import drouot_url_matches


_DROUOT_NUMBERS = {
    # https://drouot.com/fr/l/36007953
    "36007953": ("Quai des Enchères", "187811", date(2026, 11, 20), "97", "97-1"),
    # https://www.interencheres.com/art-decoration/tableaux-anciens-et-modernes-estampes-sculptures-et-tapis-693682/lot-89946549.html
    "36035570": ("Les Andelys Enchères", "188346", date(2026, 12, 12), "601", "601-1"),
    # Artcurial lists Jim Dine's Pinocchio as 75-b and James Turrell's aquatint as 75.
    # https://www.artcurial.com/en/sales/6573/lots/75-b
    # https://drouot.com/fr/v/187761-limited-edition
    "35815049": ("Artcurial", "187761", date(2026, 11, 24), "75", "75-b"),
}


def calendar_lot_number(lot):
    """Return a narrowly verified display correction, otherwise the raw number."""
    correction = _DROUOT_NUMBERS.get(lot.source_lot_id)
    if lot.source.casefold() != "drouot" or correction is None:
        return lot.lot_number
    house, sale_id, day, raw_number, display_number = correction
    event_at = lot.event_at
    if (
        lot.auction_house == house and lot.lot_number == raw_number
        and isinstance(event_at, datetime) and event_at.tzinfo is not None
        and event_at.astimezone(ZoneInfo("Europe/Paris")).date() == day
        and drouot_url_matches(lot.sale_url, "v", sale_id)
        and drouot_url_matches(lot.lot_url, "l", lot.source_lot_id)
    ):
        return display_number
    return lot.lot_number
