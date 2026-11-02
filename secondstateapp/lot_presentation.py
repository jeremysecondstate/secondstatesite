"""Display-only lot text and artist ordering; never use these as identity keys.

The artist table is deliberately curated rather than a last-token heuristic.
Unknown names, collaborations and other unresolved labels retain their order.
No registry files, database records or network resources are read at runtime.
"""

from __future__ import annotations

from html import unescape
from html.entities import html5
import re
import unicodedata


def _byte_characters(codec: str, start: int, end: int) -> str:
    characters = []
    for value in range(start, end + 1):
        try:
            characters.append(bytes([value]).decode(codec))
        except UnicodeDecodeError:
            pass
    return re.escape("".join(characters))


def _mojibake_pattern(codec: str) -> re.Pattern[str]:
    continuation = f"[{_byte_characters(codec, 0x80, 0xBF)}]"
    return re.compile("|".join(
        f"[{_byte_characters(codec, start, end)}]{continuation}{{{length}}}"
        for start, end, length in ((0xC2, 0xDF, 1), (0xE0, 0xEF, 2), (0xF0, 0xF4, 3))
    ))


_MOJIBAKE = tuple((codec, _mojibake_pattern(codec)) for codec in ("cp1252", "latin1"))
_ENTITY = re.compile(r"&(?:#[xX][0-9a-fA-F]+|#[0-9]+|[A-Za-z][A-Za-z0-9]+);")
_LOT_MARKERS = re.compile(r"^[\s§*]+")


def _repair_mojibake(value: str) -> str:
    # Repair only exact, reversible byte sequences. Local matches allow good
    # Unicode and damaged text to coexist, and leave a real Â in L'Âge intact.
    for _ in range(3):
        previous = value
        for codec, pattern in _MOJIBAKE:
            def repair(match: re.Match[str]) -> str:
                original = match.group()
                try:
                    candidate = original.encode(codec).decode("utf-8")
                    if candidate.encode("utf-8").decode(codec) == original:
                        return candidate
                except (UnicodeEncodeError, UnicodeDecodeError):
                    pass
                return original

            value = pattern.sub(repair, value)
        if value == previous:
            break
    return value


def clean_display_text(value: object, *, strip_lot_markers: bool = False) -> str:
    """Return plain display text, preserving symbols except opted-in prefixes.

    This is not an HTML sanitizer: callers must retain normal template escaping.
    Irrecoverable replacement characters become spacing, never invented letters.
    """
    text = "" if value is None else str(value)
    for _ in range(3):
        previous = text
        # Repair before collapsing NBSP: it can still be a UTF-8 byte (Ã ).
        text = _repair_mojibake(text)
        text = _ENTITY.sub(
            lambda match: unescape(match.group())
            if match.group().startswith("&#") or match.group()[1:] in html5 else match.group(), text,
        )
        if text == previous:
            break
    text = _repair_mojibake(text)
    text = "".join(
        " " if character.isspace() or character == "\ufffd" else
        "" if unicodedata.category(character) == "Cc" or character in "\ufeff\u200b\u00ad" else character
        for character in text
    )
    text = " ".join(unicodedata.normalize("NFC", text).split())
    return _LOT_MARKERS.sub("", text).strip() if strip_lot_markers else text


# Surname-first display labels from the curated artist bookmarks, with explicit
# source aliases. Verified provider differences also appear in liveart_artist.py.
# Stage names remain intact even when a bookmark mechanically inverts them.
_ARTISTS = (
    ("Adams, Derrick",), ("Albers, Josef",), ("Alechinsky, Pierre",),
    ("Appel, Karel",), ("Arman",), ("Banksy",), ("Barnet, Will", "Will Barnett", "Barnett, Will"),
    ("Baumann, Gustave",),
    ("Bearden, Romare Howard", "Romare Bearden", "Bearden, Romare"),
    ("Benton, Thomas Hart",), ("Botero, Fernando",), ("Braque, Georges",),
    ("Calder, Alexander", "Alexander (1898) Calder"), ("Catlett, Elizabeth",),
    ("Chagall, Marc",), ("CHARLY ROCKS",), ("Christo",), ("Close, Chuck",), ("Corinth, Lovis",),
    ("Dalí, Salvador",), ("de Kooning, Willem",), ("Delaunay, Sonia",), ("Delvaux, Paul",),
    ("Dine, Jim",), ("Dürer, Albrecht", "Albrecht (1471) Dürer"), ("Ernst, Max",),
    ("Estes, Richard",), ("Fairey, Shepard",), ("Francis, Sam",), ("Friedeberg, Pedro",),
    ("Frink, Elisabeth",), ("Garcia, Jerry",), ("Gottlieb, Adolph",), ("Goya, Francisco de",),
    ("Haring, Keith",), ("Hirst, Damien",), ("Hockney, David",),
    ("Hundertwasser, Friedensreich", "Friedrich Hundertwasser", "Hundertwasser, Friedrich"),
    ("Icart, Louis",), ("Kahn, Wolf",), ("Katz, Alex",), ("Kelly, Ellsworth",), ("Kent, Rockwell",),
    ("Kollwitz, Käthe",), ("Kusama, Yayoi",), ("Lam, Wifredo",), ("Léger, Fernand",),
    ("Lewis, Martin",), ("Lichtenstein, Roy",), ("Liebermann, Max",), ("Magritte, René",),
    ("Matisse, Henri",), ("Max, Peter",), ("Megargee, Alonzo",), ("Miró, Joan",),
    ("Moore, Henry", "Henry (1898) Moore"), ("Motherwell, Robert",),
    ("Mr. Brainwash", "Mr Brainwash", "Brainwash, Mr.", "Brainwash, Mr"),
    ("Mucha, Alphonse",), ("Murakami, Takashi",),
    ("Neiman, LeRoy", "Leroy Neimann", "Neimann, Leroy"),
    ("Nieto, John", "John W Nieto", "John W. Nieto", "Nieto, John W.", "Nieto, John W"),
    ("Picasso, Pablo",), ("Piranesi, Giovanni Battista",), ("Ramos, Mel",),
    ("Rauschenberg, Robert",), ("Rembrandt",),
    ("Renoir, Pierre-Auguste", "Auguste Renoir", "Renoir, Auguste", "Pierre Auguste Renoir"),
    ("Rizzi, James",), ("Rockwell, Norman Perceval", "Norman Rockwell", "Rockwell, Norman"),
    ("Rodrigue, George",), ("Rosenquist, James",), ("Shrigley, David",),
    ("Sloan, John", "John (1871) Sloan"), ("Stella, Frank",), ("Tamayo, Rufino",),
    ("Tàpies, Antoni",), ("Thiebaud, Wayne",), ("Toulouse-Lautrec, Henri de",),
    ("Vasarely, Victor",), ("Warhol, Andy",), ("Wood, Grant",),
    ("Zao, Wou-Ki", "Zao Wou-Ki"), ("Zúñiga, Francisco",),
    # Additional explicit labels in the existing research registry/bookmarks.
    ("Adnan, Etel",), ("Ai, Weiwei", "Ai Weiwei"), ("Arp, Jean (Hans)", "Jean Arp", "Hans Arp"),
    ("Bacon, Francis",), ("Baldessari, John",), ("Basquiat, Jean-Michel",), ("Beckmann, Max",),
    ("Bernhardt, Katherine",), ("Blake, William",), ("Bourgeois, Louise",), ("Bravo, Claudio",),
    ("Carrington, Leonora",), ("Chu, Teh-Chun", "Chu Teh-Chun"), ("Condo, George",),
    ("de Kooning, Elaine Marie", "Elaine de Kooning", "de Kooning, Elaine"),
    ("de Lempicka, Tamara",), ("de Saint-Phalle, Niki", "Niki de Saint Phalle", "Niki de Saint-Phalle"),
    ("El Anatsui",), ("Gauguin, Paul",), ("Gober, Robert",), ("Guston, Philip",),
    ("Johns, Jasper",), ("Kapoor, Anish",), ("Kaphar, Titus",), ("KAWS",), ("Koons, Jeff",),
    ("Marden, Brice",), ("Martin, Agnes",), ("Mehretu, Julie",), ("Mitchell, Joan",),
    ("Nara, Yoshitomo",), ("Nevelson, Louise",), ("Party, Nicolas",), ("Pistoletto, Michelangelo",),
    ("Prince, Richard",), ("Richter, Gerhard",), ("Riley, Bridget",), ("Ruscha, Ed",),
    ("Ryman, Robert",), ("Sheeler, Charles", "Charles R. Sheeler"), ("Sherman, Cindy",),
    ("Sillman, Amy",), ("Smith, Kiki",), ("Soulages, Pierre",), ("Thomas, Mickalene",),
    ("Twombly, Cy",), ("Valdés, Manolo",), ("Walker, Kara",), ("Winters, Terry",),
    ("O'Keeffe, Georgia", "Georgia O’Keeffe"),
    # Individual artists already represented by the saved whole-sale Calendar.
    # Curated bookmarks also explicitly establish Nauman/Judd/Frankenthaler/
    # Lozowick/Serra/Matta/LeWitt/Ruff/Ting. Retain qualifiers and stage names.
    ("Albuquerque, Lita",), ("Anderson, Noel",), ("Armleder, John",), ("Arsham, Daniel",),
    ("Bartlett, Jennifer",), ("Bidlo, Mike",), ("Bochner, Mel",), ("Bolotowsky, Ilya",),
    ("Brice, Lisa",), ("Burr, George Elbert",), ("Cannon, T.C.", "T. C. Cannon"),
    ("Cole, Willie",), ("Copley, William N.", "William N Copley"), ("Crichlow, Ernest",),
    ("Diebenkorn, Richard",), ("Dunham, Carroll",),
    ("Escher, Maurits Cornelis", "M.C. Escher", "M. C. Escher"),
    ("Frankenthaler, Helen",), ("Garber-Maikovska, Aaron",), ("Gibson, Jeffrey",),
    ("Gibson, Jeffrey (Choctaw/Cherokee)", "Jeffrey Gibson (Choctaw/Cherokee)"),
    ("Giorno, John",), ("Hadzi, Dimitri",), ("Hodgkin, Howard",), ("Indiana, Robert",),
    ("Johnson, Rashid",), ("Judd, Donald",), ("Kass, Deborah",), ("Katz, Ada",),
    ("Kent, Caroline",), ("Lawrence, Jacob",), ("Le Corbusier",), ("LeWitt, Sol",),
    ("Ligon, Glenn",), ("Longo, Robert",), ("Lozowick, Louis",), ("Mangold, Robert",),
    ("Marclay, Christian",), ("Marsh, Reginald",), ("Matta, Roberto",), ("Milhazes, Beatriz",),
    ("Minter, Marilyn",), ("Murray, Elizabeth",), ("Nakian, Reuben",), ("Nares, Jamie",),
    ("Nauman, Bruce",), ("Neel, Alice",), ("Neto, Ernesto",), ("Noland, Kenneth",),
    ("Opie, Julian",), ("Pennell, Joseph",), ("Perez, Enoc",), ("Ramié, Alain",),
    ("Reeder, Scott",), ("Rothenberg, Susan",), ("Ruff, Thomas",), ("Sanguinetti, Alessandra",),
    ("Scharf, Kenny",), ("Seliger, Jonathan",), ("Serra, Richard",), ("Spero, Nancy",),
    ("Steir, Pat",), ("Sultan, Donald",), ("Sze, Sarah",), ("Thomas, Hank Willis",),
    ("Thompson, Bob",), ("Ting, Walasse",), ("Vicente, Esteban",), ("Wesley, John",),
    ("Wesselmann, Tom",), ("Whistler, James Abbott McNeill",), ("White, Charles",), ("Wiiralt, Eduard",),
    # Getty ULAN 500476131 and 500011051 explicitly provide these index names.
    ("Pettway, Essie Bendolph",), ("Rijn, Rembrandt van", "Rembrandt van Rijn"),
    # His representing gallery uses Shibuya: bsandcgallery.com/artists/sho-shibuya.
    ("Shibuya, Sho",),
)


def _name_key(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).casefold()
    value = "".join(character for character in value if not unicodedata.combining(character))
    value = value.translate(str.maketrans({"’": "'", "‘": "'", "‐": "-", "‑": "-", ".": ""}))
    return re.sub(r"\s*,\s*", ", ", " ".join(value.split()))


_DISPLAY_NAMES: dict[str, str] = {}
for _display, *_aliases in _ARTISTS:
    _variants = [_display, *_aliases]
    if _display.count(",") == 1:
        _surname, _given = _display.split(",", 1)
        _variants.append(f"{_given.strip()} {_surname}")
    for _variant in _variants:
        _DISPLAY_NAMES[_name_key(_variant)] = _display

_ATTRIBUTION = r"(?:attributed to|circle of|school of|studio of|workshop of|manner of|style of|followers? of|after)"
_ATTRIBUTION_PREFIX = re.compile(rf"^(?P<prefix>{_ATTRIBUTION})\s+(?P<name>.+)$", re.IGNORECASE)
_ATTRIBUTION_SUFFIX = re.compile(rf"^(?P<name>.+?)(?P<suffix>\s*\({_ATTRIBUTION}\)|,\s*{_ATTRIBUTION})$", re.IGNORECASE)
_GENERATION = re.compile(r"^(?P<name>.+?)(?P<suffix>,?\s+(?:Jr\.?|Sr\.?|II|III|IV))$", re.IGNORECASE)


def _attribution_parts(value: str) -> tuple[str, str, str]:
    prefix = suffix = ""
    for _ in range(3):
        match = _ATTRIBUTION_PREFIX.fullmatch(value)
        if not match:
            break
        prefix += match["prefix"] + " "
        value = match["name"]
    match = _ATTRIBUTION_SUFFIX.fullmatch(value)
    if match:
        value, suffix = match["name"], match["suffix"]
    return prefix, value, suffix


def artist_display_name(value: object) -> str:
    """Use curated surname-first spelling while retaining attribution wording."""
    label = clean_display_text(value)
    prefix, name, suffix = _attribution_parts(label)
    display = _DISPLAY_NAMES.get(_name_key(name))
    if display is None:
        generation = _GENERATION.fullmatch(name)
        if generation:
            known = _DISPLAY_NAMES.get(_name_key(generation["name"]))
            if known:
                display = known + generation["suffix"]
    return prefix + (display or name) + suffix


def artist_sort_key(value: object) -> str:
    """Collate the displayed surname, ignoring attribution prefixes/suffixes.

    Accents are removed only from this sorting value, never the display label.
    Unresolved names keep their original token order rather than a guessed surname.
    """
    _, name, _ = _attribution_parts(artist_display_name(value))
    return _name_key(name)


_ATTRIBUTION_WARNING = re.compile(r"\b(after|attributed\s+to)\b", re.IGNORECASE)
_FRENCH_ATTRIBUTION = r"(?:d['’‘ʼ]?\s*apr[eè]s|attribu[eé]e?\s+[aà])"
_ATTRIBUTION_TITLE_MARKER = re.compile(rf"\b(?:after|attributed\s+to|{_FRENCH_ATTRIBUTION})\b", re.IGNORECASE)
_FRENCH_CREDIT_PREFIX = re.compile(rf"^(?P<lead>\(?\s*)(?P<marker>{_FRENCH_ATTRIBUTION})(?=\s|\)|:|$)", re.IGNORECASE)
_FRENCH_CREDIT_SUFFIX = re.compile(rf"(?P<lead>\(\s*|,\s*)(?P<marker>{_FRENCH_ATTRIBUTION})(?P<tail>\s*\)?)$", re.IGNORECASE)
_CREDIT_BIOGRAPHY = re.compile(r"\s*\([^)]*\b\d{4}\b[^)]*\)\s*")
_BILINGUAL_AFTER = re.compile(r"\bnach\s*[-–—/]\s*after\b", re.IGNORECASE)
# Explicit auction-credit alias; retain strict full-name matching in titles.
_CREDIT_NAME_ALIASES = {("harmensz", "rembrandt", "rijn", "van"): ("rembrandt",)}


def _attribution_credit(value: object) -> tuple[str, str]:
    """Read explicit credit markers without changing the supplied artist text."""
    text = clean_display_text(value, strip_lot_markers=True)
    text = " ".join(_CREDIT_BIOGRAPHY.sub(" ", text).split())
    text = _BILINGUAL_AFTER.sub("After", text)
    # Translate only explicit credit-position markers, never the stored source.
    def translate_marker(match):
        label = "After" if match["marker"].casefold().startswith("d") else "Attributed to"
        return match["lead"] + label + match.groupdict().get("tail", "")
    text = _FRENCH_CREDIT_PREFIX.sub(translate_marker, text)
    text = _FRENCH_CREDIT_SUFFIX.sub(translate_marker, text)
    wrapped = re.fullmatch(r"\(\s*((?:after|attributed\s+to)\b.+)\s*\)", text, re.IGNORECASE)
    if wrapped:
        text = wrapped[1].strip()
    text = re.sub(r"^\(\s*(after|attributed\s+to)\s*\)\s*:?\s*", r"\1 ", text, flags=re.IGNORECASE)
    text = re.sub(r"^(after|attributed\s+to)\s*:\s*", r"\1 ", text, flags=re.IGNORECASE)
    prefix, name, suffix = _attribution_parts(text)
    marker = _ATTRIBUTION_WARNING.search(prefix + " " + suffix)
    label = "Attributed to" if marker and marker[1].casefold().startswith("attributed") else "After" if marker else ""
    return label, name


def _credit_name_key(value: object) -> tuple[str, ...]:
    _, name = _attribution_credit(value)
    # Use only a complete supplied name or its existing curated display alias.
    # Sorted tokens permit explicit surname-first labels, not fuzzy matching.
    key = tuple(sorted(re.findall(r"\w+", _name_key(artist_display_name(name)))))
    return _CREDIT_NAME_ALIASES.get(key, key)


def artist_attribution_label(*artists: object, title: object = "") -> str:
    """Flag explicit After/Attributed-to credits, including bound title credits.

    Inspect the raw auction artist before a canonical watchlist label can hide
    its qualifier. A title contributes only a structured credit naming that
    same artist; ordinary work titles such as After the Party remain unflagged.
    """
    for artist in artists:
        label, _ = _attribution_credit(artist)
        if label:
            return label
    # Keep the bilingual marker together before splitting title/credit fields.
    text = _BILINGUAL_AFTER.sub("After", clean_display_text(title, strip_lot_markers=True))
    if not _ATTRIBUTION_TITLE_MARKER.search(text):
        return ""
    names = {_credit_name_key(artist) for artist in artists if clean_display_text(artist)}
    names.discard(())
    if not names:
        return ""
    candidates = [text, *str(title or "").splitlines()]
    candidates.extend(re.split(r"\s+[—–-]\s+|[:;]", text))
    candidates.extend(match[1] for match in re.finditer(r"\(([^()]*)\)", text))
    # A catalog can write After Picasso, Pablo, Title or Picasso, Pablo, after.
    for comma in re.finditer(",", text):
        candidates.extend((text[:comma.start()], text[comma.end():]))
    for candidate in dict.fromkeys(candidates):
        label, name = _attribution_credit(candidate)
        if label and _credit_name_key(name) in names:
            return label
    return ""
