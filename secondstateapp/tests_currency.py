"""Deterministic currency normalization tests; no live exchange-rate requests."""

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import Mock, patch

import requests
from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from .currency import convert_to_usd


@override_settings(CACHES={"default": {
    "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    "LOCATION": "currency-tests",
}})
class CurrencyConversionTests(SimpleTestCase):
    now = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        clock = patch("secondstateapp.currency.timezone.now", return_value=self.now)
        self.clock = clock.start()
        self.addCleanup(clock.stop)
        request = patch("secondstateapp.currency.requests.get")
        self.request = request.start()
        self.addCleanup(request.stop)

    def response(self, currency="ZAR", rate="0.06075", **overrides):
        payload = {"base": currency, "quote": "USD", "date": "2026-10-16", "rate": rate}
        payload.update(overrides)
        response = Mock()
        response.json.return_value = payload
        self.request.return_value = response
        return response

    def test_zar_cad_eur_conversions_include_serializable_provenance(self):
        for code, rate, source, expected in (
            ("ZAR", "0.06075", "20000", "1215.00"),
            ("CAD", "0.730012", "1000", "730.01"),
            ("EUR", "1.089512", "800", "871.61"),
        ):
            with self.subTest(code=code):
                response = self.response(code, rate)
                result = convert_to_usd(Decimal(source), code)
                self.assertEqual(result, {
                    "source_currency": code,
                    "source_amount": f"{source}.00",
                    "usd_amount": expected,
                    "rate": rate,
                    "rate_date": "2026-10-16",
                    "provider": "Frankfurter",
                })
                json.dumps(result)
                self.request.assert_called_with(
                    f"https://api.frankfurter.dev/v2/rate/{code.lower()}/usd", timeout=3,
                )
                response.json.assert_called_once_with(parse_float=Decimal)

    def test_usd_passthrough_and_round_half_up_never_fetch_rates(self):
        result = convert_to_usd("10.005", " usd ")
        self.assertEqual(result, {
            "source_currency": "USD", "source_amount": "10.01", "usd_amount": "10.01",
            "rate": "1", "rate_date": None, "provider": None,
        })
        self.request.assert_not_called()

    def test_conversion_rounds_half_cent_up_without_float_loss(self):
        self.response("CAD", Decimal("0.7335"))
        self.assertEqual(convert_to_usd("10", "cad")["usd_amount"], "7.34")

    def test_invalid_currencies_and_amounts_do_not_request_rates(self):
        for currency in (None, "", "unknown", "$", "US", "USDD", "US/", 123):
            with self.subTest(currency=currency):
                self.assertIsNone(convert_to_usd("100", currency))
        for amount in (None, "", "NaN", "Infinity", "-Infinity", "bogus", True, False,
                       "0", "-1", "0.001", "1000000000000.01", "1e1000000"):
            with self.subTest(amount=amount):
                self.assertIsNone(convert_to_usd(amount, "EUR"))
        self.request.assert_not_called()

    def test_amount_limits_apply_to_source_and_converted_amount(self):
        self.assertEqual(convert_to_usd("1000000000000", "USD")["usd_amount"], "1000000000000.00")
        self.response("EUR", "1.01")
        self.assertIsNone(convert_to_usd("1000000000000", "EUR"))
        self.response("ZAR", "0.00001")
        self.assertIsNone(convert_to_usd("0.01", "ZAR"))

    def test_successful_quote_is_reused_for_different_amounts(self):
        self.response()
        with patch("secondstateapp.currency.cache.set", wraps=cache.set) as cache_set:
            self.assertEqual(convert_to_usd("20000", "ZAR")["usd_amount"], "1215.00")
            self.assertEqual(convert_to_usd("10000", "ZAR")["usd_amount"], "607.50")
        self.request.assert_called_once()
        self.assertEqual(cache_set.call_args.kwargs["timeout"], 6 * 60 * 60)

    def test_network_and_unsupported_currency_failures_are_cached_briefly(self):
        for failure in (requests.Timeout(), requests.ConnectionError(), requests.HTTPError()):
            with self.subTest(failure=type(failure).__name__):
                cache.clear()
                self.request.reset_mock()
                self.request.side_effect = failure
                with patch("secondstateapp.currency.cache.set", wraps=cache.set) as cache_set:
                    self.assertIsNone(convert_to_usd("100", "XXX"))
                    self.assertIsNone(convert_to_usd("200", "XXX"))
                self.request.assert_called_once()
                self.assertEqual(cache_set.call_args.kwargs["timeout"], 5 * 60)

    def test_http_error_and_invalid_json_fail_gracefully(self):
        response = self.response()
        response.raise_for_status.side_effect = requests.HTTPError("422 invalid currency")
        self.assertIsNone(convert_to_usd("100", "ZAR"))
        response.json.assert_not_called()
        cache.clear()
        response.raise_for_status.side_effect = None
        response.json.side_effect = ValueError("invalid JSON")
        self.assertIsNone(convert_to_usd("100", "ZAR"))

    def test_malformed_or_stale_payloads_are_not_converted(self):
        valid = {"base": "ZAR", "quote": "USD", "date": "2026-10-16", "rate": "0.06"}
        payloads = [None, [], "invalid", {},
                    {**valid, "base": "EUR"}, {**valid, "quote": "CAD"}]
        payloads.extend({**valid, "rate": rate} for rate in (
            None, "", True, "NaN", "Infinity", "0", "-1", "1000000000001", "not a rate",
        ))
        payloads.extend({**valid, "date": observed} for observed in (
            None, "bad date", "20261016", "2026-10-16T00:00:00Z", "2026-10-09", "2026-10-18",
        ))
        for payload in payloads:
            with self.subTest(payload=payload):
                cache.clear()
                self.response().json.return_value = payload
                self.assertIsNone(convert_to_usd("100", "ZAR"))

    def test_seven_day_old_quote_is_accepted_and_cache_age_rechecked(self):
        self.response(date="2026-10-10")
        self.assertEqual(convert_to_usd("100", "ZAR")["usd_amount"], "6.08")
        self.clock.return_value = self.now + timedelta(days=1)
        self.request.side_effect = requests.Timeout()
        self.assertIsNone(convert_to_usd("100", "ZAR"))
        self.assertEqual(self.request.call_count, 2)

    def test_invalid_cached_quote_is_replaced_with_fresh_valid_quote(self):
        cache.set("currency:frankfurter:v2:ZAR:USD", {
            "base": "ZAR", "quote": "USD", "date": "2026-10-01", "rate": "0.01",
        })
        self.response()
        self.assertEqual(convert_to_usd("20000", "ZAR")["usd_amount"], "1215.00")
        self.request.assert_called_once()
