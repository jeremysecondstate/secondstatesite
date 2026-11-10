"""Evidence-backed presentation times; never modify a provider's saved timestamp."""

import re
import unicodedata
from datetime import date, datetime, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo


TIMETABLE_URL = "https://www.dobiaschofsky.com/g246.html"
HERITAGE_8256_URL = "https://fineart.ha.com/c/auction-home.zx?saleNo=8256"
ZWAAN_117_TIMETABLE_URL = "https://veilinggebouw.dezwaan.nl/wp-content/uploads/Orde-der-veiling-V117-2.pdf"
# V117's November 12 sessions restart numbering at 6000, 6400 and 6800.
# The house publishes session starts, not a lot pace. Keep the existing
# one-minute assumption explicit, separate from Heritage's published pace.
_ZWAAN_117_SESSIONS = ((6000, 6233, 10), (6400, 6586, 14), (6800, 7015, 19))
_ZWAAN_MISSING_SALE_LOTS = {
    "207089942": (6013, "ec74e69e12"),
    "207090023": (6094, "8ce2d40a25"),
    "207090363": (6816, "b76b923688"),
    "207090373": (6826, "26fe2ebe4b"),
    "207090378": (6831, "0412df604c"),
    "207090388": (6841, "9a66b5395d"),
    "207090419": (6872, "5c79b43c74"),
    "207090428": (6881, "b8c66dea46"),
    "207090449": (6902, "8e0a8dea68"),
    "207090473": (6926, "daa06ad00c"),
    "207090487": (6940, "699a5dbdf1"),
    "207090491": (6944, "132b9d48e9"),
    "207090507": (6960, "e4323fd328"),
}
# A-142, 5-6 November 2026, published house timetable. Each time is
# the start of a numbered block, not an exact promise for every lot in it.
# Captured 2026-11-05; the date and sale checks below prevent later-sale reuse.
_BLOCKS = {
    date(2026, 11, 5): (
        (2001, 2032, "09:00", "09:00"), (2033, 2043, "09:15", "09:00"),
        (2044, 2057, "09:20", "09:00"),
        (2201, 2230, "09:25", "09:00"), (2231, 2261, "09:40", "09:00"),
        (2262, 2291, "09:55", "09:00"), (2292, 2321, "10:10", "09:00"),
        (2322, 2351, "10:25", "09:00"), (2352, 2382, "10:40", "09:00"),
        (2383, 2412, "10:55", "09:00"), (2413, 2442, "11:10", "09:00"),
        (2443, 2472, "14:00", "14:00"), (2473, 2501, "14:15", "14:00"),
        (2502, 2531, "14:30", "14:00"), (2532, 2559, "14:45", "14:00"),
        (2560, 2589, "15:00", "14:00"), (2601, 2617, "15:15", "14:00"),
        (2701, 2731, "15:25", "14:00"), (2732, 2762, "15:40", "14:00"),
        (2763, 2794, "15:55", "14:00"), (2795, 2804, "16:10", "14:00"),
        (2901, 2927, "16:15", "14:00"), (2928, 2936, "16:30", "14:00"),
    ),
    date(2026, 11, 6): (
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
    ),
}
_SALE_IDS = {
    date(2026, 11, 5): ("186531", "JS1Q8ZMLH2"),
    date(2026, 11, 6): ("186532", "A4TLQ5DFCI"),
}
# These two original Invaluable observations omit sale_url. Their source
# IDs, catalogue lot numbers and public lot links were independently verified.
_MISSING_SALE_LOTS = {
    "206830784": (3443, "217ffff078"),
    "206830861": (3520, "f180321dbe"),
}


def _zwaan_session_estimate(lot):
    event = lot.event_at
    if lot.is_all_day or not event or event.utcoffset() is None:
        return None
    if event.astimezone(ZoneInfo("Europe/Amsterdam")).date() != date(2026, 11, 12):
        return None
    house = " ".join(unicodedata.normalize("NFKC", lot.auction_house).casefold().split())
    if house not in {"veilinggebouw de zwaan", "de zwaan amsterdam"}:
        return None
    match = re.fullmatch(r"([0-9]+)[A-Za-z]*", str(lot.lot_number).strip())
    if not match:
        return None
    number = int(match[1])
    try:
        sale = urlsplit(lot.sale_url)
        if lot.source == "Drouot":
            matches_sale = sale.scheme == "https" and sale.hostname in {"drouot.com", "www.drouot.com"} and bool(
                re.fullmatch(r"/(?:[a-z]{2}/)?v/186921(?:/[^/]+)?/?", sale.path)
            )
        elif lot.source == "Invaluable":
            matches_sale = sale.scheme == "https" and sale.hostname in {"invaluable.com", "www.invaluable.com"} and sale.path.rstrip("/") == "/catalog/9ESB0TMK4J"
            if not lot.sale_url:
                # These retained source observations omit sale_url. Require their
                # verified provider ID, lot number and public link together.
                expected_number, ref = _ZWAAN_MISSING_SALE_LOTS.get(str(lot.source_lot_id), (None, None))
                link = urlsplit(lot.lot_url)
                matches_sale = number == expected_number and link.scheme == "https" and link.hostname in {"invaluable.com", "www.invaluable.com"} and bool(
                    re.fullmatch(rf"/auction-lot/[^/]+-{number}-c-{ref}/?", link.path)
                )
        else:
            matches_sale = False
    except ValueError:
        return None
    if not matches_sale:
        return None
    for first, last, hour in _ZWAAN_117_SESSIONS:
        if first <= number <= last:
            start = datetime(2026, 11, 12, hour, tzinfo=ZoneInfo("Europe/Amsterdam"))
            return {
                "kind": "session_estimate",
                "session_start_at": start.astimezone(timezone.utc).isoformat(),
                "first_lot": first,
                "last_lot": last,
                "lots_per_hour": 60,
                "source_url": ZWAAN_117_TIMETABLE_URL,
            }
    return None


def sale_arrival_estimate(lot):
    """Supply verified sale start/pace without replacing the source's timestamp."""
    zwaan = _zwaan_session_estimate(lot)
    if zwaan:
        return zwaan
    # Heritage 8256, Tiffany, Lalique & Art Glass: the official session starts
    # at 11 AM Central on Nov 11 and lists approximately 54 lots/hour, 79001-79230.
    # Drouot 187633 lists its proxy-bid cutoff instead. Keep that raw time and
    # use the house's session only for arrival estimates, not promised times.
    event = lot.event_at
    if lot.is_all_day or not event or event.utcoffset() is None:
        return None
    if event.astimezone(ZoneInfo("America/Chicago")).date() != date(2026, 11, 11):
        return None
    house = " ".join(unicodedata.normalize("NFKC", lot.auction_house).casefold().split())
    if lot.source != "Drouot" or house != "heritage auctions":
        return None
    number_match = re.fullmatch(r"([0-9]+)[A-Za-z]*", str(lot.lot_number).strip())
    if not number_match or not 79001 <= int(number_match[1]) <= 79230:
        return None
    try:
        sale = urlsplit(lot.sale_url)
        matches_sale = sale.scheme == "https" and sale.hostname in {"drouot.com", "www.drouot.com"} and bool(
            re.fullmatch(r"/(?:[a-z]{2}/)?v/187633(?:/[^/]+)?/?", sale.path)
        )
    except ValueError:
        return None
    if not matches_sale:
        return None
    return {
        "session_start_at": "2026-11-11T17:00:00+00:00",
        "first_lot": 79001,
        "last_lot": 79230,
        "lots_per_hour": 54,
        "source_url": HERITAGE_8256_URL,
    }


def published_lot_arrival(lot):
    event = lot.event_at
    if lot.is_all_day or not event or event.utcoffset() is None:
        return None
    sale_day = event.astimezone(ZoneInfo("Europe/Zurich")).date()
    if sale_day not in _BLOCKS:
        return None
    house = " ".join(unicodedata.normalize("NFKC", lot.auction_house).casefold().split())
    if house not in {"dobiaschofsky auktionen", "dobiaschofsky auktionen ag"}:
        return None
    number_match = re.fullmatch(r"([0-9]+)[A-Za-z]*", str(lot.lot_number).strip())
    if not number_match:
        return None
    number = int(number_match[1])
    drouot_sale, invaluable_sale = _SALE_IDS[sale_day]
    try:
        sale = urlsplit(lot.sale_url)
        if lot.source == "Drouot":
            matches_sale = sale.scheme == "https" and sale.hostname in {"drouot.com", "www.drouot.com"} and bool(
                re.fullmatch(rf"/(?:[a-z]{{2}}/)?v/{drouot_sale}/?", sale.path)
            )
        elif lot.source == "Invaluable":
            # Nov 5's catalogue covers the whole print day. Nov 6's
            # Invaluable catalogue is only the afternoon International Art session.
            if sale_day == date(2026, 11, 6) and not 3401 <= number <= 3587:
                return None
            matches_sale = sale.scheme == "https" and sale.hostname in {"invaluable.com", "www.invaluable.com"} and sale.path.rstrip("/") == f"/catalog/{invaluable_sale}"
            if sale_day == date(2026, 11, 6) and not lot.sale_url and str(lot.source_lot_id) in _MISSING_SALE_LOTS:
                expected_number, ref = _MISSING_SALE_LOTS[str(lot.source_lot_id)]
                link = urlsplit(lot.lot_url)
                matches_sale = number == expected_number and link.scheme == "https" and link.hostname in {"invaluable.com", "www.invaluable.com"} and link.path.rstrip("/").endswith(f"-{number}-c-{ref}")
        else:
            matches_sale = False
    except ValueError:
        return None
    if not matches_sale:
        return None
    for first, last, block_time, session_time in _BLOCKS[sale_day]:
        if first <= number <= last:
            def instant(clock):
                hour, minute = map(int, clock.split(":"))
                return datetime(sale_day.year, sale_day.month, sale_day.day, hour, minute, tzinfo=ZoneInfo("Europe/Zurich")).astimezone(timezone.utc).isoformat()

            return {
                "kind": "published_timetable",
                "at": instant(block_time),
                "session_start_at": instant(session_time),
                "first_lot": first,
                "last_lot": last,
                "source_url": TIMETABLE_URL,
            }
    return None
