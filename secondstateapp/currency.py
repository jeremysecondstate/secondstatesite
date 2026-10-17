"""USD normalization using dated Frankfurter reference exchange rates."""

import re
from datetime import date
from decimal import Decimal, DecimalException, ROUND_HALF_UP, localcontext

import requests
from django.core.cache import cache
from django.utils import timezone


_API_URL = "https://api.frankfurter.dev/v2/rate/{currency}/usd"
_QUOTE_TTL = 6 * 60 * 60
_FAILURE_TTL = 5 * 60
_MAX_QUOTE_AGE_DAYS = 7
_MAX_AMOUNT = Decimal("1000000000000")
_MAX_RATE = Decimal("1000000000000")
_CENT = Decimal("0.01")
_CACHE_MISS = object()


def _positive_decimal(value, maximum):
    if value is None or isinstance(value, bool):
        return None
    try:
        text = str(value).strip()
        if not text or len(text) > 128:
            return None
        number = Decimal(text)
        if number.is_finite() and 0 < number <= maximum:
            return number
    except (DecimalException, ValueError, TypeError):
        pass
    return None


def _validate_quote(payload, currency):
    if not isinstance(payload, dict):
        return None
    if payload.get("base") != currency or payload.get("quote") != "USD":
        return None
    rate = _positive_decimal(payload.get("rate"), _MAX_RATE)
    if rate is None:
        return None
    try:
        observed_on = date.fromisoformat(payload["date"])
        # Accept only the documented YYYY-MM-DD date representation.
        if observed_on.isoformat() != payload["date"]:
            return None
        age = (timezone.now().date() - observed_on).days
    except (KeyError, ValueError, TypeError):
        return None
    if not 0 <= age <= _MAX_QUOTE_AGE_DAYS:
        return None
    return {
        "base": currency,
        "quote": "USD",
        "rate": str(rate),
        "date": observed_on.isoformat(),
    }


def _usd_quote(currency):
    key = f"currency:frankfurter:v2:{currency}:USD"
    cached = cache.get(key, _CACHE_MISS)
    if cached is None:
        return None
    if cached is not _CACHE_MISS:
        quote = _validate_quote(cached, currency)
        if quote is not None:
            return quote

    try:
        response = requests.get(_API_URL.format(currency=currency.lower()), timeout=3)
        response.raise_for_status()
        quote = _validate_quote(response.json(parse_float=Decimal), currency)
    except (requests.RequestException, ValueError, TypeError, DecimalException):
        quote = None
    cache.set(key, quote, timeout=_QUOTE_TTL if quote is not None else _FAILURE_TTL)
    return quote


def convert_to_usd(amount, currency):
    """Return serializable conversion provenance, or None when unavailable.

    Amounts are positive monetary values rounded to cents with ROUND_HALF_UP.
    Rate is USD per source currency unit; a USD amount needs no external quote.
    Missing/unknown currencies never inherit USD, and stale quotes are rejected.
    """
    if not isinstance(currency, str):
        return None
    currency = currency.strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", currency):
        return None
    source = _positive_decimal(amount, _MAX_AMOUNT)
    if source is None:
        return None
    try:
        with localcontext() as context:
            context.prec = max(28, len(source.as_tuple().digits) + 2)
            source = source.quantize(_CENT, rounding=ROUND_HALF_UP)
        if not 0 < source <= _MAX_AMOUNT:
            return None

        quote = None if currency == "USD" else _usd_quote(currency)
        if currency != "USD" and quote is None:
            return None
        rate = Decimal(quote["rate"]) if quote else Decimal("1")
        with localcontext() as context:
            context.prec = max(28, len(source.as_tuple().digits) + len(rate.as_tuple().digits) + 2)
            usd = source * rate
            if not 0 < usd <= _MAX_AMOUNT:
                return None
            usd = usd.quantize(_CENT, rounding=ROUND_HALF_UP)
        if usd <= 0:
            return None
    except DecimalException:
        return None

    return {
        "source_currency": currency,
        "source_amount": format(source, ".2f"),
        "usd_amount": format(usd, ".2f"),
        "rate": str(rate),
        "rate_date": quote["date"] if quote else None,
        "provider": "Frankfurter" if quote else None,
    }
