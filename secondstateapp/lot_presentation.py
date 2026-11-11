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
    ("Bacon, Francis",), ("Baldessari, John",), ("Basquiat, Jean-Michel", "Jean Michel Basquiat"), ("Beckmann, Max",),
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
    # Complete November 2026 Calendar credit audit. These are explicit full
    # names, not a rule that treats an unknown name's final token as its surname.
    # Keep supplied middle names, compound family names and established aliases.
    ("Agam, Yaacov",), ("Ahrendt, William",), ("Aitchison, Craigie",),
    ("Albright, Ivan Le Lorraine",), ("Avery, Milton",), ("Ayres, Gillian",),
    ("Baechler, Donald",), ("Baskin, Leonard",), ("Beuys, Joseph",),
    ("Bernheim de Villers, Gaston",),
    # Preserve this source spelling; a display-order change is not an identity correction.
    ("Balderssari, John",),
    ("Biggers, Sanford",), ("Bonnard, Pierre", "Pierre (1867) Bonnard"),
    ("Borofsky, Jonathan",), ("Bowling, Frank",),
    ("Brown, Christopher",), ("Brown, Harley",), ("Brown, Roger",), ("Burden, Chris",),
    ("Cassatt, Mary",), ("Cassatt, Mary Stevenson",), ("Cézanne, Paul",),
    ("Chadwick, Helen",), ("Chughtai, Abdur Rahman",), ("Cocteau, Jean",),
    ("Craig-Martin, Michael",), ("De Forest, Roy Dean",), ("Degas, Edgar",),
    ("Dix, Otto",), ("Dorazio, Piero",), ("Driskell, David Clyde",),
    ("Dubuffet, Jean",), ("Duchamp, Marcel",), ("Dylan, Bob",),
    ("Emin, Tracey",), ("Ensor, James",), ("Fahlström, Öyvind",),
    ("Feininger, Lyonel",), ("Fini, Leonor",), ("Fitzpatrick, Tony",),
    ("Fontana, Lucio",), ("Foujita, Léonard Tsuguharu",), ("Fry, Anthony",),
    ("García Ortega, José",), ("Giacometti, Alberto",), ("Gilliam, Sam",),
    ("Golub, Leon Albert",), ("Grignion, Charles",), ("Gromaire, Marcel",),
    ("Hall, Norma Bassett",), ("Hamaguchi, Yozo",), ("Hamilton, Ann",),
    ("Hancock, Trenton Doyle",), ("Heilmann, Mary",), ("Heizer, Michael",),
    ("Held, Al",), ("Helleu, Paul César",), ("Howell-Sickles, Donna",),
    ("Hoyland, John",), ("Hughes, Shara",), ("Kandinsky, Wassily",),
    ("Kent, Mary Corita",), ("Kentridge, William",), ("Klimt, Gustav",),
    ("Knight, Gwendolyn",), ("Kohlmeyer, Ida Rittenberg",), ("Laurencin, Marie",),
    ("Le Parc, Julio",), ("Lowry, Laurence Stephen",), ("Lynch, Rhett",),
    ("Maillol, Aristide",), ("Manet, Édouard",), ("Mapplethorpe, Robert",),
    ("Marini, Marino",), ("Martin, Fletcher",), ("Mell, Ed",), ("Milton, Peter",),
    ("Monet, Claude",), ("Morgan, Barbara",), ("Murphy, Brenda",),
    ("Oiestad, H Steven",), ("Olitski, Jules",), ("Paladino, Mimmo",),
    ("Paschke, Ed",), ("Pasmore, Victor",), ("Perkinson, Tom",), ("Perry, Grayson",),
    ("Pirnie, Larry",), ("Pollock, Jackson",), ("Porter, Fairfield",),
    ("Ramberg, Christina",), ("Rego, Paula",), ("Reinhardt, Ad",),
    ("Rijn, Rembrandt Harmensz. van",), ("Robert, Hubert",), ("Roberts, Dolona",),
    ("Salle, David",), ("Schenck, Bill",), ("Scholder, Fritz",), ("Scholz, Georg",),
    ("Scully, Sean",), ("Severini, Gino",), ("Shapiro, Joel",), ("Shires, William",),
    ("Shonibare, Yinka",), ('Shufelt, Robert "Shoofly"',), ("Sorlier, Charles",),
    ("Sultan, Donald K.",), ("Surls, James",), ("Thornley, Georges William",),
    ("Trova, Ernest Tino",), ("Turk, Gavin",), ("van Ostade, Adriaen Jansz",),
    ("Vigil, Dan",), ("Villon, Jacques",), ("Walker, Caroline",), ("Wewerka, Stefan",),
    ("Whitney, Stanley",), ("Wieghorst, Olaf",), ("Wilson, John Woodrow",),
    ("Wylie, Rose",), ("Yoshida, Hiroshi",), ("Young, Russell",), ("Zerbini, Luiz",),
    # Verified artist credits in Bukowskis Modern Art & Design sale 676.
    ("Bærtling, Olle", "Olle Baertling", "Baertling, Olle"),
    ("Dufy, Raoul",), ("Lindström, Bengt",), ("Poliakoff, Serge",),
    # Verified artist credits in Sotheby's Modern & Contemporary Discoveries DE2640.
    ("da Corte, Alex",), ("Förg, Günther",), ("Heckel, Erich",), ("Horn, Rebecca",),
    ("Ikemura, Leiko",), ("Monk, Jonathan",), ("Nitsch, Hermann",), ("Price, Seth",),
    ("Reyle, Anselm",), ("Scheiber, Hugó",), ("Schütte, Thomas",),
    ("Tillmans, Wolfgang",), ("West, Franz",), ("Zimmermann, Peter",),
    # Established stage names and mononyms are not given-name/surname pairs.
    ("A. R. Penck", "A.R. Penck", "Penck, A.R.", "Penck, A. R."),
    ("Invader",), ("Man Ray",), ("Panamarenko",), ("Yvaral (Jean-Pierre Vasarely)",),
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
_ATTRIBUTION_PREFIX = re.compile(rf"^(?P<prefix>{_ATTRIBUTION}|\({_ATTRIBUTION}\))\s+(?P<name>.+)$", re.IGNORECASE)
_ATTRIBUTION_SUFFIX = re.compile(
    rf"^(?P<name>.+?)(?P<suffix>\s*\({_ATTRIBUTION}\)|(?:,\s*|\s+){_ATTRIBUTION}\.?)$", re.IGNORECASE,
)
_GENERATION = re.compile(r"^(?P<name>.+?)(?P<suffix>,?\s+(?:Jr\.?|Sr\.?|II|III|IV))$", re.IGNORECASE)
_DISPLAY_BIOGRAPHY = re.compile(r"^(?P<name>.+?)(?P<suffix>\s+\([^()]*\b\d{4}\b[^()]*\))$")
_DISPLAY_MAKER_CREDIT = re.compile(
    r"^(?P<name>.+?)(?P<separator>,\s*by\s+|\s+after\.\s+)(?P<maker>.+)$", re.IGNORECASE,
)


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


def _known_artist_display(name: str) -> str | None:
    display = _DISPLAY_NAMES.get(_name_key(name))
    if display is None:
        ending = _GENERATION.fullmatch(name) or _DISPLAY_BIOGRAPHY.fullmatch(name)
        if ending:
            known = _DISPLAY_NAMES.get(_name_key(ending["name"]))
            if known:
                display = known + ending["suffix"]
    return display


def artist_display_name(value: object) -> str:
    """Use curated surname-first spelling while retaining attribution wording."""
    label = clean_display_text(value)
    prefix, name, suffix = _attribution_parts(label)
    display = _known_artist_display(name)
    if display is None:
        # These source credits identify an original artist and a printmaker.
        # Reformat only two complete curated names, keeping their roles/order;
        # an unknown collaborator or arbitrary title must remain untouched.
        credit = _DISPLAY_MAKER_CREDIT.fullmatch(name)
        if credit:
            original = _known_artist_display(credit["name"])
            maker = _known_artist_display(credit["maker"])
            if original and maker:
                display = original + credit["separator"] + maker
    return prefix + (display or name) + suffix


def artist_sort_key(value: object) -> str:
    """Collate the displayed surname, ignoring attribution prefixes/suffixes.

    Accents are removed only from this sorting value, never the display label.
    Unresolved names keep their original token order rather than a guessed surname.
    """
    _, name, _ = _attribution_parts(artist_display_name(value))
    return _name_key(name)


_ATTRIBUTION_WARNING = re.compile(r"\b(after|attributed\s+to)\b", re.IGNORECASE)
_FRENCH_AFTER = r"d\s*['’‘ʼ]?\s*apr[eè]s"
_FRENCH_ATTRIBUTION = rf"(?:{_FRENCH_AFTER}|attribu[eé]e?\s+[aà])"
_ATTRIBUTION_TITLE_MARKER = re.compile(rf"\b(?:after|attributed\s+to|{_FRENCH_ATTRIBUTION})\b", re.IGNORECASE)
_FRENCH_CREDIT_PREFIX = re.compile(rf"^(?P<lead>\(?\s*)(?P<marker>{_FRENCH_ATTRIBUTION})(?=\s|\)|:|$)", re.IGNORECASE)
_FRENCH_CREDIT_SUFFIX = re.compile(rf"(?P<lead>\(\s*|,\s*)(?P<marker>{_FRENCH_ATTRIBUTION})(?P<tail>\s*\)?)$", re.IGNORECASE)
_CREDIT_BIOGRAPHY = re.compile(r"\s*\([^)]*\b\d{4}\b[^)]*\)\s*")
_BILINGUAL_AFTER = re.compile(r"\bnach\s*[-–—/]\s*after\b", re.IGNORECASE)
_TRAILING_CREDIT_SUFFIX = re.compile(
    rf"^(?P<name>.+?)(?:,\s*|\s+)(?P<marker>after|attributed\s+to|{_FRENCH_ATTRIBUTION})"
    r"(?:\.(?:\s+(?:Jacques\s+Villon|Villon,\s*Jacques))?)?$", re.IGNORECASE,
)
_QUOTED_TITLE_AFTER_CREDIT = re.compile(
    r'^(?P<name>.+?)\s+after\s+(?:"[^"]+"|“[^”]+”)$', re.IGNORECASE,
)
_QUOTED_WORK = r'(?:"[^"]+"|“[^”]+”|«[^»]+»)'
_STRUCTURED_TITLE_CREDITS = (
    # A quoted work is separated from the artist credit, optionally by medium.
    re.compile(rf"^(?:(?:lithographie|oeuvre|œuvre|tableau)\s+)?{_QUOTED_WORK}\s+(?P<credit>.+)$", re.IGNORECASE),
    # The qualifier itself separates an artist heading from its following work.
    re.compile(rf"^(?P<credit>.+?\(\s*(?:after|attributed\s+to|{_FRENCH_ATTRIBUTION})\s*\))\s+\S.*$", re.IGNORECASE),
    # Retain the collective credit in Lux's explicitly colored Haring/Banksy lot.
    re.compile(rf"^(?P<credit>.+\s+&\s+.+\s+{_FRENCH_AFTER})\s+\(blanc\)$", re.IGNORECASE),
    # This Artcurial caption has mismatched title quotes, but a complete credit
    # and a separate publisher suffix. Do not strip arbitrary trailing prose.
    re.compile(rf'''^carr[ée]\s+["“«][^"“”«»]+['"”»]\s+(?P<credit>{_FRENCH_AFTER}\s+.+?)\s+[ée]dition\s+artcurial\.?$''', re.IGNORECASE),
)
_FRENCH_AFTER_WORK_CREDIT = re.compile(
    rf"^{_FRENCH_AFTER}\s+une\s+lithographie\s+{_QUOTED_WORK}\s+"
    r"(?:de\s+|d\s*['’‘ʼ]\s*)(?P<name>.+)$", re.IGNORECASE,
)
# Explicit auction-credit alias; retain strict full-name matching in titles.
_CREDIT_NAME_ALIASES = {("harmensz", "rembrandt", "rijn", "van"): ("rembrandt",)}


def _attribution_credit(value: object) -> tuple[str, str]:
    """Read explicit credit markers without changing the supplied artist text."""
    text = clean_display_text(value, strip_lot_markers=True)
    text = " ".join(_CREDIT_BIOGRAPHY.sub(" ", text).split())
    text = _BILINGUAL_AFTER.sub("After", text)
    # Lux uses bare trailing d'après; Forum can end a qualifier with a full
    # stop and append printmaker Jacques Villon. Normalize these credit endings
    # only; source text stays intact and title credits still require a name match.
    trailing = _TRAILING_CREDIT_SUFFIX.fullmatch(text)
    if trailing:
        text = f"{trailing['name']}, {trailing['marker']}"
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


def _credit_matches_artist(name: str, names: set[tuple[str, ...]]) -> bool:
    if _credit_name_key(name) in names:
        return True
    # An explicit collective credit qualifies both complete, known names.
    # A substring, unknown collaborator, or generation suffix is insufficient.
    components = re.split(r"\s+&\s+", name)
    return (len(components) > 1
            and all(_name_key(artist_display_name(part)) in _DISPLAY_NAMES for part in components)
            and any(_credit_name_key(part) in names for part in components))


def _structured_title_credits(text: str):
    for pattern in _STRUCTURED_TITLE_CREDITS:
        match = pattern.fullmatch(text)
        if match:
            yield match["credit"]
    # The offered work is explicitly after a named artist's quoted lithograph.
    match = _FRENCH_AFTER_WORK_CREDIT.fullmatch(text)
    if match:
        yield f"After {match['name']}"


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
    # Felima separates its full artist credit from the work with quotation
    # marks: Andy Warhol After “Mao Yellow”. Keep unquoted After titles out.
    quoted_credit = _QUOTED_TITLE_AFTER_CREDIT.fullmatch(text)
    if quoted_credit and _credit_name_key(quoted_credit["name"]) in names:
        return "After"
    candidates = [text, *str(title or "").splitlines(), *_structured_title_credits(text)]
    candidates.extend(re.split(r"\s+[—–/-]\s+|[:;]", text))
    candidates.extend(match[1] for match in re.finditer(r"\(([^()]*)\)", text))
    # A catalog can write After Picasso, Pablo, Title or Picasso, Pablo, after.
    for comma in re.finditer(",", text):
        candidates.extend((text[:comma.start()], text[comma.end():]))
    for candidate in dict.fromkeys(candidates):
        label, name = _attribution_credit(candidate)
        if label and _credit_matches_artist(name, names):
            return label
    return ""
