"""Sale geography for Calendar browsing, without rewriting source observations.

Native non-USD sales belong to the Outside the U.S. browsing category. Country
metadata comes from explicit sale location or an exact, evidence-backed house
alias for empty/online-only locations. International houses deliberately have
no global country fallback: headquarters are not a sale location.
"""

import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit


def _key(value):
    text = unicodedata.normalize("NFKD", str(value or "")).casefold()
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


_REGISTRY = json.loads(
    (Path(__file__).with_name("data") / "auction_house_countries.json").read_text(encoding="utf-8")
)
_HOUSE_COUNTRIES = {
    _key(name): house["country_code"]
    for house in _REGISTRY["houses"]
    for name in (house["name"], *house.get("aliases", []))
}
_SALE_COUNTRIES = json.loads(
    (Path(__file__).with_name("data") / "auction_sale_countries.json").read_text(encoding="utf-8")
)["sales"]
_COUNTRY_NAMES = {
    "US": ("United States", "United States of America", "USA", "U.S.", "U.S.A."),
    "GB": ("United Kingdom", "Great Britain", "UK", "U.K.", "England", "Scotland", "Wales", "Northern Ireland"),
    "CA": ("Canada",),
    "FR": ("France",),
    "DE": ("Germany", "Deutschland", "Allemagne"),
    "IT": ("Italy", "Italia", "Italie"),
    "ES": ("Spain", "Espana", "Espagne"),
    "PT": ("Portugal",),
    "BE": ("Belgium", "Belgique", "Belgie"),
    "NL": ("Netherlands", "The Netherlands", "Nederland", "Pays Bas"),
    "LU": ("Luxembourg",),
    "CH": ("Switzerland", "Schweiz", "Suisse", "Svizzera"),
    "AT": ("Austria", "Osterreich", "Autriche"),
    "SE": ("Sweden", "Sverige", "Suede"),
    "NO": ("Norway", "Norge", "Norvege"),
    "DK": ("Denmark", "Danmark", "Danemark"),
    "FI": ("Finland", "Finlande", "Suomi"),
    "IE": ("Ireland", "Irlande"),
    "AU": ("Australia", "Australie"),
    "NZ": ("New Zealand", "Nouvelle Zelande"),
    "HK": ("Hong Kong",),
    "CN": ("China", "Chine"),
    "JP": ("Japan", "Japon"),
    "SG": ("Singapore", "Singapour"),
    "KR": ("South Korea", "Republic of Korea"),
    "TW": ("Taiwan",),
    "ZA": ("South Africa",),
    "AE": ("United Arab Emirates", "UAE"),
    "MC": ("Monaco",),
    "GR": ("Greece", "Grece"),
    "PL": ("Poland", "Pologne"),
    "CZ": ("Czech Republic", "Czechia"),
    "HU": ("Hungary",),
    "RO": ("Romania",),
    "BG": ("Bulgaria",),
    "RS": ("Serbia",),
    "HR": ("Croatia",),
    "BR": ("Brazil", "Brasil"),
    "MX": ("Mexico",),
    "IL": ("Israel",),
    "IN": ("India",),
    "AR": ("Argentina",),
    "CO": ("Colombia",),
    "CL": ("Chile",),
    "UY": ("Uruguay",),
}
_COUNTRY_LABELS = {
    _key(name): code for code, names in _COUNTRY_NAMES.items() for name in names
}
# These ISO codes also name US states. A bare address ending ", CA" does not
# establish Canada, and ", DE" can mean Delaware. Require an unambiguous city
# for such codes or a spelled-out country instead.
_AMBIGUOUS_COUNTRY_CODES = {"CA", "DE", "IN", "AR", "CO", "IL"}
_COUNTRY_CODES = set(_COUNTRY_NAMES) - _AMBIGUOUS_COUNTRY_CODES
_COUNTRY_CODES.add("US")
_AMBIGUOUS_CODE_CITIES = {
    "CA": {"toronto", "montreal", "vancouver", "ottawa", "calgary", "edmonton", "quebec"},
    "DE": {"berlin", "heidelberg", "cologne", "koln", "dusseldorf", "munich", "munchen", "hamburg", "frankfurt", "stuttgart"},
    "IN": {"mumbai", "new delhi", "delhi", "kolkata", "bengaluru"},
    "AR": {"buenos aires"},
    "CO": {"bogota", "medellin"},
    "IL": {"tel aviv", "jerusalem", "netanya"},
}
# These labels occur as complete sale locations, rather than inferred words in
# artwork descriptions or titles. New York denotes the US city/state; the
# other labels are not reused for a US state or a country.
_EXACT_LOCATION_COUNTRIES = {
    "new york": "US", "new york city": "US",
    "hong kong": "HK", "stockholm": "SE", "cologne": "DE",
}
_ONLINE_LOCATIONS = {"", "online", "online only", "internet", "virtual"}


def _location_country(location):
    parts = [part.strip() for part in re.split(r"[,;\n]", str(location or "")) if part.strip()]
    if not parts:
        return ""
    # Multiple explicit country labels are ambiguous (e.g. a dual-site sale).
    named_countries = {_COUNTRY_LABELS[_key(part)] for part in parts if _key(part) in _COUNTRY_LABELS}
    named_countries.update(part.upper() for part in parts if part.upper() in _COUNTRY_CODES)
    for index, part in enumerate(parts):
        code = part.upper()
        if code in _AMBIGUOUS_CODE_CITIES and any(
            _key(city) in _AMBIGUOUS_CODE_CITIES[code] for city in parts[:index]
        ):
            named_countries.add(code)
    if len(named_countries) > 1:
        return ""
    tail = _key(parts[-1])
    if tail in _COUNTRY_LABELS:
        return _COUNTRY_LABELS[tail]
    raw_code = parts[-1].strip().upper()
    if raw_code in _COUNTRY_CODES:
        return raw_code
    if raw_code in _AMBIGUOUS_CODE_CITIES:
        if any(_key(part) in _AMBIGUOUS_CODE_CITIES[raw_code] for part in parts[:-1]):
            return raw_code
    if len(parts) == 1:
        return _EXACT_LOCATION_COUNTRIES.get(tail, "")
    return ""


def _source_url(value):
    """Ignore a trailing slash, but retain provider paths and sale queries."""
    try:
        parsed = urlsplit(str(value or ""))
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"}:
        return ""
    return f"{parsed.hostname}{parsed.path.rstrip('/')}" + (f"?{parsed.query}" if parsed.query else "")


def _verified_sale_country(lot):
    event_at = getattr(lot, "event_at", None)
    if isinstance(event_at, datetime):
        day = (event_at.astimezone(timezone.utc) if event_at.tzinfo else event_at).date().isoformat()
    else:
        day = str(event_at or "")[:10]
    house = _key(getattr(lot, "auction_house", ""))
    source = _key(getattr(lot, "source", ""))
    sale_url = _source_url(getattr(lot, "sale_url", ""))
    for sale in _SALE_COUNTRIES:
        if (house, source, day) != (_key(sale["auction_house"]), _key(sale["source"]), sale["date"]):
            continue
        if sale_url and sale_url in {_source_url(url) for url in sale.get("sale_urls", [])}:
            return sale["country_code"]
        # Old imports may have no catalog URL. Exact source identity, lot URL,
        # number, house and date bind these entries to the verified sale.
        if not sale_url:
            known = sale.get("lots", {}).get(str(getattr(lot, "source_lot_id", "")))
            if (
                known
                and str(getattr(lot, "lot_number", "")).strip() == known["lot_number"]
                and _source_url(getattr(lot, "lot_url", "")) == _source_url(known["lot_url"])
            ):
                return sale["country_code"]
    return ""


def sale_geography(lot):
    """Return the browsing region and independently verified country.

    The Calendar's native-currency rule puts non-USD sales outside the US,
    without inventing a specific country. Use only the imported lot.currency;
    USD display conversions and research/sold currencies are not sale currency.
    USD or missing currencies still require location/house evidence. A nonempty,
    unresolved sale location is not overridden by the house's usual country.
    No network requests, database reads or source mutation occur.
    """
    location = getattr(lot, "location", "") or ""
    country = _location_country(location)
    if not country and _key(location) in _ONLINE_LOCATIONS:
        country = _verified_sale_country(lot) or _HOUSE_COUNTRIES.get(_key(getattr(lot, "auction_house", "")), "")
    currency = str(getattr(lot, "currency", "") or "").strip().upper()
    native_foreign_currency = bool(re.fullmatch(r"[A-Z]{3}", currency)) and currency not in {"USD", "XXX"}
    region = "us" if country == "US" else "outside_us" if country else "unknown"
    return {
        "region": "outside_us" if native_foreign_currency else region,
        "country_code": country,
    }

