"""Regression coverage for live feeds that return HTML with successful HTTP status."""

from unittest import TestCase
from unittest.mock import Mock

import requests

from catalogapp.watchlist_fetch import HttpPageFetcher, SourceAccessError


class CatalogResponseTests(TestCase):
    def test_html_accepted_response_reports_failed_refresh_without_retrying(self):
        response = requests.Response()
        response.status_code = 202
        response.headers["Content-Type"] = "text/html; charset=UTF-8"
        response._content = b"<html>PRIVATE RESPONSE CONTENT</html>"
        session = Mock()
        session.post.return_value = response
        fetcher = HttpPageFetcher(session=session, min_interval_seconds=0, max_retries=2)

        with self.assertRaises(SourceAccessError) as raised:
            fetcher.post_json("https://www.invaluable.com/catResults", {"requests": []})

        message = str(raised.exception)
        self.assertIn("web page instead of auction data (HTTP 202)", message)
        self.assertIn("Live auction data was not refreshed", message)
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
