"""Evidence-backed presentation times; never modify a provider's saved timestamp."""

import re
import unicodedata
from datetime import date, datetime, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo


TIMETABLE_URL = "https://www.dobiaschofsky.com/g246.html"
# A-142, Friday 6 November 2026, published house timetable. Each time is
# the start of a numbered block, not an exact promise for every lot in it.
# Captured 2026-11-05; the date and sale checks below prevent later-sale reuse.
_BLOCKS = (
    (3001, 3030, "09:00", "09:00"), (3031, 3060, "09:15", "09:00"),
    (3061, 3090, "09:30", "09:00"), (3091, 3120, "09:45", "09:00"),
    (3121, 3150, "10:00", "09:00"), (3151, 3180, "10:15", "09:00"),
    (3181, 3210, "10:30", "09:00"), (3211, 3240, "10:45", "09:00"),
    (3241, 3270, "11:00", "09:00"), (3271, 3290, "11:15", "09:00"),
    (3401, 3422, "14:00", "14:00"), (3423, 3445, "14:15", "14:00"),
    (3446, 3467, "14:30", "14:00"), (3468, 3490, "14:45", "14:00"),
    (3491, 3512, "15:00", "14:00"), (3513, 3535, "15:15", "14:00"),
    (3536, 3557, "15:30", "14:00"), (3558, 3580, "15:45", "14:00"),
    (3581, 3587, "16:00", "14:00"),
    (3701, 3723, "18:00", "18:00"), (3724, 3745, "18:15", "18:00"),
    (3746, 3768, "18:30", "18:00"), (3769, 3790, "18:45", "18:00"),
    (3791, 3813, "19:00", "18:00"), (3814, 3835, "19:15", "18:00"),
    (3836, 3858, "19:30", "18:00"), (3859, 3880, "19:45", "18:00"),
    (3881, 3903, "20:00", "18:00"),
)
# These two original Invaluable observations omit sale_url. Their source
# IDs, catalogue lot numbers and public lot links were independently verified.
_MISSING_SALE_LOTS = {
    "206830784": (3443, "217ffff078"),
    "206830861": (3520, "f180321dbe"),
}


def published_lot_arrival(lot):
    event = lot.event_at
    if lot.is_all_day or not event or event.utcoffset() is None:
        return None
    if event.astimezone(ZoneInfo("Europe/Zurich")).date() != date(2026, 11, 6):
        return None
    house = " ".join(unicodedata.normalize("NFKC", lot.auction_house).casefold().split())
    if house not in {"dobiaschofsky auktionen", "dobiaschofsky auktionen ag"}:
        return None
    number_match = re.fullmatch(r"([0-9]+)[A-Za-z]*", str(lot.lot_number).strip())
    if not number_match:
        return None
    number = int(number_match[1])
    try:
        sale = urlsplit(lot.sale_url)
        if lot.source == "Drouot":
            matches_sale = sale.scheme == "https" and sale.hostname in {"drouot.com", "www.drouot.com"} and bool(
                re.fullmatch(r"/(?:[a-z]{2}/)?v/186532/?", sale.path)
            )
        elif lot.source == "Invaluable":
            # This catalogue is the afternoon International Art session;
            # the Drouot catalogue covers all three sessions of the day.
            if not 3401 <= number <= 3587:
                return None
            matches_sale = sale.scheme == "https" and sale.hostname in {"invaluable.com", "www.invaluable.com"} and sale.path.rstrip("/") == "/catalog/A4TLQ5DFCI"
            if not lot.sale_url and str(lot.source_lot_id) in _MISSING_SALE_LOTS:
                expected_number, ref = _MISSING_SALE_LOTS[str(lot.source_lot_id)]
                link = urlsplit(lot.lot_url)
                matches_sale = number == expected_number and link.scheme == "https" and link.hostname in {"invaluable.com", "www.invaluable.com"} and link.path.rstrip("/").endswith(f"-{number}-c-{ref}")
        else:
            matches_sale = False
    except ValueError:
        return None
    if not matches_sale:
        return None
    for first, last, block_time, session_time in _BLOCKS:
        if first <= number <= last:
            def instant(clock):
                hour, minute = map(int, clock.split(":"))
                return datetime(2026, 11, 6, hour, minute, tzinfo=ZoneInfo("Europe/Zurich")).astimezone(timezone.utc).isoformat()

            return {
                "kind": "published_timetable",
                "at": instant(block_time),
                "session_start_at": instant(session_time),
                "first_lot": first,
                "last_lot": last,
                "source_url": TIMETABLE_URL,
            }
    return None
