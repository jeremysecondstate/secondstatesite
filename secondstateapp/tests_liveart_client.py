"""Mocked LiveArt transport tests; these never consume trial Data Units."""

from decimal import Decimal
from unittest import TestCase
from unittest.mock import Mock, patch

import requests

from secondstateapp import liveart_client
from secondstateapp.liveart_client import (
    LiveArtAPIError,
    LiveArtClient,
    LiveArtConfigurationError,
    verify_sold_hammer_usd,
)


def _response(payload, *, status=200, headers=None):
    response = Mock()
    response.status_code = status
    response.headers = headers or {}
    response.json.return_value = payload
    return response


class LiveArtClientTests(TestCase):
    def setUp(self):
        liveart_client._NEXT_REQUEST_AT = 0
        self.session = Mock()
        self.client = LiveArtClient(session=self.session, api_key="private-test-key", _min_interval_seconds=0)

    def test_requires_server_key(self):
        with patch.dict("os.environ", {"LIVEART_API_KEY": ""}):
            with self.assertRaises(LiveArtConfigurationError):
                LiveArtClient(session=self.session)

    def test_bounded_filtered_sale_and_lot_pages_capture_provenance(self):
        self.session.get.side_effect = [
            _response(
                {"items": [{"id": 9}], "total_count": 2},
                headers={
                    "X-LiveArt-DataUnits": "3.0",
                    "X-LiveArt-DataUnits-Remaining": "997",
                    "X-LiveArt-Request-Id": "request-1",
                },
            ),
            _response({"items": [{"id": 91, "status": "sold"}], "has_more": False}),
        ]
        sales = self.client.list_sales(auction_house_id=4, start_datetime__gte="2026-10-01", limit=3)
        lots = self.client.list_lots(sale_id=9, status="sold", limit=5)

        self.assertEqual(sales.items, [{"id": 9}])
        self.assertTrue(sales.has_more)
        self.assertEqual(sales.data_units, Decimal("3.0"))
        self.assertEqual(sales.remaining_data_units, Decimal("997"))
        self.assertEqual(sales.request_id, "request-1")
        self.assertIn("+00:00", sales.retrieved_at)
        self.assertFalse(lots.has_more)
        sale_request = self.session.get.call_args_list[0]
        self.assertEqual(sale_request.args[0], "https://api.liveart.ai/v1/sales")
        self.assertEqual(sale_request.kwargs["params"]["limit"], 3)
        self.assertEqual(sale_request.kwargs["headers"]["Authorization"], "Bearer private-test-key")
        self.assertEqual(sale_request.kwargs["timeout"], (3.05, 10))

    def test_artist_and_artwork_lookup_use_documented_response_shapes(self):
        self.session.get.side_effect = [
            _response(
                {"artists": [{"id": 516, "name": "Alexander Calder"}], "total": 2},
                headers={"X-LiveArt-DataUnits": "3"},
            ),
            _response(
                {"items": [{"id": 2707811, "description": {"name": "Nez et oreilles tres gais"}}],
                 "total_count": 1},
                headers={"X-LiveArt-DataUnits": "3.5"},
            ),
        ]
        artists = self.client.list_artists(q=" Alexander Calder ", limit=1)
        artworks = self.client.list_artworks(
            artist_id=516, search="Nez et oreilles tres gais", limit=5,
        )

        self.assertEqual(artists.items[0]["id"], 516)
        self.assertEqual(artists.total_count, 2)
        self.assertTrue(artists.has_more)
        self.assertEqual(artists.data_units, Decimal("3"))
        self.assertEqual(artworks.items[0]["id"], 2707811)
        self.assertFalse(artworks.has_more)
        self.assertEqual(artworks.data_units, Decimal("3.5"))
        artist_request, artwork_request = self.session.get.call_args_list
        self.assertEqual(artist_request.args[0], "https://api.liveart.ai/v1/artists")
        self.assertEqual(artist_request.kwargs["params"]["q"], "Alexander Calder")
        self.assertEqual(artwork_request.args[0], "https://api.liveart.ai/v1/artworks")
        self.assertEqual(artwork_request.kwargs["params"]["artist_id"], 516)
        self.assertEqual(artwork_request.kwargs["params"]["search"], "Nez et oreilles tres gais")
        self.assertEqual(artwork_request.kwargs["headers"]["Authorization"], "Bearer private-test-key")

    def test_artist_and_artwork_lookup_remain_bounded(self):
        for lookup in (
            lambda: self.client.list_artists(q=""),
            lambda: self.client.list_artists(q="Calder", limit=100),
            lambda: self.client.list_artworks(),
            lambda: self.client.list_artworks(artist_id=516, limit=100),
            lambda: self.client.list_artworks(artist_id=516, unsupported="value"),
        ):
            with self.subTest(lookup=lookup):
                with self.assertRaises(ValueError):
                    lookup()
        self.session.get.assert_not_called()

    def test_related_sold_lots_can_be_bounded_by_artist_and_category(self):
        self.session.get.return_value = _response({"items": [], "has_more": False})
        self.client.list_lots(artist_id=516, category_id=7, status="sold", limit=10)
        self.assertEqual(
            self.session.get.call_args.kwargs["params"],
            {"artist_id": 516, "category_id": 7, "status": "sold", "limit": 10, "offset": 0},
        )

    def test_filters_and_page_sizes_prevent_broad_expensive_queries(self):
        for kwargs in ({}, {"status": "sold"}, {"artist_id": 7, "limit": 100}, {"bogus": "x"}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    self.client.list_lots(**kwargs)
        self.session.get.assert_not_called()

    def test_usage_is_authenticated_and_unmetered_endpoint(self):
        self.session.get.return_value = _response({"du_limit": 1000, "du_consumed": 10})
        self.assertEqual(self.client.get_usage()["du_consumed"], 10)
        self.assertEqual(self.session.get.call_args.args[0], "https://api.liveart.ai/v1/usage")

    def test_short_retry_after_is_honored_once(self):
        self.session.get.side_effect = [
            _response({}, status=429, headers={"Retry-After": "2"}),
            _response({"items": [], "has_more": False}),
        ]
        with patch.object(liveart_client.time, "sleep") as sleep:
            self.assertEqual(self.client.list_lots(artist_id=7).items, [])
        sleep.assert_called_once_with(2.0)
        self.assertEqual(self.session.get.call_count, 2)

    def test_long_retry_after_is_exposed_without_sleeping(self):
        self.session.get.return_value = _response({}, status=429, headers={"Retry-After": "30"})
        with patch.object(liveart_client.time, "sleep") as sleep:
            with self.assertRaises(LiveArtAPIError) as raised:
                self.client.list_lots(artist_id=7)
        self.assertEqual(raised.exception.status_code, 429)
        self.assertEqual(raised.exception.retry_after, 30)
        sleep.assert_not_called()

    def test_timeout_is_a_safe_domain_error(self):
        self.session.get.side_effect = requests.Timeout("internal transport details")
        with self.assertRaisesRegex(LiveArtAPIError, "timed out") as raised:
            self.client.list_sales(name__ilike="Modern")
        self.assertNotIn("internal transport details", str(raised.exception))

    def test_only_positive_sold_usd_hammer_qualifies(self):
        self.assertEqual(
            verify_sold_hammer_usd({"status": "sold", "price": {"hammer_usd": 1200, "premium_usd": 1500}}),
            Decimal("1200"),
        )
        for lot in (
            {"status": "passed", "price": {"hammer_usd": 1200}},
            {"status": "sold", "price": {"hammer_usd": None, "premium_usd": 1500}},
            {"status": "sold", "price": {"hammer_usd": 0}},
            {"status": "sold", "price": {"hammer_usd": "NaN"}},
            {"status": "sold"},
        ):
            with self.subTest(lot=lot):
                self.assertIsNone(verify_sold_hammer_usd(lot))
