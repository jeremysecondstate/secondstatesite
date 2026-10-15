"""Consistent, conservative formatting for public artwork dimensions.

Catalog height/width cells are inches unless an explicit unit says otherwise.
Unrecognized free text is retained, so editing a listing cannot silently erase
qualifiers such as "sight", "framed", or a diameter measurement.
"""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
import re


_MISSING_VALUES = {"", "nan", "none", "null", "<na>", "nat", "n/a", "na"}
_NUMBER = r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_MEASUREMENT = re.compile(
    rf"^(?P<number>{_NUMBER}|\d+\s+(?:-\s*)?\d+\s*/\s*\d+|\d+-\d+\s*/\s*\d+|\d+\s*/\s*\d+)"
    r"\s*(?P<unit>\"|″|[“”]|in\.?|inch(?:es)?|cm\.?|centimet(?:er|re)s?|mm\.?|millimet(?:er|re)s?)?$",
    re.IGNORECASE,
)
_PAIR_SEPARATOR = re.compile(r"\s*(?:[xX×✕]|\bby\b)\s*", re.IGNORECASE)
_SHEET_PREFIX = re.compile(r"^s\s*(?=[\d.¼½¾⅐⅑⅒⅓⅔⅕⅖⅗⅘⅙⅚⅛⅜⅝⅞])", re.IGNORECASE)
_VULGAR_FRACTIONS = {
    "¼": "1/4", "½": "1/2", "¾": "3/4", "⅐": "1/7", "⅑": "1/9",
    "⅒": "1/10", "⅓": "1/3", "⅔": "2/3", "⅕": "1/5", "⅖": "2/5",
    "⅗": "3/5", "⅘": "4/5", "⅙": "1/6", "⅚": "5/6", "⅛": "1/8",
    "⅜": "3/8", "⅝": "5/8", "⅞": "7/8",
}


def _text(value):
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.casefold() in _MISSING_VALUES else text


def _measurement(value):
    """Return (Decimal, explicit unit) only for a fully understood value."""
    text = _text(value)
    for symbol, fraction in _VULGAR_FRACTIONS.items():
        text = text.replace(symbol, " " + fraction)
    match = _MEASUREMENT.fullmatch(text.strip())
    if not match:
        return None
    number = match.group("number")
    try:
        with localcontext() as context:
            context.prec = 40
            if "/" in number:
                numerator_text, denominator_text = number.rsplit("/", 1)
                parts = re.split(r"\s+|\s*-\s*", numerator_text.strip())
                parts = [part for part in parts if part]
                whole = Decimal(parts[0]) if len(parts) == 2 else Decimal(0)
                numerator = Decimal(parts[-1])
                denominator = Decimal(denominator_text)
                if denominator == 0:
                    return None
                amount = whole + numerator / denominator
            else:
                amount = Decimal(number)
    except (InvalidOperation, ZeroDivisionError):
        return None
    if not amount.is_finite():
        return None
    raw_unit = (match.group("unit") or "").lower()
    if raw_unit.startswith(("cm", "centimet")):
        unit = "cm"
    elif raw_unit.startswith(("mm", "millimet")):
        unit = "mm"
    else:
        unit = "in" if raw_unit else ""
    return amount, unit


def _inches(amount, unit):
    with localcontext() as context:
        # Decimal arithmetic removes Excel conversion noise without introducing
        # another binary float or rounding to arbitrary fractional inch steps.
        context.prec = max(40, len(amount.as_tuple().digits) + abs(amount.adjusted()) + 4)
        if unit == "cm":
            amount /= Decimal("2.54")
        elif unit == "mm":
            amount /= Decimal("25.4")
        rounded = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return format(rounded, "f").rstrip("0").rstrip(".") or "0"


def _format_pair(height, width):
    height_measurement = _measurement(height)
    width_measurement = _measurement(width)
    if height_measurement is None or width_measurement is None:
        return None
    height_amount, height_unit = height_measurement
    width_amount, width_unit = width_measurement
    # "61 x 91 cm" uses one shared suffix. Explicit units on each side win.
    height_unit = height_unit or width_unit or "in"
    width_unit = width_unit or height_unit
    return f'{_inches(height_amount, height_unit)}" x {_inches(width_amount, width_unit)}"'


def normalize_dimensions(value):
    """Normalize an understood two-part size to inches; retain other text.

    Examples: ``11.5 × 14.750 in`` becomes ``11.5" x 14.75"`` and
    ``61 x 91 cm`` becomes ``24.02" x 35.83"``. Fractions are rendered as
    decimals, rounded to at most two places. Blank and missing values become
    empty strings. Labels, annotations, ranges, and other ambiguous text are
    preserved, apart from surrounding whitespace.
    """
    text = _text(value)
    parts = _PAIR_SEPARATOR.split(text)
    if len(parts) != 2:
        return text
    return _format_pair(*parts) or text


def format_catalog_dimensions(height, width):
    """Return ``(image_size, sheet_size)`` for catalog height/width cells.

    A leading ``S`` on either cell marks sheet dimensions, following the
    catalog convention. Both dimensions must be present. Recognized numeric
    cells use the same inch formatting as :func:`normalize_dimensions`;
    unrecognized cell text is retained without adding unsupported inch units.
    """
    height_text, width_text = _text(height), _text(width)
    if not height_text or not width_text:
        return "", ""
    sheet_size = bool(_SHEET_PREFIX.match(height_text) or _SHEET_PREFIX.match(width_text))
    height_text = _SHEET_PREFIX.sub("", height_text).strip()
    width_text = _SHEET_PREFIX.sub("", width_text).strip()
    if not _text(height_text) or not _text(width_text):
        return "", ""
    formatted = _format_pair(height_text, width_text) or f"{height_text} x {width_text}"
    return ("", formatted) if sheet_size else (formatted, "")
