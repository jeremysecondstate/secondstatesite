"""Browser recovery waits for public search access without requiring sold-price login."""

from pathlib import Path
import re
from tempfile import TemporaryDirectory
import threading
from unittest import TestCase
from unittest.mock import Mock, patch

from bs4 import BeautifulSoup

from catalogapp.watchlist_browser import InvaluablePublicBrowserFetcher
from catalogapp.watchlist_fetch import SourceAccessBlocked, SourceAccessError, WatchlistStopped


SEARCH_URL = "https://www.invaluable.com/search?query=Alexander%20Calder"
CATALOG_URL = "https://www.invaluable.com/catResults"
LOT_URL = "https://www.invaluable.com/auction-lot/alexander-calder-116-c-example"
SEARCH_HTML = f'<h4>1 items</h4><a href="{LOT_URL}">Alexander Calder</a>'
GATED_HTML = "<h1>Lot 116: Alexander Calder</h1><p><b>Sold:</b> Log in to view</p>"


class _Locator:
    """Minimal DOM locator with meaningful visibility checks for search readiness."""

    def __init__(self, nodes):
        self.nodes = nodes

    def all(self):
        return [_Locator([node]) for node in self.nodes]

    def is_visible(self, **_kwargs):
        if not self.nodes:
            return False
        node = self.nodes[0]
        return all(
            not ancestor.has_attr("hidden")
            and ancestor.get("aria-hidden") != "true"
            and not re.search(r"(?:display\s*:\s*none|visibility\s*:\s*hidden)", ancestor.get("style", ""))
            for ancestor in [node, *node.parents]
        )

    def inner_text(self, **_kwargs):
        return self.nodes[0].get_text(" ", strip=True) if self.nodes else ""


class PublicBrowserRecoveryTests(TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.profile = Path(temporary.name) / "InvaluableBrowser"
        self.now = 0.0
        self.html = SEARCH_HTML
        self.title = "Search results | Invaluable"
        self.initial_status = 200
        self.after_wait = lambda: None
        self.page = Mock()
        self.page.url = "about:blank"
        self.page.is_closed.return_value = False
        self.page.title.side_effect = lambda: self.title
        self.page.content.side_effect = lambda: self.html
        self.page.locator.side_effect = self.locator
        self.page.goto.side_effect = self.navigate
        self.page.wait_for_timeout.side_effect = self.advance
        self.page.evaluate.return_value = {
            "status": 200, "url": CATALOG_URL,
            "content_type": "application/json", "data": {"results": []},
        }
        self.context = Mock()
        self.context.pages = [self.page]
        self.playwright = Mock()
        self.playwright.chromium.launch_persistent_context.return_value = self.context
        self.manager = Mock()
        self.manager.start.return_value = self.playwright
        patcher = patch("catalogapp.watchlist_browser._load_playwright", return_value=self.manager)
        self.load = patcher.start()
        self.addCleanup(patcher.stop)

    def locator(self, selector):
        soup = BeautifulSoup(f"<body>{self.html}</body>", "html.parser")
        return _Locator(soup.select(selector))

    def navigate(self, url, **_kwargs):
        self.page.url = url
        return Mock(status=self.initial_status, url=url)

    def advance(self, milliseconds):
        self.now += milliseconds / 1000
        self.after_wait()

    def fetcher(self, **kwargs):
        return InvaluablePublicBrowserFetcher(
            self.profile, monotonic=lambda: self.now, min_interval_seconds=0,
            access_timeout_seconds=1, **kwargs,
        )

    def post(self, fetcher, payload=None):
        return fetcher.post_json(CATALOG_URL, payload or {}, referer=SEARCH_URL)

    def test_invalid_endpoint_or_referer_never_opens_browser(self):
        for endpoint, referer in (
            ("https://example.com/catResults", SEARCH_URL),
            ("http://www.invaluable.com/catResults", SEARCH_URL),
            ("https://www.invaluable.com/changePassword", SEARCH_URL),
            ("https://user:password@www.invaluable.com/catResults", SEARCH_URL),
            (CATALOG_URL, "https://example.com/search"),
            (CATALOG_URL, "https://invaluable.com/search"),
            (CATALOG_URL, "https://www.invaluable.com/login"),
            (CATALOG_URL, ""),
        ):
            with self.subTest(endpoint=endpoint, referer=referer):
                with self.assertRaises(SourceAccessError):
                    self.fetcher().post_json(endpoint, {}, referer=referer)
        self.load.assert_not_called()

    def test_initial_access_response_waits_for_search_without_repeated_navigation(self):
        for status in (202, 401, 403):
            with self.subTest(status=status):
                self.page.goto.reset_mock()
                self.page.evaluate.reset_mock()
                self.page.bring_to_front.reset_mock()
                self.initial_status = status
                self.html = "<p>Loading search results</p>"
                self.after_wait = lambda: setattr(self, "html", SEARCH_HTML)
                started = self.now
                with self.fetcher() as fetcher:
                    self.assertEqual(self.post(fetcher), {"results": []})
                self.assertGreater(self.now, started)
                self.page.bring_to_front.assert_called_once()
                self.page.goto.assert_called_once_with(SEARCH_URL, wait_until="domcontentloaded", timeout=45_000)
                self.page.evaluate.assert_called_once()
        self.assertFalse(self.playwright.chromium.launch_persistent_context.call_args.kwargs["headless"])

    def test_visible_zero_item_count_is_a_ready_search(self):
        self.html = "<h4>0 items</h4>"
        with self.fetcher() as fetcher:
            self.assertEqual(self.post(fetcher), {"results": []})
        self.assertEqual(self.now, 0)
        self.page.evaluate.assert_called_once()

    def test_visible_auction_link_without_count_is_a_ready_search(self):
        self.html = f'<a hidden href="{LOT_URL}">Hidden template</a><a href="{LOT_URL}">Alexander Calder</a>'
        with self.fetcher() as fetcher:
            self.assertEqual(self.post(fetcher), {"results": []})
        self.assertEqual(self.now, 0)

    def test_challenge_hidden_results_and_empty_shell_time_out_without_posting(self):
        for html in (
            "<h1>Verify you are human</h1>" + SEARCH_HTML,
            f'<section hidden>{SEARCH_HTML}</section>',
            "<script>const message = '0 items';</script><p>Loading</p>",
            "<app-root></app-root>",
        ):
            with self.subTest(html=html):
                self.page.goto.reset_mock()
                self.html = html
                started = self.now
                with self.fetcher() as fetcher:
                    for _ in range(2):
                        with self.assertRaisesRegex(SourceAccessBlocked, "Retry with browser"):
                            self.post(fetcher)
                self.assertGreaterEqual(self.now - started, 1)
                self.page.goto.assert_called_once()
        self.page.evaluate.assert_not_called()

    def test_stop_or_closed_window_cancels_wait_and_releases_browser(self):
        for cancellation in ("stop", "close", "close_during_wait"):
            with self.subTest(cancellation=cancellation):
                self.context.close.reset_mock()
                self.playwright.stop.reset_mock()
                self.page.is_closed.return_value = False
                event = threading.Event()
                self.html = "<p>Loading</p>"
                def cancel():
                    if cancellation == "stop":
                        event.set()
                    else:
                        self.page.is_closed.return_value = True
                        if cancellation == "close_during_wait":
                            raise RuntimeError("Target page, context or browser has been closed")

                self.after_wait = cancel
                with self.assertRaises(WatchlistStopped):
                    with self.fetcher(stop_event=event) as fetcher:
                        self.post(fetcher)
                self.context.close.assert_called_once()
                self.playwright.stop.assert_called_once()
        self.page.evaluate.assert_not_called()

    def test_catalog_batches_reuse_one_warmup_and_never_visit_a_sold_sign_in_lot(self):
        payloads = [{"page": 0}, {"page": 1}]
        with self.fetcher() as fetcher:
            for payload in payloads:
                self.assertEqual(self.post(fetcher, payload), {"results": []})
            self.assertEqual(fetcher.pages_fetched, 2)
        self.page.goto.assert_called_once_with(SEARCH_URL, wait_until="domcontentloaded", timeout=45_000)
        self.assertEqual([call.args[1]["payload"] for call in self.page.evaluate.call_args_list], payloads)
        self.playwright.chromium.launch_persistent_context.assert_called_once()

    def test_denied_catalog_response_stops_source_without_reposting(self):
        for status in (200, 202, 401, 403, 429):
            with self.subTest(status=status):
                self.page.goto.reset_mock()
                self.page.evaluate.reset_mock()
                self.page.evaluate.return_value = {"status": status, "url": CATALOG_URL, "content_type": "text/html"}
                with self.fetcher() as fetcher:
                    for _ in range(2):
                        with self.assertRaisesRegex(SourceAccessBlocked, "Retry with browser"):
                            self.post(fetcher)
                    self.assertEqual(fetcher.pages_fetched, 0)
                self.page.goto.assert_called_once()
                self.page.evaluate.assert_called_once()

    def test_rate_limited_initial_page_stops_immediately(self):
        self.initial_status = 429
        with self.fetcher() as fetcher:
            with self.assertRaisesRegex(SourceAccessBlocked, "HTTP 429"):
                self.post(fetcher)
        self.assertEqual(self.now, 0)
        self.page.wait_for_timeout.assert_not_called()
        self.page.evaluate.assert_not_called()

    def test_sold_login_requirement_does_not_block_public_lot_html(self):
        with self.fetcher() as fetcher:
            self.post(fetcher)
            self.html = GATED_HTML
            self.assertEqual(fetcher.fetch(LOT_URL), GATED_HTML)
            self.assertEqual(fetcher.pages_fetched, 2)
        self.assertEqual([call.args[0] for call in self.page.goto.call_args_list], [SEARCH_URL, LOT_URL])

    def test_later_lot_access_denial_keeps_strict_http_checks(self):
        with self.fetcher() as fetcher:
            self.post(fetcher)
            self.initial_status = 202
            for _ in range(2):
                with self.assertRaisesRegex(SourceAccessBlocked, "HTTP 202"):
                    fetcher.fetch(LOT_URL)
        self.assertEqual([call.args[0] for call in self.page.goto.call_args_list], [SEARCH_URL, LOT_URL])
