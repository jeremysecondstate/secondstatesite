"""Calendar catalog identities corroborated by reviewed physical-lot links."""

import re
from collections import defaultdict
from urllib.parse import urlsplit

from .calendar_sessions_2026 import PUBLISHED_SESSIONS, drouot_url_matches


_DROUOT_HOSTS = {"drouot.com", "www.drouot.com"}
_INVALUABLE_HOSTS = {"invaluable.com", "www.invaluable.com"}
_PHOTO = re.compile(r"(/housePhotos/[A-Za-z0-9_-]+/[0-9]+/[0-9]+/H[0-9]+)-[A-Za-z0-9_-]+\.(?i:jpg)")
_LEMPERTZ_SESSIONS = {
    "/housePhotos/Lempertz/82/821482": (
        "Day Sale – Modern Art", "https://www.lempertz.com/en/catalogues/detail/1303-1-day-sale-modern-art.html",
    ),
    "/housePhotos/Lempertz/83/821483": (
        "Day Sale – Contemporary Art", "https://www.lempertz.com/en/catalogues/detail/1303-2-day-sale-contemporary-art.html",
    ),
}
_MULTI_SESSION = {
    (rule.drouot_catalog, rule.published): rule for rule in PUBLISHED_SESSIONS
    if rule.drouot_catalog in {"187112", "188574"}
}


def _provider_path(url, hosts):
    try:
        parsed = urlsplit(url or "")
    except ValueError:
        return ""
    return parsed.path if parsed.scheme == "https" and parsed.netloc in hosts else ""


def _drouot_catalog(lot):
    path = _provider_path(lot.sale_url, _DROUOT_HOSTS)
    match = re.fullmatch(r"/[a-z]{2}/v/([0-9]+)(?:-[^/]+)?/?", path)
    return match[1] if match else ""


def _invaluable_catalog(lot):
    number = lot.lot_number
    if not re.fullmatch(r"[0-9]+[a-zA-Z]?", number or ""):
        return None
    lot_path = _provider_path(lot.lot_url, _INVALUABLE_HOSTS)
    if not re.fullmatch(rf"/auction-lot/[^/]+-(?i:{number})-c-[a-fA-F0-9]{{10}}/?", lot_path):
        return None
    photo = _PHOTO.fullmatch(_provider_path(lot.image_url, {"image.invaluable.com"}))
    if not photo:
        return None
    ref = ""
    if lot.sale_url:
        path = _provider_path(lot.sale_url, _INVALUABLE_HOSTS)
        match = re.fullmatch(r"/(?:catalog/|auction-catalog/[^/]+_)([a-zA-Z0-9]{10})/?", path)
        if not match:
            return None
        ref = match[1].lower()
    return (lot.auction_house, lot.event_at, photo[1]), ref


def _in_number_range(lot, rule):
    return re.fullmatch(r"[0-9]+", lot.lot_number or "") and int(lot.lot_number) in rule.lot_numbers


def _matching_lot(copy, survivor):
    # Drouot sometimes separates a letter suffix, e.g. 293-A versus 293A.
    number = re.sub(r"(?<=[0-9])[ -](?=[A-Za-z]$)", "", copy.lot_number.strip())
    return (
        number.casefold() == survivor.lot_number.casefold()
        and re.fullmatch(r"[0-9]+", copy.source_lot_id)
        and drouot_url_matches(copy.lot_url, "l", copy.source_lot_id)
    )


class LinkedCatalogs:
    """One request's catalog lookup, indexed by provider, exact house and session."""

    def __init__(self, copies):
        photos_by_catalog = defaultdict(set)
        catalogs_by_photo = defaultdict(set)
        refs_by_photo = defaultdict(set)
        photos_by_ref = defaultdict(set)
        for copy in copies:
            survivor = copy.superseded_by
            catalog = _drouot_catalog(copy)
            evidence = _invaluable_catalog(survivor)
            if (not catalog or not evidence or not copy.auction_house or not survivor.auction_house
                    or not _matching_lot(copy, survivor)):
                continue
            photo, ref = evidence
            rule = _MULTI_SESSION.get((catalog, survivor.event_at))
            if rule and not _in_number_range(survivor, rule):
                continue
            key = (copy.auction_house, catalog)
            photos_by_catalog[key].add(photo)
            catalogs_by_photo[photo].add(key)
            if ref:
                refs_by_photo[photo].add(ref)
                photos_by_ref[ref].add(photo)

        self._drouot = {}
        self._invaluable = {}
        for (house, catalog), photos in photos_by_catalog.items():
            # Normally a catalog must correspond to one photo catalog and one
            # start. The two published multi-session catalogs have exact rules.
            sessions = [(photo, _MULTI_SESSION.get((catalog, photo[1]))) for photo in photos]
            if len(photos) > 1 and (not all(rule for _, rule in sessions)
                                    or len({photo[1] for photo in photos}) != len(photos)):
                continue
            if any(len(catalogs_by_photo[photo]) != 1 or len(refs_by_photo[photo]) > 1
                   or any(len(photos_by_ref[ref]) != 1 for ref in refs_by_photo[photo])
                   for photo in photos):
                continue
            for photo, rule in sessions:
                inv_house, start, prefix = photo
                if catalog in {"187112", "188574"}:
                    if not rule or house != rule.house or inv_house != rule.house:
                        continue
                    directory = rule.invaluable_catalog_path or "/housePhotos/malletauctionjapan/51/823051"
                    if prefix.rsplit("/", 1)[0] != directory:
                        continue
                url = f"https://drouot.com/en/v/{catalog}"
                title = ""
                if catalog == "187112":
                    title, url = _LEMPERTZ_SESSIONS[rule.invaluable_catalog_path]
                sale = {
                    "identity": "linked:" + url, "catalog_url": url, "session_title": title,
                    "starts_at": start, "combined_starts": catalog == "188574",
                }
                self._drouot[house, catalog, start] = (sale, rule)
                self._invaluable[photo] = (sale, rule, refs_by_photo[photo])

    def sale(self, lot):
        if not lot.event_at or lot.is_all_day:
            return None
        if lot.source == "Drouot":
            result = self._drouot.get((lot.auction_house, _drouot_catalog(lot), lot.event_at))
            if not result:
                return None
            sale, rule = result
        elif lot.source == "Invaluable":
            evidence = _invaluable_catalog(lot)
            if not evidence:
                return None
            photo, ref = evidence
            result = self._invaluable.get(photo)
            if not result:
                return None
            sale, rule, refs = result
            if ref and ref not in refs:
                return None
        else:
            return None
        return sale if not rule or _in_number_range(lot, rule) else None
