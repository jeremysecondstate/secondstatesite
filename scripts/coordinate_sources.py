"""Bounded, unauthenticated public-page research for Coordinate.

Resolve and validate every destination, then connect to that exact IP while
retaining the original TLS hostname. No proxies, cookies, credentials or browser
execution are involved. Page text is evidence, never instructions for the worker.
"""

from datetime import datetime, timezone
from html.parser import HTMLParser
import http.client
import ipaddress
import queue
import re
import socket
import ssl
import threading
import time
import unicodedata
from urllib.parse import quote, unquote, urljoin, urlsplit


MAX_URLS = 8
MAX_URL_LENGTH = 2048
MAX_BYTES = 512_000
MAX_TEXT = 6000
MAX_REDIRECTS = 3
TOTAL_SECONDS = 45
PAGE_SECONDS = 10
DNS_SECONDS = 4
REDIRECT_STATUSES = (301, 302, 303, 307, 308)
URL_PATTERN = re.compile(r"https?://[^\s<>\"`]+", re.IGNORECASE)

# These are completeness signals, not extracted facts. A long auction page can
# contain navigation and estimates without the fields needed to coordinate it.
FIELD_SIGNALS = {
    "sold_price": r"\b(?:sold\s*(?:for\b|:|price\b)|hammer\s*(?:price\b|:)|price\s*realized\b|winning\s*bid\b)\s*:?[\s$€£A-Z]{0,12}\d",
    "medium_edition": r"\b(?:lithograph|serigraph|screenprint|etching|oil on|acrylic|bronze|edition|watercolo[u]?r|medium)\b",
    "artwork_dimensions": r"\b(?:dimensions|image size|sheet size|size|measurements)\b|\d\s*(?:x|×)\s*\d",
    "framed_dimensions": r"\bfram(?:e|ed)\s*(?:dimensions|size|measures)|\bframed\s*[:\-]?\s*\d",
    "condition": r"\bcondition\b",
    "auction_date": r"\b(?:auction|sale)\s*(?:date|ended|closed|held)|\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2},?\s+20\d{2}\b",
    "location": r"\b(?:location|address|collection address|pickup address)\b",
    "pickup_release_storage": r"\b(?:pick.?up|collection|storage|release|removal)\b",
    "shipping_contacts": r"\b(?:shipping|shipper|packing|transport)\b.{0,180}(?:@|\bcontact\b|\d{3}[-. )])",
}

SHIPPING_CHECK_TOPICS = ("pickup", "storage", "third_party_release", "house_recommended",
                         "nearby_ups", "fine_art_packers")
MARKETPLACE_HOSTS = {"invaluable.com", "liveauctioneers.com", "hibid.com", "bidsquare.com"}


def public_lot_url(url):
    """Only recognizable public lot routes may seed shipping discovery."""
    path = urlsplit(url).path
    return (not re.search(r"\.(?:pdf|docx?|xlsx?|eml|msg)(?:/|$)", path, re.IGNORECASE)
            and bool(re.search(r"/(?:auction-lot|lots?|auction_lot)/", path, re.IGNORECASE)))


def shipping_discovery(record):
    """Public house/provider queries independent of artwork-field completeness.

    A private destination, invoice, email, playbook or arbitrary submitted file
    is never an input. A nearby-city seed must be explicitly labelled on the
    successfully opened public lot page, otherwise the operator discovers it.
    """
    if not public_lot_url(record["source_url"]):
        return None
    host = (urlsplit(record["source_url"]).hostname or "").lower().removeprefix("www.")
    if not host:
        return None
    house_name = public_identity(record)["auction_house"]
    marketplace = any(host == domain or host.endswith("." + domain) for domain in MARKETPLACE_HOSTS)
    city = ""
    if not record.get("error"):
        match = re.search(r"(?im)^(?:(?:auction|sale|pickup|collection)\s+)?(?:location|city)\s*:\s*"
                          r"([A-Za-zÀ-ÖØ-öø-ÿ .'-]{2,60},\s*[A-Z]{2})(?:\s|$)", record.get("text", ""))
        if match:
            city = " ".join(match.group(1).split())
    nearby = ([f"site:locations.theupsstore.com {city} art packing shipping",
               f"{city} fine art packing shipping auction collection"] if city else [])
    house_queries = [f"site:{host} shipping recommended shippers packing",
                     f"site:{host} pickup collection storage third party release authorization"]
    if marketplace and house_name:
        house_queries = [f"{house_name} official shipping recommended shippers",
                         f"{house_name} official pickup storage third party release authorization"]
    return {"house_host": host, "public_house_name": house_name, "house_memory_enabled": not marketplace,
        "source_url": record["source_url"], "public_pickup_city": city, "house_queries": house_queries,
        "provider_queries": nearby,
        "provider_followups": ["After opening the official house pickup location, search nearby UPS Store packing and shipping options.",
                               "Search nearby fine-art packers using only that published city; open each provider's own service/contact page."],
        "check_topics": list(SHIPPING_CHECK_TOPICS),
        "lot_handling_checks": ["artwork_dimensions", "framed_dimensions", "medium", "mat", "glazing", "loose_certificate"],
        "quote_comparison": "Use both known size sets and the private destination in draft quotes only. Ask packers to assess framed/unframed safety, mat/glazing, loose certificate protection and conditional pricing; do not decide removal before their advice."}


def missing_fields(record):
    text = record.get("title", "") + "\n" + record.get("text", "")
    return [field for field, pattern in FIELD_SIGNALS.items()
            if not re.search(pattern, text, re.IGNORECASE | re.DOTALL)]


def public_identity(record):
    """Only explicitly labelled facts from public evidence become constraints.

    URL slugs are discovery hints, never proof of an artist, lot or sale date.
    Artwork dates are intentionally not interpreted as auction dates.
    """
    text = record.get("text", "") if not record.get("error") else ""
    identity = {key: "" for key in ("artist", "title", "auction_house", "auction_date", "lot_number")}
    for field, pattern in {
        "artist": r"(?im)^artist\s*:\s*([^\n]{1,150})",
        "title": r"(?im)^title\s*:\s*([^\n]{1,200})",
        "auction_house": r"(?im)^auction house\s*:\s*([^\n]{1,150})",
        "auction_date": r"(?im)^(?:auction|sale) date\s*:\s*([^\n]{1,100})",
        "lot_number": r"(?im)^lot\s*(?:number|no\.?|#)?\s*[:#]?\s*(\d+[A-Za-z]?)\b",
    }.items():
        match = re.search(pattern, text)
        if match:
            identity[field] = match.group(1).strip()
    if identity["auction_date"]:
        value = identity["auction_date"]
        identity["auction_date"] = ""
        for pattern in ("%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%m/%d/%Y"):
            try:
                identity["auction_date"] = datetime.strptime(value, pattern).date().isoformat()
                break
            except ValueError:
                continue
    return identity


def discovery_queries(record):
    """A bounded initial search queue built without private message/doc contents.

    The operator augments these using *public* identifying facts it discovers.
    Query parameters are omitted: they may carry private tracking information.
    """
    parts = urlsplit(record["source_url"])
    # A submitted HTTPS link can be a private invoice/share link. Do not publish
    # arbitrary filenames, sharing IDs or path tokens to a search engine.
    lot_route = public_lot_url(record["source_url"])
    slug = unquote(parts.path.rstrip("/").rsplit("/", 1)[-1]) if lot_route else ""
    slug = re.sub(r"[_-][a-f0-9]{8,}$", "", slug, flags=re.IGNORECASE)
    slug = re.sub(r"[_-]+", " ", slug)
    slug = re.sub(r"[^\w\s'’]", " ", slug, flags=re.UNICODE)
    seed = " ".join(slug.split())[:220]
    host = parts.hostname.lower().removeprefix("www.")
    identity = public_identity(record)
    if identity["artist"] and identity["title"]:
        seed = " ".join((identity["artist"], identity["title"]))[:220]
    elif not lot_route:
        return [f"site:{host} auction catalog results", f"site:{host} shipping pickup storage contact"]
    # Opaque identifiers are not meaningful public identifying facts. This also
    # avoids publishing incidental tokens from an otherwise public-looking URL.
    if not re.search(r"[a-zA-Z]{3}", seed) or re.fullmatch(r"[a-fA-F0-9\s]{12,}", seed):
        seed = "auction catalog results"
    constraints = " ".join(value for value in (identity["auction_date"],
                          "lot " + identity["lot_number"] if identity["lot_number"] else "") if value)
    ascii_seed = "".join(char for char in unicodedata.normalize("NFKD", seed) if not unicodedata.combining(char))
    candidates = [f"site:{host} {seed}", f"{seed} {host} sold {constraints}",
                  f"{ascii_seed} auction {constraints}", f"site:invaluable.com {seed} {constraints}",
                  f"site:{host} {seed} condition dimensions", f"site:{host} shipping pickup storage contact"]
    return list(dict.fromkeys(" ".join(query.split())[:500] for query in candidates))[:6]


class SourceError(Exception):
    """A fixed, safe source failure message suitable for model context."""


def staff_urls(messages):
    """Prioritize the latest staff message, then earlier staff links, deduplicated."""
    result = []
    for message in reversed(messages):
        if message.get("role") != "staff":
            continue
        for match in URL_PATTERN.finditer(str(message.get("body", ""))):
            value = match.group().rstrip(".,;!?")
            # Markdown's closing delimiter is not part of the pasted URL.
            for opening, closing in (("(", ")"), ("[", "]"), ("{", "}")):
                while value.endswith(closing) and value.count(closing) > value.count(opening):
                    value = value[:-1]
            if len(value) <= MAX_URL_LENGTH and value not in result:
                result.append(value)
                if len(result) == MAX_URLS:
                    return result
    return result


def _remaining(deadline):
    left = deadline - time.monotonic()
    if left <= 0:
        raise SourceError("Public-page research time budget exhausted.")
    return left


def _destination(url, *, allow_http=False):
    if len(url) > MAX_URL_LENGTH or any(ord(char) <= 32 or ord(char) == 127 for char in url):
        raise SourceError("The source URL is invalid or too long.")
    if "\\" in url:
        raise SourceError("The source URL is invalid.")
    try:
        parts = urlsplit(url)
        scheme = parts.scheme.lower()
        if scheme != "https" and not (allow_http and scheme == "http"):
            raise SourceError("Only public HTTPS sources can be researched.")
        if parts.username is not None or parts.password is not None:
            raise SourceError("URLs containing credentials are not fetched.")
        default_port = 80 if scheme == "http" else 443
        if not parts.hostname or parts.port not in (None, default_port) or "%" in parts.hostname:
            raise SourceError("The source must use a valid hostname and its standard web port.")
        hostname = parts.hostname.encode("idna").decode("ascii").lower().rstrip(".")
        if not hostname:
            raise ValueError
    except (ValueError, UnicodeError) as exc:
        raise SourceError("The source URL is invalid.") from exc
    target = quote(parts.path or "/", safe="/%:@!$&'()*+,;=-._~")
    if parts.query:
        target += "?" + quote(parts.query, safe="/%?:@!$&'()*+,;=-._~[]")
    return hostname, target


def _public_ip(address):
    try:
        value = ipaddress.ip_address(address)
    except ValueError:
        return False
    return value.is_global and not (
        value.is_private or value.is_loopback or value.is_link_local
        or value.is_reserved or value.is_multicast or value.is_unspecified
        or getattr(value, "ipv4_mapped", None) is not None
        or getattr(value, "sixtofour", None) is not None
        or getattr(value, "teredo", None) is not None
    )


def _resolve_public(hostname, deadline):
    # OS DNS resolution does not honor socket timeouts. Bound the wait in a daemon
    # thread, so an unresponsive resolver cannot hold the job's lease indefinitely.
    results = queue.Queue(maxsize=1)

    def resolve():
        try:
            results.put(socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM))
        except OSError:
            results.put(None)

    threading.Thread(target=resolve, daemon=True).start()
    try:
        answers = results.get(timeout=min(DNS_SECONDS, _remaining(deadline)))
    except queue.Empty as exc:
        raise SourceError("DNS lookup timed out.") from exc
    if not answers:
        raise SourceError("The public hostname could not be resolved.")
    addresses = []
    for family, kind, protocol, _, sockaddr in answers:
        if family not in (socket.AF_INET, socket.AF_INET6) or not _public_ip(sockaddr[0]):
            # Reject mixed public/private records too, rather than choosing the
            # apparently public answer and trusting a later resolution.
            raise SourceError("The source resolves to a non-public or reserved address.")
        if (family, sockaddr) not in addresses:
            addresses.append((family, sockaddr))
    return addresses[0]


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, hostname, address, deadline):
        super().__init__(hostname, 443, timeout=_remaining(deadline), context=ssl.create_default_context())
        self.address = address
        self.deadline = deadline
        self.expired = False
        self.retain_transport = False

    def close(self):
        # HTTPConnection normally closes/detaches the socket after reading
        # Connection: close headers. Retain it until the body is consumed so the
        # absolute-deadline watchdog can still interrupt slow body reads.
        if not self.retain_transport:
            super().close()

    def finish(self):
        self.retain_transport = False
        super().close()

    def abort(self):
        self.expired = True
        connection = self.sock
        if connection is not None:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            connection.close()

    def connect(self):
        family, sockaddr = self.address
        raw = socket.socket(family, socket.SOCK_STREAM)
        self.sock = raw
        try:
            raw.settimeout(_remaining(self.deadline))
            raw.connect(sockaddr)  # Numeric address only: no second DNS lookup.
            if self.expired:
                raise TimeoutError
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host, do_handshake_on_connect=False)
            if self.expired:
                raise TimeoutError
            self.sock.settimeout(_remaining(self.deadline))
            self.sock.do_handshake()
            self.retain_transport = True
        except Exception:
            self.close()
            raise


class PageText(HTMLParser):
    ignored = {"script", "style", "noscript", "template", "svg", "nav", "footer"}
    blocks = {"p", "div", "li", "br", "h1", "h2", "h3", "h4", "tr", "section", "article", "main"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = []
        self.in_title = False
        self.title = []
        self.text = []

    def handle_starttag(self, tag, attrs):
        if tag in self.ignored:
            self.hidden.append(tag)
        if not self.hidden:
            if tag == "title":
                self.in_title = True
            if tag in self.blocks:
                self.text.append("\n")

    def handle_endtag(self, tag):
        if self.hidden:
            if tag == self.hidden[-1]:
                self.hidden.pop()
            return
        if tag == "title":
            self.in_title = False
        if tag in self.blocks:
            self.text.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            (self.title if self.in_title else self.text).append(data)

    def result(self):
        title = " ".join(" ".join(self.title).split())[:300]
        lines = [" ".join(line.split()) for line in "".join(self.text).splitlines()]
        text = "\n".join(line for line in lines if line)[:MAX_TEXT]
        return title, text


def _read_page(url, deadline):
    hostname, target = _destination(url)
    address = _resolve_public(hostname, deadline)
    connection = PinnedHTTPSConnection(hostname, address, deadline)
    # A fixed watchdog also bounds slow headers / trickle responses, which a
    # socket's per-read timeout alone would not bound.
    watchdog = threading.Timer(_remaining(deadline), connection.abort)
    watchdog.daemon = True
    watchdog.start()
    response = None
    try:
        connection.request("GET", target, headers={
            "User-Agent": "SecondState-Coordinate/1.0 (public page research)",
            "Accept": "text/html, application/xhtml+xml, text/plain;q=0.8",
            "Accept-Encoding": "identity", "Connection": "close",
        })
        response = connection.getresponse()
        if response.status in REDIRECT_STATUSES:
            location = response.getheader("Location")
            if not location:
                raise SourceError("The source returned a redirect without a destination.")
            return {"redirect": urljoin(url, location)}
        if response.status != 200:
            raise SourceError("The public page returned HTTP " + str(response.status) + ".")
        content_type = response.getheader("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type not in ("text/html", "application/xhtml+xml", "text/plain"):
            raise SourceError("This source is not a supported HTML or text page; PDFs need a text excerpt.")
        if response.getheader("Content-Encoding", "identity").strip().lower() not in ("", "identity"):
            raise SourceError("Compressed source responses are not supported.")
        length = response.getheader("Content-Length")
        if length:
            try:
                if int(length) > MAX_BYTES:
                    raise SourceError("The public page exceeded the research size limit.")
            except ValueError as exc:
                raise SourceError("The source returned an invalid content length.") from exc
        chunks = []
        size = 0
        while True:
            _remaining(deadline)
            if connection.expired:
                raise TimeoutError
            if connection.sock is not None:
                connection.sock.settimeout(_remaining(deadline))
            chunk = response.read1(min(16_384, MAX_BYTES + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > MAX_BYTES:
                raise SourceError("The public page exceeded the research size limit.")
        _remaining(deadline)
        raw = b"".join(chunks)
        charset = response.headers.get_content_charset() or "utf-8"
        try:
            decoded = raw.decode(charset, errors="replace")
        except LookupError:
            decoded = raw.decode("utf-8", errors="replace")
        if content_type == "text/plain":
            return {"title": "", "text": decoded[:MAX_TEXT]}
        parser = PageText()
        parser.feed(decoded)
        parser.close()
        title, text = parser.result()
        if not text:
            raise SourceError("The public page contained no readable text; it may require a browser.")
        return {"title": title, "text": text}
    except (TimeoutError, socket.timeout) as exc:
        raise SourceError("Public-page research timed out.") from exc
    except (OSError, http.client.HTTPException, ValueError) as exc:
        raise SourceError("The public page could not be retrieved securely.") from exc
    finally:
        watchdog.cancel()
        if response is not None:
            response.close()
        connection.finish()


def fetch_source(source_url, total_deadline):
    record = {"source_url": source_url, "final_url": source_url, "title": "", "text": "",
              "fetched_at": datetime.now(timezone.utc).isoformat(), "error": ""}
    deadline = min(total_deadline, time.monotonic() + PAGE_SECONDS)
    current = source_url
    try:
        for step in range(MAX_REDIRECTS + 1):
            _remaining(deadline)
            page = _read_page(current, deadline)
            if "redirect" not in page:
                record.update(page)
                record["final_url"] = current
                return record
            if step == MAX_REDIRECTS:
                raise SourceError("The public page exceeded the redirect limit.")
            current = page["redirect"]
            # Validate each redirect separately before any new connection. The
            # recorded final URL is only a destination successfully fetched.
            _destination(current)
        raise SourceError("The public page could not be retrieved.")
    except SourceError as exc:
        record["error"] = str(exc)[:200]
        return record


def research_messages(messages):
    deadline = time.monotonic() + TOTAL_SECONDS
    records = []
    for url in staff_urls(messages):
        record = fetch_source(url, deadline)
        try:
            # A safe ordinary HTTP URL can be recorded as an unsupported-source
            # error. Credential-bearing, malformed and nonstandard-port URLs do
            # not fit the server's artifact contract; leave them only in the
            # original staff message instead of failing an otherwise valid job.
            for key in ("source_url", "final_url"):
                _destination(record[key], allow_http=bool(record["error"]))
        except SourceError:
            continue
        records.append(record)
    return records
