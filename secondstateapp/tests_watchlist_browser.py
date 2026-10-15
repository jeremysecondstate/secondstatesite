"""The optional browser keeps a dedicated sign-in without exposing credentials."""

from pathlib import Path
from tempfile import TemporaryDirectory
import threading
from unittest import TestCase
from unittest.mock import Mock, patch

from catalogapp.watchlist_browser import (
    INVALUABLE_SIGN_IN_LOT,
    InvaluableBrowserFetcher,
    connect_invaluable,
)
from catalogapp.watchlist_fetch import SourceAccessError, WatchlistStopped


LOT_URL = INVALUABLE_SIGN_IN_LOT
CATALOG_URL = "https://www.invaluable.com/catResults"
SOLD_HTML = "<h1>Lot 116: Alexander Calder</h1><p><b>Sold:</b> $11,000 USD</p>"
SOLD_TEXT = "Lot 116: Alexander Calder\nSold: $11,000 USD"
GATED_HTML = "<h1>Lot 116: Alexander Calder</h1><p><b>Sold:</b> Log in to view</p>"
GATED_TEXT = "Lot 116: Alexander Calder\nSold: Log in to view"


class BrowserSessionTests(TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.profile = Path(self.temporary.name) / "InvaluableBrowser"
        self.now = 0.0
        self.page = Mock()
        self.page.url = LOT_URL
        self.page.title.return_value = "Lot 116: Alexander Calder"
        self.page.is_closed.return_value = False
        self.page.content.return_value = SOLD_HTML
        self.page.locator.return_value.inner_text.return_value = SOLD_TEXT
        self.page.goto.return_value = Mock(status=200, url=LOT_URL)
        self.page.wait_for_timeout.side_effect = self.advance
        self.context = Mock()
        self.context.pages = [self.page]
        self.playwright = Mock()
        self.playwright.chromium.launch_persistent_context.return_value = self.context
        self.manager = Mock()
        self.manager.start.return_value = self.playwright
        self.load = patch("catalogapp.watchlist_browser._load_playwright", return_value=self.manager).start()
        self.addCleanup(patch.stopall)

    def advance(self, milliseconds):
        self.now += milliseconds / 1000

    def fetcher(self, **kwargs):
        return InvaluableBrowserFetcher(self.profile, monotonic=lambda: self.now, **kwargs)

    def show(self, html, text):
        self.page.content.return_value = html
        self.page.locator.return_value.inner_text.return_value = text

    def test_reuses_profile_and_browser_until_context_exit(self):
        with self.fetcher() as fetcher:
            self.assertEqual(fetcher.fetch(LOT_URL), SOLD_HTML)
            self.assertEqual(fetcher.fetch(LOT_URL), SOLD_HTML)
            self.assertEqual(fetcher.pages_fetched, 2)
            self.context.close.assert_not_called()
        launch = self.playwright.chromium.launch_persistent_context
        launch.assert_called_once_with(
            user_data_dir=str(self.profile.resolve()), channel="chrome", headless=False,
            chromium_sandbox=True, accept_downloads=False,
        )
        self.assertTrue(self.profile.is_dir())
        self.context.close.assert_called_once()
        self.playwright.stop.assert_called_once()
        self.assertGreaterEqual(self.now, 1.0)

    def test_lazy_optional_browser_needs_no_install_until_used(self):
        fetcher = self.fetcher()
        self.load.assert_not_called()
        fetcher.close()
        self.load.assert_not_called()

    def test_uses_most_recent_invaluable_tab_from_the_dedicated_profile(self):
        first = Mock(url="https://www.invaluable.com/search")
        unrelated = Mock(url="about:blank")
        self.context.pages = [first, self.page, unrelated]
        with self.fetcher() as fetcher:
            self.assertEqual(fetcher.fetch(LOT_URL), SOLD_HTML)
        first.goto.assert_not_called()
        unrelated.goto.assert_not_called()
        self.context.new_page.assert_not_called()

    def test_waits_for_result_after_estimate_arrives(self):
        html = "<h1>Alexander Calder</h1><p>Est: $3,000 - $5,000 USD</p>"
        self.page.content.side_effect = [html, html, SOLD_HTML]
        self.page.locator.return_value.inner_text.side_effect = ["Est: $3,000 - $5,000 USD"] * 2 + [SOLD_TEXT]
        with self.fetcher() as fetcher:
            self.assertEqual(fetcher.fetch(LOT_URL), SOLD_HTML)
        self.assertGreater(self.now, 0)

    def test_waits_for_signed_in_state_before_reporting_login_expired(self):
        self.page.content.side_effect = [GATED_HTML, SOLD_HTML]
        self.page.locator.return_value.inner_text.side_effect = [GATED_TEXT, SOLD_TEXT]
        with self.fetcher() as fetcher:
            self.assertEqual(fetcher.fetch(LOT_URL), SOLD_HTML)

    def test_waits_longer_than_two_seconds_for_sold_component(self):
        estimate = "<h1>Alexander Calder</h1><p>Est: $3,000 - $5,000 USD</p><p>Auction ended</p>"
        self.page.content.side_effect = lambda: estimate if self.now < 3.5 else SOLD_HTML
        self.page.locator.return_value.inner_text.side_effect = lambda **_kw: "Est: $3,000 - $5,000 USD\nAuction ended" if self.now < 3.5 else SOLD_TEXT
        with self.fetcher() as fetcher:
            self.assertEqual(fetcher.fetch(LOT_URL), SOLD_HTML)
        self.assertGreaterEqual(self.now, 3.5)

    def test_slow_signed_in_state_does_not_falsely_expire_session(self):
        self.page.content.side_effect = lambda: GATED_HTML if self.now < 3.5 else SOLD_HTML
        self.page.locator.return_value.inner_text.side_effect = lambda **_kw: GATED_TEXT if self.now < 3.5 else SOLD_TEXT
        with self.fetcher() as fetcher:
            self.assertEqual(fetcher.fetch(LOT_URL), SOLD_HTML)
        self.assertGreaterEqual(self.now, 3.5)

    def test_estimate_only_waits_until_render_deadline(self):
        estimate = "<h1>Alexander Calder</h1><p>Est: $3,000 - $5,000 USD</p>"
        self.show(estimate, "Est: $3,000 - $5,000 USD")
        with self.fetcher(render_timeout_seconds=4) as fetcher:
            self.assertEqual(fetcher.fetch(LOT_URL), estimate)
        self.assertGreaterEqual(self.now, 4)

    def test_related_lot_result_does_not_finish_main_lot_loading(self):
        estimate = '<h1>Alexander Calder</h1><p>Est: $3,000 - $5,000 USD</p><aside class="related-lots"><p>Unsold</p></aside>'
        self.show(estimate, "Est: $3,000 - $5,000 USD\nUnsold")
        with self.fetcher(render_timeout_seconds=4) as fetcher:
            self.assertEqual(fetcher.fetch(LOT_URL), estimate)
        self.assertGreaterEqual(self.now, 4)

    def test_explicit_unsold_result_finishes_without_full_timeout(self):
        html = '<h1>Alexander Calder</h1><p>Unsold</p>'
        self.show(html, "Alexander Calder\nUnsold")
        with self.fetcher() as fetcher:
            self.assertEqual(fetcher.fetch(LOT_URL), html)
        self.assertEqual(self.now, 0)

    def test_expired_login_stops_source_without_retrying_every_lot(self):
        self.show(GATED_HTML, GATED_TEXT)
        with self.fetcher() as fetcher:
            for _ in range(2):
                with self.assertRaisesRegex(SourceAccessError, "Connect Invaluable"):
                    fetcher.fetch(LOT_URL)
            self.assertEqual(fetcher.pages_fetched, 0)
        self.page.goto.assert_called_once()

    def test_unrendered_shell_is_not_a_success(self):
        self.show("<app-root></app-root>", "Loading")
        with self.fetcher(render_timeout_seconds=0.5) as fetcher:
            with self.assertRaisesRegex(SourceAccessError, "did not finish displaying"):
                fetcher.fetch(LOT_URL)
            self.assertEqual(fetcher.pages_fetched, 0)

    def test_visible_challenge_stops_without_retry(self):
        self.show("<h1>Verify you are human</h1>", "Verify you are human")
        with self.fetcher() as fetcher:
            with self.assertRaisesRegex(SourceAccessError, "access challenge"):
                fetcher.fetch(LOT_URL)
        self.page.goto.assert_called_once()

    def test_challenge_library_in_script_does_not_block_a_readable_lot(self):
        html = SOLD_HTML + '<script src="captcha.js"></script>'
        self.show(html, SOLD_TEXT)
        with self.fetcher() as fetcher:
            self.assertEqual(fetcher.fetch(LOT_URL), html)

    def test_javascript_access_screen_is_not_a_success(self):
        self.show("<h1>Please enable JavaScript and cookies</h1>", "Please enable JavaScript and cookies")
        with self.fetcher() as fetcher:
            with self.assertRaisesRegex(SourceAccessError, "access challenge"):
                fetcher.fetch(LOT_URL)

    def test_forbidden_http_responses_stop_immediately(self):
        for status in (202, 401, 403, 429):
            with self.subTest(status=status):
                self.page.goto.return_value.status = status
                with self.fetcher() as fetcher:
                    with self.assertRaisesRegex(SourceAccessError, f"HTTP {status}"):
                        fetcher.fetch(LOT_URL)
        self.page.content.assert_not_called()

    def test_disallows_external_urls_before_opening_browser(self):
        for url in (
            "https://example.com/auction-lot/116", "http://www.invaluable.com/auction-lot/116",
            "https://www.invaluable.com.evil.example/auction-lot/116",
            "https://www.invaluable.com:9443/auction-lot/116",
            "https://user:password@www.invaluable.com/auction-lot/116",
        ):
            with self.subTest(url=url), self.assertRaises(SourceAccessError):
                self.fetcher().fetch(url)
        self.load.assert_not_called()

    def test_redirect_is_rejected_before_reading_html(self):
        self.page.goto.return_value.url = "https://example.com/"
        with self.fetcher() as fetcher:
            with self.assertRaisesRegex(SourceAccessError, "outside its website"):
                fetcher.fetch(LOT_URL)
        self.page.content.assert_not_called()

    def test_stop_cancels_browser_wait_and_always_closes_context(self):
        event = threading.Event()
        self.show(GATED_HTML, GATED_TEXT)
        self.page.wait_for_timeout.side_effect = lambda _ms: event.set()
        with self.assertRaises(WatchlistStopped):
            with self.fetcher(stop_event=event) as fetcher:
                fetcher.fetch(LOT_URL)
        self.context.close.assert_called_once()
        self.playwright.stop.assert_called_once()

    def test_missing_chrome_falls_back_to_edge(self):
        launch = self.playwright.chromium.launch_persistent_context
        launch.side_effect = [RuntimeError("Chromium distribution 'chrome' is not found"), self.context]
        with self.fetcher() as fetcher:
            fetcher.fetch(LOT_URL)
        self.assertEqual([call.kwargs["channel"] for call in launch.call_args_list], ["chrome", "msedge"])

    def test_locked_profile_does_not_fall_back_or_leak_raw_error(self):
        launch = self.playwright.chromium.launch_persistent_context
        launch.side_effect = RuntimeError("profile locked PRIVATE SESSION DETAILS")
        with self.assertRaises(SourceAccessError) as raised:
            with self.fetcher():
                pass
        self.assertNotIn("PRIVATE SESSION DETAILS", str(raised.exception))
        launch.assert_called_once()
        self.playwright.stop.assert_called_once()

    def test_catalog_post_uses_same_session_without_following_redirects(self):
        result = {"results": [{"hits": []}]}
        self.page.evaluate.return_value = {"status": 200, "url": CATALOG_URL, "content_type": "application/json", "data": result}
        payload = {"requests": []}
        with self.fetcher() as fetcher:
            self.assertEqual(fetcher.post_json(CATALOG_URL, payload, referer="https://www.invaluable.com/search"), result)
            self.assertEqual(fetcher.fetch(LOT_URL), SOLD_HTML)
            self.assertEqual(fetcher.pages_fetched, 2)
        self.page.evaluate.assert_called_once()
        script, arguments = self.page.evaluate.call_args.args
        self.assertEqual(arguments, {"url": CATALOG_URL, "payload": payload, "referer": "https://www.invaluable.com/search"})
        self.assertIn("credentials: 'same-origin'", script)
        self.assertIn("redirect: 'error'", script)
        self.context.request.post.assert_not_called()
        self.playwright.chromium.launch_persistent_context.assert_called_once()

    def test_catalog_post_opens_site_origin_before_fetching_from_blank_tab(self):
        self.page.url = "about:blank"
        self.page.evaluate.return_value = {"status": 200, "url": CATALOG_URL, "content_type": "application/json", "data": {"results": []}}

        def navigate(url, **_kwargs):
            self.page.url = url
            return Mock(status=200, url=url)

        self.page.goto.side_effect = navigate
        with self.fetcher() as fetcher:
            fetcher.post_json(CATALOG_URL, {}, referer="https://www.invaluable.com/search")
        self.page.goto.assert_called_once_with("https://www.invaluable.com/search", wait_until="domcontentloaded", timeout=45_000)
        self.page.evaluate.assert_called_once()

    def test_browser_catalog_request_stops_on_202_without_retrying(self):
        self.page.evaluate.return_value = {"status": 202, "url": CATALOG_URL, "content_type": "text/html"}
        with self.fetcher() as fetcher:
            for _ in range(2):
                with self.assertRaisesRegex(SourceAccessError, "HTTP 202"):
                    fetcher.post_json(CATALOG_URL, {})
        self.page.evaluate.assert_called_once()

    def test_browser_catalog_invalid_json_is_a_failed_refresh(self):
        self.page.evaluate.return_value = {"status": 200, "url": CATALOG_URL, "content_type": "application/json", "invalid_json": True}
        with self.fetcher() as fetcher:
            with self.assertRaisesRegex(SourceAccessError, "invalid catalog JSON"):
                fetcher.post_json(CATALOG_URL, {})
            self.assertEqual(fetcher.pages_fetched, 0)

    def test_post_rejects_non_catalog_endpoints_or_external_referer(self):
        with self.assertRaises(SourceAccessError):
            self.fetcher().post_json("https://www.invaluable.com/changePassword", {})
        with self.assertRaises(SourceAccessError):
            self.fetcher().post_json(CATALOG_URL, {}, referer="https://example.com/")
        self.load.assert_not_called()

    def test_html_catalog_response_fails_and_does_not_reveal_body(self):
        self.page.evaluate.return_value = {"status": 200, "url": CATALOG_URL, "content_type": "text/html"}
        with self.fetcher() as fetcher:
            with self.assertRaisesRegex(SourceAccessError, "instead of catalog data"):
                fetcher.post_json(CATALOG_URL, {})
        self.context.request.post.assert_not_called()

    def test_connect_saves_only_after_visible_numeric_sold_price(self):
        progress = Mock()
        self.page.content.side_effect = [GATED_HTML, SOLD_HTML]
        self.page.locator.return_value.inner_text.side_effect = [GATED_TEXT, SOLD_TEXT]
        with patch("catalogapp.watchlist_browser.time.monotonic", side_effect=lambda: self.now):
            self.assertTrue(connect_invaluable(self.profile, progress=progress, timeout_seconds=1))
        self.assertIn("connected", progress.call_args.args[0])
        self.page.bring_to_front.assert_called_once()
        self.context.close.assert_called_once()
        self.playwright.stop.assert_called_once()

    def test_connect_brings_window_forward_before_navigation(self):
        def navigate(*_args, **_kwargs):
            self.page.bring_to_front.assert_called_once()
            self.context.close.assert_not_called()
            return Mock(status=200, url=LOT_URL)

        self.page.goto.side_effect = navigate
        self.assertTrue(connect_invaluable(self.profile, timeout_seconds=1))

    def test_connect_sanitizes_window_error_and_closes_session(self):
        self.page.bring_to_front.side_effect = RuntimeError("PRIVATE SESSION DETAILS")
        with self.assertRaisesRegex(SourceAccessError, "Could not show") as raised:
            connect_invaluable(self.profile)
        self.assertNotIn("PRIVATE SESSION DETAILS", str(raised.exception))
        self.page.goto.assert_not_called()
        self.context.close.assert_called_once()
        self.playwright.stop.assert_called_once()

    def test_connect_keeps_blocked_page_open_until_user_reaches_visible_result(self):
        progress = Mock()
        self.page.goto.return_value.status = 202
        self.show("<h1>Verify you are human</h1>", "Verify you are human")

        def user_navigation(milliseconds):
            self.context.close.assert_not_called()
            self.page.bring_to_front.assert_called_once()
            self.advance(milliseconds)
            if self.now < 0.5:
                self.show(GATED_HTML, GATED_TEXT)
            else:
                self.show(SOLD_HTML, SOLD_TEXT)

        self.page.wait_for_timeout.side_effect = user_navigation
        with patch("catalogapp.watchlist_browser.time.monotonic", side_effect=lambda: self.now):
            self.assertTrue(connect_invaluable(self.profile, progress=progress, timeout_seconds=1))
        self.page.goto.assert_called_once()
        messages = [call.args[0] for call in progress.call_args_list]
        self.assertTrue(any("access screen" in message for message in messages))
        self.assertIn("connected", messages[-1])
        self.context.close.assert_called_once()

    def test_connect_waits_on_denied_access_without_retry_or_success(self):
        for status in (202, 401, 403, 429):
            with self.subTest(status=status):
                self.now = 0
                self.context.close.reset_mock()
                self.page.goto.reset_mock()
                self.page.goto.return_value.status = status
                self.show("<h1>Access denied</h1>", "Access denied")
                progress = Mock()

                def wait(milliseconds):
                    self.context.close.assert_not_called()
                    self.advance(milliseconds)

                self.page.wait_for_timeout.side_effect = wait
                with patch("catalogapp.watchlist_browser.time.monotonic", side_effect=lambda: self.now):
                    self.assertFalse(connect_invaluable(self.profile, progress=progress, timeout_seconds=1))
                self.page.goto.assert_called_once()
                self.context.close.assert_called_once()
                messages = [call.args[0] for call in progress.call_args_list]
                self.assertEqual(sum("access screen" in message for message in messages), 1)
                self.assertFalse(any("connected" in message for message in messages))

    def test_connect_keeps_window_open_after_navigation_failure(self):
        self.page.goto.side_effect = RuntimeError("timeout PRIVATE SESSION DETAILS")
        self.show(GATED_HTML, GATED_TEXT)
        progress = Mock()

        def user_navigation(milliseconds):
            self.context.close.assert_not_called()
            self.advance(milliseconds)
            self.show(SOLD_HTML, SOLD_TEXT)

        self.page.wait_for_timeout.side_effect = user_navigation
        with patch("catalogapp.watchlist_browser.time.monotonic", side_effect=lambda: self.now):
            self.assertTrue(connect_invaluable(self.profile, progress=progress, timeout_seconds=1))
        self.page.goto.assert_called_once()
        messages = [call.args[0] for call in progress.call_args_list]
        self.assertTrue(any("did not finish loading" in message for message in messages))
        self.assertFalse(any("PRIVATE SESSION DETAILS" in message for message in messages))

    def test_connect_can_cancel_while_access_screen_is_visible(self):
        event = threading.Event()
        self.page.goto.return_value.status = 202
        self.show("<h1>Access denied</h1>", "Access denied")
        self.page.wait_for_timeout.side_effect = lambda _milliseconds: event.set()
        with self.assertRaises(WatchlistStopped):
            connect_invaluable(self.profile, stop_event=event, timeout_seconds=1)
        self.page.goto.assert_called_once()
        self.context.close.assert_called_once()
        self.playwright.stop.assert_called_once()

    def test_connect_stop_during_dom_read_does_not_report_success(self):
        event = threading.Event()
        progress = Mock()

        def stop_during_read(**_kwargs):
            event.set()
            return SOLD_TEXT

        self.page.locator.return_value.inner_text.side_effect = stop_during_read
        with self.assertRaises(WatchlistStopped):
            connect_invaluable(self.profile, stop_event=event, progress=progress, timeout_seconds=1)
        self.assertFalse(any("connected" in call.args[0] for call in progress.call_args_list))
        self.context.close.assert_called_once()
        self.playwright.stop.assert_called_once()

    def test_connect_handles_user_closing_blocked_browser(self):
        self.page.goto.return_value.status = 202
        self.show("<h1>Access denied</h1>", "Access denied")

        def close_browser(milliseconds):
            self.advance(milliseconds)
            self.context.pages = []

        self.page.wait_for_timeout.side_effect = close_browser
        with patch("catalogapp.watchlist_browser.time.monotonic", side_effect=lambda: self.now):
            self.assertFalse(connect_invaluable(self.profile, timeout_seconds=1))
        self.page.goto.assert_called_once()
        self.context.close.assert_called_once()

    def test_connect_never_accepts_bid_as_proof_of_sign_in(self):
        self.show("<h1>Alexander Calder</h1><p>Current bid: $11,000 USD</p>", "Current bid: $11,000 USD")
        with patch("catalogapp.watchlist_browser.time.monotonic", side_effect=lambda: self.now):
            self.assertFalse(connect_invaluable(self.profile, timeout_seconds=0.5))
        self.context.close.assert_called_once()

    def test_connect_ignores_hidden_and_embedded_results(self):
        self.show(
            GATED_HTML + '<p hidden>Sold: $11,000 USD</p><script type="application/ld+json">'
            '{"lotId":"116","title":"Alexander Calder","soldPrice":11000}</script>',
            GATED_TEXT,
        )
        with patch("catalogapp.watchlist_browser.time.monotonic", side_effect=lambda: self.now):
            self.assertFalse(connect_invaluable(self.profile, timeout_seconds=0.5))

    def test_connect_does_not_accept_a_different_lot(self):
        self.page.url = "https://www.invaluable.com/auction-lot/another-lot"
        with patch("catalogapp.watchlist_browser.time.monotonic", side_effect=lambda: self.now):
            self.assertFalse(connect_invaluable(self.profile, timeout_seconds=0.5))

    def test_connect_does_not_accept_result_after_redirect_during_dom_read(self):
        def redirected_content():
            self.page.url = "https://www.invaluable.com/auction-lot/another-lot"
            return SOLD_HTML

        self.page.content.side_effect = redirected_content
        with patch("catalogapp.watchlist_browser.time.monotonic", side_effect=lambda: self.now):
            self.assertFalse(connect_invaluable(self.profile, timeout_seconds=0.5))

    def test_connect_handles_user_closing_browser(self):
        self.context.pages = []
        self.context.new_page.return_value = self.page
        with patch("catalogapp.watchlist_browser.time.monotonic", side_effect=lambda: self.now):
            self.assertFalse(connect_invaluable(self.profile, timeout_seconds=1))
        self.context.close.assert_called_once()

    def test_connect_waits_for_user_to_return_to_lot_after_login(self):
        self.page.url = "https://www.invaluable.com/login"

        def next_navigation(milliseconds):
            self.advance(milliseconds)
            self.context.close.assert_not_called()
            if self.now < 0.5:
                self.page.url = "https://www.invaluable.com/"
            else:
                self.page.url = LOT_URL

        self.page.wait_for_timeout.side_effect = next_navigation
        with patch("catalogapp.watchlist_browser.time.monotonic", side_effect=lambda: self.now):
            self.assertTrue(connect_invaluable(self.profile, timeout_seconds=2))
        self.page.goto.assert_called_once()
