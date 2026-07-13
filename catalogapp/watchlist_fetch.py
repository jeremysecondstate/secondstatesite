"""Conservative local page retrieval; no search engine or access-control bypasses."""

from __future__ import annotations

import os
from pathlib import Path
import threading
import time
from typing import Callable
from urllib.parse import urlsplit

import requests

from catalogapp.bookmark_watchlist import DEFAULT_ALLOWED_DOMAINS


class WatchlistStopped(RuntimeError):
    pass


class SourceAccessError(RuntimeError):
    pass


def _allowed_url(url: str) -> bool:
    parts = urlsplit(url)
    host = (parts.hostname or "").casefold()
    return parts.scheme.casefold() in {"http", "https"} and any(
        host == domain or host.endswith(f".{domain}") for domain in DEFAULT_ALLOWED_DOMAINS
    )


class HttpPageFetcher:
    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        stop_event: threading.Event | None = None,
        min_interval_seconds: float = 1.0,
        max_retries: int = 2,
        timeout: tuple[float, float] = (10, 30),
        sleeper: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.session = session or requests.Session()
        self.stop_event = stop_event or threading.Event()
        self.min_interval_seconds = max(0.0, float(min_interval_seconds))
        self.max_retries = max(0, int(max_retries))
        self.timeout = timeout
        self.sleeper = sleeper
        self.monotonic = monotonic
        self._last_request_by_host: dict[str, float] = {}
        self.pages_fetched = 0
        self.http_attempts = 0

    def fetch(self, url: str) -> str:
        if not _allowed_url(url):
            raise SourceAccessError("Refusing to fetch a URL outside the explicit watchlist domain allowlist.")
        host = (urlsplit(url).hostname or "").casefold()
        for attempt in range(self.max_retries + 1):
            self._check_stopped()
            self._throttle(host)
            self.http_attempts += 1
            try:
                response = self.session.get(
                    url,
                    headers={
                        "User-Agent": "SecondState-Artist-Watchlist/1.0 (+local bookmark monitor)",
                        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
                    },
                    timeout=self.timeout,
                    allow_redirects=True,
                )
            except requests.RequestException as exc:
                if attempt >= self.max_retries:
                    raise SourceAccessError(f"Could not fetch {host}: {exc}") from exc
                self._backoff(attempt, None)
                continue
            self._last_request_by_host[host] = self.monotonic()
            final_url = getattr(response, "url", None) or url
            if not _allowed_url(final_url):
                raise SourceAccessError("The source redirected outside the explicit watchlist domain allowlist.")
            if response.status_code in {401, 403}:
                raise SourceAccessError(
                    f"{host} requires authentication or blocked automation (HTTP {response.status_code}). "
                    "The watchlist will not bypass that control."
                )
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < self.max_retries:
                    self._backoff(attempt, response.headers.get("Retry-After"))
                    continue
            try:
                response.raise_for_status()
            except requests.RequestException as exc:
                raise SourceAccessError(f"{host} returned HTTP {response.status_code}.") from exc
            content_type = (response.headers.get("Content-Type") or "").casefold()
            if content_type and not any(item in content_type for item in ("html", "json", "text")):
                raise SourceAccessError(f"{host} returned an unsupported content type.")
            self.pages_fetched += 1
            return response.text
        raise SourceAccessError(f"Could not fetch {host}.")

    def _check_stopped(self) -> None:
        if self.stop_event.is_set():
            raise WatchlistStopped("Watchlist refresh stopped by the user.")

    def _throttle(self, host: str) -> None:
        last = self._last_request_by_host.get(host)
        if last is None:
            return
        remaining = self.min_interval_seconds - (self.monotonic() - last)
        if remaining > 0:
            self.sleeper(remaining)
            self._check_stopped()

    def _backoff(self, attempt: int, retry_after: str | None) -> None:
        try:
            delay = min(10.0, max(0.0, float(retry_after))) if retry_after else min(8.0, 2.0 ** attempt)
        except (TypeError, ValueError):
            delay = min(8.0, 2.0 ** attempt)
        self.sleeper(delay)
        self._check_stopped()


class ControlledPlaywrightFetcher:
    """Explicit opt-in browser fetcher using one user-selected persistent profile.

    It does not solve challenges, enter credentials, or bypass authentication. Playwright
    is an optional dependency and is imported only when this fetcher is selected.
    """

    def __init__(self, profile_directory: str | Path, *, stop_event: threading.Event | None = None) -> None:
        self.profile_directory = Path(profile_directory).expanduser().resolve()
        if not self.profile_directory.is_dir():
            raise ValueError("The selected Playwright profile directory does not exist.")
        self.stop_event = stop_event or threading.Event()
        self.pages_fetched = 0

    def fetch(self, url: str) -> str:
        if not _allowed_url(url):
            raise SourceAccessError("Refusing to open a URL outside the explicit watchlist domain allowlist.")
        if self.stop_event.is_set():
            raise WatchlistStopped("Watchlist refresh stopped by the user.")
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise SourceAccessError(
                "Playwright is not installed. Install it only if a bookmarked source requires an explicitly selected browser session."
            ) from exc
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_directory),
                headless=False,
            )
            try:
                page = context.pages[0] if context.pages else context.new_page()
                response = page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                if response and response.status in {401, 403, 429}:
                    raise SourceAccessError(
                        f"The source returned HTTP {response.status}. The watchlist will not bypass that control."
                    )
                html = page.content()
                challenge_text = f"{page.title()} {html[:4000]}".casefold()
                if any(term in challenge_text for term in ("captcha", "verify you are human", "access denied")):
                    raise SourceAccessError("The source presented an access challenge; refresh stopped without bypassing it.")
                self.pages_fetched += 1
                return html
            finally:
                context.close()


def page_fetcher_from_environment(stop_event: threading.Event | None = None):
    if os.environ.get("WATCHLIST_USE_PLAYWRIGHT", "0").strip().casefold() in {"1", "true", "yes", "on"}:
        profile = os.environ.get("WATCHLIST_PLAYWRIGHT_PROFILE", "").strip()
        if not profile:
            raise ValueError("WATCHLIST_PLAYWRIGHT_PROFILE must name the user-selected profile directory.")
        return ControlledPlaywrightFetcher(profile, stop_event=stop_event)
    return HttpPageFetcher(stop_event=stop_event)
