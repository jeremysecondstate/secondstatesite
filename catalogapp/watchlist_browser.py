"""A dedicated, user-signed-in Invaluable browser for the desktop watchlist.

The caller supplies an application-owned profile directory. This module never
opens the user's regular Chrome profile, copies cookies, or enters credentials.
Playwright and the browser are only started when this optional feature is used.
Create, use, and close each fetcher on the same worker thread.
"""

from __future__ import annotations

from pathlib import Path
import json
import math
import re
import threading
import time
from typing import Callable
from urllib.parse import parse_qsl, urlsplit

from bs4 import BeautifulSoup

from catalogapp.watchlist_adapters import InvaluableAdapter
from catalogapp.watchlist_fetch import SourceAccessBlocked, SourceAccessError, WatchlistStopped


INVALUABLE_SIGN_IN_LOT = (
    "https://www.invaluable.com/auction-lot/"
    "alexander-calder-nid-d-araignee-116-c-3e46f2f787"
)
_HOSTS = {"invaluable.com", "www.invaluable.com"}
_CHALLENGE = re.compile(
    r"\b(?:verify (?:that )?you are human|checking your browser|access denied|"
    r"unusual traffic|complete the captcha|security verification|just a moment|"
    r"(?:please )?enable javascript(?: and cookies)?|javascript (?:is )?disabled)\b",
    re.I,
)
_PERMANENT_ACCESS_DENIAL = re.compile(
    r"\byour request has been blocked by (?:our )?security policies\b",
    re.I,
)
_BROWSER_UNAVAILABLE = re.compile(
    r"(?:target page, context or browser has been closed|"
    r"(?:target|page|browser) (?:has been |is )?crashed|"
    r"(?:browser|context|page|connection) (?:has been |is )?closed|"
    r"target closed)",
    re.I,
)
_VISIBLE_SOLD = re.compile(
    r"\bSold(?:\s+(?:for|price))?\s*:\s*(?:[A-Z]{3}\s*)?[$€£¥]?\s*\d",
    re.I,
)
_LOT_STATUS = re.compile(
    r"\b(?:Sold\s*:|Est(?:imate)?\s*:|Estimate\s+[\d$€£¥]|Current\s+bid\s*:|"
    r"Starting\s+bid\s*:|Auction\s+(?:closed|ended)|Bidding\s+(?:closed|ended)|"
    r"Unsold\b|Passed\b|Withdrawn\b)",
    re.I,
)
_SETTLED_RESULT = re.compile(
    r"^\s*(?:Sold(?:\s+(?:for|price))?\s*:\s*(?:Not disclosed|Not available|Price unavailable)|"
    r"Unsold|Passed|Withdrawn)\s*\.?\s*$",
    re.I,
)
_CATALOG_FETCH_SCRIPT = """async ({url, payload, referer}) => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 30000);
    try {
        const response = await fetch(url, {
            method: 'POST',
            headers: {'Accept': 'application/json', 'Content-Type': 'application/json'},
            body: JSON.stringify(payload),
            credentials: 'same-origin',
            redirect: 'error',
            referrer: referer || window.location.href,
            signal: controller.signal,
        });
        const result = {
            status: response.status,
            url: response.url,
            content_type: response.headers.get('Content-Type') || '',
        };
        if (response.ok && result.content_type.toLowerCase().includes('json')) {
            try { result.data = await response.json(); }
            catch (_) { result.invalid_json = true; }
        }
        return result;
    } finally {
        clearTimeout(timer);
    }
}"""


def _allowed_url(url: str) -> bool:
    try:
        parts = urlsplit(url)
        return (
            parts.scheme.casefold() == "https"
            and (parts.hostname or "").casefold() in _HOSTS
            and parts.port in {None, 443}
            and parts.username is None
            and parts.password is None
        )
    except ValueError:
        return False


def _load_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise SourceAccessError(
            "Invaluable browser access needs the optional browser support. Install "
            "requirements-watchlist-browser.txt with the desktop app's Python, then retry the browser operation."
        ) from exc
    return sync_playwright()


def _navigation_timed_out(error: Exception) -> bool:
    """Recognize navigation timeouts without requiring the optional dependency."""
    try:
        from playwright.sync_api import TimeoutError as BrowserTimeoutError
    except ImportError:
        return isinstance(error, TimeoutError)
    return isinstance(error, (TimeoutError, BrowserTimeoutError))


def _browser_unavailable(error: Exception) -> bool:
    """Recognize closure races, including wrapped navigation errors."""
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        if _BROWSER_UNAVAILABLE.search(str(error)):
            return True
        error = error.__cause__
    return False


def _dom_lot(html: str, url: str):
    # Embedded metadata is not proof that the signed-in user can see a result.
    soup = BeautifulSoup(html, "html.parser")
    for node in soup.select("script, style, template, noscript"):
        node.decompose()
    return InvaluableAdapter().parse_lot_detail(str(soup), url, "")


def _has_settled_result(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    # Whole-page text can include related lots. Apply the same exclusions as
    # the sold-price parser, and require an explicit final result label.
    for node in soup.find_all(string=_SETTLED_RESULT):
        parent = node.parent
        if parent.name not in {"script", "style", "template", "noscript"} and not InvaluableAdapter._sold_node_excluded(parent, soup):
            return True
    return any(_SETTLED_RESULT.fullmatch(text) for text in InvaluableAdapter._sold_label_texts(soup))


class InvaluableBrowserFetcher:
    """Reuse one persistent browser session for a complete watchlist refresh."""

    def __init__(
        self,
        profile_directory: str | Path,
        *,
        stop_event: threading.Event | None = None,
        headless: bool = False,
        min_interval_seconds: float = 1.0,
        render_timeout_seconds: float = 15.0,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.profile_directory = Path(profile_directory).expanduser().resolve()
        self.stop_event = stop_event or threading.Event()
        self.headless = headless
        self.min_interval_seconds = max(0.0, min_interval_seconds)
        self.render_timeout_seconds = max(0.0, render_timeout_seconds)
        self.monotonic = monotonic
        self.pages_fetched = 0
        self.http_attempts = 0
        self._playwright = None
        self._context = None
        self._page = None
        self._last_request: float | None = None
        self._access_error = ""
        self._owner_thread: int | None = None

    def __enter__(self):
        self._ensure_context()
        return self

    def __exit__(self, *_exc):
        self.close()

    def close(self) -> None:
        """Flush profile state and release the browser, including after failures."""
        if self._owner_thread is not None and self._owner_thread != threading.get_ident():
            raise RuntimeError("Close the Invaluable browser on the worker thread that opened it.")
        context, playwright = self._context, self._playwright
        self._context = self._page = self._playwright = None
        self._owner_thread = None
        close_error = None
        for resource, method in ((context, "close"), (playwright, "stop")):
            if resource is None:
                continue
            try:
                getattr(resource, method)()
            except Exception as exc:
                # A user can close the recovery window before ExitStack runs.
                # It is already released; do not let that race abort upload.
                if not _browser_unavailable(exc) and close_error is None:
                    close_error = exc
        if close_error is not None:
            raise close_error

    def _check_stopped(self) -> None:
        if self.stop_event.is_set():
            raise WatchlistStopped("Invaluable browser operation stopped by the user.")
        if self._access_error:
            raise SourceAccessBlocked(self._access_error)
        if self._owner_thread is not None and self._owner_thread != threading.get_ident():
            raise RuntimeError("Use the Invaluable browser only on the worker thread that opened it.")

    def _blocked(self, message: str):
        # Stop this source for the rest of this refresh instead of retrying each lot.
        self._access_error = message
        raise SourceAccessBlocked(message)

    def _ensure_context(self) -> None:
        self._check_stopped()
        if self._context is not None:
            return
        self.profile_directory.mkdir(parents=True, exist_ok=True)
        manager = _load_playwright()
        try:
            self._playwright = manager.start()
            self._owner_thread = threading.get_ident()
            for channel in ("chrome", "msedge"):
                try:
                    self._context = self._playwright.chromium.launch_persistent_context(
                        user_data_dir=str(self.profile_directory),
                        channel=channel,
                        headless=self.headless,
                        chromium_sandbox=True,
                        accept_downloads=False,
                    )
                    break
                except Exception as exc:
                    # A locked/broken profile must not silently switch browsers.
                    missing = re.search(r"(?:executable.*(?:doesn't exist|not found)|distribution.*not found)", str(exc), re.I)
                    if channel != "chrome" or not missing:
                        raise
            self._context.set_default_timeout(5_000)
            pages = self._context.pages
            self._page = next(
                (page for page in reversed(pages) if _allowed_url(page.url)),
                pages[-1] if pages else None,
            ) or self._context.new_page()
        except Exception as exc:
            self.close()
            raise SourceAccessError(
                "Could not open the dedicated Invaluable browser. Install Chrome or Edge, close any "
                "other Invaluable browser window, then retry the browser operation."
            ) from exc

    def _pause(self, seconds: float = 0.25) -> None:
        self._check_stopped()
        self._page.wait_for_timeout(max(1, seconds * 1000))
        self._check_stopped()

    def _throttle(self) -> None:
        while self._last_request is not None:
            remaining = self.min_interval_seconds - (self.monotonic() - self._last_request)
            if remaining <= 0:
                return
            self._pause(min(0.25, remaining))

    def _check_response(self, response, *, url: str) -> None:
        if response is None:
            raise SourceAccessError("Invaluable did not return a page. Please try the refresh again.")
        final_url = response.url or url
        self._check_status(response.status, final_url)

    def _check_status(self, status: int, final_url: str) -> None:
        if not _allowed_url(final_url):
            self._blocked("Invaluable redirected outside its website; the browser refresh stopped.")
        if status in {202, 401, 403, 429}:
            self._blocked(
                f"Invaluable requires sign-in or blocked this request (HTTP {status}). "
                "Reconnect Invaluable before refreshing sold prices again."
            )
        if status >= 300:
            raise SourceAccessError(f"Invaluable returned HTTP {status}; this page was not refreshed.")

    def _read_page(self, page=None) -> tuple[str, str]:
        page = page or self._page
        if not _allowed_url(page.url):
            self._blocked("Invaluable redirected outside its website; the browser refresh stopped.")
        text = page.locator("body").inner_text(timeout=5_000)
        if _CHALLENGE.search(f"{page.title()}\n{text[:3000]}"):
            self._blocked(
                "Invaluable displayed an access challenge. The refresh stopped; "
                "try Connect Invaluable again when normal access is available."
            )
        return page.content(), text

    def _navigate(self, url: str) -> None:
        if not _allowed_url(url):
            raise SourceAccessError("The Invaluable browser only opens HTTPS URLs on invaluable.com.")
        self._ensure_context()
        self._throttle()
        self._check_stopped()
        self.http_attempts += 1
        try:
            response = self._page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        except Exception as exc:
            raise SourceAccessError(
                "The Invaluable page did not load. Keep its browser window open during refresh, "
                "or reconnect Invaluable if the session has expired."
            ) from exc
        finally:
            self._last_request = self.monotonic()
        self._check_response(response, url=url)

    def fetch(self, url: str) -> str:
        """Wait for the rendered lot, including its result, before returning HTML."""
        self._navigate(url)
        deadline = self.monotonic() + self.render_timeout_seconds
        try:
            while True:
                self._check_stopped()
                html, text = self._read_page()
                if not re.search(r"/(?:auction-lot|lot)/", urlsplit(url).path, re.I):
                    self.pages_fetched += 1
                    return html
                lot = _dom_lot(html, url)
                if lot and lot.sold_price is not None and _VISIBLE_SOLD.search(text):
                    self.pages_fetched += 1
                    return html
                gated = lot and "sold_price_login" in lot.ambiguities
                if gated:
                    # Allow the site's signed-in state to hydrate before declaring expiry.
                    if self.monotonic() >= deadline:
                        self._blocked(
                            "Invaluable is hiding sold prices behind 'Log in to view'. "
                            "Click Connect Invaluable to sign in again, then refresh."
                        )
                else:
                    if lot and _has_settled_result(html):
                        self.pages_fetched += 1
                        return html
                if self.monotonic() >= deadline:
                    # Estimates and bids often render before sold results. Only
                    # accept those after giving the result component the full
                    # loading window, never after an arbitrary short delay.
                    if lot and not gated and _LOT_STATUS.search(text):
                        self.pages_fetched += 1
                        return html
                    raise SourceAccessError(
                        "Invaluable did not finish displaying this lot's price information. "
                        "The lot was not marked as successfully refreshed."
                    )
                self._pause()
        except (SourceAccessError, WatchlistStopped):
            raise
        except Exception as exc:
            raise SourceAccessError(
                "The Invaluable browser closed or could not read the lot. Reconnect Invaluable and refresh again."
            ) from exc

    def post_json(self, url: str, payload: object, *, referer: str = "") -> object:
        """Use the same signed-in browser session for the ordinary catalog feed."""
        if not _allowed_url(url) or urlsplit(url).path.rstrip("/") != "/catResults":
            raise SourceAccessError("The Invaluable browser only posts to its catalog-results endpoint.")
        if referer and (not _allowed_url(referer) or urlsplit(referer).netloc != urlsplit(url).netloc):
            raise SourceAccessError("The Invaluable catalog referer must belong to the same website.")
        self._ensure_context()
        # A new persistent profile starts on about:blank. Fetch from the actual
        # site's origin so the browser, its cookies, and its network stack match
        # the session the user signed into. APIRequestContext uses a separate
        # HTTP client and may be blocked even when normal Chrome access works.
        if not _allowed_url(self._page.url) or urlsplit(self._page.url).netloc != urlsplit(url).netloc:
            self._navigate(referer or f"https://{urlsplit(url).netloc}/")
        self._read_page()
        self._throttle()
        self._check_stopped()
        self.http_attempts += 1
        try:
            response = self._page.evaluate(
                _CATALOG_FETCH_SCRIPT,
                {"url": url, "payload": payload, "referer": referer},
            )
            self._check_stopped()
            self._check_status(response["status"], response["url"])
            if "json" not in response["content_type"].casefold():
                self._blocked("Invaluable returned a web page instead of catalog data. Reconnect Invaluable and retry.")
            if response.get("invalid_json") or "data" not in response:
                raise SourceAccessError("Invaluable returned invalid catalog JSON.")
            self.pages_fetched += 1
            return response["data"]
        except (SourceAccessError, WatchlistStopped):
            raise
        except Exception as exc:
            raise SourceAccessError("The signed-in Invaluable catalog request could not complete.") from exc
        finally:
            self._last_request = self.monotonic()


class InvaluablePublicBrowserFetcher(InvaluableBrowserFetcher):
    """Explicit browser retry for public catalogs, independent of sold-price login.

    Let the site's normal JavaScript load and leave verification to the user.
    Never copy the user's Chrome profile, read cookies, or solve a challenge.
    """

    uses_natural_catalog_requests = True
    _catalog_request_params = frozenset({
        # Scope fields are checked separately below; the remaining fields only
        # choose returned fields, display formatting, facet counts, or telemetry.
        "query", "facetFilters", "filters", "page", "hitsPerPage",
        "attributesToRetrieve", "attributesToHighlight", "attributesToSnippet",
        "highlightPreTag", "highlightPostTag", "snippetEllipsisText",
        "restrictHighlightAndSnippetArrays", "facets", "maxValuesPerFacet",
        "facetingAfterDistinct", "getRankingInfo", "responseFields",
        "analytics", "analyticsTags", "clickAnalytics", "userToken",
    })

    def __init__(self, profile_directory, *, progress=None, access_timeout_seconds=120, **kwargs):
        super().__init__(profile_directory, **kwargs)
        self.progress = progress or (lambda _message: None)
        self.access_timeout_seconds = max(0, float(access_timeout_seconds))

    @staticmethod
    def _request_params(request: object) -> dict:
        if not isinstance(request, dict):
            return {}
        params = request.get("params")
        if isinstance(params, dict):
            return params
        if isinstance(params, str):
            parsed = dict(parse_qsl(params, keep_blank_values=True))
            if "facetFilters" in parsed:
                try:
                    parsed["facetFilters"] = json.loads(parsed["facetFilters"])
                except (TypeError, ValueError):
                    return {}
            return parsed
        return {}

    @staticmethod
    def _facet_groups(value: object) -> set[frozenset[str]] | None:
        if not isinstance(value, list):
            return None
        groups = set()
        for group in value:
            values = [group] if isinstance(group, str) else group
            if not isinstance(values, list) or not values or not all(isinstance(item, str) for item in values):
                return None
            groups.add(frozenset(values))
        return groups

    @classmethod
    def _matching_requests(
        cls, body: object, expected: dict, diagnostics: list[str] | None = None,
    ) -> list[tuple[int, dict, bool]]:
        """Select the requested results, excluding facet-only and hydration calls."""
        def mismatch(reason: str) -> None:
            if diagnostics is not None and reason not in diagnostics:
                diagnostics.append(reason)

        if not isinstance(body, dict) or body.get("isCatalogPageRequest") is not False:
            mismatch("the page sent a different type of catalog request")
            return []
        requests = body.get("requests")
        if not isinstance(requests, list):
            mismatch("the page sent an unrecognized catalog request")
            return []
        wanted = expected["params"]
        wanted_facets = cls._facet_groups(wanted["facetFilters"])
        artist_facets = {group for group in (wanted_facets or set()) if all(value.startswith("artistName:") for value in group)}
        matches = []
        for index, request in enumerate(requests):
            if not isinstance(request, dict) or request.get("indexName") != expected["indexName"]:
                mismatch("the search sort did not match the bookmark")
                continue
            params = cls._request_params(request)
            try:
                page = int(params.get("page", 0))
                page_size = int(params.get("hitsPerPage", 0))
            except (TypeError, ValueError):
                mismatch("the search request had invalid pagination")
                continue
            if page != wanted["page"] or page_size <= 0:
                mismatch("only a different results page or facet counts were returned")
                continue
            # Additional numeric/tag/geo/attribute/rule filters can turn an
            # ordinary artist search into a narrower zero. Never let that zero
            # retire cached lots. Unknown nonempty controls are conservative
            # failures until their semantics have been explicitly reviewed.
            if any(key not in cls._catalog_request_params and value not in (None, "", False, [], {})
                   for key, value in params.items()):
                mismatch("the page applied additional unsupported search restrictions")
                continue
            if params.get("query", "") != wanted["query"]:
                mismatch("the search text did not match the bookmark")
                continue
            actual_facets = cls._facet_groups(params.get("facetFilters", []))
            # With no artist results the site may never add category facets.
            # An exact-artist all-category zero also proves the subset empty;
            # nonzero hydration responses still require every requested facet.
            zero_only = bool(artist_facets and actual_facets == artist_facets and actual_facets != wanted_facets)
            if actual_facets != wanted_facets and not zero_only:
                mismatch("the artist or category filters did not match the bookmark")
                continue
            # These define upcoming/public listings. A different filter must
            # not silently become a narrower (or archived) completed search.
            if " ".join(str(params.get("filters", "")).split()) != wanted["filters"]:
                mismatch("the upcoming-lot filters did not match the bookmark")
                continue
            matches.append((index, params, zero_only))
        return matches

    @staticmethod
    def _validated_result(result: object, params: dict) -> dict | None:
        if not isinstance(result, dict) or not isinstance(result.get("hits"), list):
            return None
        values = []
        for key in ("page", "nbPages", "nbHits", "hitsPerPage"):
            value = result.get(key)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                return None
            values.append(value)
        page, page_count, total, page_size = values
        if page_size <= 0 or page != int(params.get("page", 0)):
            return None
        if page_size != int(params.get("hitsPerPage", 0)):
            return None
        # Truncated/capped pages are incomplete, never proof that missing lots
        # ended. An explicit, coherent zero-result response is safe to accept.
        expected_pages = math.ceil(total / page_size)
        if page_count != expected_pages or (total and page >= page_count) or (not total and page != 0):
            return None
        hits = result["hits"]
        expected_hits = min(page_size, max(0, total - page * page_size))
        if len(hits) != expected_hits or any(not isinstance(hit, dict) for hit in hits):
            return None
        identities = [str(hit.get("objectID") or hit.get("lotRef") or "") for hit in hits]
        if any(not identity for identity in identities) or len(set(identities)) != len(identities):
            return None
        if any(not hit.get("lotRef") or not (hit.get("lotTitle") or hit.get("title")) for hit in hits):
            return None
        return result

    def _check_browser_open(self) -> None:
        self._check_stopped()
        if self._page.is_closed():
            self._browser_unavailable()

    def _browser_unavailable(self) -> None:
        self._blocked(
            "The Invaluable retry browser was closed or stopped responding. "
            "Cached lots were retained. Use my browser to recover this search."
        )

    def _raise_if_browser_unavailable(self, error: Exception) -> None:
        if self.stop_event.is_set():
            raise WatchlistStopped("Invaluable browser retry stopped by the user.") from None
        if _browser_unavailable(error):
            self._browser_unavailable()
        if self._page is not None:
            try:
                closed = self._page.is_closed()
            except Exception as exc:
                if _browser_unavailable(exc):
                    self._browser_unavailable()
                raise
            if closed:
                self._browser_unavailable()

    @classmethod
    def _current_search_matches(cls, current_url: str, requested_url: str, expected: dict) -> bool:
        """Do not use a captured response after the user changes the search."""
        if (not _allowed_url(current_url)
                or urlsplit(current_url).netloc != urlsplit(requested_url).netloc
                or urlsplit(current_url).path.rstrip("/") != "/search"):
            return False
        current = InvaluableAdapter()._catalog_request_payload(current_url)["requests"][0]
        wanted, actual = expected["params"], current["params"]
        return (
            current["indexName"] == expected["indexName"]
            and actual["query"] == wanted["query"]
            and actual["page"] == wanted["page"]
            and cls._facet_groups(actual["facetFilters"]) == cls._facet_groups(wanted["facetFilters"])
        )

    def fetch_search_page(self, url: str) -> str:
        """Read the ordinary search page's own successful catalog response.

        Observe only its matching public search response. Do not resend the
        request, extract session cookies, or accept an earlier unfiltered call
        while the site's artist/category controls are still hydrating.
        """
        try:
            return self._fetch_search_page(url)
        except Exception as exc:
            # Include context setup, throttling, and listener registration;
            # a failed optional browser must not cancel the calendar upload.
            self._raise_if_browser_unavailable(exc)
            raise

    def _fetch_search_page(self, url: str) -> str:
        if not _allowed_url(url) or urlsplit(url).path.rstrip("/") != "/search":
            raise SourceAccessError("Browser retry requires an HTTPS Invaluable search bookmark.")
        expected = InvaluableAdapter()._catalog_request_payload(url)["requests"][0]
        self._ensure_context()
        self._throttle()
        self._check_stopped()
        self.progress(
            "Opening Invaluable in the retry browser. If verification appears, complete it there; "
            "sync continues when the search results load. Use Stop to cancel."
        )
        captured: list[dict] = []
        failures: list[str] = []
        mismatches: list[str] = []
        rate_limited = False

        def capture(response):
            nonlocal rate_limited
            try:
                response_url = urlsplit(response.url)
                if (not _allowed_url(response.url) or response_url.netloc != urlsplit(url).netloc
                        or response_url.path.rstrip("/") != "/catResults"):
                    return
                request = response.request
                if request.method != "POST":
                    return
                matches = self._matching_requests(request.post_data_json, expected, mismatches)
                if not matches:
                    return
                status = response.status
                if status == 429:
                    rate_limited = True
                if status != 200:
                    failures.append(f"the search's catalog request returned HTTP {status}")
                    return
                if "json" not in str(response.headers.get("content-type", "")).casefold():
                    failures.append("the search returned a web page instead of catalog data")
                    return
                payload = response.json()
                results = payload.get("results") if isinstance(payload, dict) else None
                if not isinstance(results, list):
                    failures.append("the search returned invalid catalog data")
                    return
                for index, params, zero_only in matches:
                    result = self._validated_result(results[index] if index < len(results) else None, params)
                    if result is not None and (not zero_only or result["nbHits"] == 0):
                        captured.append(result)
                        return
                failures.append("the search returned incomplete catalog data")
            except Exception:
                failures.append("the search's catalog response could not be read")

        self._page.on("response", capture)
        self.http_attempts += 1
        try:
            self._check_browser_open()
            self._page.bring_to_front()
            navigation_timeout = False
            response = None
            try:
                response = self._page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            except Exception as exc:
                self._check_browser_open()
                if not _navigation_timed_out(exc):
                    raise SourceAccessError("The Invaluable retry browser could not open the search. Try Retry with browser again.") from exc
                # A slow document can already have produced the catalog data.
                # Keep observing this navigation within the normal access wait;
                # do not reload it or issue an additional catalog request.
                navigation_timeout = True
            finally:
                self._last_request = self.monotonic()
            self._check_browser_open()
            if response is None and not navigation_timeout:
                raise SourceAccessError("Invaluable did not return a search page. Try Retry with browser again.")
            if response is not None and not _allowed_url(response.url or url):
                self._blocked("Invaluable redirected outside its website; browser retry stopped.")
            if response is not None and response.status not in {200, 202, 401, 403}:
                self._check_status(response.status, response.url or url)
            deadline = self.monotonic() + self.access_timeout_seconds
            while True:
                self._check_browser_open()
                if not _allowed_url(self._page.url) and not (navigation_timeout and self._page.url == "about:blank"):
                    self._blocked("Invaluable redirected outside its website; browser retry stopped.")
                if rate_limited:
                    self._blocked("Invaluable rate-limited its search (HTTP 429). Cached lots were retained.")
                challenge_found = False
                try:
                    text = self._page.locator("body").inner_text(timeout=1_000)
                    title = self._page.title()
                    challenge = _CHALLENGE.search(f"{title}\n{text[:3000]}")
                    challenge_found = bool(challenge)
                except Exception as exc:
                    self._raise_if_browser_unavailable(exc)
                    self._check_browser_open()
                    challenge = True
                else:
                    if (title.strip().casefold() == "access denied"
                            or _PERMANENT_ACCESS_DENIAL.search(text[:3000])):
                        self._blocked(
                            "Invaluable denied access to the retry browser. Cached lots were retained. "
                            "Use my browser to recover the search from your usual browser."
                        )
                self._check_browser_open()
                search_matches = self._current_search_matches(self._page.url, url, expected)
                if not search_matches:
                    captured.clear()
                    if "the visible search no longer matches the bookmark" not in mismatches:
                        mismatches.append("the visible search no longer matches the bookmark")
                if captured and not challenge and search_matches:
                    self.pages_fetched += 1
                    self.progress("Invaluable search loaded. Retrieved its live catalog results.")
                    return json.dumps({"results": [captured[-1]]}, ensure_ascii=False, separators=(",", ":"))
                if self.monotonic() >= deadline:
                    if challenge_found:
                        reason = "the search page displayed an access screen"
                    elif failures:
                        reason = failures[-1]
                    elif mismatches:
                        reason = "; ".join(mismatches[-2:])
                    else:
                        reason = "no catalog response was observed"
                    self._blocked(
                        "Invaluable did not provide a complete catalog response for this bookmarked search"
                        f" ({reason}). Cached lots were retained. Try Retry with browser again or import a saved search page."
                    )
                self._pause()
        finally:
            try:
                self._page.remove_listener("response", capture)
            except Exception as exc:
                # Listener teardown can race a closed window or connection.
                # Preserve the useful result/failure already produced above.
                if not _browser_unavailable(exc):
                    raise

    def post_json(self, url: str, payload: object, *, referer: str = "") -> object:
        raise SourceAccessError("Public browser retry reads the search page's own catalog response; direct catalog requests are disabled.")

    def fetch(self, url: str) -> str:
        """Read public details without requiring a signed-in numeric sold result."""
        try:
            return self._fetch_public_lot(url)
        except Exception as exc:
            self._raise_if_browser_unavailable(exc)
            raise

    def _fetch_public_lot(self, url: str) -> str:
        self._navigate(url)
        deadline = self.monotonic() + self.render_timeout_seconds
        while True:
            self._check_browser_open()
            html, text = self._read_page()
            self._check_browser_open()
            lot = _dom_lot(html, url)
            if lot and ("sold_price_login" in lot.ambiguities or _LOT_STATUS.search(text)):
                self.pages_fetched += 1
                return html
            if self.monotonic() >= deadline:
                raise SourceAccessError("Invaluable did not finish displaying this lot's details; cached data was retained.")
            self._pause()


def connect_invaluable(
    profile_directory: str | Path,
    *,
    stop_event: threading.Event | None = None,
    progress: Callable[[str], None] | None = None,
    timeout_seconds: float = 600,
) -> bool:
    """Let the user sign in normally, and save only a proven, working session.

    Returns False if the user closes the window or the allotted time expires.
    Cancellation raises WatchlistStopped. Access challenges stay visible for the
    user; this connection flow never retries navigation or resolves them itself.
    No password, account details, or cookies are read by application code.
    """
    progress = progress or (lambda _message: None)
    with InvaluableBrowserFetcher(profile_directory, stop_event=stop_event, headless=False) as fetcher:
        # Interactive connection is not an automatic refresh. Bring the window
        # forward before loading the site, and let the user see any sign-in or
        # access screen instead of closing Chrome on the first HTTP 202/403.
        try:
            fetcher._page.bring_to_front()
        except Exception as exc:
            raise SourceAccessError(
                "Could not show the Invaluable browser window. Close any existing connection window and try again."
            ) from exc
        instructions = "Sign in to Invaluable in the opened browser. Return to the sold lot; the connection saves when its sold price appears."
        progress(instructions)
        last_progress = instructions

        def report(message):
            nonlocal last_progress
            if message != last_progress:
                progress(message)
                last_progress = message

        try:
            response = fetcher._page.goto(INVALUABLE_SIGN_IN_LOT, wait_until="domcontentloaded", timeout=45_000)
            if response is None or response.status >= 300 or response.status == 202:
                report(
                    "Invaluable has not opened the lot yet. Its browser window will stay open so you can "
                    "check the page and sign in normally. Return to the sold lot when it is available."
                )
        except Exception:
            report(
                "The Invaluable page did not finish loading. Its browser window will stay open; "
                "open the sold lot there when the website is available."
            )
        deadline = time.monotonic() + max(0, timeout_seconds)
        while time.monotonic() < deadline:
            fetcher._check_stopped()
            try:
                pages = [page for page in fetcher._context.pages if not page.is_closed()]
            except Exception:
                pages = []
            if not pages:
                progress("Invaluable connection cancelled because its browser window was closed.")
                return False
            for page in pages:
                if not _allowed_url(page.url):
                    continue
                path = urlsplit(page.url).path.rstrip("/")
                # Do not confirm login from an unrelated recommended or public lot.
                if path != urlsplit(INVALUABLE_SIGN_IN_LOT).path:
                    continue
                try:
                    text = page.locator("body").inner_text(timeout=5_000)
                    if _CHALLENGE.search(f"{page.title()}\n{text[:3000]}"):
                        report(
                            "Invaluable is showing an access screen. The browser will stay open for you to "
                            "check it. The app will wait without retrying; return to the sold lot when normal access is available."
                        )
                        continue
                    html = page.content()
                    # A login redirect can replace the document between reads.
                    if not _allowed_url(page.url) or urlsplit(page.url).path.rstrip("/") != path:
                        continue
                    lot = _dom_lot(html, page.url)
                    if lot and lot.sold_price is not None and _VISIBLE_SOLD.search(text):
                        fetcher._check_stopped()
                        progress("Invaluable connected. This local browser session will refresh posted sold prices automatically.")
                        return True
                    if lot and "sold_price_login" in lot.ambiguities:
                        report(instructions)
                except WatchlistStopped:
                    raise
                except Exception:
                    # Normal login navigation may temporarily replace the DOM.
                    continue
            try:
                # The original tab may have been replaced by the site's login flow.
                if fetcher._page.is_closed():
                    fetcher._page = pages[-1]
                fetcher._pause()
            except (SourceAccessError, WatchlistStopped):
                raise
            except Exception:
                progress("Invaluable connection cancelled because its browser window was closed.")
                return False
        progress("Invaluable sign-in timed out. Click Connect Invaluable when ready to try again.")
        return False
