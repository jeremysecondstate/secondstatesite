"""Regression coverage for live feeds that return HTML with successful HTTP status."""

from unittest import TestCase
from unittest.mock import Mock

import requests

from catalogapp.watchlist_fetch import HttpPageFetcher, SourceAccessBlocked, SourceAccessError


class CatalogResponseTests(TestCase):
    def test_detail_access_pages_are_not_successful_lot_observations(self):
        for status, html in ((202, ""), (200, "<h1>JavaScript is disabled</h1>")):
            with self.subTest(status=status):
                response = requests.Response()
                response.status_code = status
                response.headers["Content-Type"] = "text/html"
                response._content = html.encode()
                session = Mock()
                session.get.return_value = response
                fetcher = HttpPageFetcher(session=session, min_interval_seconds=0)
                with self.assertRaisesRegex(SourceAccessBlocked, "not refreshed"):
                    fetcher.fetch("https://www.invaluable.com/auction-lot/example-116")
                self.assertEqual(session.get.call_count, 1)

    def test_html_accepted_response_reports_failed_refresh_without_retrying(self):
        response = requests.Response()
        response.status_code = 202
        response.headers["Content-Type"] = "text/html; charset=UTF-8"
        response._content = b"<html>PRIVATE RESPONSE CONTENT</html>"
        session = Mock()
        session.post.return_value = response
        fetcher = HttpPageFetcher(session=session, min_interval_seconds=0, max_retries=2)

        with self.assertRaises(SourceAccessBlocked) as raised:
            fetcher.post_json("https://www.invaluable.com/catResults", {"requests": []})

        message = str(raised.exception)
        self.assertIn("web page instead of auction data (HTTP 202)", message)
        self.assertIn("Live auction data was not refreshed", message)
        self.assertIn("Use Retry with browser", message)
        self.assertIn("Import saved Invaluable pages", message)
        self.assertIn("cached lots, if any", message)
        self.assertNotIn("Try Sync to Calendar again", message)
        self.assertNotIn("Connect Invaluable", message)
        self.assertNotIn("PRIVATE RESPONSE CONTENT", message)
        self.assertEqual(session.post.call_count, 1)

    def test_other_non_json_responses_keep_general_error(self):
        response = requests.Response()
        response.status_code = 200
        response.headers["Content-Type"] = "application/octet-stream"
        response._content = b"unreadable"
        session = Mock()
        session.post.return_value = response
        fetcher = HttpPageFetcher(session=session, min_interval_seconds=0)

        with self.assertRaisesRegex(SourceAccessError, r"non-JSON response \(HTTP 200\)"):
            fetcher.post_json("https://www.invaluable.com/catResults", {"requests": []})

    def test_authentication_and_rate_limit_errors_are_source_wide(self):
        for status in (401, 403, 429):
            with self.subTest(status=status):
                response = requests.Response()
                response.status_code = status
                session = Mock()
                session.get.return_value = response
                fetcher = HttpPageFetcher(session=session, min_interval_seconds=0, max_retries=0)
                with self.assertRaises(SourceAccessBlocked):
                    fetcher.fetch("https://www.invaluable.com/auction-lot/example-116")

    def test_invaluable_access_errors_offer_recovery_without_assuming_a_cache_exists(self):
        for method, status, html in (
            ("get", 202, ""), ("get", 403, ""), ("post", 403, ""),
            ("get", 200, "<h1>Verify you are human</h1>"),
        ):
            with self.subTest(method=method, status=status):
                response = requests.Response()
                response.status_code = status
                response.headers["Content-Type"] = "text/html"
                response._content = html.encode()
                session = Mock()
                getattr(session, method).return_value = response
                fetcher = HttpPageFetcher(session=session, min_interval_seconds=0)
                with self.assertRaises(SourceAccessBlocked) as raised:
                    if method == "post":
                        fetcher.post_json("https://www.invaluable.com/catResults", {})
                    else:
                        fetcher.fetch("https://www.invaluable.com/auction-lot/example-116")
                message = str(raised.exception)
                self.assertIn("Retry with browser", message)
                self.assertIn("Import saved Invaluable pages", message)
                self.assertIn("cached lots, if any", message)
                self.assertEqual(getattr(session, method).call_count, 1)

    def test_missing_individual_lot_is_not_a_source_wide_block(self):
        response = requests.Response()
        response.status_code = 404
        session = Mock()
        session.get.return_value = response
        fetcher = HttpPageFetcher(session=session, min_interval_seconds=0, max_retries=0)
        with self.assertRaises(SourceAccessError) as raised:
            fetcher.fetch("https://www.invaluable.com/auction-lot/example-116")
        self.assertNotIsInstance(raised.exception, SourceAccessBlocked)

    def test_catalog_challenge_heading_is_a_source_wide_block(self):
        response = requests.Response()
        response.status_code = 200
        response.headers["Content-Type"] = "text/html"
        response._content = b"<h1>Verify you are human</h1>"
        session = Mock()
        session.post.return_value = response
        fetcher = HttpPageFetcher(session=session, min_interval_seconds=0)
        with self.assertRaises(SourceAccessBlocked):
            fetcher.post_json("https://www.invaluable.com/catResults", {"requests": []})
