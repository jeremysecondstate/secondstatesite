"""Validate public Drouot browser evidence and import it without source requests.

The collector observes Drouot's own lot-search responses and the corresponding
visible cards. Keyword results are not artist attribution. Every returned ID is
accounted for, but only a leading artist credit plus an explicit print medium
can become a Calendar observation.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from html import unescape
import json
import math
from pathlib import Path
import re
from typing import Iterable
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from catalogapp.artprice_artist_links import artist_identity_key, normalize_artist_name
from catalogapp.bookmark_watchlist import BookmarkEntry, parse_netscape_bookmarks
from catalogapp.watchlist_cache import WatchlistCache
from catalogapp.watchlist_models import NormalizedLot, parse_lot_datetime
from catalogapp.watchlist_service import WatchlistMetrics, _retain_missing_static_fields


CAPTURE_FORMAT = "secondstate-drouot-browser-capture"
MAX_CAPTURE_BYTES = 40 * 1024 * 1024
MAX_CAPTURE_PAGES = 2000
MAX_PAGE_LOTS = 100
_SEARCH_PATH = "/en/c/50/lithographs"
_LOT_FIELDS = frozenset({
    "id", "num", "lowEstim", "highEstim", "currentBid", "nextBid", "result", "date",
    "saleType", "saleStatus", "saleId", "auctioneerId", "saleFees", "displayStartingPrice",
    "bidEndDate", "description", "timezone", "currencyId", "slug", "photo",
})
_CARD_FIELDS = frozenset({"id", "url", "heading", "description", "text", "image_url", "price_text", "date_text"})
_PRINT_MEDIUM = re.compile(
    r"\b(?:(?:photo|grano|chromo|grapho)?lithograph(?:ic|ie|y|s|ies)?|lithographie[s]?|etching[s]?|engraving[s]?|"
    r"screen\s?print(?:ed|s)?|silk\s?screen[s]?|serigraph(?:ie|y|s|ies)?|s[eé]rigraphie[s]?|"
    r"gravure[s]?|estampe[s]?|eau[x]?[ -]forte[s]?|aquatin[dt](?:e|s)?|drypoint|"
    r"pointe[ -]s[eè]che|woodcut[s]?|woodblock|stencil\s+print[s]?|linocut[s]?|linogravure[s]?|"
    r"monotype[s]?|monoprint[s]?|gicl[eé]e[s]?|phototype[s]?|photogravure[s]?|zincograph(?:y|s)?|burin|(?:photo|foto)print[s]?|collotype[s]?|pochoir|h[eé]liogravure[s]?|letterpress|offset|printed(?=\s+poster\b)|print[s]?)\b",
    re.IGNORECASE,
)
_QUALIFIED_CREDIT = re.compile(
    r"^\(?(?:after\b|according\s+to\b|attributed(?:\s+to)?\b|attribu[eé](?:e)?(?:\s+[aà])?\b|d[\u2019']?apr[eè]s\b|"
    r"based\s+on(?:\s+(?:a\s+work|works)\s+by)?\b|"
    r"in\s+(?:the\s+)?(?:style|manner|taste)(?:\s+of)?\b|school\s+of\b|entourage(?:\s+de)?\b|"
    r"[eé]cole(?:\s+de)?\b|atelier(?:\s+de)?\b|follower(?:\s+of)?\b|circle\s+of\b|"
    r"homage\s+to\b|hommage\s+[aà]\b)\)?\s*", re.IGNORECASE,
)
_FOLLOWING_QUALIFIER = re.compile(
    r"^[\s,;:.\u2013\u2014-]*(?P<qualifier>\(?(?:after|according\s+to|attributed(?:\s+to)?|"
    r"d[\u2019']?apr[eè]s|attribu[eé](?:e)?(?:\s+[aà])?|circle\s+of|school\s+of|"
    r"in\s+(?:the\s+)?(?:style|manner|taste)(?:\s+of)?|despu[eé]s(?:\s+de)?|naar|"
    r"homage\s+to|hommage\s+[aà]|based\s+on|copy\s+after)\)?)(?=\s|[.,;:\u2013\u2014-]|$)", re.IGNORECASE,
)
_REFERENCE_SECTION = re.compile(
    r"\b(?:provenance|bibliograph(?:y|ie)|literature|exhibition(?:\s+history)?|expositions?|"
    r"biograph(?:y|ie)|publisher|printer)\s*:", re.IGNORECASE,
)
_NONPRINT_MEDIUM = re.compile(
    r"\b(?:oil\s+on|huile\s+sur|acrylic\s+on|acrylique\s+sur|gouache|watercolou?r|"
    r"aquarelle|charcoal|fusain|pencil\s+(?:on|drawing)|crayon\s+sur|pastel|tempera|"
    r"india\s+ink|encre\s+de\s+chine|lithographic\s+(?:pencil|crayon|chalk))\b", re.IGNORECASE,
)
# Verified expanded source credits for maintained artist bookmarks. Prefer the
# full name when locating the end of a credit, before the actual work title.
_SOURCE_CREDIT_ALIASES = {
    "rembrandt": ("Rembrandt Harmenszoon van Rijn", "Rembrandt van Rijn Harmensz", "H van Rijn Rembrandt", "Rembrandt van Rijn"),
    "dali salvador": ("Salvador Dali Y Domenech",),
    "alphonse mucha": ("Alphonse Marie Mucha",),
    "pablo picasso": ("Pablo Ruiz Picasso",),
    "jean pierre vasarely yvaral": ("Jean-Pierre Vasarely",),
    "manolo valdes": ("Manolo Valdes Blasco",),
    "arman": ("Armand Pierre Fernandez known as Arman",),
    "de francisco goya": ("Francisco de Goya y Lucientes",),
    "jacques villon": ("Jacques Villon Gaston Duchamp dit",),
}


@dataclass(slots=True)
class DrouotCaptureResult:
    lots: list[NormalizedLot]
    metrics: WatchlistMetrics
    errors: list[str] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)
    fallback_lot_keys: set[str] = field(default_factory=set)
    rejected_lots: list[dict] = field(default_factory=list)
    capture_summary: dict = field(default_factory=dict)
    attribution_notes: list[dict] = field(default_factory=list)


@dataclass(slots=True)
class ValidatedDrouotCapture:
    lots: list[NormalizedLot]
    memberships: dict[str, set[str]]
    rejected_lots: list[dict]
    page_count: int
    result_count: int
    outside_window: int
    window: dict[str, str]
    attribution_notes: list[dict]


def _text(value: object, *, maximum: int = 20000) -> str:
    if not isinstance(value, str) or len(value) > maximum:
        raise ValueError("public text must be a bounded string")
    if any(ord(c) < 32 and c not in "\n\r\t" for c in value):
        raise ValueError("public text contains control characters")
    return unescape(re.sub(r"<[^>]+>", " ", value)).strip()


def _public_url(value: object, *, host: str = "drouot.com", optional: bool = False) -> str:
    if optional and value in (None, ""):
        return ""
    if not isinstance(value, str) or len(value) > 4096 or any(ord(c) < 33 for c in value):
        raise ValueError("a public HTTPS URL is required")
    parts = urlsplit(value)
    if (parts.scheme != "https" or parts.username or parts.password or parts.port not in {None, 443}
            or not parts.hostname or not (parts.hostname == host or parts.hostname.endswith("." + host))):
        raise ValueError("a public Drouot HTTPS URL is required")
    return value


def _source_query(value: str) -> str:
    _public_url(value)
    parts = urlsplit(value)
    query = parse_qs(parts.query, keep_blank_values=True)
    if (parts.hostname != "drouot.com" or parts.path != _SEARCH_PATH or parts.fragment
            or set(query) != {"query"} or len(query["query"]) != 1 or not query["query"][0].strip()):
        raise ValueError("Drouot scope must be a category-50 artist query without extra filters")
    return query["query"][0]


def select_drouot_entries(html: str) -> list[BookmarkEntry]:
    """Use readable bookmark identities; query aliases are search terms only."""
    entries = []
    for entry in parse_netscape_bookmarks(html):
        if entry.folder != "DROUOT \u2014 PRINTS":
            continue
        parts = urlsplit(entry.url)
        if parts.hostname not in {"drouot.com", "www.drouot.com"}:
            continue
        _source_query(entry.url)
        artist = entry.title.split(":", 1)[0].strip()
        if not artist or ": Drouot" not in entry.title:
            raise ValueError("Each Drouot bookmark needs its canonical artist title")
        entries.append(replace(entry, artist=artist, source="Drouot"))
    if len({entry.url for entry in entries}) != len(entries):
        raise ValueError("The Drouot bookmarks contain duplicate search URLs")
    if len({artist_identity_key(entry.artist) for entry in entries}) != len(entries):
        raise ValueError("The Drouot bookmarks contain duplicate artist identities")
    return entries


def _timestamp(value: object, observed_at: datetime, label: str) -> datetime:
    try:
        if not isinstance(value, str):
            raise ValueError
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.tzinfo is None or stamp > observed_at.replace(microsecond=0) + timedelta(minutes=5):
            raise ValueError
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError(f"{label} needs a timezone-aware timestamp no later than now") from exc
    return stamp


def _integer(value: object, label: str, *, minimum: int = 0, maximum: int = 2**53 - 1) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{label} must be an integer between {minimum} and {maximum}")
    return value


def _id(value: object, label: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)) or not re.fullmatch(r"[1-9][0-9]*", str(value)):
        raise ValueError(f"{label} needs a numeric Drouot lot ID")
    return str(value)


def _amount(value: object, label: str) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError(f"{label} must be a nonnegative finite number")
    return float(value) if value else None


def _source_time(value: object, label: str) -> str:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a Unix timestamp")
    if value in (None, 0):
        return ""
    _integer(value, label, minimum=1)
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
    except (ValueError, OverflowError, OSError) as exc:
        raise ValueError(f"{label} is not a valid Unix timestamp") from exc


def _leading_credit_matches(value: str, aliases: Iterable[str]) -> bool:
    credit = value.lstrip(" *#_\t\r\n")
    qualified = _QUALIFIED_CREDIT.match(credit)
    if qualified:
        credit = credit[qualified.end():]
    credit = re.sub(r"\([^)]*\d{4}[^)]*\)", " ", credit)
    words = normalize_artist_name(credit).split()
    for alias in aliases:
        alias_credit = _QUALIFIED_CREDIT.sub("", alias.lstrip(" *#_\t\r\n"))
        wanted = normalize_artist_name(re.sub(r"\([^)]*\)", " ", alias_credit)).split()
        if wanted and len(words) >= len(wanted) and sorted(words[:len(wanted)]) == sorted(wanted):
            # A conjunction immediately after the credited name introduces
            # another creator. Later conjunctions may simply be a work title.
            return not (len(words) > len(wanted) and words[len(wanted)] in {"and", "et", "with", "avec"})
    return False


def _credit_prefix_end(value: str, aliases: Iterable[str]) -> int | None:
    """Locate the actual name span without assuming first-name/surname order."""
    leading = re.match(r"^[\s*#_]*", value).end()
    credit = value[leading:]
    qualified = _QUALIFIED_CREDIT.match(credit)
    if qualified:
        leading += qualified.end()
        credit = value[leading:]
    spans = list(re.finditer(r"[^\W_]+|&", credit, re.UNICODE))
    for alias in aliases:
        wanted = normalize_artist_name(re.sub(r"\([^)]*\)", " ", alias)).split()
        if len(spans) < len(wanted) or not wanted:
            continue
        actual = [normalize_artist_name(span.group()) for span in spans[:len(wanted)]]
        if sorted(actual) == sorted(wanted):
            end = leading + spans[len(wanted) - 1].end()
            if value[end:end + 1] == ")" and value[:end].count("(") > value[:end].count(")"):
                end += 1
            return end
    return None


def _biography_line(value: str) -> bool:
    # A plate title can cite the book's author with birth/death dates. Those
    # dates do not turn the named plate and book into the artist's biography.
    if re.search(
        r"\bplate\s+(?:[IVXLCDM]+|[0-9]+)\s+from\b.+?\bby\s+[^()\n]+"
        r"\([0-9]{4}\s*[-\u2013\u2014]\s*[0-9]{4}\)\s*$", value, re.IGNORECASE,
    ):
        return False
    # A work title can repeat its date ("Painting, July 4, 2021, 2021").
    # Only distinct years support the birth/death-line heuristic.
    if len(set(re.findall(r"\b(?:1[4-9]\d{2}|20\d{2})\b", value))) >= 2 and not _PRINT_MEDIUM.search(value) and not re.search(r'["\u201c\u201d\u00ab\u00bb]', value):
        return True
    return bool(
        re.fullmatch(r"\d{4}", value)
        or re.fullmatch(r"[^0-9]+\((?:Spain|France|England|Italy|Germany|Japan|China|United States|USA)\)\s*\d{4}", value, re.IGNORECASE)
    )


def _strip_leading_biography(value: str) -> str:
    while True:
        cleaned = re.sub(r"^\s*\([^)]*\d{4}[^)]*\)\s*", "", value)
        if cleaned == value:
            return value
        value = cleaned


def _following_qualifier(value: str) -> tuple[str, str]:
    value = _strip_leading_biography(value)
    match = _FOLLOWING_QUALIFIER.match(value)
    if match:
        return match.group("qualifier"), value[match.end():].strip(" *_\t.,:;-\u2013\u2014")
    return "", value


def _separate_line_qualifier(credit: str, following: str, aliases: Iterable[str]) -> tuple[str, str]:
    """An explicit After: label can follow an otherwise bare artist/date line."""
    end = _credit_prefix_end(credit, aliases)
    if end is None or _strip_leading_biography(credit[end:]).strip(" *_\t.,:;-\u2013\u2014"):
        return "", following
    # Require the source's colon. A work title such as After the Rain is not
    # an attribution qualifier, nor is a later biography/reference mention.
    match = re.match(r"^(?P<qualifier>after)\s*:\s*(?P<title>.*)$", following, re.IGNORECASE)
    return (match.group("qualifier"), match.group("title")) if match else ("", following)


def _title(description: str, heading: str, aliases: Iterable[str]) -> str:
    """Use a work title from the source's actual inline or repeated-credit layout."""
    lines = [line.strip(" *_\t") for line in description.splitlines() if line.strip(" *_\t")]
    for index, line in enumerate(lines):
        separate, separate_title = _separate_line_qualifier(lines[index - 1], line, aliases) if index else ("", line)
        # In an explicit After: work line, even a title beginning with the
        # artist's name belongs to the title rather than another credit.
        end = None if separate else _credit_prefix_end(line, aliases)
        if end is not None:
            value = line[end:].strip(" *_\t.,:;-")
            # Birth/death locations and source attribution can follow the name;
            # remove them only in this leading credit span, never from the work.
            while value:
                before = value
                value = _strip_leading_biography(value).strip(" *_\t.,:;-")
                _, value = _following_qualifier(value)
                value = re.sub(r"^\d{4}\s*[-\u2013\u2014]\s*\d{4}\b\s*", "", value).strip(" *_\t.,:;-")
                value = re.sub(r"^\d{4}\b\s+(?=\S)", "", value)
                if value == before:
                    break
            if (not value or _biography_line(value)
                    or re.fullmatch(r"(?:also\s+)?known\s+as\s+[^,;:()\n]+(?:\s*\([^)]*\d{4}[^)]*\))?",
                                    value, re.IGNORECASE)):
                continue
            if re.match(r"^[\u2013\u2014-]?\s*Chalcographie\s+du\s+Louvre\b", value, re.IGNORECASE):
                continue
        else:
            value = separate_title
            if _biography_line(value) or _REFERENCE_SECTION.match(value):
                continue
        # Inline Swiss descriptions place a quoted work after the artist dates.
        if re.match(r"^plate[ -]signed\b", value, re.IGNORECASE):
            # An intermediate repeated-credit line may describe only the
            # signature/printing; a later source line gives the actual title.
            continue
        if re.match(r"^(?:naar\s+)?prints?\b", value, re.IGNORECASE):
            quoted_work = re.search(r'["\u201c\u00ab](.+?)["\u201d\u00bb]', value)
            if quoted_work:
                return quoted_work.group(1).replace("*", "")[:500]
            opened_work = re.search(r'["\u201c\u00ab](.+)$', value)
            if opened_work:
                work_title = re.split(r"\s+-\s+\d+(?:[.,]\d+)?\s*[x\u00d7]\s*\d", opened_work.group(1), maxsplit=1)[0]
                return work_title.replace("*", "").strip()[:500]
        quoted = re.match(r'^["\u201c\u00ab](.+?)["\u201d\u00bb](.*)$', value)
        if quoted:
            value = quoted.group(1) + quoted.group(2)
        value = re.split(r"\s+[-\u2014]\s+(?=(?:color\s+|colour\s+)?(?:etching|aquatint|lithograph|engraving|screenprint)\b)", value, maxsplit=1, flags=re.IGNORECASE)[0]
        return value.replace("*", "")[:500]
    return (heading or description).replace("*", "")[:500]


def _offered_work_prefix(description: str) -> str:
    # A short production credit can precede the actual medium statement:
    # "Printer: Mourlot. Original color lithograph on Arches paper". Only
    # ignore that boundary when the very next sentence starts with a print
    # technique; ordinary reference/biography sections still end the work.
    work = re.sub(
        r"\bprinter\s*:\s*[^:;.\r\n]{1,100}[.;]\s*"
        r"(?=(?:(?:original|color|colour)\s+)*" + _PRINT_MEDIUM.pattern + ")",
        lambda match: re.sub(r"[^\r\n]", " ", match.group()),
        description, flags=re.IGNORECASE,
    )
    return _REFERENCE_SECTION.split(work, maxsplit=1)[0]


def _work_level_after(description: str, aliases: Iterable[str]) -> str:
    """Preserve an explicit offered-print 'after' credit outside the name span.

    An original artist's print can be based on their own painting or photograph;
    that relationship alone is not an attribution qualifier. Require the actual
    word 'after' in the offered print's medium line, excluding quoted titles,
    reference material and accompanying works.
    """
    work = _offered_work_prefix(description)
    work = re.split(r"\n\s*(?:information|references|notes|shipping|registered\s+colissimo)\b",
                    work, maxsplit=1, flags=re.IGNORECASE)[0]
    for line in work.splitlines():
        line = re.sub(r'"[^"\n]*"|\u201c[^\u201d\n]*\u201d|\u00ab[^\u00bb\n]*\u00bb|\u2018[^\u2019\n]*\u2019|(?<!\w)\'[^\'\n]*\'(?!\w)',
                      lambda match: " " * len(match.group()), line)
        if not _PRINT_MEDIUM.search(line) or re.search(
            r"\b(?:included\s+is|accompanied\s+by|together\s+with|known\s+for|other\s+works|"
            r"previously\s+exhibited|biograph(?:y|ie))\b", line, re.IGNORECASE
        ):
            continue
        for match in re.finditer(r"\bafter\s+", line, re.IGNORECASE):
            following = line[match.end():]
            work_object = re.match(r"(?:an?\s+|the\s+)?(?:original|oil\s+painting|painting|pastel|drawing|design|work|"
                                   r"d[eé]coupage|gouache|gouche)\b",
                                   following, re.IGNORECASE)
            if work_object:
                named_creator = re.match(r"\s+by\s+(.+)", following[work_object.end():], re.IGNORECASE)
                if named_creator:
                    named_credit = re.sub(r"\band\s+under\s+(?:his|her|their)\s+direction\b", "",
                                          named_creator.group(1), flags=re.IGNORECASE)
                    if not _leading_credit_matches(named_credit, aliases):
                        continue
            if work_object or _leading_credit_matches(following, aliases):
                return match.group().strip()
    return ""


def _qualified_source_credit(heading: str, description: str, aliases: Iterable[str]) -> str:
    lines = [line for line in description.splitlines() if line.strip()]
    candidates = [(heading, ""), *((line, lines[index + 1] if index + 1 < len(lines) else "")
                                    for index, line in enumerate(lines[:4]))]
    for value, following in candidates:
        credit = value.lstrip(" *#_\t\r\n")
        name_end = _credit_prefix_end(credit, aliases)
        if name_end is None:
            continue
        # The matched name/qualifier span is the source credit. Everything
        # after it may be a long work description, certificate or dimensions.
        name = " ".join(credit[:name_end].split()).strip(" .,;:-")
        if _QUALIFIED_CREDIT.match(credit):
            return name
        qualifier, _ = _following_qualifier(credit[name_end:])
        if not qualifier:
            qualifier, _ = _separate_line_qualifier(credit, following.strip(), aliases)
        if qualifier:
            return name + (" " if qualifier.startswith("(") else ", ") + qualifier
    work_qualifier = _work_level_after(description, aliases)
    if work_qualifier:
        # Preserve the spelling/order of the source's primary artist credit.
        for value, _ in candidates:
            credit = value.lstrip(" *#_\t\r\n")
            name_end = _credit_prefix_end(credit, aliases)
            if name_end is not None:
                return " ".join(credit[:name_end].split()).strip(" .,;:-") + ", " + work_qualifier
    return ""


def _print_technique(description: str, aliases: Iterable[str] = ()):
    """Find work-medium evidence before provenance or an artist biography."""
    work = _offered_work_prefix(description)
    # A carrier's allowance for several lithographs is not this lot's medium.
    work = re.split(r"\n\s*(?:shipping|registered\s+colissimo)\b", work,
                    maxsplit=1, flags=re.IGNORECASE)[0]
    # Exhibition and artwork titles are not evidence of the object's medium.
    # Keep positions stable so returned source spans remain easy to audit.
    work = re.sub(r'"[^"\n]*"|\u201c[^\u201d\n]*\u201d|\u00ab[^\u00bb\n]*\u00bb|\u2018[^\u2019\n]*\u2019|(?<!\w)\'[^\'\n]*\'(?!\w)',
                  lambda match: " " * len(match.group()), work)
    # A series name or the technique of an original being reproduced is not
    # the technique of this offered impression.
    work = re.sub(r"\((?:From\s+the\s+(?:set|series)\b)[^()\n]*\)",
                  lambda match: " " * len(match.group()), work, flags=re.IGNORECASE)
    work = re.sub(r"\b(?:reprints?|reproductions?)\s+(?:based\s+on|after)\s+(?:the\s+)?" + _PRINT_MEDIUM.pattern,
                  lambda match: " " * len(match.group()), work, flags=re.IGNORECASE)
    # A catalogue work called "Lithograph No. 22" may be reproduced as a
    # poster. Its title identifies the original work, not the offered medium.
    # Mask bare numbered titles and explicit references to them, preserving
    # positions and any separate technique statement about the actual object.
    numbered_title = (
        "(?:" + _PRINT_MEDIUM.pattern + "|" + _NONPRINT_MEDIUM.pattern + ")"
        + r"\s+(?:(?:no\.?|number|n[\u00b0o])\s*)?"
        r"(?:[0-9]+|[IVXLCDM]+)\b(?:\s*,\s*[0-9]{4})?"
    )
    lines = work.splitlines(keepends=True)
    for index, line in enumerate(lines):
        candidate = line.strip(" *_\t\r\n.,:;-\u2013\u2014")
        end = _credit_prefix_end(candidate, aliases)
        if end is not None:
            candidate = _strip_leading_biography(candidate[end:]).strip(" *_\t.,:;-\u2013\u2014")
        dated_nonprint_poster_title = (
            re.fullmatch(_NONPRINT_MEDIUM.pattern + r"\s+on\s+paper\s*,\s*[0-9]{4}", candidate, re.IGNORECASE)
            and re.match(r"\s*(?:original\s+)?poster\b", "".join(lines[index + 1:]), re.IGNORECASE)
        )
        exhibition_medium_title = (
            re.fullmatch(r"[^.\n]{1,60}\.\s*(?:paintings?|drawings?|lithographs?|etchings?|prints?|sculptures?|ceramics)"
                         r"(?:\s*[,\u2013\u2014-]\s*(?:paintings?|drawings?|lithographs?|etchings?|prints?|sculptures?|ceramics))*"
                         r"\s*,\s*[0-9]{4}", candidate, re.IGNORECASE)
            and re.match(r"\s*(?:(?:original|color|black|white|three-color)\s+)*lithographic\s+poster\b",
                         "".join(lines[index + 1:]), re.IGNORECASE)
        )
        if re.fullmatch(numbered_title, candidate, re.IGNORECASE) or dated_nonprint_poster_title or exhibition_medium_title:
            lines[index] = re.sub(r"[^\r\n]", " ", line)
    work = "".join(lines)
    work = re.sub(r"\b(?:after|based\s+on)\s+(?:the\s+)?" + numbered_title,
                  lambda match: " " * len(match.group()), work, flags=re.IGNORECASE)
    nonprint = _NONPRINT_MEDIUM.search(work)
    for positive in _PRINT_MEDIUM.finditer(work):
        # A lithographic pencil/crayon is a drawing implement; its name does
        # not establish that the offered sheet is a printed impression.
        if positive.group().casefold() == "lithographic" and re.match(
            r"\s+(?:pencil|crayon|chalk)\b", work[positive.end():], re.IGNORECASE,
        ):
            continue
        if positive.group().casefold() == "lithographic":
            # A later explicit process in the same offered-object line can
            # refine the earlier adjective, e.g. "lithographic poster ...;
            # color offset lithograph". Do not search later reference lines.
            same_line = work[positive.end():].split("\n", 1)[0]
            offset = re.search(r"\boffset\b(?=\s+lithograph\b)", same_line, re.IGNORECASE)
            if offset:
                start = positive.end() + offset.start()
                positive = _PRINT_MEDIUM.match(work, start)
        if positive.group().casefold() in {"print", "prints"}:
            before, after = work[:positive.start()], work[positive.end():]
            if re.search(r"\b(?:signed|dated|monogrammed|numbered)(?:\s+and\s+(?:signed|dated|monogrammed|numbered))?\s+in\s+$",
                         before, re.IGNORECASE):
                continue
            modifier = re.search(r"\b(?:art|original|color|colour|vintage|fine\s+art|digital|pigment|signed|numbered|"
                                 r"reproduction|offset|gicl[eé]e|edition|relief|sepia[ -]toned|\d+)\s+$", before, re.IGNORECASE)
            context = re.match(
                r"\s*(?:on\b|in\b|with\b|signed\b|numbered\b|edition\b|n[\u00b0o.]\s*\d|"
                r"\((?:(?:minor|slight|some)\s+)?(?:wear|damage|foxing|staining|creases?)\b|"
                r"(?:after|based\s+on)\s+(?:an?\s+|the\s+)?(?:original\s+)?(?:work|painting|drawing|design)\b|"
                r"produced\s+for\s+(?:the\s+|a\s+)?book\b|[,;.]|$)", after, re.IGNORECASE,
            )
            # Auction headings can name a group as "PRINTS (3)" and put
            # the sheet dimensions on the following line. The plural/count
            # plus physical dimensions identifies offered objects; a bare
            # numbered title or a reference to such a title does not.
            line_prefix = before.rsplit("\n", 1)[-1]
            credit_end = _credit_prefix_end(line_prefix, aliases)
            if credit_end is not None:
                line_prefix = _following_qualifier(line_prefix[credit_end:])[1]
            counted_prints = (
                positive.group().casefold() == "prints"
                and re.match(r"\s*\((?:[2-9]|[1-9][0-9]{1,2})\)(?=\s|$)", after)
                and re.search(
                    r"\b[0-9]+(?:[.,][0-9]+)?\s*(?:cm|mm|in(?:ches)?)?\s*[x\u00d7]\s*"
                    r"[0-9]+(?:[.,][0-9]+)?\s*(?:cm|mm|in(?:ches)?)\b",
                    "\n".join(after.splitlines()[:2]), re.IGNORECASE,
                )
                and not re.search(r"\b(?:after|based\s+on|titled|called|exhibition|retrospective)\b",
                                  line_prefix, re.IGNORECASE)
            )
            dash_medium = re.match(
                r"\s*[\u2013\u2014-]\s*(?:signed\b|numbered\b|on\s+(?:paper|board|card)\b)",
                after, re.IGNORECASE,
            )
            written_count = (
                positive.group().casefold() == "prints"
                and re.search(r"\b(?:two|three|four|five|six|seven|eight|nine|ten)\s+$", before, re.IGNORECASE)
                and re.match(r"\s+from\b", after, re.IGNORECASE)
                and re.search(r"\b[0-9]+(?:[.,][0-9]+)?\s*[x\u00d7]\s*[0-9]+(?:[.,][0-9]+)?\s*(?:cm|mm|in(?:ches)?)\b", work, re.IGNORECASE)
            )
            if not (modifier or context or counted_prints or dash_medium or written_count):
                continue
        if nonprint and nonprint.start() < positive.start() and not re.search(r"\bmixed[ -]media\b|\btechnique\s+mixte\b", work, re.IGNORECASE):
            continue
        return positive
    return None


def _resolved_collaboration(description: str, aliases: Iterable[str]) -> tuple[str, str, str] | None:
    """Resolve a co-credit attached to one explicitly described print work.

    A repeated credit can include an alias and collaborator before the actual
    work title. A single following title and offered-print medium establish the
    joint credit without requiring a redundant collaboration sentence.
    An empty tuple marks a recognized but unresolved multiple-artist credit.
    """
    lines = [line.strip() for line in description.splitlines() if line.strip()]
    for index, line in enumerate(lines[:3]):
        end = _credit_prefix_end(line, aliases)
        if end is None:
            continue
        # Explicit comma-separated creator lists are collective lots, not a
        # single resolved collaboration or a work by only the first artist.
        # Requiring multiple list items and "others" avoids treating an
        # ordinary comma-delimited artwork title as another creator.
        collective = _strip_leading_biography(line[end:])
        if not re.match(r"\s*,\s*(?:also\s+)?known\s+as\b", collective, re.IGNORECASE) and (re.match(r"\s*,\s*[^,;\n]+,\s*(?:[^,;\n]+,\s*)?(?:and\s+|et\s+)?(?:others|autres)\b",
                    collective, re.IGNORECASE) or re.match(
                        r"\s*,\s*[^,()\n]+\([^)]*\d{4}[^)]*\),?\s*(?:and|et)\s+[^,()\n]+\([^)]*\d{4}[^)]*\)",
                        collective, re.IGNORECASE)):
            return "", "", ""
        tail = _strip_leading_biography(line[end:].lstrip(" *")).strip(" ,;:")
        # Some source headings place a full second name after the qualifier.
        # Retain that source relationship and read the next line as the work.
        named_after = re.fullmatch(r"after\s+([A-ZÀ-ÖØ-Þ][A-ZÀ-ÖØ-Þ -]+)", tail)
        if (named_after and len(normalize_artist_name(named_after.group(1)).split()) >= 2
                and index + 2 < len(lines) and _print_technique(lines[index + 2], aliases) is not None):
            suffix = " " + named_after.group(1)
            return line, lines[index + 1].strip(" *_\t"), suffix
        # A named, quoted work can follow both credits on the same line.
        # Keep the complete credit instead of promoting the first creator.
        inline = re.match(
            r"(?P<separator>and|et|&)\s+(?P<collaborator>[^,;:()\n]+?)"
            r"(?:\s*\([^)]*\d{4}[^)]*\))?[\s*,;:.\u2013\u2014-]*"
            r"(?P<context>fragment\s+from\s+the\s+illustrated\s+work\s+)?"
            r"[\"'\u201c\u2018*](?P<title>[^\"'\u201d\u2019*\n]+)[\"'\u201d\u2019*]",
            tail, re.IGNORECASE,
        )
        if inline:
            collaborator = inline.group("collaborator").strip(" *.,;:")
            named = normalize_artist_name(collaborator).split()
            # Do not absorb a sentence about another work into a name.
            if (2 <= len(named) <= 5 and not any(c.isdigit() for c in collaborator)
                    and not re.search(r"\b(?:from|with|including|collection|portfolio|prints|works)\b", collaborator, re.IGNORECASE)
                    and _print_technique(description, aliases) is not None):
                suffix = " " + inline.group("separator") + " " + collaborator
                title = inline.group("title").strip(" ,")
                if inline.group("context"):
                    title = "Fragment from " + title
                return line[:end].strip(" ,;:") + suffix, title, suffix
            return "", "", ""
        # Explicit production roles resolve a dash-separated engraver credit.
        # Require that both source names occur in the role statement; retain
        # that statement visibly so an engraving after a drawing stays clear.
        secondary = re.fullmatch(r"[-\u2013\u2014]\s*([^,;:()\n]+)", tail)
        if secondary and index + 2 < len(lines):
            collaborator = secondary.group(1).strip()
            role = re.search(r"\bengraved\s+by\s+([^,.;\n]+?)\s+after\s+a\s+drawing\s+by\s+([^,.;\n]+)",
                             _offered_work_prefix(description), re.IGNORECASE)
            if (role and normalize_artist_name(role.group(1)) == normalize_artist_name(collaborator)
                    and any(set(normalize_artist_name(role.group(2)).split()) <= set(normalize_artist_name(alias).split()) for alias in aliases)
                    and _print_technique(lines[index + 2], aliases) is not None):
                suffix = " - " + collaborator + " (" + role.group(0).strip() + ")"
                return line[:end].strip(" ,;:") + suffix, lines[index + 1].strip(" *_\t"), suffix
        match = re.fullmatch(
            r"(?:also\s+known\s+as\s+[^,]+,\s*)?(?P<separator>x|and|et|&)\s+"
            r"(?P<collaborator>[^,;:()\n]+?)(?:\s*\([^)]*\d{4}[^)]*\))?",
            tail, re.IGNORECASE,
        )
        if not match:
            continue
        collaborator = match.group("collaborator").strip()
        named = normalize_artist_name(collaborator)
        # A mononym such as Invader is a source credit when the same offered
        # work explicitly carries both creators' signatures. Do not accept an
        # arbitrary single trailing word as a second artist on its own.
        both_signed = any(
            _PRINT_MEDIUM.search(statement)
            and re.search(r"\bsigned(?:\s+and\s+dated)?\s+by\s+both(?:\s+artists)?\b|"
                          r"\bgetekend\s+door\s+beide\b", statement, re.IGNORECASE)
            and not re.search(r"\b(?:other\s+works|previously|biograph(?:y|ie)|known\s+for|"
                              r"included\s+is|accompanied\s+by)\b", statement, re.IGNORECASE)
            for statement in _offered_work_prefix(description).splitlines()
        )
        supported_mononym = (len(named.split()) == 1 and both_signed
                             and re.fullmatch(r"[^\W\d_][^\W\d_'-]*(?:[-'][^\W\d_]+)*", collaborator, re.UNICODE))
        confirmations = re.findall(
            r"\b(?:this|the)\s+(?:edition|print|work)\s+was\s+(?:created|made|produced)"
            r"\s+in\s+collaboration\s+with\s+([^.;:(\n]+)", description, re.IGNORECASE,
        )
        if (len(named.split()) < 2 and not supported_mononym or any(character.isdigit() for character in named)
                or confirmations and not any(normalize_artist_name(value) == named for value in confirmations)
                or index + 2 >= len(lines)):
            return "", "", ""
        suffix = " " + match.group("separator") + " " + collaborator
        joint_credit = line[:end].strip(" ,;:") + suffix
        # A repeated joint credit can describe a single signed photoprint of
        # a named project in one sentence instead of separate title/medium
        # lines. Require both-signature evidence and the exact named object.
        statement = lines[index + 1]
        repeated_end = _credit_prefix_end(statement, (joint_credit,))
        project = re.fullmatch(
            r'\s*signed\s+(?:photo|foto)print\s+of\s+the\s+project\s+'
            r'["\u201c](?P<title>[^"\u201d\n]+)["\u201d]\s+and\s+print\s+dated\s+'
            r'[0-9]{4}\s*/\s*[0-9]{4}\s*',
            statement[repeated_end:] if repeated_end is not None else "", re.IGNORECASE,
        )
        if project and both_signed:
            return joint_credit, project.group("title").strip(), suffix
        title = lines[index + 1].strip(" *_\t")
        if _credit_prefix_end(title, aliases) is not None:
            continue
        if (not title or _REFERENCE_SECTION.match(title) or _PRINT_MEDIUM.search(title)
                or re.search(r"^(?:lot|set|pair)\s+of\b|;", title, re.IGNORECASE)
                or _print_technique(lines[index + 2]) is None):
            return "", "", ""
        return joint_credit, title, suffix
    return None


def _contradictory_offered_creator(description: str, aliases: Iterable[str]) -> bool:
    """A direct offered-technique 'by' credit must not contradict its heading."""
    work = _offered_work_prefix(description)
    for match in re.finditer(_PRINT_MEDIUM.pattern + r"\s+by\s+([A-ZÀ-ÖØ-Þ][\w'’.-]+(?:\s+[A-ZÀ-ÖØ-Þ][\w'’.-]+){1,3})", work):
        named = normalize_artist_name(match.group(1)).split()
        wanted_names = [normalize_artist_name(alias).split() for alias in aliases]
        if any(all(part in wanted or len(part) == 1 and any(word.startswith(part) for word in wanted)
                       for part in named) for wanted in wanted_names):
            continue
        # Shared surname but a different full name is an explicit conflict,
        # e.g. Giovanni Battista / Francesco Piranesi. A printer's separate
        # production credit or a surname-only reference is not this case.
        for wanted in wanted_names:
            if named[-1:] == wanted[-1:] and not set(named) <= set(wanted):
                return True
    return False


def _normalized_lot(raw: dict, card: dict, entry: BookmarkEntry, captured_at: datetime, auctioneers: dict) -> tuple[NormalizedLot | None, str]:
    identity = _id(raw.get("id"), "lot.id")
    if set(raw) - _LOT_FIELDS or set(card) - _CARD_FIELDS:
        raise ValueError(f"lot {identity}: non-public or unsupported capture fields")
    for name, value in raw.items():
        if name == "photo":
            if value is None:
                continue
            if not isinstance(value, dict) or set(value) - {"path", "w", "h"}:
                raise ValueError(f"lot {identity}: unsupported photo metadata")
            if "path" in value:
                _text(value["path"], maximum=2000)
            for dimension in ("w", "h"):
                if dimension in value:
                    _integer(value[dimension], "photo." + dimension, maximum=100000)
        elif name == "displayStartingPrice":
            if type(value) is not bool:
                raise ValueError(f"lot {identity}: invalid displayStartingPrice flag")
        elif value is not None:
            if isinstance(value, str):
                _text(value)
            elif isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"lot {identity}: unsupported nested or private metadata")
    for name, value in card.items():
        if name != "id":
            _text(value)
    if _id(card.get("id"), "card.id") != identity:
        raise ValueError(f"lot {identity}: DOM/source identities differ")
    lot_url = _public_url(card.get("url"))
    if not re.match(rf"^/en/l/{re.escape(identity)}(?:-|/|$)", urlsplit(lot_url).path):
        raise ValueError(f"lot {identity}: DOM URL does not match its numeric source ID")
    description, heading = _text(raw.get("description", "")), _text(card.get("heading", ""))
    aliases = (*_SOURCE_CREDIT_ALIASES.get(artist_identity_key(entry.artist), ()),
               entry.artist, _source_query(entry.url))
    collaboration = _resolved_collaboration(description, aliases)
    if not _leading_credit_matches(description, aliases) or not _leading_credit_matches(heading, aliases):
        # A joint heading can identify one explicitly described work. Require
        # the same resolved full credit at the start of both source fields;
        # a name mention or an unresolved collection remains insufficient.
        if (not collaboration or not collaboration[0]
                or not _leading_credit_matches(description, (collaboration[0],))
                or not _leading_credit_matches(heading, (collaboration[0],))):
            return None, "The source's leading artist credit does not unambiguously match the bookmarked artist."
    medium = _print_technique(description, aliases)
    if medium is None:
        return None, "No explicit print technique is visible in the captured source description."
    if collaboration == ("", "", ""):
        return None, "The source's multiple-artist credit is unresolved."
    if not collaboration and _contradictory_offered_creator(description, aliases):
        return None, "The offered print's named creator contradicts its leading artist credit."
    zone = raw.get("timezone")
    try:
        if not isinstance(zone, str):
            raise ValueError
        ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"lot {identity}: source timezone is missing or invalid") from exc
    currency = raw.get("currencyId", "")
    if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValueError(f"lot {identity}: source currency must be an explicit ISO code")
    start, end = _source_time(raw.get("date"), "lot.date"), _source_time(raw.get("bidEndDate"), "lot.bidEndDate")
    if not (start or end):
        return None, "No source sale or closing date was captured."
    image = card.get("image_url", "")
    if image.startswith("data:image/"):
        # A not-yet-loaded card may expose the site's generic placeholder.
        # Only the public response's documented photo path supplies artwork.
        image = ""
    photo = raw.get("photo")
    if not image and isinstance(photo, dict) and re.fullmatch(r"[0-9]+/[0-9]+/[a-zA-Z0-9_-]+", photo.get("path", "")):
        image = "https://cdn.drouot.com/d/lot/ftall/" + photo["path"]
    image = _public_url(image, optional=True)
    for field in ("description", "text", "price_text", "date_text"):
        if field in card:
            _text(card[field])
    sale_id = raw.get("saleId")
    sale_url = "https://drouot.com/en/v/" + _id(sale_id, "lot.saleId") if sale_id else ""
    house = _text(auctioneers.get(str(raw.get("auctioneerId", "")), ""), maximum=1000)
    number = raw.get("num", "")
    if isinstance(number, bool) or not isinstance(number, (str, int)):
        raise ValueError(f"lot {identity}: invalid lot number")
    low, high = _amount(raw.get("lowEstim"), "lot.lowEstim"), _amount(raw.get("highEstim"), "lot.highEstim")
    if low is not None and high is not None and low > high:
        raise ValueError(f"lot {identity}: estimate range is reversed")
    # Search result zero values are placeholders, not evidence of a zero bid or
    # a sold result. Posted results require an explicit future results workflow.
    bid = _amount(raw.get("currentBid"), "lot.currentBid")
    posted = _amount(raw.get("result"), "lot.result")
    # A live sale can remain IN_PROGRESS while an individual lot card already
    # shows its sold-price label. Preserve that evidence as a rejection; a zero
    # API result must not replace it or manufacture a normalized sold amount.
    card_sold = re.search(
        r"(?:^|\n)\s*Sold\s*\n\s*(?:[A-Z]{3}|US\$|[\u20ac\u00a3$])\s*"
        r"[0-9][0-9,.\s\u2019']*\s*$", card.get("text", ""),
    )
    if (posted is not None or card_sold
            or str(raw.get("saleStatus", "")).upper() in {"ENDED", "FINISHED", "CLOSED"}):
        return None, "Posted or ended lots are excluded from the upcoming capture import."
    lot = NormalizedLot(
        source="Drouot", source_lot_id=identity, artist=entry.artist,
        artist_watchlist_name=entry.artist,
        title=collaboration[1] if collaboration else _title(description, heading, aliases),
        medium=medium.group(0), auction_house=house, lot_number=str(number),
        start_at=start, end_at=end, estimate_low=low, estimate_high=high,
        currency=currency, current_bid=bid, lot_url=lot_url, sale_url=sale_url,
        image_url=image, first_seen_at=captured_at.isoformat(), last_seen_at=captured_at.isoformat(),
    )
    source_credit = _qualified_source_credit(heading, description, aliases)
    if collaboration:
        source_credit = source_credit + collaboration[2] if source_credit else collaboration[0]
    if source_credit:
        lot.artist = source_credit
        lot.title = source_credit + " \u2014 " + lot.title
        lot.content_hash = lot.calculate_content_hash()
    return lot, ""


def validate_drouot_capture(payload: object, entries: Iterable[BookmarkEntry], *, now: datetime | None = None) -> ValidatedDrouotCapture:
    """Validate exact scope, complete pagination and source/DOM agreement first."""
    observed_at = now or datetime.now(timezone.utc)
    if observed_at.tzinfo is None:
        raise ValueError("now must include a timezone")
    if (not isinstance(payload, dict) or payload.get("format") != CAPTURE_FORMAT
            or type(payload.get("version")) is not int or payload["version"] != 1):
        raise ValueError("unsupported Drouot capture format or version")
    if set(payload) - {"format", "version", "exported_at", "window", "searches", "auctioneers"}:
        raise ValueError("unsupported capture metadata")
    exported = _timestamp(payload.get("exported_at"), observed_at, "exported_at")
    window = payload.get("window")
    try:
        if not isinstance(window, dict) or set(window) != {"start_date", "end_date", "time_zone"}:
            raise ValueError
        start, end = date.fromisoformat(window["start_date"]), date.fromisoformat(window["end_date"])
        if not 0 <= (end - start).days < 90 or window["time_zone"] != "America/New_York":
            raise ValueError
        zone = ZoneInfo(window["time_zone"])
    except (KeyError, TypeError, ValueError, ZoneInfoNotFoundError) as exc:
        raise ValueError("capture window requires inclusive dates and America/New_York") from exc
    chosen = list(entries)
    selected = {entry.url: entry for entry in chosen}
    if not selected or len(selected) != len(chosen):
        raise ValueError("select a nonempty distinct Drouot bookmark scope")
    for entry in chosen:
        _source_query(entry.url)
        if not entry.artist or entry.source != "Drouot":
            raise ValueError("selected entries need canonical Drouot artist identities")
    searches = payload.get("searches")
    if not isinstance(searches, list) or len(searches) != len(selected):
        raise ValueError("capture must cover every selected Drouot bookmark exactly once")
    auctioneers = payload.get("auctioneers", {})
    if not isinstance(auctioneers, dict) or len(auctioneers) > 5000:
        raise ValueError("invalid public auctioneer mapping")
    for house_id, name in auctioneers.items():
        _id(house_id, "auctioneer ID")
        _text(name, maximum=1000)
    observed: dict[str, NormalizedLot] = {}
    memberships: dict[str, set[str]] = {}
    rejected, searched, attribution_notes = [], set(), []
    page_count = result_count = outside = 0
    for search in searches:
        if not isinstance(search, dict) or set(search) - {"artist", "source_url", "pages"}:
            raise ValueError("invalid search evidence metadata")
        source_url = search.get("source_url")
        entry = selected.get(source_url)
        if entry is None or source_url in searched or artist_identity_key(str(search.get("artist", ""))) != artist_identity_key(entry.artist):
            raise ValueError("capture search identity differs from the current bookmark scope")
        searched.add(source_url)
        query = _source_query(source_url)
        pages = search.get("pages")
        if not isinstance(pages, list) or not pages:
            raise ValueError(f"{entry.artist}: no captured result pages")
        totals, page_numbers, identities = set(), set(), set()
        for page in pages:
            page_count += 1
            if page_count > MAX_CAPTURE_PAGES:
                raise ValueError("Drouot capture exceeds the page limit")
            if not isinstance(page, dict) or set(page) - {"page_url", "captured_at", "page", "total_pages", "total_results", "request_url", "status", "content_type", "lots", "cards"}:
                raise ValueError("invalid public page metadata")
            number = _integer(page.get("page"), "page", minimum=1)
            count = _integer(page.get("total_results"), "total_results")
            total_pages = _integer(page.get("total_pages"), "total_pages", minimum=1, maximum=MAX_CAPTURE_PAGES)
            if total_pages != max(1, math.ceil(count / MAX_PAGE_LOTS)) or number > total_pages or number in page_numbers:
                raise ValueError(f"{entry.artist}: inconsistent or repeated result page")
            totals.add((total_pages, count))
            page_numbers.add(number)
            captured = _timestamp(page.get("captured_at"), observed_at, "page.captured_at")
            if captured > exported:
                raise ValueError("a page was captured after the bundle export time")
            page_url = _public_url(page.get("page_url"))
            parts = urlsplit(page_url)
            page_query = parse_qs(parts.query, keep_blank_values=True)
            if (parts.hostname != "drouot.com" or parts.path != _SEARCH_PATH or parts.fragment
                    or set(page_query) - {"query", "page"} or page_query.get("query") != [query]
                    or page_query.get("page", ["1"]) != [str(number)]):
                raise ValueError("visible page URL does not preserve its bookmarked search scope")
            request = _public_url(page.get("request_url"))
            req = urlsplit(request)
            params = parse_qs(req.query, keep_blank_values=True)
            if (req.hostname != "api.drouot.com" or req.path != "/drouot/gingolem/neoGingo/lot/search"
                    or req.fragment or set(params) - {"lang", "q", "cat", "page", "facet"}
                    or params.get("q") != [query] or params.get("cat") != ["50"]
                    or params.get("page", ["1"]) != [str(number)] or params.get("lang") != ["en"]
                    or params.get("facet", ["false"]) not in (["false"], ["true"])):
                raise ValueError("Drouot response request does not match category, artist, language and page")
            if page.get("status") != 200 or "json" not in str(page.get("content_type", "")).casefold():
                raise ValueError("Drouot page needs a successful JSON response")
            raw_lots, cards = page.get("lots"), page.get("cards")
            expected_count = min(MAX_PAGE_LOTS, max(0, count - (number - 1) * MAX_PAGE_LOTS))
            if not isinstance(raw_lots, list) or not isinstance(cards, list) or len(raw_lots) != expected_count or len(cards) != expected_count:
                raise ValueError(f"{entry.artist}: truncated source or visible result page")
            if any(not isinstance(raw, dict) for raw in raw_lots) or any(not isinstance(card, dict) for card in cards):
                raise ValueError("Drouot response lots and cards must be public objects")
            ids = [_id(raw.get("id"), "lot.id") for raw in raw_lots]
            card_ids = [_id(card.get("id"), "card.id") for card in cards]
            if len(set(ids)) != len(ids) or len(set(card_ids)) != len(card_ids) or set(ids) != set(card_ids) or identities.intersection(ids):
                raise ValueError(f"{entry.artist}: duplicate IDs or source/visible result mismatch")
            identities.update(ids)
            result_count += len(ids)
            by_card = dict(zip(card_ids, cards))
            for raw in raw_lots:
                identity = str(raw["id"])
                lot, reason = _normalized_lot(raw, by_card[identity], entry, captured, auctioneers)
                if lot is None:
                    rejected.append({"artist": entry.artist, "source_lot_id": identity, "source_url": source_url, "reason": reason})
                    continue
                if lot.artist != entry.artist:
                    attribution_notes.append({"source_lot_id": identity, "watched_artist": entry.artist, "source_artist_credit": lot.artist})
                stamp, _ = parse_lot_datetime(lot.relevant_at)
                if not start <= stamp.astimezone(zone).date() <= end:
                    outside += 1
                    rejected.append({"artist": entry.artist, "source_lot_id": identity, "source_url": source_url, "reason": "Outside the inclusive capture date window."})
                    continue
                prior = observed.get(lot.cache_key)
                if prior is not None and prior.content_hash != lot.content_hash:
                    raise ValueError(f"lot {identity}: contradictory observations across artist searches")
                if prior is None or lot.last_seen_at > prior.last_seen_at:
                    observed[lot.cache_key] = lot
                memberships.setdefault(lot.cache_key, set()).add(source_url)
        if len(totals) != 1:
            raise ValueError(f"{entry.artist}: source result count changed while paging; recapture this search")
        total_pages, count = next(iter(totals))
        if page_numbers != set(range(1, total_pages + 1)) or len(identities) != count:
            raise ValueError(f"{entry.artist}: capture does not include every source result page")
    if searched != set(selected):
        raise ValueError("capture is missing a selected Drouot search")
    return ValidatedDrouotCapture(list(observed.values()), memberships, rejected, page_count, result_count, outside, dict(window), attribution_notes)


def import_saved_drouot_capture(path: str | Path, entries: Iterable[BookmarkEntry], cache: WatchlistCache, *, now: datetime | None = None) -> DrouotCaptureResult:
    """Validate the entire capture before any write; never retire absent lots."""
    chosen = list(entries)
    metrics = WatchlistMetrics(bookmark_urls=len(chosen), artists=len(chosen))
    try:
        with Path(path).open("rb") as stream:
            raw = stream.read(MAX_CAPTURE_BYTES + 1)
        if len(raw) > MAX_CAPTURE_BYTES:
            raise ValueError("Drouot capture is larger than 40 MiB")
        capture = validate_drouot_capture(json.loads(raw.decode("utf-8-sig")), chosen, now=now)
    except (ValueError, TypeError, KeyError, OSError, OverflowError, RecursionError) as exc:
        return DrouotCaptureResult([], metrics, errors=[f"Invalid Drouot capture: {exc}; no lots were imported."])
    known = {lot.cache_key: lot for entry in chosen for lot in cache.active_lots_for_watch_url(entry.url)}
    accepted, notices = {}, []
    for incoming in capture.lots:
        previous = cache.lookup(incoming)
        if previous:
            prior = previous.lot
            before, _ = parse_lot_datetime(prior.last_seen_at)
            after, _ = parse_lot_datetime(incoming.last_seen_at)
            if before and after < before:
                notices.append(f"{incoming.cache_key}: newer cached observation preserved; stale capture was not uploaded.")
                continue
            if prior.sold_price is not None or prior.status == "ended":
                notices.append(f"{incoming.cache_key}: existing sold or ended state preserved; upcoming observation excluded.")
                continue
            _retain_missing_static_fields(incoming, prior)
            incoming.first_seen_at = prior.first_seen_at
            incoming.content_hash = incoming.calculate_content_hash()
        accepted[incoming.cache_key] = incoming
    for key, incoming in accepted.items():
        stamp, _ = parse_lot_datetime(incoming.last_seen_at)
        transitions = [cache.upsert(incoming, watch_url=url, search_hash=incoming.content_hash, observed_at=stamp)
                       for url in sorted(capture.memberships[key])]
        incoming.status = "new" if "new" in transitions else "changed" if "changed" in transitions else "unchanged"
        cache.update_payload(incoming)
        if incoming.status == "new":
            metrics.new_lots += 1
        elif incoming.status == "changed":
            metrics.changed_lots += 1
        else:
            metrics.unchanged_lots += 1
    fallback = set(known) - set(accepted)
    lots = {**known, **accepted}
    notices.append(f"Validated {len(chosen)} Drouot searches and {capture.page_count} complete pages; imported {len(accepted)} dated artist/print observations. Unobserved lots were retained.")
    if capture.rejected_lots:
        notices.append(f"{len(capture.rejected_lots)} keyword results were excluded with explicit rejection reasons.")
    return DrouotCaptureResult(
        sorted(lots.values(), key=lambda lot: (lot.relevant_at, lot.artist.casefold(), lot.source_lot_id)),
        metrics, notices=notices, fallback_lot_keys=fallback,
        rejected_lots=capture.rejected_lots,
        attribution_notes=capture.attribution_notes,
        capture_summary={"searches": len(chosen), "pages": capture.page_count, "source_results": capture.result_count,
                         "accepted": len(accepted), "rejected": len(capture.rejected_lots), "outside_window": capture.outside_window,
                         "window": capture.window},
    )
