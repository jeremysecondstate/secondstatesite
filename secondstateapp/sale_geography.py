"""Sale geography for Calendar browsing, without rewriting source observations.

Explicit sale location takes precedence. Empty/online-only locations can use an
exact, evidence-backed house alias. International houses deliberately have no
global fallback: the country of their headquarters is not a sale location.
"""

import json
import re
import unicodedata
from pathlib import Path


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
    "IL": {"tel aviv", "jerusalem"},
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


def sale_geography(lot):
    """Return region/country from explicit location or a verified exact house.

    Unknown locations never silently become "outside_us". A nonempty,
    unresolved sale location is also not overridden by the house's usual
    country. No network requests, database reads or source mutation occur.
    """
    location = getattr(lot, "location", "") or ""
    country = _location_country(location)
    if not country and _key(location) in _ONLINE_LOCATIONS:
        country = _HOUSE_COUNTRIES.get(_key(getattr(lot, "auction_house", "")), "")
    return {
        "region": "us" if country == "US" else "outside_us" if country else "unknown",
        "country_code": country,
    }

