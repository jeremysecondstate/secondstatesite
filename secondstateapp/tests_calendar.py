import json
import os
from datetime import date, datetime, timedelta
from decimal import Decimal
from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from catalogapp.watchlist_models import NormalizedLot
from catalogapp.watchlist_sync import CalendarSyncError, sync_watchlist_lots
from secondstateapp.artprice_max_bid import (
    analyze_artprice_comparables,
    analyze_artprice_html,
    calculate_bid_rows,
    choose_resale_value,
    extract_preloaded_state,
    money_to_decimal,
    parse_auction_results,
)
from secondstateapp.calendar_views import _uploaded_artprice_html
from secondstateapp.auction_reminders import (
    ReminderDispatchOutcome,
    ReminderConfigurationError,
    ReminderRunResult,
    TwilioSendResult,
    TwilioSmsSender,
    build_due_digests,
    dispatch_active_auction_reminders,
    run_auction_reminders,
)
from secondstateapp.models import (
    AuctionMaxBidAnalysis,
    AuctionReminderControl,
    AuctionReminderDelivery,
    AuctionWatchLot,
)


CALENDAR_ZONE = ZoneInfo("America/Los_Angeles")
ARTPRICE_UPLOAD_LIMIT = 5 * 1024 * 1024


def artprice_html(lots=None, *, currency="usd", suffix=""):
    if lots is None:
        lots = [
            {
                "id": "result-1",
                "title": "Sanitized comparable",
                "price": "$ 1,205",
                "saleDtStart": "26 Mar 2026",
                "auctioneerName": "Dawson's Auctioneers & Valuers",
                "number": "42",
                "lotstatus": 1,
                "estimation": {"low": "$ 1,000", "high": "$ 1,500"},
            }
        ]
    state = {
        "preferences": {"currency": currency},
        "search": {"lots": {str(index): lot for index, lot in enumerate(lots)}},
    }
    return f"<html><script>window.__PRELOADED_STATE__ = {json.dumps(state)};</script>{suffix}</html>"


def artprice_upload(filename="saved-results.html", *, lots=None, currency="usd", suffix=""):
    return SimpleUploadedFile(
        filename,
        artprice_html(lots, currency=currency, suffix=suffix).encode("utf-8"),
        content_type="application/octet-stream",
    )


def stored_analysis(lot, *, created_by=None):
    return AuctionMaxBidAnalysis.objects.create(
        lot=lot,
        source_filename="saved-results.html",
        currency="USD",
        resale_method="median",
        manual_resale_value=None,
        recent_count=3,
        expected_resale_hammer=Decimal("1205.00"),
        net_resale_proceeds=Decimal("1205.00"),
        inbound_shipping=Decimal("200.00"),
        target_profit=Decimal("100.00"),
        seller_commission_pct=Decimal("0.00"),
        outbound_shipping=Decimal("0.00"),
        other_resale_costs=Decimal("0.00"),
        premium_min=23,
        premium_max=35,
        sold_records_count=1,
        comparables=[
            {
                "sale_date": "26 Mar 2026",
                "hammer_price": "1205.00",
                "auction_house": "Dawson's",
                "title": "Sanitized comparable",
                "lot_number": "42",
                "estimate_low": "1000.00",
                "estimate_high": "1500.00",
            }
        ],
        bid_rows=[
            {
                "premium_pct": 23,
                "max_bid": "735.77",
                "buyers_premium": "169.23",
                "shipping": "200.00",
                "all_in_acquisition": "1105.00",
                "projected_profit": "100.00",
            }
        ],
        created_by=created_by,
    )


def watch_lot(**overrides):
    values = {
        "source": "Invaluable",
        "source_lot_id": "inv-100",
        "artist": "Joan Miró",
        "artist_watchlist_name": "Joan Miró",
        "title": "Jeune fille aux papillons",
        "medium": "Lithograph",
        "auction_house": "Bonhams",
        "sale_title": "Modern Prints",
        "lot_number": "25",
        "event_at": datetime(2026, 7, 25, 13, 30, tzinfo=CALENDAR_ZONE),
        "estimate_low": 2000,
        "estimate_high": 3000,
        "currency": "USD",
        "lot_url": "https://www.invaluable.com/auction-lot/example-100",
        "sale_url": "https://www.invaluable.com/catalog/example-sale",
        "source_status": "new",
        "active": True,
    }
    values.update(overrides)
    return AuctionWatchLot.objects.create(**values)


class ArtpriceMaxBidParserTests(SimpleTestCase):
    def test_money_string_parsing(self):
        self.assertEqual(money_to_decimal("$ 1,266.50"), Decimal("1266.50"))
        self.assertEqual(money_to_decimal("USD 2,000"), Decimal("2000"))
        self.assertIsNone(money_to_decimal("Not sold"))
        self.assertIsNone(money_to_decimal(""))
        self.assertIsNone(money_to_decimal(None))
        self.assertIsNone(money_to_decimal(Decimal("1e999999999")))

    def test_embedded_json_extraction_and_safe_failures(self):
        state = extract_preloaded_state(artprice_html())
        self.assertEqual(state["preferences"]["currency"], "usd")

        with self.assertRaisesRegex(ValueError, "preloaded"):
            extract_preloaded_state("<html>No Artprice data here</html>")

        secret = "PRIVATE-CUSTOMER-TOKEN"
        with self.assertRaises(ValueError) as raised:
            extract_preloaded_state(
                f"<script>window.__PRELOADED_STATE__ = {{invalid {secret}</script>"
            )
        self.assertNotIn(secret, str(raised.exception))

    def test_filters_unsold_deduplicates_and_sorts_newest_first(self):
        lots = [
            {
                "id": "new",
                "title": "Newest sold",
                "price": "$ 1,266",
                "saleDtStart": "26 Mar 2026",
                "auctioneerName": "Dawson's",
                "number": "42",
                "lotstatus": 1,
                "estimation": {"low": "$ 1,066", "high": "$ 1,599"},
            },
            {
                "id": "old",
                "title": "Older sold",
                "price": "$ 900",
                "saleDtStart": "10 Jan 2024",
                "auctioneerName": "Example House",
                "lotstatus": 1,
            },
            {
                "id": "duplicate",
                "title": "Newest sold",
                "price": "$ 1,266",
                "saleDtStart": "26 Mar 2026",
                "auctioneerName": "Duplicate House",
                "lotstatus": 1,
            },
            {
                "id": "unsold-number",
                "title": "Not sold",
                "price": "$ 8,000",
                "saleDtStart": "1 Apr 2026",
                "auctioneerName": "Example House",
                "lotstatus": 3,
            },
            {
                "id": "unsold-string",
                "title": "Also not sold",
                "price": "$ 9,000",
                "saleDtStart": "2 Apr 2026",
                "auctioneerName": "Example House",
                "lotstatus": "3",
            },
            {
                "id": "no-price",
                "title": "No hammer",
                "price": "Not sold",
                "saleDtStart": "3 Apr 2026",
                "auctioneerName": "Example House",
                "lotstatus": 1,
            },
        ]

        records = parse_auction_results(artprice_html(lots))

        self.assertEqual([record.title for record in records], ["Newest sold", "Older sold"])
        self.assertEqual(records[0].hammer_price, Decimal("1266"))
        self.assertEqual(records[0].estimate_low, Decimal("1066"))

    def test_selects_largest_coherent_lot_group_and_supports_list_layouts(self):
        primary_lots = [
            {
                "id": f"primary-{index}",
                "title": f"Primary {index}",
                "price": f"$ {1000 + index}",
                "saleDtStart": f"{26 - index} Mar 2026",
                "auctioneerName": "Primary House",
                "lotstatus": 1,
            }
            for index in range(2)
        ]
        unrelated_lot = {
            "id": "cached",
            "title": "Unrelated cached lot",
            "price": "$ 9999",
            "saleDtStart": "27 Mar 2026",
            "auctioneerName": "Cached House",
            "lotstatus": 1,
        }
        state = {
            "preferences": {"currency": "usd"},
            "search": {"results": {str(i): lot for i, lot in enumerate(primary_lots)}},
            "account": {"recent": {"cached": unrelated_lot}},
        }
        html = (
            "<script>window.__PRELOADED_STATE__ = "
            f"{json.dumps(state)};</script>"
        )

        coherent_records = parse_auction_results(html)

        self.assertEqual(
            [record.title for record in coherent_records],
            ["Primary 0", "Primary 1"],
        )

        state["search"] = {"results": primary_lots}
        list_html = (
            "<script>window.__PRELOADED_STATE__ = "
            f"{json.dumps(state)};</script>"
        )
        list_records = parse_auction_results(list_html)
        self.assertEqual(
            [record.title for record in list_records],
            ["Primary 0", "Primary 1"],
        )

    def test_deep_valid_state_is_walked_without_a_recursion_failure(self):
        base_state = {
            "preferences": {"currency": "usd"},
            "search": {
                "lots": {
                    "0": {
                        "id": "deep-result",
                        "title": "Deep comparable",
                        "price": "$ 1,205",
                        "saleDtStart": "26 Mar 2026",
                        "auctioneerName": "House",
                        "lotstatus": 1,
                    }
                }
            },
        }
        depth = 900
        nested_json = (
            '{"nested":' * depth
            + json.dumps(base_state)
            + "}" * depth
        )
        html = f"<script>window.__PRELOADED_STATE__ = {nested_json};</script>"

        result = analyze_artprice_html(html)

        self.assertEqual(result["sold_records_count"], 1)
        self.assertEqual(result["expected_resale_hammer"], "1205.00")

    def test_all_supported_valuation_methods(self):
        values = [Decimal("100"), Decimal("200"), Decimal("400")]
        expected = {
            "median": Decimal("200"),
            "mean": Decimal("233.3333333333333333333333333"),
            "recent": Decimal("150"),
            "max": Decimal("400"),
            "min": Decimal("100"),
            "manual": Decimal("525"),
        }

        for method, expected_value in expected.items():
            with self.subTest(method=method):
                actual = choose_resale_value(
                    values,
                    method,
                    manual_value=Decimal("525"),
                    recent_count=2,
                )
                self.assertEqual(actual, expected_value)

        with self.assertRaisesRegex(ValueError, "greater than zero"):
            choose_resale_value(values, "manual", manual_value=Decimal("0"))

    def test_maximum_bid_formula_and_no_positive_bid_error(self):
        net_proceeds, rows = calculate_bid_rows(
            expected_resale_hammer=Decimal("1205"),
            premium_min=23,
            premium_max=35,
            inbound_shipping=Decimal("200"),
            target_profit=Decimal("100"),
            seller_commission_pct=Decimal("0"),
            outbound_shipping=Decimal("0"),
            other_resale_costs=Decimal("0"),
        )

        self.assertEqual(net_proceeds, Decimal("1205"))
        self.assertEqual(rows[0]["premium_pct"], 23)
        self.assertEqual(rows[0]["max_bid"].quantize(Decimal("0.01")), Decimal("735.77"))
        self.assertEqual(rows[0]["buyers_premium"].quantize(Decimal("0.01")), Decimal("169.23"))
        self.assertEqual(rows[0]["all_in_acquisition"].quantize(Decimal("0.01")), Decimal("1105.00"))
        self.assertEqual(rows[-1]["max_bid"].quantize(Decimal("0.01")), Decimal("670.37"))

        net_with_costs, rows_with_costs = calculate_bid_rows(
            expected_resale_hammer=Decimal("1205"),
            premium_min=23,
            premium_max=23,
            inbound_shipping=Decimal("100"),
            target_profit=Decimal("100"),
            seller_commission_pct=Decimal("10"),
            outbound_shipping=Decimal("50"),
            other_resale_costs=Decimal("25"),
        )
        self.assertEqual(net_with_costs, Decimal("1009.5"))
        self.assertEqual(
            rows_with_costs[0]["max_bid"].quantize(Decimal("0.01")),
            Decimal("658.13"),
        )
        self.assertEqual(
            rows_with_costs[0]["buyers_premium"].quantize(Decimal("0.01")),
            Decimal("151.37"),
        )
        self.assertEqual(
            rows_with_costs[0]["all_in_acquisition"].quantize(Decimal("0.01")),
            Decimal("909.50"),
        )
        self.assertEqual(
            rows_with_costs[0]["projected_profit"].quantize(Decimal("0.01")),
            Decimal("100.00"),
        )

        with self.assertRaisesRegex(ValueError, "No positive bid"):
            calculate_bid_rows(
                expected_resale_hammer=Decimal("100"),
                premium_min=23,
                premium_max=35,
                inbound_shipping=Decimal("200"),
                target_profit=Decimal("100"),
                seller_commission_pct=Decimal("0"),
                outbound_shipping=Decimal("0"),
                other_resale_costs=Decimal("0"),
            )

    def test_high_level_analysis_is_json_safe_and_uses_two_decimal_money_strings(self):
        lots = [
            {
                "id": "one",
                "title": "One",
                "price": "$ 1,000",
                "saleDtStart": "3 Mar 2026",
                "auctioneerName": "House",
                "lotstatus": 1,
            },
            {
                "id": "two",
                "title": "Two",
                "price": "$ 1,410",
                "saleDtStart": "2 Mar 2026",
                "auctioneerName": "House",
                "lotstatus": 1,
            },
        ]

        result = analyze_artprice_html(artprice_html(lots))

        self.assertEqual(result["currency"], "USD")
        self.assertEqual(result["sold_records_count"], 2)
        self.assertEqual(result["expected_resale_hammer"], "1205.00")
        self.assertEqual(result["net_resale_proceeds"], "1205.00")
        self.assertEqual(result["assumptions"]["manual_resale_value"], None)
        self.assertEqual(result["comparables"][0]["hammer_price"], "1000.00")
        self.assertEqual(result["bid_rows"][0]["max_bid"], "735.77")
        self.assertEqual(result["bid_rows"][0]["premium_pct"], 23)
        json.dumps(result)

        manual = analyze_artprice_html(
            artprice_html(lots),
            method="manual",
            manual_resale_value="1500",
        )
        self.assertEqual(manual["expected_resale_hammer"], "1500.00")

    def test_persisted_precision_recalculates_identically(self):
        lots = [
            {
                "id": "one",
                "title": "One",
                "price": "$ 1,000.005",
                "saleDtStart": "3 Mar 2026",
                "auctioneerName": "House",
                "lotstatus": 1,
            },
            {
                "id": "two",
                "title": "Two",
                "price": "$ 1,410.004",
                "saleDtStart": "2 Mar 2026",
                "auctioneerName": "House",
                "lotstatus": 1,
            },
        ]
        result = analyze_artprice_html(
            artprice_html(lots),
            seller_commission_pct="7.25",
            outbound_shipping="40.50",
            other_resale_costs="12.25",
        )

        recalculated = analyze_artprice_comparables(
            result["comparables"],
            currency=result["currency"],
            method=result["method"],
            **result["assumptions"],
        )

        self.assertEqual(result, recalculated)
        self.assertEqual(
            [item["hammer_price"] for item in result["comparables"]],
            ["1000.00", "1410.00"],
        )

        for kwargs in (
            {"inbound_shipping": "1.001"},
            {"seller_commission_pct": "0.0049"},
            {"method": "manual", "manual_resale_value": "1205.001"},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaisesRegex(ValueError, "two decimal places"):
                    analyze_artprice_html(artprice_html(), **kwargs)

    def test_recent_mean_max_min_and_manual_high_level_results(self):
        lots = [
            {
                "id": str(index),
                "title": f"Comparable {index}",
                "price": price,
                "saleDtStart": sale_date,
                "auctioneerName": "House",
                "lotstatus": 1,
            }
            for index, (price, sale_date) in enumerate(
                (
                    ("$ 100", "3 Mar 2026"),
                    ("$ 200", "2 Mar 2026"),
                    ("$ 400", "1 Mar 2026"),
                )
            )
        ]
        expected = {
            "median": "200.00",
            "mean": "233.33",
            "recent": "150.00",
            "max": "400.00",
            "min": "100.00",
            "manual": "525.00",
        }
        for method, expected_value in expected.items():
            with self.subTest(method=method):
                result = analyze_artprice_html(
                    artprice_html(lots),
                    method=method,
                    manual_resale_value="525" if method == "manual" else None,
                    recent_count=2,
                    inbound_shipping=0,
                    target_profit=0,
                )
                self.assertEqual(result["expected_resale_hammer"], expected_value)

    def test_explicit_non_usd_page_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "USD"):
            analyze_artprice_html(artprice_html(currency="eur"))


@override_settings(CALENDAR_TIME_ZONE="America/Los_Angeles")
class AuctionCalendarViewTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user("calendar-admin", password="test-pass", is_staff=True)

    def test_calendar_is_staff_password_protected(self):
        response = self.client.get(reverse("auction_calendar"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.url)

        ordinary = get_user_model().objects.create_user("ordinary", password="test-pass")
        self.client.force_login(ordinary)
        response = self.client.get(reverse("auction_calendar"))
        self.assertEqual(response.status_code, 302)

    def test_calendar_groups_lots_and_exposes_details_for_staff(self):
        artprice_url = (
            "https://www.artprice.com/artist/15266/rockwell-kent/lots/pasts"
            "?idcategory=2&keyword=Starry%20Night&p=1&signed=1&sort=datesale_desc"
        )
        saved_lot = watch_lot(artprice_url=artprice_url)
        watch_lot(source_lot_id="inv-101", artist="Henri Matisse", artist_watchlist_name="Henri Matisse")
        self.client.force_login(self.staff)

        response = self.client.get(reverse("auction_calendar"), {"month": "2026-07"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "July 2026")
        self.assertContains(response, "Bonhams")
        self.assertEqual(response.context["calendar_data"]["2026-07-25"][0]["estimate"], "$2,000–3,000 estimate")
        lot_details = response.context["calendar_data"]["2026-07-25"]
        self.assertEqual({item["artist"] for item in lot_details}, {"Joan Miró", "Henri Matisse"})
        saved_detail = next(item for item in lot_details if item["id"] == saved_lot.pk)
        self.assertEqual(saved_detail["artprice_url"], artprice_url)
        self.assertEqual(
            saved_detail["artprice_analysis_url"],
            reverse("auction_lot_artprice_analysis", args=(saved_lot.pk,)),
        )
        self.assertNotIn("comparables", saved_detail)
        self.assertContains(response, "Artprice Max-Bid Analysis")
        self.assertContains(response, "Analyze HTML")
        self.assertEqual(response.context["weeks"][0][0]["date"].weekday(), 0)

    def test_invalid_month_falls_back_without_error(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("auction_calendar"), {"month": "not-a-month"})
        self.assertEqual(response.status_code, 200)

    def test_calendar_renders_the_paused_reminder_controls_and_preview(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("auction_calendar"), {"month": "2026-07"})
        self.assertContains(response, "Start Reminder Texts")
        self.assertContains(response, "Preview due texts")
        self.assertFalse(response.context["reminder_control"].active)

    def test_reminder_control_endpoints_are_staff_only(self):
        ordinary = get_user_model().objects.create_user("reminder-ordinary", password="test-pass")
        self.client.force_login(ordinary)
        for endpoint in ("auction_reminder_control", "auction_reminder_send"):
            response = self.client.post(reverse(endpoint), {"action": "start", "month": "2026-07"})
            self.assertEqual(response.status_code, 302)
            self.assertIn("login", response.url)


class AuctionArtpriceLinkViewTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user("artprice-admin", password="test-pass", is_staff=True)
        self.lot = watch_lot()
        self.endpoint = reverse("auction_lot_artprice_link", args=(self.lot.pk,))
        self.artprice_url = (
            "https://www.artprice.com/artist/15266/rockwell-kent/lots/pasts"
            "?idcategory=2&keyword=Starry%20Night&p=1&signed=1&sort=datesale_desc"
        )

    def test_artprice_link_editor_is_staff_only(self):
        ordinary = get_user_model().objects.create_user("artprice-ordinary", password="test-pass")
        self.client.force_login(ordinary)

        response = self.client.post(self.endpoint, {"artprice_url": self.artprice_url})

        self.assertEqual(response.status_code, 302)
        self.lot.refresh_from_db()
        self.assertEqual(self.lot.artprice_url, "")

    def test_staff_can_save_and_remove_an_artprice_link(self):
        self.client.force_login(self.staff)

        response = self.client.post(self.endpoint, {"artprice_url": self.artprice_url})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["artprice_url"], self.artprice_url)
        self.lot.refresh_from_db()
        self.assertEqual(self.lot.artprice_url, self.artprice_url)

        response = self.client.post(self.endpoint, {"artprice_url": ""})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["message"], "Artprice link removed.")
        self.lot.refresh_from_db()
        self.assertEqual(self.lot.artprice_url, "")

    def test_non_artprice_and_insecure_links_are_rejected(self):
        self.client.force_login(self.staff)

        for invalid_url in (
            "https://www.artprice.com.evil.example/artist/15266",
            "http://www.artprice.com/artist/15266",
            "https://user:password@www.artprice.com/artist/15266",
        ):
            with self.subTest(invalid_url=invalid_url):
                response = self.client.post(self.endpoint, {"artprice_url": invalid_url})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["error"], "Enter a valid secure artprice.com link.")

        self.lot.refresh_from_db()
        self.assertEqual(self.lot.artprice_url, "")


class AuctionArtpriceAnalysisViewTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user(
            "analysis-admin",
            password="test-pass",
            is_staff=True,
        )
        self.lot = watch_lot()
        self.endpoint = reverse("auction_lot_artprice_analysis", args=(self.lot.pk,))

    @staticmethod
    def assumptions(**overrides):
        values = {
            "method": "median",
            "recent_count": "3",
            "inbound_shipping": "200",
            "target_profit": "100",
            "seller_commission_pct": "0",
            "outbound_shipping": "0",
            "other_resale_costs": "0",
            "premium_min": "23",
            "premium_max": "35",
        }
        values.update(overrides)
        return values

    def analyze(self, *, upload=None, **overrides):
        data = self.assumptions(action="analyze", **overrides)
        data["artprice_html"] = upload or artprice_upload()
        return self.client.post(self.endpoint, data)

    def test_logged_out_and_nonstaff_users_cannot_access_analysis(self):
        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.url)

        response = self.client.post(self.endpoint, {"action": "delete"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.url)

        ordinary = get_user_model().objects.create_user("analysis-ordinary", password="test-pass")
        self.client.force_login(ordinary)
        for method in ("get", "post"):
            with self.subTest(method=method):
                response = getattr(self.client, method)(
                    self.endpoint,
                    {"action": "delete"} if method == "post" else None,
                )
                self.assertEqual(response.status_code, 302)
                self.assertIn("login", response.url)
        self.assertFalse(AuctionMaxBidAnalysis.objects.exists())

    def test_staff_gets_null_when_no_analysis_exists(self):
        self.client.force_login(self.staff)

        response = self.client.get(self.endpoint)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True, "analysis": None})

    def test_staff_can_upload_and_persist_only_normalized_analysis(self):
        private_marker = "PRIVATE_AUTHENTICATED_ACCOUNT_STATE"
        self.client.force_login(self.staff)

        response = self.analyze(
            upload=artprice_upload(
                "../../customer-results.html",
                suffix=f"<!-- {private_marker} -->",
            )
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["analysis"]["source_filename"], "customer-results.html")
        self.assertEqual(payload["analysis"]["currency"], "USD")
        self.assertEqual(payload["analysis"]["sold_records_count"], 1)
        self.assertEqual(payload["analysis"]["expected_resale_hammer"], "1205.00")
        self.assertEqual(payload["analysis"]["bid_rows"][0]["max_bid"], "735.77")

        analysis = AuctionMaxBidAnalysis.objects.get(lot=self.lot)
        self.assertEqual(analysis.created_by, self.staff)
        self.assertEqual(analysis.source_filename, "customer-results.html")
        self.assertEqual(analysis.expected_resale_hammer, Decimal("1205.00"))
        self.assertFalse(
            any(field.get_internal_type() == "FileField" for field in analysis._meta.get_fields())
        )
        normalized_storage = json.dumps(
            {
                "source_filename": analysis.source_filename,
                "comparables": analysis.comparables,
                "bid_rows": analysis.bid_rows,
            }
        )
        self.assertNotIn("window.__PRELOADED_STATE__", normalized_storage)
        self.assertNotIn(private_marker, normalized_storage)

        refreshed = self.client.get(self.endpoint).json()["analysis"]
        self.assertEqual(refreshed["comparables"], payload["analysis"]["comparables"])
        self.assertEqual(refreshed["updated_at"], payload["analysis"]["updated_at"])

    def test_oversized_upload_is_rejected_before_parsing(self):
        self.client.force_login(self.staff)
        upload = SimpleUploadedFile(
            "too-large.html",
            b"x" * (ARTPRICE_UPLOAD_LIMIT + 1),
            content_type="text/html",
        )

        with patch("secondstateapp.calendar_views.analyze_artprice_html") as analyze:
            response = self.analyze(upload=upload)

        self.assertEqual(response.status_code, 413)
        self.assertIn("5 MB", response.json()["error"])
        analyze.assert_not_called()
        self.assertFalse(AuctionMaxBidAnalysis.objects.exists())

    def test_upload_helper_bounds_reads_and_sanitizes_the_filename(self):
        upload = SimpleNamespace(
            name="../../customer-results.html",
            read=Mock(return_value=artprice_html().encode("utf-8")),
        )

        filename, html_text = _uploaded_artprice_html(
            SimpleNamespace(FILES={"artprice_html": upload})
        )

        self.assertEqual(filename, "customer-results.html")
        self.assertIn("window.__PRELOADED_STATE__", html_text)
        upload.read.assert_called_once_with(ARTPRICE_UPLOAD_LIMIT + 1)

    def test_invalid_extension_missing_marker_and_malformed_state_are_safe(self):
        self.client.force_login(self.staff)

        invalid_extension = self.analyze(upload=artprice_upload("results.txt"))
        self.assertEqual(invalid_extension.status_code, 400)
        self.assertIn(".html", invalid_extension.json()["error"])

        missing_marker = self.analyze(
            upload=SimpleUploadedFile("results.html", b"<html>Not an Artprice page</html>")
        )
        self.assertEqual(missing_marker.status_code, 400)
        self.assertIn("preloaded", missing_marker.json()["error"].lower())

        private_marker = "PRIVATE-CUSTOMER-JSON"
        malformed = self.analyze(
            upload=SimpleUploadedFile(
                "results.htm",
                f"<script>window.__PRELOADED_STATE__ = {{broken {private_marker}</script>".encode(),
            )
        )
        self.assertEqual(malformed.status_code, 400)
        self.assertNotIn(private_marker, malformed.json()["error"])
        self.assertFalse(AuctionMaxBidAnalysis.objects.exists())

    def test_invalid_assumptions_are_rejected_without_replacing_saved_data(self):
        invalid_cases = (
            {"inbound_shipping": "-1"},
            {"inbound_shipping": "not-money"},
            {"inbound_shipping": "1.001"},
            {"target_profit": "NaN"},
            {"outbound_shipping": "Infinity"},
            {"seller_commission_pct": "100"},
            {"seller_commission_pct": "0.0049"},
            {"recent_count": "0"},
            {"premium_min": "36", "premium_max": "35"},
            {"premium_min": "0", "premium_max": "1000"},
            {"method": "unsupported"},
            {"method": "manual", "manual_resale_value": ""},
            {"method": "manual", "manual_resale_value": "0"},
            {"other_resale_costs": "999999999999999999999"},
            {"other_resale_costs": "1e999999999"},
        )
        self.client.force_login(self.staff)

        for overrides in invalid_cases:
            with self.subTest(overrides=overrides):
                response = self.analyze(**overrides)
                self.assertEqual(response.status_code, 400)
                self.assertFalse(AuctionMaxBidAnalysis.objects.exists())

        original = self.analyze().json()["analysis"]
        response = self.analyze(target_profit="NaN")
        self.assertEqual(response.status_code, 400)
        persisted = self.client.get(self.endpoint).json()["analysis"]
        self.assertEqual(persisted, original)

    def test_staff_can_recalculate_without_reuploading(self):
        self.client.force_login(self.staff)
        original = self.analyze().json()["analysis"]
        original_pk = AuctionMaxBidAnalysis.objects.get(lot=self.lot).pk

        response = self.client.post(
            self.endpoint,
            self.assumptions(
                action="recalculate",
                method="manual",
                manual_resale_value="2000",
                inbound_shipping="150",
                target_profit="250",
                premium_min="25",
                premium_max="26",
            ),
        )

        self.assertEqual(response.status_code, 200)
        updated = response.json()["analysis"]
        self.assertEqual(updated["method"], "manual")
        self.assertEqual(updated["expected_resale_hammer"], "2000.00")
        self.assertEqual(updated["assumptions"]["inbound_shipping"], "150.00")
        self.assertEqual(updated["assumptions"]["target_profit"], "250.00")
        self.assertEqual(updated["source_filename"], original["source_filename"])
        self.assertEqual(updated["comparables"], original["comparables"])
        self.assertEqual([row["premium_pct"] for row in updated["bid_rows"]], [25, 26])
        self.assertEqual(AuctionMaxBidAnalysis.objects.get(lot=self.lot).pk, original_pk)

    def test_recalculate_requires_an_existing_analysis(self):
        self.client.force_login(self.staff)

        response = self.client.post(
            self.endpoint,
            self.assumptions(action="recalculate"),
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("before recalculating", response.json()["error"])

    def test_staff_can_replace_existing_html(self):
        self.client.force_login(self.staff)
        self.analyze(upload=artprice_upload("first.html"))
        original_pk = AuctionMaxBidAnalysis.objects.get(lot=self.lot).pk
        replacement_lots = [
            {
                "id": "replacement-new",
                "title": "Replacement newest",
                "price": "$ 2,000",
                "saleDtStart": "4 Apr 2026",
                "auctioneerName": "Replacement House",
                "lotstatus": 1,
            },
            {
                "id": "replacement-old",
                "title": "Replacement older",
                "price": "$ 1,000",
                "saleDtStart": "3 Apr 2026",
                "auctioneerName": "Replacement House",
                "lotstatus": 1,
            },
        ]

        response = self.analyze(
            upload=artprice_upload("replacement.htm", lots=replacement_lots)
        )

        self.assertEqual(response.status_code, 200)
        replaced = response.json()["analysis"]
        self.assertEqual(replaced["source_filename"], "replacement.htm")
        self.assertEqual(replaced["sold_records_count"], 2)
        self.assertEqual(replaced["expected_resale_hammer"], "1500.00")
        self.assertEqual(AuctionMaxBidAnalysis.objects.get(lot=self.lot).pk, original_pk)

    def test_staff_can_delete_analysis(self):
        self.client.force_login(self.staff)
        self.analyze()

        response = self.client.post(self.endpoint, {"action": "delete"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["analysis"], None)
        self.assertEqual(response.json()["message"], "Artprice analysis removed.")
        self.assertFalse(AuctionMaxBidAnalysis.objects.filter(lot=self.lot).exists())

    def test_analysis_post_requires_csrf(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.staff)

        response = csrf_client.post(self.endpoint, {"action": "delete"})

        self.assertEqual(response.status_code, 403)


@override_settings(
    CALENDAR_TIME_ZONE="America/Los_Angeles",
    TWILIO_SMS_ENABLED=True,
    TWILIO_ACCOUNT_SID="AC" + "1" * 32,
    TWILIO_API_KEY_SID="SK" + "2" * 32,
    TWILIO_API_KEY_SECRET="test-secret",
    TWILIO_FROM_NUMBER="+12065550123",
    TWILIO_MESSAGING_SERVICE_SID="",
    AUCTION_REMINDER_TO_NUMBERS="+12065550124",
)
class AuctionReminderControlViewTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user("reminder-admin", password="test-pass", is_staff=True)
        self.client.force_login(self.staff)

    @patch("secondstateapp.calendar_views.dispatch_active_auction_reminders")
    def test_start_activates_and_immediately_runs_catch_up(self, dispatch):
        dispatch.return_value = ReminderDispatchOutcome(
            status="no_due",
            summary="Nothing due.",
            control_active=True,
            master_enabled=True,
            attempted=True,
            result=ReminderRunResult(),
        )

        response = self.client.post(
            reverse("auction_reminder_control"),
            {"action": "start", "month": "2026-07"},
        )

        self.assertRedirects(response, "/calendar/?month=2026-07", fetch_redirect_response=False)
        control = AuctionReminderControl.load()
        self.assertTrue(control.active)
        self.assertEqual(control.updated_by, self.staff)
        dispatch.assert_called_once_with(source="start")

    @override_settings(TWILIO_SMS_ENABLED=False)
    @patch("secondstateapp.calendar_views.dispatch_active_auction_reminders")
    def test_start_refuses_when_the_render_safety_switch_is_off(self, dispatch):
        response = self.client.post(reverse("auction_reminder_control"), {"action": "start"})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(AuctionReminderControl.load().active)
        dispatch.assert_not_called()

    def test_pause_blocks_send_due_now(self):
        control = AuctionReminderControl.load()
        control.active = True
        control.save(update_fields=("active", "updated_at"))

        response = self.client.post(reverse("auction_reminder_control"), {"action": "pause"})
        self.assertEqual(response.status_code, 302)
        control.refresh_from_db()
        self.assertFalse(control.active)

        response = self.client.post(reverse("auction_reminder_send"))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(AuctionReminderControl.load().active)

    @patch("secondstateapp.calendar_views.dispatch_active_auction_reminders")
    def test_send_due_now_uses_the_same_idempotent_dispatcher(self, dispatch):
        control = AuctionReminderControl.load()
        control.active = True
        control.save(update_fields=("active", "updated_at"))
        dispatch.return_value = ReminderDispatchOutcome(
            status="up_to_date",
            summary="Already covered.",
            control_active=True,
            master_enabled=True,
            attempted=True,
            result=ReminderRunResult(skipped=1),
        )

        response = self.client.post(reverse("auction_reminder_send"), {"month": "2026-07"})

        self.assertRedirects(response, "/calendar/?month=2026-07", fetch_redirect_response=False)
        dispatch.assert_called_once_with(source="manual")


@override_settings(CALENDAR_TIME_ZONE="America/Los_Angeles")
class CalendarSyncApiTests(TestCase):
    endpoint = "/calendar/sync/"

    def _payload(self, **overrides):
        lot = {
            "source": "Invaluable",
            "source_lot_id": "205299494",
            "artist": "Rufino Tamayo",
            "artist_watchlist_name": "Rufino Tamayo",
            "title": "Galaxia",
            "medium": "Mixografia",
            "auction_house": "Bonhams",
            "sale_title": "Prints & Multiples",
            "lot_number": "47",
            "end_at": "2026-07-29T13:00:00-07:00",
            "estimate_low": 10000,
            "estimate_high": 15000,
            "currency": "USD",
            "lot_url": "https://www.invaluable.com/auction-lot/rufino-tamayo-galaxia",
            "sale_url": "https://www.invaluable.com/catalog/example",
            "first_seen_at": "2026-07-20T10:00:00Z",
            "last_seen_at": "2026-07-20T10:00:00Z",
            "status": "new",
        }
        lot.update(overrides)
        return {"lots": [lot]}

    @patch.dict(os.environ, {"CATALOG_API_KEY": "sync-test-key"}, clear=False)
    def test_sync_requires_the_catalog_api_key(self):
        response = self.client.post(self.endpoint, data=json.dumps(self._payload()), content_type="application/json")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(AuctionWatchLot.objects.count(), 0)

    @patch.dict(os.environ, {"CATALOG_API_KEY": "sync-test-key"}, clear=False)
    def test_sync_creates_updates_and_ends_a_lot(self):
        response = self.client.post(
            self.endpoint,
            data=json.dumps(self._payload()),
            content_type="application/json",
            HTTP_X_API_KEY="sync-test-key",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["created"], 1)
        lot = AuctionWatchLot.objects.get()
        self.assertEqual(lot.title, "Galaxia")
        self.assertEqual(lot.event_at.astimezone(CALENDAR_ZONE).hour, 13)
        self.assertTrue(lot.active)
        lot.artprice_url = "https://www.artprice.com/artist/1/example/lots/pasts"
        lot.save(update_fields=("artprice_url",))
        analysis = stored_analysis(lot)
        analysis_pk = analysis.pk

        response = self.client.post(
            self.endpoint,
            data=json.dumps(self._payload(title="Galaxia (updated)", status="ended")),
            content_type="application/json",
            HTTP_X_API_KEY="sync-test-key",
        )
        lot.refresh_from_db()
        self.assertEqual(response.json()["updated"], 1)
        self.assertEqual(response.json()["ended"], 1)
        self.assertEqual(lot.title, "Galaxia (updated)")
        self.assertFalse(lot.active)
        self.assertEqual(lot.artprice_url, "https://www.artprice.com/artist/1/example/lots/pasts")
        analysis.refresh_from_db()
        self.assertEqual(analysis.pk, analysis_pk)
        self.assertEqual(analysis.lot, lot)
        self.assertEqual(analysis.expected_resale_hammer, Decimal("1205.00"))
        self.assertEqual(response.json()["reminders"]["status"], "paused")

    @patch("secondstateapp.calendar_views.dispatch_active_auction_reminders")
    @patch.dict(os.environ, {"CATALOG_API_KEY": "sync-test-key"}, clear=False)
    def test_successful_sync_runs_and_reports_the_reminder_catch_up(self, dispatch):
        dispatch.return_value = ReminderDispatchOutcome(
            status="sent",
            summary="Reminder catch-up sent 1 text.",
            control_active=True,
            master_enabled=True,
            attempted=True,
            result=ReminderRunResult(sent=1),
        )

        response = self.client.post(
            self.endpoint,
            data=json.dumps(self._payload()),
            content_type="application/json",
            HTTP_X_API_KEY="sync-test-key",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["reminders"]["status"], "sent")
        self.assertEqual(response.json()["reminders"]["sent"], 1)
        dispatch.assert_called_once_with(source="sync")

    @patch("secondstateapp.calendar_views.dispatch_active_auction_reminders", side_effect=RuntimeError("boom"))
    @patch.dict(os.environ, {"CATALOG_API_KEY": "sync-test-key"}, clear=False)
    def test_reminder_error_does_not_roll_back_a_successful_calendar_sync(self, _dispatch):
        with patch("secondstateapp.calendar_views.logger.exception"):
            response = self.client.post(
                self.endpoint,
                data=json.dumps(self._payload()),
                content_type="application/json",
                HTTP_X_API_KEY="sync-test-key",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["reminders"]["status"], "error")
        self.assertEqual(AuctionWatchLot.objects.count(), 1)

    @patch.dict(os.environ, {"CATALOG_API_KEY": "sync-test-key"}, clear=False)
    def test_date_only_sale_is_all_day_and_bad_data_is_atomic(self):
        response = self.client.post(
            self.endpoint,
            data=json.dumps(self._payload(end_at="2026-07-29")),
            content_type="application/json",
            HTTP_X_API_KEY="sync-test-key",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(AuctionWatchLot.objects.get().is_all_day)

        bad = self._payload(source_lot_id="bad", estimate_low="not-money")
        response = self.client.post(
            self.endpoint,
            data=json.dumps(bad),
            content_type="application/json",
            HTTP_X_API_KEY="sync-test-key",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(AuctionWatchLot.objects.filter(source_lot_id="bad").exists())

        invalid_date = self._payload(source_lot_id="bad-date", end_at="2026-99-99")
        response = self.client.post(
            self.endpoint,
            data=json.dumps(invalid_date),
            content_type="application/json",
            HTTP_X_API_KEY="sync-test-key",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(AuctionWatchLot.objects.filter(source_lot_id="bad-date").exists())

    @patch.dict(os.environ, {"CATALOG_API_KEY": ""}, clear=False)
    def test_unconfigured_sync_returns_service_unavailable(self):
        response = self.client.post(self.endpoint, data='{"lots": []}', content_type="application/json")
        self.assertEqual(response.status_code, 503)


class _FakeSender:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def send(self, recipient, body):
        self.calls.append((recipient, body))
        if self.fail:
            raise RuntimeError("test failure")
        return TwilioSendResult(message_sid=f"SM{len(self.calls):032d}", status="queued")


@override_settings(
    CALENDAR_TIME_ZONE="America/Los_Angeles",
    SECONDSTATE_PUBLIC_URL="https://secondstate.art",
    SECRET_KEY="reminder-test-secret",
)
class AuctionReminderTests(TestCase):
    today = date(2026, 7, 20)

    def _event(self, days_ahead, **overrides):
        target = self.today + timedelta(days=days_ahead)
        return watch_lot(
            source_lot_id=f"due-{days_ahead}-{AuctionWatchLot.objects.count()}",
            event_at=datetime.combine(target, datetime.min.time(), tzinfo=CALENDAR_ZONE) + timedelta(hours=13),
            **overrides,
        )

    def test_builds_only_the_remaining_three_two_one_day_digests(self):
        self._event(3)
        self._event(2)
        self._event(1)
        self._event(4)
        self._event(0)

        digests = build_due_digests(self.today)

        self.assertEqual([item.days_before for item in digests], [3, 2, 1])
        self.assertTrue(all("Calendar: https://secondstate.art/calendar/" in item.body for item in digests))

    def test_late_discovery_one_day_before_sends_only_one_reminder(self):
        self._event(1)
        digests = build_due_digests(self.today)
        self.assertEqual(len(digests), 1)
        self.assertEqual(digests[0].days_before, 1)

    def test_delivery_is_idempotent_and_phone_is_not_stored_in_plaintext(self):
        self._event(3)
        sender = _FakeSender()
        recipient = "+12065550123"

        first = run_auction_reminders(today=self.today, recipients=[recipient], sender=sender)
        second = run_auction_reminders(today=self.today, recipients=[recipient], sender=sender)

        self.assertEqual(first.sent, 1)
        self.assertEqual(second.skipped, 1)
        self.assertEqual(len(sender.calls), 1)
        delivery = AuctionReminderDelivery.objects.get()
        self.assertEqual(delivery.status, AuctionReminderDelivery.Status.SENT)
        self.assertEqual(delivery.recipient_display, "***0123")
        self.assertNotIn(recipient, delivery.recipient_hash)

    def test_failed_delivery_is_recorded_and_can_retry(self):
        self._event(2)
        failed = run_auction_reminders(today=self.today, recipients=["+12065550123"], sender=_FakeSender(fail=True))
        retried_sender = _FakeSender()
        retried = run_auction_reminders(today=self.today, recipients=["+12065550123"], sender=retried_sender)

        self.assertEqual(failed.failed, 1)
        self.assertEqual(retried.sent, 1)
        self.assertEqual(AuctionReminderDelivery.objects.get().status, AuctionReminderDelivery.Status.SENT)

    def test_new_sale_added_after_a_digest_gets_one_supplemental_message(self):
        self._event(2, auction_house="Bonhams", sale_url="https://example.com/sale/bonhams")
        sender = _FakeSender()
        recipient = "+12065550123"
        first = run_auction_reminders(today=self.today, recipients=[recipient], sender=sender)

        self._event(2, auction_house="Phillips", sale_url="https://example.com/sale/phillips")
        supplemental = run_auction_reminders(today=self.today, recipients=[recipient], sender=sender)
        unchanged = run_auction_reminders(today=self.today, recipients=[recipient], sender=sender)

        self.assertEqual(first.sent, 1)
        self.assertEqual(supplemental.sent, 1)
        self.assertEqual(unchanged.skipped, 1)
        self.assertEqual(len(sender.calls), 2)
        self.assertIn("Phillips", sender.calls[1][1])
        self.assertNotIn("Bonhams", sender.calls[1][1])
        self.assertEqual(len(AuctionReminderDelivery.objects.get().covered_sale_hashes), 2)

    def test_dry_run_command_does_not_require_or_send_twilio_configuration(self):
        self._event(1)
        stdout = StringIO()
        call_command("send_auction_reminders", "--dry-run", "--date", "2026-07-20", stdout=stdout)
        self.assertIn("1-day digest", stdout.getvalue())
        self.assertEqual(AuctionReminderDelivery.objects.count(), 0)

    def test_live_command_exits_cleanly_while_reminders_are_paused(self):
        self._event(1)
        stdout = StringIO()
        call_command("send_auction_reminders", "--date", "2026-07-20", stdout=stdout)
        self.assertIn("paused", stdout.getvalue().lower())
        self.assertEqual(AuctionReminderDelivery.objects.count(), 0)

    @override_settings(
        TWILIO_SMS_ENABLED=True,
        TWILIO_ACCOUNT_SID="AC" + "1" * 32,
        TWILIO_API_KEY_SID="SK" + "2" * 32,
        TWILIO_API_KEY_SECRET="test-secret",
        TWILIO_FROM_NUMBER="+12065550123",
        TWILIO_MESSAGING_SERVICE_SID="",
        AUCTION_REMINDER_TO_NUMBERS="+12065550124",
    )
    @patch("secondstateapp.auction_reminders.TwilioSmsSender.from_settings")
    def test_active_dispatch_sends_once_and_records_the_run(self, sender_from_settings):
        self._event(2)
        sender = _FakeSender()
        sender_from_settings.return_value = sender
        control = AuctionReminderControl.load()
        control.active = True
        control.save(update_fields=("active", "updated_at"))

        first = dispatch_active_auction_reminders(source="sync", today=self.today)
        second = dispatch_active_auction_reminders(source="scheduler", today=self.today)

        self.assertEqual(first.status, "sent")
        self.assertEqual(first.result.sent, 1)
        self.assertEqual(second.status, "up_to_date")
        self.assertEqual(second.result.skipped, 1)
        self.assertEqual(len(sender.calls), 1)
        control.refresh_from_db()
        self.assertEqual(control.last_run_source, "scheduler")
        self.assertEqual(control.last_run_status, "up_to_date")

    @override_settings(TWILIO_SMS_ENABLED=False)
    def test_active_control_still_obeys_the_render_safety_switch(self):
        control = AuctionReminderControl.load()
        control.active = True
        control.save(update_fields=("active", "updated_at"))

        outcome = dispatch_active_auction_reminders(source="sync", today=self.today)

        self.assertEqual(outcome.status, "disabled")
        self.assertFalse(outcome.attempted)
        self.assertEqual(AuctionReminderDelivery.objects.count(), 0)


class _JsonResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self.payload = payload

    def json(self):
        return self.payload


class _RecordingSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


class TwilioSenderTests(SimpleTestCase):
    def test_api_key_auth_and_messaging_service_are_sent_to_twilio(self):
        session = _RecordingSession(_JsonResponse(201, {"sid": "SM123", "status": "queued"}))
        account_sid = "AC" + "1" * 32
        api_key_sid = "SK" + "2" * 32
        messaging_service_sid = "MG" + "3" * 32
        sender = TwilioSmsSender(
            account_sid=account_sid,
            api_key_sid=api_key_sid,
            api_key_secret="secret",
            messaging_service_sid=messaging_service_sid,
            session=session,
        )

        result = sender.send("+12065550123", "Reminder")

        self.assertEqual(result.message_sid, "SM123")
        self.assertEqual(session.calls[0][1]["auth"], (api_key_sid, "secret"))
        self.assertEqual(session.calls[0][1]["data"]["MessagingServiceSid"], messaging_service_sid)
        self.assertNotIn("From", session.calls[0][1]["data"])

    def test_placeholder_messaging_service_sid_fails_before_a_request(self):
        with self.assertRaisesMessage(
            ReminderConfigurationError,
            "TWILIO_MESSAGING_SERVICE_SID must be empty or a valid MG-prefixed Messaging Service SID.",
        ):
            TwilioSmsSender(
                account_sid="AC" + "1" * 32,
                api_key_sid="SK" + "2" * 32,
                api_key_secret="secret",
                from_number="+12065550123",
                messaging_service_sid="???",
            )


class DesktopCalendarSyncTests(SimpleTestCase):
    def test_sync_uploads_only_normalized_calendar_fields(self):
        lot = NormalizedLot(
            source="Invaluable",
            source_lot_id="lot-1",
            artist="Joan Miró",
            artist_watchlist_name="Joan Miró",
            title="Lithograph",
            end_at="2026-07-25T13:00:00-07:00",
            image_url="https://images.example/private.jpg",
            ambiguities=["example"],
        )
        session = _RecordingSession(
            _JsonResponse(
                200,
                {
                    "ok": True,
                    "received": 1,
                    "created": 1,
                    "updated": 0,
                    "ended": 0,
                    "reminders": {
                        "status": "sent",
                        "summary": "Reminder catch-up sent 1 text.",
                        "sent": 1,
                        "skipped": 0,
                        "failed": 0,
                    },
                },
            )
        )

        result = sync_watchlist_lots(
            [lot],
            base_url="https://secondstate.art",
            api_key="catalog-key",
            session=session,
        )

        self.assertEqual(result.created, 1)
        url, request = session.calls[0]
        self.assertEqual(url, "https://secondstate.art/calendar/sync/")
        self.assertEqual(request["headers"]["X-API-KEY"], "catalog-key")
        sent_lot = request["json"]["lots"][0]
        self.assertNotIn("image_url", sent_lot)
        self.assertNotIn("ambiguities", sent_lot)
        self.assertNotIn("content_hash", sent_lot)
        self.assertEqual(result.reminder_status, "sent")
        self.assertEqual(result.reminder_sent, 1)
        self.assertIn("Reminder catch-up sent 1 text.", result.summary())

    def test_remote_plain_http_is_rejected(self):
        with self.assertRaises(CalendarSyncError):
            sync_watchlist_lots([], base_url="http://secondstate.art", api_key="key")
