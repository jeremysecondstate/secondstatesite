"""Shared, dependency-free provenance rules for bounded public research.

These rules validate the handoff, not the truth of external page text. Opened
pages remain untrusted evidence, and search snippets are discovery leads only.
"""
from collections import Counter
from datetime import datetime, timezone
import ipaddress
import re
import unicodedata
from urllib.parse import urlsplit


MAX_RESEARCH = 24
MAX_PER_SOURCE = 6
MAX_ATTEMPTS = 64
MAX_SEARCH_ATTEMPTS = 24
NEW_SOURCE_KINDS = ("public_fetch", "public_browser", "authenticated_browser", "search_only")
PROVENANCE_FIELDS = ("discovery_method", "discovery_query", "discovery_url", "match_reason", "identity_match", "attempts")
IDENTITY_FIELDS = ("artist", "title", "auction_house", "auction_date", "lot_number")


def bounded_text(value, maximum, required=False):
    if not isinstance(value, str) or len(value) > maximum or (required and not value.strip()):
        raise ValueError("Invalid research provenance text.")
    return value.strip()


def public_evidence_url(value, *, required=True, allow_http=False):
    """Validate an observed URL without making a server-side network request.

    Fetchers must still resolve and validate every IP and redirect before access.
    Literal and obvious local destinations are forbidden in browser provenance.
    """
    original = value
    value = bounded_text(value, 2048, required)
    if value != original:
        raise ValueError("Research URLs must retain their exact observed form.")
    if not value and not required:
        return ""
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 or c == "\\" for c in value):
        raise ValueError("Invalid observed research URL.")
    try:
        parts = urlsplit(value)
        schemes = {"https": 443, **({"http": 80} if allow_http else {})}
        host = (parts.hostname or "").encode("idna").decode("ascii").lower().rstrip(".")
        if (parts.scheme not in schemes or not host or parts.username is not None
                or parts.password is not None or parts.port not in (None, schemes[parts.scheme])
                or "%" in host or host == "localhost" or host.endswith((".localhost", ".local", ".internal"))):
            raise ValueError
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            labels = host.split(".")
            # Browsers interpret shortened/octal/hexadecimal IPv4 forms that
            # Python's ipaddress deliberately rejects (127.1, 0177.0.0.1).
            # Require normal DNS labels and a non-numeric top-level label.
            if (len(host) > 253 or len(labels) < 2
                    or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels)
                    or re.fullmatch(r"(?:[0-9]+|0x[0-9a-f]+)", labels[-1])):
                raise ValueError
        else:
            if (not address.is_global or address.is_multicast or address.is_reserved
                    or getattr(address, "ipv4_mapped", None) or getattr(address, "sixtofour", None)
                    or getattr(address, "teredo", None)):
                raise ValueError
    except (ValueError, UnicodeError):
        raise ValueError("Research evidence must reference a public web URL without credentials.") from None
    return value


def _identity_text(value):
    value = unicodedata.normalize("NFKD", value).casefold()
    return " ".join(re.findall(r"[^\W_]+", "".join(c for c in value if not unicodedata.combining(c)), re.UNICODE))


def _same_identity(field, expected, observed):
    left, right = _identity_text(expected), _identity_text(observed)
    if field == "lot_number":
        left, right = re.sub(r"^lot\s*", "", left), re.sub(r"^lot\s*", "", right)
        return left.lstrip("0") == right.lstrip("0")
    if field in ("artist", "title"):
        # Accent/punctuation and a parenthetical translated title are harmless.
        return left == right or bool(left and right and (f" {left} " in f" {right} " or f" {right} " in f" {left} "))
    return left == right


def validate_evidence_provenance(item, *, expected_identity=None):
    """Return new provenance fields; legacy records are validated by their caller."""
    kind = item.get("source_kind")
    if kind not in NEW_SOURCE_KINDS:
        raise ValueError("Invalid research source kind.")
    error = bounded_text(item.get("error", ""), 200)
    source = public_evidence_url(item.get("source_url"), allow_http=bool(error) or kind != "public_fetch")
    final = public_evidence_url(item.get("final_url", ""), required=not bool(error))
    if source != item.get("source_url") or final != item.get("final_url", ""):
        raise ValueError("Research URLs must match the observed URLs exactly.")
    method = item.get("discovery_method", "direct")
    if method not in ("direct", "search", "link"):
        raise ValueError("Invalid research discovery method.")
    query = bounded_text(item.get("discovery_query", ""), 500)
    discovery_url = public_evidence_url(item.get("discovery_url", ""), required=False)
    reason = bounded_text(item.get("match_reason", ""), 1200)
    identity = item.get("identity_match", {})
    if not isinstance(identity, dict) or set(identity) - {*IDENTITY_FIELDS, "status"}:
        raise ValueError("Invalid lot identity provenance.")
    identity = {field: bounded_text(identity.get(field, ""), 300 if field != "auction_date" else 10)
                for field in IDENTITY_FIELDS} | {"status": identity.get("status", "unverified")}
    status = identity["status"]
    if status not in ("exact", "context", "historical", "unverified"):
        raise ValueError("Invalid lot identity match status.")
    if identity["auction_date"]:
        try:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", identity["auction_date"]):
                raise ValueError
            datetime.strptime(identity["auction_date"], "%Y-%m-%d")
        except ValueError:
            raise ValueError("Lot auction dates must use YYYY-MM-DD.") from None
    if not error:
        if not bounded_text(item.get("text", ""), 6000, True):
            raise ValueError("Successful research requires observed source text.")
        if not reason:
            raise ValueError("Successful research requires an identity match explanation.")
        if method == "search" and not query:
            raise ValueError("Search discoveries require the query used.")
        if method == "link" and not discovery_url:
            raise ValueError("Linked discoveries require the observed parent URL.")
        if status == "exact" and (not all(identity[key] for key in ("artist", "title", "auction_house"))
                                   or not (identity["auction_date"] or identity["lot_number"])):
            raise ValueError("Exact matches require artist, title, auction house, and sale date or lot number.")
        if kind == "search_only" and (status != "unverified" or method != "search"):
            raise ValueError("Search snippets are unverified discovery leads only.")
        if method == "direct" and (urlsplit(source).hostname.lower().removeprefix("www.")
                                    != urlsplit(final).hostname.lower().removeprefix("www.")):
            raise ValueError("Alternate-domain sources require search or linked discovery provenance.")
        if expected_identity and status in ("exact", "context"):
            for field in IDENTITY_FIELDS:
                expected, observed = expected_identity.get(field, ""), identity[field]
                if expected and observed and not _same_identity(field, expected, observed):
                    raise ValueError("Research evidence conflicts with the requested lot identity.")
    elif item.get("text") or item.get("title"):
        raise ValueError("Failed research observations cannot contain source evidence.")
    attempts = item.get("attempts", [])
    if not isinstance(attempts, list) or len(attempts) > 16:
        raise ValueError("Too many research attempts for one source.")
    cleaned_attempts = []
    for attempt in attempts:
        if not isinstance(attempt, dict) or set(attempt) - {"method", "query", "url", "status", "detail", "observed_at"}:
            raise ValueError("Invalid research attempt.")
        attempt_method = bounded_text(attempt.get("method", ""), 40, True)
        if attempt_method not in ("public_fetch", "search", "public_browser", "authenticated_browser", "browser_launch", "validation"):
            raise ValueError("Invalid research attempt method.")
        attempt_status = bounded_text(attempt.get("status", ""), 40, True)
        if attempt_status not in ("success", "partial", "unavailable", "timeout", "challenge", "login_required", "rejected", "no_results", "tool_unavailable"):
            raise ValueError("Invalid research attempt status.")
        observed = bounded_text(attempt.get("observed_at", ""), 64, True)
        try:
            stamp = datetime.fromisoformat(observed.replace("Z", "+00:00"))
            if stamp.tzinfo is None or (stamp - datetime.now(timezone.utc)).total_seconds() > 300:
                raise ValueError
        except (TypeError, ValueError):
            raise ValueError("Invalid research attempt observation time.") from None
        cleaned_attempts.append({"method": attempt_method, "query": bounded_text(attempt.get("query", ""), 500),
                                 "url": public_evidence_url(attempt.get("url", ""), required=False, allow_http=True),
                                 "status": attempt_status, "detail": bounded_text(attempt.get("detail", ""), 300),
                                 "observed_at": observed})
    return {"discovery_method": method, "discovery_query": query, "discovery_url": discovery_url,
            "match_reason": reason, "identity_match": identity, "attempts": cleaned_attempts}


def research_identity_key(item):
    identity = item.get("identity_match") or {}
    status = identity.get("status", "unverified") if isinstance(identity, dict) else None
    return item["source_url"], item.get("final_url", ""), item.get("source_kind", "public"), status


def validate_research_bounds(records):
    if not isinstance(records, list) or len(records) > MAX_RESEARCH:
        raise ValueError("Too many research records.")
    counts, identities, attempts, searches = Counter(), set(), 0, 0
    for item in records:
        if not isinstance(item, dict):
            raise ValueError("Invalid research record.")
        if not isinstance(item.get("source_url"), str) or not isinstance(item.get("attempts", []), list):
            raise ValueError("Invalid research record bounds.")
        counts[item["source_url"]] += 1
        key = research_identity_key(item)
        if not all(isinstance(value, str) for value in key):
            raise ValueError("Invalid research record identity.")
        if key in identities:
            raise ValueError("Duplicate research observation.")
        identities.add(key)
        attempts += len(item.get("attempts", []))
        searches += sum(isinstance(attempt, dict) and attempt.get("method") == "search"
                        for attempt in item.get("attempts", []))
    if (any(count > MAX_PER_SOURCE for count in counts.values()) or attempts > MAX_ATTEMPTS
            or searches > MAX_SEARCH_ATTEMPTS):
        raise ValueError("Research evidence exceeded the per-lot or attempt budget.")
