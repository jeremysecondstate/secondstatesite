"""Calendar USD prices use recorded amounts and cached, dated exchange rates."""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import Mock, patch

import requests
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from .tests_calendar import watch_lot


@override_settings(
    CALENDAR_TIME_ZONE="America/Los_Angeles",
    AUCTION_EMAIL_SENDING_ENABLED=False,
    CACHES={"default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "calendar-currency-tests",
    }},
)
class CalendarCurrencyTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.staff = get_user_model().objects.create_user("currency-staff", is_staff=True)
        self.client.force_login(self.staff)
        self.url = reverse("auction_calendar_usd_prices")
        self.rates = {"EUR": "1.10", "JPY": "0.0067", "CAD": "0.7335", "GBP": "1.30"}
        self.observation_date = "2026-10-21"
        clock = patch("secondstateapp.currency.timezone.now", return_value=datetime(2026, 10, 22, 1, tzinfo=timezone.utc))
        clock.start()
        self.addCleanup(clock.stop)
        request = patch("secondstateapp.currency.requests.get", side_effect=self.quote)
        self.request = request.start()
        self.addCleanup(request.stop)

    def quote(self, url, **kwargs):
        currency = url.split("/")[-2].upper()
        if currency not in self.rates:
            raise requests.HTTPError("No quote available")
        response = Mock()
        response.json.return_value = {
            "base": currency, "quote": "USD", "rate": self.rates[currency], "date": self.observation_date,
        }
        return response

    def prices(self, day="2026-07-25"):
        response = self.client.get(self.url, {"day": day})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["day"], day)
        self.assertIn("no-store", response.headers["Cache-Control"])
        return {lot["id"]: lot for lot in response.json()["lots"]}

    def test_requires_staff_and_get(self):
        for user in (None, get_user_model().objects.create_user("currency-customer")):
            with self.subTest(user=user):
                self.client.logout()
                if user:
                    self.client.force_login(user)
                response = self.client.get(self.url, {"day": "2026-07-25"})
                self.assertEqual(response.status_code, 302)
                self.assertIn("/admin/login/", response.headers["Location"])
        self.client.force_login(self.staff)
        for method in ("post", "put", "delete", "head"):
            with self.subTest(method=method):
                self.assertEqual(getattr(self.client, method)(self.url, {"day": "2026-07-25"}).status_code, 405)
        self.request.assert_not_called()

    def test_requires_strict_valid_day_in_calendar_range(self):
        for day in (None, "", "2026-7-25", "20260725", "2026-02-30", "2026-07-25T00:00:00", "1999-12-31", "2101-01-01"):
            with self.subTest(day=day):
                params = {} if day is None else {"day": day}
                self.assertEqual(self.client.get(self.url, params).status_code, 400)
        self.request.assert_not_called()

    def test_converts_estimates_bids_and_results_using_correct_currency_without_mutating_sources(self):
        lot = watch_lot(currency="EUR", estimate_low=Decimal("900.25"), estimate_high=Decimal("1200.50"),
                        current_bid=Decimal("100.00"), sold_price=Decimal("250.00"), sold_currency="GBP")
        prices = self.prices()[lot.pk]
        self.assertEqual(prices["estimate_low"], {
            "source_currency": "EUR", "source_amount": "900.25", "usd_amount": "990.28",
            "rate": "1.10", "rate_date": "2026-10-21", "provider": "Frankfurter",
        })
        self.assertEqual(prices["estimate_high"]["usd_amount"], "1320.55")
        self.assertEqual(prices["current_bid"]["usd_amount"], "110.00")
        self.assertEqual(prices["sold_price"]["usd_amount"], "325.00")
        self.assertEqual(prices["sold_price"]["source_currency"], "GBP")
        lot.refresh_from_db()
        self.assertEqual((lot.estimate_low, lot.estimate_high, lot.current_bid, lot.sold_price),
                         (Decimal("900.25"), Decimal("1200.50"), Decimal("100.00"), Decimal("250.00")))
        self.assertEqual((lot.currency, lot.sold_currency), ("EUR", "GBP"))
        self.assertEqual(self.request.call_count, 2)

    def test_usd_amounts_need_no_quote_and_missing_or_nonpositive_amounts_stay_null(self):
        lot = watch_lot(estimate_low=Decimal("10.25"), estimate_high=None,
                        current_bid=Decimal("0"), sold_price=Decimal("-1"))
        prices = self.prices()[lot.pk]
        self.assertEqual(prices["estimate_low"], {
            "source_currency": "USD", "source_amount": "10.25", "usd_amount": "10.25",
            "rate": "1", "rate_date": None, "provider": None,
        })
        self.assertIsNone(prices["estimate_high"])
        self.assertIsNone(prices["current_bid"])
        self.assertIsNone(prices["sold_price"])
        self.request.assert_not_called()

    def test_high_only_estimates_and_sold_currency_fallback_use_source_currency(self):
        lot = watch_lot(currency="CAD", estimate_low=None, estimate_high=Decimal("10"),
                        sold_price=Decimal("20"), sold_currency="")
        prices = self.prices()[lot.pk]
        self.assertIsNone(prices["estimate_low"])
        self.assertEqual(prices["estimate_high"]["usd_amount"], "7.34")
        self.assertEqual(prices["sold_price"]["usd_amount"], "14.67")
        self.assertEqual(prices["sold_price"]["source_currency"], "CAD")
        self.request.assert_called_once()

    def test_same_quote_is_reused_across_all_lots_fields_and_subsequent_requests(self):
        for index in range(4):
            watch_lot(source_lot_id=f"currency-{index}", currency="JPY",
                      estimate_low=20000 + index, estimate_high=30000 + index,
                      current_bid=15000 + index, sold_price=24000 + index)
        first = self.prices()
        second = self.prices()
        self.assertEqual(first, second)
        self.assertEqual(len(first), 4)
        self.assertEqual(next(iter(first.values()))["estimate_low"]["usd_amount"], "134.00")
        self.request.assert_called_once_with("https://api.frankfurter.dev/v2/rate/jpy/usd", timeout=3)

    def test_lookup_failures_unknown_currencies_and_stale_quotes_never_relabel_native_amounts(self):
        for currency, failure in (("EUR", requests.Timeout()), ("XXX", requests.HTTPError()),
                                  ("", None), ("EUR", "stale")):
            with self.subTest(currency=currency, failure=failure):
                cache.clear()
                self.request.reset_mock()
                self.observation_date = "2026-10-01" if failure == "stale" else "2026-10-21"
                self.request.side_effect = failure if isinstance(failure, Exception) else self.quote
                lot = watch_lot(source_lot_id=f"unavailable-{currency}-{failure}", currency=currency,
                                current_bid=100, sold_price=250)
                prices = self.prices()[lot.pk]
                for field in ("estimate_low", "estimate_high", "current_bid", "sold_price"):
                    self.assertIsNone(prices[field])
                lot.delete()

    def test_local_day_spans_both_dst_hours_excludes_neighbors_and_superseded_lots(self):
        moments = [
            ("before", datetime(2026, 11, 1, 6, 59, tzinfo=timezone.utc)),
            ("start", datetime(2026, 11, 1, 7, 0, tzinfo=timezone.utc)),
            ("first-hour", datetime(2026, 11, 1, 8, 30, tzinfo=timezone.utc)),
            ("repeated-hour", datetime(2026, 11, 1, 9, 30, tzinfo=timezone.utc)),
            ("last", datetime(2026, 11, 2, 7, 59, tzinfo=timezone.utc)),
            ("after", datetime(2026, 11, 2, 8, 0, tzinfo=timezone.utc)),
        ]
        lots = {name: watch_lot(source_lot_id=name, event_at=moment) for name, moment in moments}
        watch_lot(source_lot_id="superseded", event_at=moments[2][1], superseded_by=lots["first-hour"])
        prices = self.prices("2026-11-01")
        self.assertEqual(set(prices), {lots[key].pk for key in ("start", "first-hour", "repeated-hour", "last")})
        self.assertEqual(self.prices("2026-11-03"), {})
        self.request.assert_not_called()

    def test_initial_calendar_html_does_not_fetch_exchange_rates(self):
        watch_lot(currency="JPY", estimate_low=20000, estimate_high=30000)
        response = self.client.get(reverse("auction_calendar"), {"month": "2026-07"})
        self.assertEqual(response.status_code, 200)
        self.request.assert_not_called()
