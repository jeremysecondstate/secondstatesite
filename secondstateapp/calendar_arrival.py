"""Evidence-backed presentation times; never modify a provider's saved timestamp."""

import re
import unicodedata
from datetime import date, datetime, timezone
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo


# Verified sale 609 selection, captured November 11, 2026. Each pair binds
# the source lot number to its stable public SHARE LINK item identity.
_KETTERER_609_ITEMS = {
    1: "126000604", 2: "126000603", 3: "126000602", 4: "126000601",
    5: "126000908", 6: "126000167", 7: "100902390", 8: "100902395",
    9: "123000206", 10: "123000207", 11: "120000252", 12: "120000260",
    13: "126000760", 14: "126000930", 19: "126000588", 20: "126000752",
    31: "126000607", 32: "126000612", 33: "126000614", 34: "126000615",
    35: "126000068", 36: "126000071", 37: "123001044", 38: "123001051",
    45: "126000657", 46: "126000788", 49: "126000909", 50: "126000742",
    51: "125001456", 54: "126000091", 57: "126000605", 61: "126000674",
    62: "126000699", 63: "126000022", 64: "126000201", 65: "126000761",
    66: "126000931", 71: "126000708", 72: "126000709", 77: "122002532",
    78: "126000688", 79: "126000411", 80: "126000807", 81: "126000983",
    82: "125000193", 83: "125001444", 84: "126000735", 86: "126000990",
    87: "126000591", 88: "126000587", 92: "113002338", 93: "126000020",
    94: "126000863", 95: "126000862", 97: "126000667", 98: "119002887",
    99: "126000085", 100: "126000791", 102: "126000775", 104: "126000649",
    105: "126000378", 106: "126000687", 107: "126000935", 108: "126001002",
    111: "126000426", 113: "126000237", 118: "126000090", 120: "126000992",
    123: "126000941", 127: "126000824", 129: "126000277", 131: "122001718",
    134: "126000731", 138: "126000655", 139: "126000986", 141: "126000564",
    142: "126000991", 147: "126000989", 148: "117000067", 149: "126000766",
}

TIMETABLE_URL = "https://www.dobiaschofsky.com/g246.html"
HERITAGE_8256_URL = "https://fineart.ha.com/c/auction-home.zx?saleNo=8256"
ZWAAN_117_TIMETABLE_URL = "https://veilinggebouw.dezwaan.nl/wp-content/uploads/Orde-der-veiling-V117-2.pdf"
HISTORIA_182_TIMETABLE_URL = "https://historia.de/en/auction/182-auction/"
# Auction 182's November 11 timetable restarts at 8000 in the afternoon.
# The house publishes a typical (not guaranteed) pace of 80 lots/hour.
_HISTORIA_182_SESSIONS = ((7350, 7686, 10), (8000, 8377, 15))
# These Invaluable observations have no sale_url. Verified November 11, 2026
# against catalog X05NBF4PNX; bind provider ID, lot number and public link.
_HISTORIA_MISSING_SALE_LOTS = {
    "206926492": (7368, "cd566fd9bb"),
    "206926555": (7431, "a7c1eb0a3f"),
    "206926827": (8016, "a8376b68f2"),
    "206926871": (8060, "a5c8d84ae1"),
    "206926872": (8061, "80adbfa4b6"),
    "206926874": (8063, "8750eba9a0"),
    "206926910": (8099, "494309a1c3"),
    "206926914": (8103, "29d271d654"),
    "206926915": (8104, "08ef8397b9"),
    "206926981": (8170, "5a30ade25e"),
    "206927009": (8198, "3002746e2a"),
    "206927019": (8208, "9492324646"),
    "206927020": (8209, "63d14f2459"),
    "206927029": (8218, "725b2b527b"),
    "206927101": (8290, "444c6654b2"),
}
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


def _historia_session_estimate(lot):
    event = lot.event_at
    if lot.is_all_day or not event or event.utcoffset() is None:
        return None
    if event.astimezone(ZoneInfo("Europe/Berlin")).date() != date(2026, 11, 11):
        return None
    house = " ".join(unicodedata.normalize("NFKC", lot.auction_house).casefold().split())
    if house not in {"historia auctionata", "historia auktionshaus"}:
        return None
    match = re.fullmatch(r"([0-9]+)[A-Za-z]*", str(lot.lot_number).strip())
    if not match:
        return None
    number = int(match[1])
    try:
        sale = urlsplit(lot.sale_url)
        valid_sale_url = sale.scheme == "https" and not sale.username and not sale.password and sale.port is None
        if lot.source == "Drouot":
            matches_sale = valid_sale_url and sale.hostname in {"drouot.com", "www.drouot.com"} and bool(
                re.fullmatch(r"/(?:[a-z]{2}/)?v/186571(?:/[^/]+)?/?", sale.path)
            )
        elif lot.source == "Invaluable":
            matches_sale = valid_sale_url and sale.hostname in {"invaluable.com", "www.invaluable.com"} and sale.path.rstrip("/") == "/catalog/X05NBF4PNX"
            if not lot.sale_url:
                expected_number, ref = _HISTORIA_MISSING_SALE_LOTS.get(str(lot.source_lot_id), (None, None))
                link = urlsplit(lot.lot_url)
                matches_sale = number == expected_number and link.scheme == "https" and not link.username and not link.password and link.port is None and link.hostname in {"invaluable.com", "www.invaluable.com"} and bool(
                    re.fullmatch(rf"/auction-lot/[^/]+-{number}-c-{ref}/?", link.path)
                )
        else:
            matches_sale = False
    except ValueError:
        return None
    if not matches_sale:
        return None
    for first, last, hour in _HISTORIA_182_SESSIONS:
        if first <= number <= last:
            start = datetime(2026, 11, 11, hour, tzinfo=ZoneInfo("Europe/Berlin"))
            return {
                "kind": "published_pace",
                "session_start_at": start.astimezone(timezone.utc).isoformat(),
                "first_lot": first,
                "last_lot": last,
                "lots_per_hour": 80,
                "source_url": HISTORIA_182_TIMETABLE_URL,
            }
    return None


def sale_arrival_estimate(lot):
    """Supply verified sale start/pace without replacing the source's timestamp."""
    zwaan = _zwaan_session_estimate(lot)
    if zwaan:
        return zwaan
    historia = _historia_session_estimate(lot)
    if historia:
        return historia
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
    if lot.source == "Sotheby's":
        return _sothebys_lot_closing(lot)
    if lot.source == "Ketterer Kunst":
        return _ketterer_lot_closing(lot)
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


def _sothebys_lot_closing(lot):
    # DE2640 publishes a separate closing time on each lot page. The saved
    # event is that observed closing, not a sale start to offset by lot number.
    event = lot.event_at
    if event.astimezone(ZoneInfo("Europe/Berlin")).date() != date(2026, 11, 12):
        return None
    if lot.auction_house != "Sotheby's" or not re.fullmatch(r"[1-9][0-9]*", str(lot.lot_number)):
        return None
    if lot.source_lot_id != f"DE2640:{lot.lot_number}":
        return None
    sale_path = "/en/buy/auction/2026/modern-contemporary-discoveries-de2640"
    try:
        sale, link = urlsplit(lot.sale_url), urlsplit(lot.lot_url)
        if any(url.scheme != "https" or url.netloc not in {"www.sothebys.com", "sothebys.com"}
               for url in (sale, link)):
            return None
        if sale.path.rstrip("/") != sale_path or not re.fullmatch(rf"{sale_path}/[^/]+/?", link.path):
            return None
    except ValueError:
        return None
    return {
        "kind": "published_closing",
        "at": event.astimezone(timezone.utc).isoformat(),
        "source_url": lot.lot_url,
    }


def _ketterer_lot_closing(lot):
    # The three published city clocks agree on each saved closing instant.
    # Never derive it from the lot number or the auction's first closing.
    event = lot.event_at
    if event.astimezone(ZoneInfo("Europe/Berlin")).date() != date(2026, 11, 15):
        return None
    if lot.auction_house != "Ketterer Kunst" or not re.fullmatch(r"[1-9][0-9]*", str(lot.lot_number)):
        return None
    item_id = _KETTERER_609_ITEMS.get(int(lot.lot_number))
    if not item_id or lot.source_lot_id != f"609:{lot.lot_number}":
        return None
    try:
        sale, link = urlsplit(lot.sale_url), urlsplit(lot.lot_url)
        if any(url.scheme != "https" or url.netloc != "onlinesale.kettererkunst.com"
               or url.fragment for url in (sale, link)):
            return None
        if sale.path != "/browse.php" or sale.query or link.path != "/item.php":
            return None
        if parse_qs(link.query, keep_blank_values=True) != {"id": [item_id]}:
            return None
    except ValueError:
        return None
    return {
        "kind": "published_closing",
        "at": event.astimezone(timezone.utc).isoformat(),
        "source_url": lot.lot_url,
    }
