"""A dedicated, user-signed-in Invaluable browser for the desktop watchlist.

The caller supplies an application-owned profile directory. This module never
opens the user's regular Chrome profile, copies cookies, or enters credentials.
Playwright and the browser are only started when this optional feature is used.
Create, use, and close each fetcher on the same worker thread.
"""

from __future__ import annotations

from pathlib import Path
import re
import threading
import time
from typing import Callable
from urllib.parse import urlsplit

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
            "Invaluable sign-in needs the optional browser support. Install "
            "requirements-watchlist-browser.txt with the desktop app's Python, then reconnect Invaluable."
        ) from exc
    return sync_playwright()


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
        try:
            if context is not None:
                context.close()
        finally:
            if playwright is not None:
                playwright.stop()

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
                "other Invaluable connection window, then try Connect Invaluable again."
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


def connect_invaluable(
    profile_directory: str | Path,
    *,
    stop_event: threading.Event | None = None,
    progress: Callable[[str], None] | None = None,
    timeout_seconds: float = 600,
) -> bool:
    """Let the user sign in normally, and save only a proven, working session.

    Returns False if the user closes the window or the allotted time expires.
    Cancellation raises WatchlistStopped; blocked access raises SourceAccessError.
    No password, account details, or cookies are read by application code.
    """
    progress = progress or (lambda _message: None)
    with InvaluableBrowserFetcher(profile_directory, stop_event=stop_event, headless=False) as fetcher:
        fetcher._navigate(INVALUABLE_SIGN_IN_LOT)
        fetcher._page.bring_to_front()
        progress("Sign in to Invaluable in the opened browser. Return to the sold lot; the connection saves when its sold price appears.")
        deadline = time.monotonic() + max(0, timeout_seconds)
        saw_login_navigation = False
        returned_to_lot = False
        while time.monotonic() < deadline:
            fetcher._check_stopped()
            if not fetcher._context.pages:
                progress("Invaluable connection cancelled because its browser window was closed.")
                return False
            for page in fetcher._context.pages:
                if page.is_closed() or not _allowed_url(page.url):
                    continue
                path = urlsplit(page.url).path.rstrip("/")
                if page == fetcher._page and re.search(r"(?:login|signin|sign-in)", path, re.I):
                    saw_login_navigation = True
                if page == fetcher._page and not path and saw_login_navigation and not returned_to_lot:
                    # A conventional sign-in page can return to the homepage.
                    # Revisit the result once; its numeric value remains the proof.
                    returned_to_lot = True
                    fetcher._navigate(INVALUABLE_SIGN_IN_LOT)
                    progress("Checking that the signed-in Invaluable session can display the posted sold price.")
                    continue
                # Do not confirm login from an unrelated recommended or public lot.
                if path != urlsplit(INVALUABLE_SIGN_IN_LOT).path:
                    continue
                try:
                    html, text = fetcher._read_page(page)
                    lot = _dom_lot(html, page.url)
                    if lot and lot.sold_price is not None and _VISIBLE_SOLD.search(text):
                        progress("Invaluable connected. This local browser session will refresh posted sold prices automatically.")
                        return True
                except SourceAccessError:
                    raise
                except Exception:
                    # Normal login navigation may temporarily replace the DOM.
                    continue
            try:
                # The original tab may have been replaced by the site's login flow.
                if fetcher._page.is_closed():
                    fetcher._page = fetcher._context.pages[-1]
                fetcher._pause()
            except (SourceAccessError, WatchlistStopped):
                raise
            except Exception:
                progress("Invaluable connection cancelled because its browser window was closed.")
                return False
        progress("Invaluable sign-in timed out. Click Connect Invaluable when ready to try again.")
        return False
