"""Public browser recovery reads the page's own scoped catalog response."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
from unittest import TestCase
from unittest.mock import Mock, patch
from urllib.parse import urlencode
from bs4 import BeautifulSoup
from catalogapp.bookmark_watchlist import BookmarkEntry
from catalogapp.watchlist_adapters import InvaluableAdapter
from catalogapp.watchlist_browser import InvaluablePublicBrowserFetcher
from catalogapp.watchlist_cache import WatchlistCache
from catalogapp.watchlist_fetch import SourceAccessBlocked, SourceAccessError, WatchlistStopped
from catalogapp.watchlist_models import NormalizedLot
from catalogapp.watchlist_service import WatchlistService

SEARCH_URL = "https://www.invaluable.com/search?artistName=Alexander+Calder&Fine+Art=Prints&query=fine+art&sort=endDateAsc"
CATALOG_URL = "https://www.invaluable.com/catResults"
LOT_URL = "https://www.invaluable.com/auction-lot/alexander-calder-116-c-example"
SEARCH_HTML = f'<h4>1 items</h4><a href="{LOT_URL}">Alexander Calder</a>'
GATED_HTML = "<h1>Lot 116: Alexander Calder</h1><p><b>Sold:</b> Log in to view</p>"


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
        self.handlers = []
        self.auto_response = True
        self.request_body = InvaluableAdapter()._catalog_request_payload(SEARCH_URL)
        self.result = {
            "page": 0, "nbPages": 1, "nbHits": 1, "hitsPerPage": 96,
            "hits": [{"objectID": "12345", "lotRef": "EXAMPLE", "lotNumber": "116",
                      "lotTitle": "Alexander Calder lithograph", "houseName": "Example House",
                      "dateTimeUTCUnix": 1792432800, "currencyCode": "USD"}],
        }
        self.page = Mock()
        self.page.url = "about:blank"
        self.page.is_closed.return_value = False
        self.page.title.side_effect = lambda: self.title
        self.page.content.side_effect = lambda: self.html
        self.page.locator.side_effect = self.locator
        self.page.goto.side_effect = self.navigate
        self.page.wait_for_timeout.side_effect = self.advance
        self.page.on.side_effect = lambda _event, handler: self.handlers.append(handler)
        self.page.remove_listener.side_effect = lambda _event, handler: self.handlers.remove(handler)
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
        return Mock(inner_text=Mock(return_value=" ".join(node.get_text(" ", strip=True) for node in soup.select(selector))))

    def emit(self, *, body=None, result=None, payload=None, status=200, content_type="application/json", url=CATALOG_URL):
        response = Mock(url=url, status=status, headers={"content-type": content_type},
                        request=Mock(method="POST", post_data_json=body if body is not None else self.request_body))
        response.json.return_value = payload if payload is not None else {"results": [result if result is not None else self.result]}
        for handler in list(self.handlers):
            handler(response)
        return response

    def navigate(self, url, **_kwargs):
        self.page.url = url
        if self.auto_response and "/search" in url:
            self.emit()
        return Mock(status=self.initial_status, url=url)

    def advance(self, milliseconds):
        self.now += milliseconds / 1000
        self.after_wait()

    def fetcher(self, **kwargs):
        return InvaluablePublicBrowserFetcher(self.profile, monotonic=lambda: self.now,
            min_interval_seconds=0, access_timeout_seconds=1, **kwargs)

    def test_reads_own_response_without_synthetic_post_and_inherits_verified_artist(self):
        with self.fetcher() as fetcher:
            page = InvaluableAdapter().fetch_search_page(SEARCH_URL, fetcher)
            lots = InvaluableAdapter().parse_search_page(page, SEARCH_URL, "Alexander Calder")
            self.assertEqual(fetcher.pages_fetched, 1)
        self.assertEqual(lots[0].artist, "Alexander Calder")
        self.assertEqual(lots[0].source_lot_id, "12345")
        self.page.goto.assert_called_once_with(SEARCH_URL, wait_until="domcontentloaded", timeout=45_000)
        self.page.evaluate.assert_not_called()
        self.assertEqual(self.handlers, [])
        self.assertFalse(self.playwright.chromium.launch_persistent_context.call_args.kwargs["headless"])

    def test_adapter_skips_or_batch_for_public_browser(self):
        pages = InvaluableAdapter().fetch_search_batch(
            [(SEARCH_URL, "Alexander Calder"), (SEARCH_URL.replace("Calder", "Other"), "Alexander Other")], self.fetcher())
        self.assertEqual(pages, {})
        self.load.assert_not_called()

    def test_invalid_search_and_direct_posts_never_open_browser(self):
        for url in ("http://www.invaluable.com/search", "https://example.com/search", LOT_URL,
                    "https://user:password@www.invaluable.com/search", "https://www.invaluable.com:444/search"):
            with self.subTest(url=url), self.assertRaises(SourceAccessError):
                self.fetcher().fetch_search_page(url)
        with self.assertRaises(SourceAccessError):
            self.fetcher().post_json(CATALOG_URL, {}, referer=SEARCH_URL)
        self.load.assert_not_called()

    def test_waits_for_full_category_hydration_and_ignores_facet_only_calls(self):
        self.auto_response = False
        incomplete = deepcopy(self.request_body)
        incomplete["requests"][0]["params"]["facetFilters"] = [["artistName:Alexander Calder"]]
        facet_only = deepcopy(self.request_body)
        facet_only["requests"][0]["params"]["hitsPerPage"] = 0
        steps = [lambda: self.emit(body=incomplete), lambda: self.emit(body=facet_only), self.emit]
        self.after_wait = lambda: steps.pop(0)()
        with self.fetcher() as fetcher:
            self.assertEqual(json.loads(fetcher.fetch_search_page(SEARCH_URL))["results"][0], self.result)
        self.assertEqual(self.now, 0.75)
        self.page.goto.assert_called_once()
        self.page.evaluate.assert_not_called()

    def test_matches_response_index_instead_of_unrelated_first_result(self):
        self.auto_response = False
        facet_request = deepcopy(self.request_body["requests"][0])
        facet_request["params"]["hitsPerPage"] = 0
        body = {"isCatalogPageRequest": False, "requests": [facet_request, self.request_body["requests"][0]]}
        unrelated = {"page": 0, "nbPages": 0, "nbHits": 76814, "hitsPerPage": 0, "hits": self.result["hits"]}
        self.after_wait = lambda: self.emit(body=body, payload={"results": [unrelated, self.result]})
        with self.fetcher() as fetcher:
            self.assertEqual(json.loads(fetcher.fetch_search_page(SEARCH_URL)), {"results": [self.result]})

    def test_initial_access_response_can_resolve_naturally_without_repeated_navigation(self):
        for status in (202, 401, 403):
            with self.subTest(status=status):
                self.page.goto.reset_mock()
                self.initial_status = status
                self.auto_response = False
                self.html = "<h1>Verify you are human</h1>"
                def loaded():
                    self.html = SEARCH_HTML
                    self.emit()
                self.after_wait = loaded
                with self.fetcher() as fetcher:
                    self.assertEqual(json.loads(fetcher.fetch_search_page(SEARCH_URL))["results"][0], self.result)
                self.page.goto.assert_called_once()
        self.page.evaluate.assert_not_called()

    def test_navigation_timeout_keeps_already_captured_and_later_catalog_results(self):
        for already_captured in (True, False):
            with self.subTest(already_captured=already_captured):
                self.page.goto.reset_mock()
                self.now = 0
                def timed_out(url, **_kwargs):
                    self.page.url = url
                    if already_captured:
                        self.emit()
                    raise TimeoutError("Page.goto: navigation timed out")
                self.page.goto.side_effect = timed_out
                self.after_wait = self.emit
                with self.fetcher() as fetcher:
                    self.assertEqual(json.loads(fetcher.fetch_search_page(SEARCH_URL))["results"][0], self.result)
                    self.assertEqual(fetcher.pages_fetched, 1)
                self.assertEqual(self.now, 0 if already_captured else 0.25)
                self.page.goto.assert_called_once()
                self.assertEqual(self.handlers, [])
        self.page.evaluate.assert_not_called()

    def test_navigation_timeout_without_results_uses_bounded_wait_without_reload(self):
        def timed_out(url, **_kwargs):
            self.page.url = url
            raise TimeoutError("Page.goto: navigation timed out")
        self.page.goto.side_effect = timed_out
        with self.fetcher() as fetcher, self.assertRaisesRegex(SourceAccessBlocked, "no catalog response"):
            fetcher.fetch_search_page(SEARCH_URL)
        self.assertEqual(self.now, 1)
        self.page.goto.assert_called_once()
        self.page.evaluate.assert_not_called()
        self.assertEqual(self.handlers, [])

    def test_navigation_network_error_is_not_treated_as_a_loading_timeout(self):
        self.page.goto.side_effect = RuntimeError("net::ERR_NAME_NOT_RESOLVED")
        with self.fetcher() as fetcher, self.assertRaisesRegex(SourceAccessError, "could not open the search"):
            fetcher.fetch_search_page(SEARCH_URL)
        self.assertEqual(self.now, 0)
        self.page.goto.assert_called_once()
        self.assertEqual(self.handlers, [])

    def test_close_is_source_failure_but_stop_cancels_during_navigation(self):
        for interruption in ("close_error", "close_timeout", "close_response", "stop_timeout"):
            with self.subTest(interruption=interruption):
                self.page.is_closed.return_value = False
                event = threading.Event()
                def interrupted(url, **_kwargs):
                    self.page.url = url
                    self.emit()
                    if interruption == "stop_timeout":
                        event.set()
                    else:
                        self.page.is_closed.return_value = True
                    if interruption == "close_response":
                        return Mock(status=200, url=url)
                    if interruption.endswith("timeout"):
                        raise TimeoutError("Page.goto: navigation timed out")
                    raise RuntimeError("Target page, context or browser has been closed")
                self.page.goto.side_effect = interrupted
                expected_error = WatchlistStopped if interruption == "stop_timeout" else SourceAccessBlocked
                with self.fetcher(stop_event=event) as fetcher, self.assertRaises(expected_error):
                    fetcher.fetch_search_page(SEARCH_URL)
                self.assertEqual(fetcher.pages_fetched, 0)
                self.assertEqual(self.handlers, [])

    def test_close_during_dom_read_at_deadline_reports_browser_unavailable(self):
        def closed_body(_selector):
            self.now = 1
            self.page.is_closed.return_value = True
            raise RuntimeError("Target page, context or browser has been closed")
        self.page.locator.side_effect = closed_body
        with self.fetcher() as fetcher, self.assertRaisesRegex(SourceAccessBlocked, "browser was closed"):
            fetcher.fetch_search_page(SEARCH_URL)
        self.assertEqual(fetcher.pages_fetched, 0)
        self.assertEqual(self.handlers, [])

    def test_close_during_throttle_or_listener_setup_is_source_failure_before_navigation(self):
        for stage in ("throttle", "listener"):
            with self.subTest(stage=stage):
                self.page.is_closed.return_value = False
                self.page.goto.reset_mock()
                def closed(*_args):
                    self.page.is_closed.return_value = True
                    raise RuntimeError("Target page, context or browser has been closed")
                with self.fetcher() as fetcher:
                    operation = patch.object(fetcher, "_throttle", side_effect=closed) if stage == "throttle" else (
                        patch.object(self.page, "on", side_effect=closed)
                    )
                    with operation, self.assertRaises(SourceAccessBlocked):
                        fetcher.fetch_search_page(SEARCH_URL)
                    self.assertEqual(fetcher.pages_fetched, 0)
                self.page.goto.assert_not_called()
                self.assertEqual(self.handlers, [])

    def test_close_during_public_detail_navigation_wait_or_content_is_source_failure(self):
        for stage in ("navigation", "wait", "read", "content"):
            with self.subTest(stage=stage):
                self.page.is_closed.return_value = False
                self.page.goto.side_effect = self.navigate
                self.page.locator.side_effect = self.locator
                self.page.content.side_effect = lambda: self.html
                self.after_wait = lambda: None
                self.html = "<h1>Lot loading</h1>"
                def closed(*_args, **_kwargs):
                    self.page.is_closed.return_value = True
                    raise RuntimeError("Target page, context or browser has been closed")
                if stage == "navigation":
                    self.page.goto.side_effect = closed
                elif stage == "read":
                    self.page.locator.side_effect = closed
                elif stage == "content":
                    self.page.content.side_effect = closed
                else:
                    self.after_wait = closed
                with self.fetcher() as fetcher, self.assertRaises(SourceAccessBlocked):
                    fetcher.fetch(LOT_URL)
                self.assertEqual(fetcher.pages_fetched, 0)

    def test_captured_results_are_rejected_after_visible_search_scope_changes(self):
        changed_urls = (
            SEARCH_URL.replace("Alexander+Calder", "Pablo+Picasso"),
            SEARCH_URL.replace("query=fine+art", "query=sculpture"),
            SEARCH_URL.replace("Fine+Art=Prints", "Fine+Art=Paintings"),
            SEARCH_URL + "&page=2",
            SEARCH_URL.replace("sort=endDateAsc", "sort=priceAsc"),
            LOT_URL,
        )
        for changed_url in changed_urls:
            with self.subTest(url=changed_url):
                self.now = 0
                def navigated_elsewhere(url, **_kwargs):
                    self.page.url = url
                    self.emit()
                    self.page.url = changed_url
                    return Mock(status=200, url=url)
                self.page.goto.side_effect = navigated_elsewhere
                with self.fetcher() as fetcher:
                    with self.assertRaisesRegex(SourceAccessBlocked, "visible search no longer matches"):
                        fetcher.fetch_search_page(SEARCH_URL)
                    self.assertEqual(fetcher.pages_fetched, 0)
                self.assertEqual(self.handlers, [])

    def test_returning_to_requested_search_requires_a_new_response(self):
        def navigated_elsewhere(url, **_kwargs):
            self.page.url = url
            self.emit()
            self.page.url = url.replace("Alexander+Calder", "Pablo+Picasso")
            return Mock(status=200, url=url)
        self.page.goto.side_effect = navigated_elsewhere
        self.after_wait = lambda: setattr(self.page, "url", SEARCH_URL)
        with self.fetcher() as fetcher, self.assertRaises(SourceAccessBlocked):
            fetcher.fetch_search_page(SEARCH_URL)
        self.assertEqual(fetcher.pages_fetched, 0)
        self.assertEqual(self.handlers, [])

    def test_coherent_zero_result_including_artist_only_zero_is_accepted(self):
        self.result.update(hits=[], nbPages=0, nbHits=0)
        self.html = "<h4>0 items</h4>"
        for artist_only in (False, True):
            if artist_only:
                self.request_body["requests"][0]["params"]["facetFilters"] = [["artistName:Alexander Calder"]]
                self.request_body["requests"][0]["params"].pop("page")
            with self.subTest(artist_only=artist_only), self.fetcher() as fetcher:
                self.assertEqual(json.loads(fetcher.fetch_search_page(SEARCH_URL))["results"][0]["nbHits"], 0)
                self.assertEqual(fetcher.pages_fetched, 1)

    def test_additional_narrowing_controls_never_turn_zero_into_complete_search(self):
        self.result.update(hits=[], nbPages=0, nbHits=0)
        self.auto_response = False
        original = deepcopy(self.request_body)
        restrictions = {
            "numericFilters": ["currentBid>10000000"], "tagFilters": ["private-sale"],
            "aroundLatLng": "40,-73", "aroundLatLngViaIP": True,
            "insideBoundingBox": [[40, -73, 41, -72]], "insidePolygon": [[40, -73, 41, -72, 42, -71]],
            "restrictSearchableAttributes": ["lotTitle"], "distinct": 1,
            "ruleContexts": ["private-view"], "enableRules": True, "unknownFilter": "limited",
        }
        for key, value in restrictions.items():
            with self.subTest(parameter=key):
                self.request_body = deepcopy(original)
                self.request_body["requests"][0]["params"][key] = value
                self.after_wait = self.emit
                with self.fetcher() as fetcher:
                    with self.assertRaisesRegex(SourceAccessBlocked, "additional unsupported search restrictions"):
                        fetcher.fetch_search_page(SEARCH_URL)
                    self.assertEqual(fetcher.pages_fetched, 0)

    def test_normal_display_and_telemetry_params_and_empty_optional_filters_are_supported(self):
        self.request_body["requests"][0]["params"].update({
            "facets": ["*"], "attributesToRetrieve": ["lotTitle", "lotRef"],
            "attributesToHighlight": [], "highlightPreTag": "<em>", "highlightPostTag": "</em>",
            "maxValuesPerFacet": 100, "clickAnalytics": True, "analytics": True,
            "userToken": "test-only-token", "numericFilters": [], "tagFilters": "",
            "aroundLatLngViaIP": False,
        })
        with self.fetcher() as fetcher:
            self.assertEqual(json.loads(fetcher.fetch_search_page(SEARCH_URL))["results"][0], self.result)

    def test_narrowed_zero_preserves_existing_cache_membership_and_observation(self):
        previous = datetime(2026, 10, 15, tzinfo=timezone.utc)
        now = datetime(2026, 10, 16, tzinfo=timezone.utc)
        entry = BookmarkEntry(folder_path=("ARTISTS INVALUABLE",), title="Calder", url=SEARCH_URL,
                              artist="Alexander Calder", source="Invaluable")
        lot = NormalizedLot(source="Invaluable", source_lot_id="existing", artist="Alexander Calder",
                            artist_watchlist_name="Alexander Calder", title="Existing print",
                            lot_url=LOT_URL, end_at="2026-10-24")
        self.request_body["requests"][0]["params"]["numericFilters"] = ["currentBid>10000000"]
        self.result.update(hits=[], nbPages=0, nbHits=0)
        with WatchlistCache(":memory:") as cache, self.fetcher() as fetcher:
            cache.upsert(lot, watch_url=SEARCH_URL, search_hash=lot.content_hash, observed_at=previous)
            service = WatchlistService(cache, fetcher=fetcher, now=lambda: now)
            result = service.refresh([entry], selected_artists=[entry.watch_label], horizon_days=30)
            self.assertTrue(result.errors)
            self.assertEqual(result.metrics.ended_lots, 0)
            self.assertEqual(result.fallback_lot_keys, {lot.cache_key})
            retained = cache.active_lots_for_watch_url(SEARCH_URL)
            self.assertEqual(len(retained), 1)
            self.assertEqual(retained[0].last_seen_at, previous.isoformat())

    def test_missing_response_has_distinct_diagnostic_without_account_data(self):
        self.auto_response = False
        with self.fetcher() as fetcher:
            with self.assertRaisesRegex(SourceAccessBlocked, "no catalog response was observed"):
                fetcher.fetch_search_page(SEARCH_URL)

    def test_visible_link_or_zero_label_without_scoped_response_never_proves_completeness(self):
        self.auto_response = False
        for html in (SEARCH_HTML, "<h4>0 items</h4>", "<app-root></app-root>"):
            with self.subTest(html=html):
                self.html = html
                with self.fetcher() as fetcher:
                    with self.assertRaisesRegex(SourceAccessBlocked, "complete catalog response"):
                        fetcher.fetch_search_page(SEARCH_URL)
                    self.assertEqual(fetcher.pages_fetched, 0)

    def test_unrelated_request_scopes_and_external_responses_are_not_used(self):
        variants = []
        for key, value in (("page", 1), ("query", "other"), ("filters", "closed:true"),
                           ("facetFilters", [["artistName:Other"], ["Fine Art:Prints"]])):
            body = deepcopy(self.request_body)
            body["requests"][0]["params"][key] = value
            variants.append({"body": body})
        body = deepcopy(self.request_body)
        body["requests"][0]["indexName"] = "past_lots_prod"
        variants.append({"body": body})
        variants.extend([{"url": "https://example.com/catResults"}, {"url": "https://invaluable.com/catResults"}])
        self.auto_response = False
        for arguments in variants:
            with self.subTest(arguments=arguments):
                self.after_wait = lambda args=arguments: self.emit(**args)
                with self.fetcher() as fetcher, self.assertRaisesRegex(SourceAccessBlocked, "complete catalog response"):
                    fetcher.fetch_search_page(SEARCH_URL)

    def test_incomplete_malformed_duplicate_and_capped_results_are_rejected(self):
        variants = [{"hits": []}, {"nbHits": 2}, {"page": 1}, {"nbPages": 0}, {"nbHits": True},
            {"nbHits": 200, "nbPages": 1}, {"hitsPerPage": 0},
            {"hits": [{"objectID": "12345", "lotTitle": "Incomplete"}]},
            {"hits": self.result["hits"] * 2, "nbHits": 2}]
        self.auto_response = False
        for changes in variants:
            with self.subTest(changes=changes):
                result = {**self.result, **changes}
                self.after_wait = lambda value=result: self.emit(result=value)
                with self.fetcher() as fetcher:
                    with self.assertRaisesRegex(SourceAccessBlocked, "incomplete catalog data"):
                        fetcher.fetch_search_page(SEARCH_URL)
                    self.assertEqual(fetcher.pages_fetched, 0)

    def test_pagination_navigates_each_page_and_retains_service_page_limit_metadata(self):
        first = deepcopy(self.result)
        first.update(nbHits=97, nbPages=2)
        first["hits"] = [{**self.result["hits"][0], "objectID": str(index), "lotRef": f"REF{index}"} for index in range(96)]
        self.result = first
        with self.fetcher() as fetcher:
            page = fetcher.fetch_search_page(SEARCH_URL)
            next_url = InvaluableAdapter().extract_next_page_url(page, SEARCH_URL)
            self.assertIn("page=2", next_url)
            self.request_body = InvaluableAdapter()._catalog_request_payload(next_url)
            self.result = {**first, "page": 1, "hits": [{**first["hits"][0], "objectID": "last", "lotRef": "LAST"}]}
            last_page = fetcher.fetch_search_page(next_url)
            self.assertEqual(InvaluableAdapter().extract_next_page_url(last_page, next_url), "")
            self.assertEqual(fetcher.pages_fetched, 2)
        self.assertEqual(self.page.goto.call_count, 2)
        self.page.evaluate.assert_not_called()

    def test_encoded_request_params_are_supported(self):
        params = dict(self.request_body["requests"][0]["params"])
        params["facetFilters"] = json.dumps(params["facetFilters"])
        self.request_body["requests"][0]["params"] = urlencode(params)
        with self.fetcher() as fetcher:
            self.assertEqual(json.loads(fetcher.fetch_search_page(SEARCH_URL))["results"][0], self.result)

    def test_denied_catalog_does_not_trigger_second_request(self):
        self.auto_response = False
        self.after_wait = lambda: self.emit(status=202, content_type="text/html")
        with self.fetcher() as fetcher:
            for _ in range(2):
                with self.assertRaisesRegex(SourceAccessBlocked, "HTTP 202"):
                    fetcher.fetch_search_page(SEARCH_URL)
        self.page.goto.assert_called_once()
        self.page.evaluate.assert_not_called()
        self.assertEqual(self.handlers, [])

    def test_rate_limit_stops_without_reposting(self):
        self.auto_response = False
        self.after_wait = lambda: self.emit(status=429)
        with self.fetcher() as fetcher, self.assertRaisesRegex(SourceAccessBlocked, "HTTP 429"):
            fetcher.fetch_search_page(SEARCH_URL)
        self.assertEqual(self.now, 0.25)
        self.page.goto.assert_called_once()
        self.page.evaluate.assert_not_called()

    def test_stop_and_closed_window_remove_listener_and_release_browser(self):
        self.auto_response = False
        for cancellation in ("stop", "close", "close_during_wait"):
            with self.subTest(cancellation=cancellation):
                self.context.close.reset_mock()
                self.playwright.stop.reset_mock()
                self.page.is_closed.return_value = False
                event = threading.Event()
                def cancel():
                    if cancellation == "stop":
                        event.set()
                    else:
                        self.page.is_closed.return_value = True
                        if cancellation == "close_during_wait":
                            raise RuntimeError("Target page, context or browser has been closed")
                self.after_wait = cancel
                expected_error = WatchlistStopped if cancellation == "stop" else SourceAccessBlocked
                with self.assertRaises(expected_error), self.fetcher(stop_event=event) as fetcher:
                    fetcher.fetch_search_page(SEARCH_URL)
                self.assertEqual(self.handlers, [])
                self.context.close.assert_called_once()
                self.playwright.stop.assert_called_once()

    def test_challenge_never_accepts_successful_background_response(self):
        self.html = "<h1>Verify you are human</h1>" + SEARCH_HTML
        with self.fetcher() as fetcher:
            with self.assertRaisesRegex(SourceAccessBlocked, "access screen"):
                fetcher.fetch_search_page(SEARCH_URL)
            self.assertEqual(fetcher.pages_fetched, 0)

    def test_access_denied_screen_stops_immediately_and_does_not_reopen_browser(self):
        self.title = "Access Denied"
        self.html = "<h1>Access Denied</h1><p>Your request has been blocked by our security policies.</p>"
        with self.fetcher() as fetcher:
            for _ in range(2):
                with self.assertRaisesRegex(SourceAccessBlocked, "Use my browser"):
                    fetcher.fetch_search_page(SEARCH_URL)
            self.assertEqual(fetcher.pages_fetched, 0)
        self.assertEqual(self.now, 0)
        self.page.goto.assert_called_once()
        self.page.wait_for_timeout.assert_not_called()
        self.assertEqual(self.handlers, [])

    def test_security_policy_denial_is_detected_before_document_title_updates(self):
        self.html = "<h1>Access Denied</h1><p>Your request has been blocked by our security policies.</p>"
        with self.fetcher() as fetcher, self.assertRaisesRegex(SourceAccessBlocked, "denied access"):
            fetcher.fetch_search_page(SEARCH_URL)
        self.assertEqual(self.now, 0)
        self.page.wait_for_timeout.assert_not_called()

    def test_close_and_crash_races_do_not_require_is_closed_to_have_updated(self):
        for stage in ("navigation", "wait", "body", "title", "status_check", "content"):
            with self.subTest(stage=stage):
                self.now = 0
                self.auto_response = False
                self.page.goto.side_effect = self.navigate
                self.page.wait_for_timeout.side_effect = self.advance
                self.page.locator.side_effect = self.locator
                self.page.title.side_effect = lambda: self.title
                self.page.content.side_effect = lambda: self.html
                self.page.is_closed.side_effect = None
                closed = RuntimeError("Target page, context or browser has been closed")
                if stage == "navigation":
                    self.page.goto.side_effect = closed
                elif stage == "wait":
                    self.page.wait_for_timeout.side_effect = RuntimeError("Page.wait_for_timeout: Page crashed")
                elif stage == "body":
                    self.page.locator.side_effect = closed
                elif stage == "title":
                    self.page.title.side_effect = closed
                elif stage == "content":
                    self.page.content.side_effect = closed
                else:
                    self.page.is_closed.side_effect = closed
                with self.fetcher() as fetcher, self.assertRaisesRegex(SourceAccessBlocked, "browser was closed"):
                    if stage == "content":
                        fetcher.fetch(LOT_URL)
                    else:
                        fetcher.fetch_search_page(SEARCH_URL)
                self.assertEqual(self.handlers, [])

    def test_stop_takes_precedence_over_closed_browser_races(self):
        self.auto_response = False
        for stage in ("wait", "body", "content"):
            with self.subTest(stage=stage):
                event = threading.Event()
                def stopped(*_args, **_kwargs):
                    event.set()
                    raise RuntimeError("Target page, context or browser has been closed")
                self.page.wait_for_timeout.side_effect = self.advance
                self.page.locator.side_effect = self.locator
                self.page.content.side_effect = lambda: self.html
                if stage == "wait":
                    self.page.wait_for_timeout.side_effect = stopped
                elif stage == "body":
                    self.page.locator.side_effect = stopped
                else:
                    self.page.content.side_effect = stopped
                with self.fetcher(stop_event=event) as fetcher, self.assertRaises(WatchlistStopped):
                    if stage == "content":
                        fetcher.fetch(LOT_URL)
                    else:
                        fetcher.fetch_search_page(SEARCH_URL)

    def test_closed_target_during_listener_teardown_preserves_successful_result(self):
        self.page.remove_listener.side_effect = RuntimeError("Target page, context or browser has been closed")
        with self.fetcher() as fetcher:
            result = fetcher.fetch_search_page(SEARCH_URL)
        self.assertEqual(json.loads(result)["results"][0], self.result)

    def test_unrelated_listener_teardown_error_is_not_hidden(self):
        self.page.remove_listener.side_effect = RuntimeError("Unexpected listener failure")
        with self.fetcher() as fetcher, self.assertRaisesRegex(RuntimeError, "Unexpected listener failure"):
            fetcher.fetch_search_page(SEARCH_URL)

    def test_closed_target_during_cleanup_does_not_mask_access_denial(self):
        self.title = "Access Denied"
        self.page.remove_listener.side_effect = RuntimeError("Target page, context or browser has been closed")
        self.context.close.side_effect = RuntimeError("Target page, context or browser has been closed")
        self.playwright.stop.side_effect = RuntimeError("Connection closed")
        with self.assertRaisesRegex(SourceAccessBlocked, "denied access"), self.fetcher() as fetcher:
            fetcher.fetch_search_page(SEARCH_URL)
        self.context.close.assert_called_once()
        self.playwright.stop.assert_called_once()

    def test_context_close_race_after_success_cannot_abort_calendar_upload(self):
        self.context.close.side_effect = RuntimeError("Target page, context or browser has been closed")
        self.playwright.stop.side_effect = RuntimeError("Connection closed")
        with self.fetcher() as fetcher:
            result = fetcher.fetch_search_page(SEARCH_URL)
        self.assertEqual(json.loads(result)["results"][0], self.result)
        self.context.close.assert_called_once()
        self.playwright.stop.assert_called_once()
        fetcher.close()
        self.context.close.assert_called_once()

    def test_unrelated_cleanup_error_is_preserved_and_still_stops_playwright(self):
        self.context.close.side_effect = RuntimeError("Could not flush profile to disk")
        self.playwright.stop.side_effect = RuntimeError("Connection closed")
        with self.assertRaisesRegex(RuntimeError, "flush profile"), self.fetcher() as fetcher:
            fetcher.fetch_search_page(SEARCH_URL)
        self.playwright.stop.assert_called_once()

    def test_initial_rate_limit_stops_immediately(self):
        self.initial_status = 429
        with self.fetcher() as fetcher, self.assertRaisesRegex(SourceAccessBlocked, "HTTP 429"):
            fetcher.fetch_search_page(SEARCH_URL)
        self.assertEqual(self.now, 0)

    def test_sold_login_requirement_does_not_block_public_lot_html(self):
        with self.fetcher() as fetcher:
            fetcher.fetch_search_page(SEARCH_URL)
            self.html = GATED_HTML
            self.assertEqual(fetcher.fetch(LOT_URL), GATED_HTML)
            self.assertEqual(fetcher.pages_fetched, 2)

    def test_later_lot_access_denial_keeps_strict_http_checks(self):
        with self.fetcher() as fetcher:
            fetcher.fetch_search_page(SEARCH_URL)
            self.initial_status = 202
            for _ in range(2):
                with self.assertRaisesRegex(SourceAccessBlocked, "HTTP 202"):
                    fetcher.fetch(LOT_URL)
        self.assertEqual([call.args[0] for call in self.page.goto.call_args_list], [SEARCH_URL, LOT_URL])
