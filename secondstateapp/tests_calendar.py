import base64
import json
import os
from datetime import datetime
from decimal import Decimal
from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command, get_commands
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
from secondstateapp.auction_email import GMAIL_SEND_SCOPE, build_mime_message, compose_auction_email, send_auction_email
from secondstateapp.calendar_views import _uploaded_artprice_html
from secondstateapp.models import (
    AuctionEmailBatch,
    AuctionEmailBatchItem,
    AuctionMaxBidAnalysis,
    AuctionWatchArtist,
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


@override_settings(
    CALENDAR_TIME_ZONE="America/Los_Angeles",
    AUCTION_EMAIL_SENDING_ENABLED=False,
)
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
        image_url = "https://image.invaluable.com/housePhotos/Bonhams/lot-primary.jpg"
        saved_lot = watch_lot(artprice_url=artprice_url, image_url=image_url)
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
        self.assertEqual(saved_detail["images"], [image_url])
        self.assertEqual(
            saved_detail["artprice_analysis_url"],
            reverse("auction_lot_artprice_analysis", args=(saved_lot.pk,)),
        )
        self.assertNotIn("comparables", saved_detail)
        self.assertContains(response, "Artprice Max-Bid Analysis")
        self.assertContains(response, "Analyze HTML")
        self.assertContains(response, 'id="day-lot-browser"')
        self.assertContains(response, 'id="day-lot-browser-launch"')
        self.assertContains(response, 'id="lot-browser-previous"')
        self.assertContains(response, 'id="lot-browser-next"')
        self.assertContains(response, 'image.referrerPolicy = "no-referrer"')
        self.assertContains(response, "moveLotBrowser(-1)")
        self.assertEqual(response.context["weeks"][0][0]["date"].weekday(), 0)

    def test_calendar_serializes_and_renders_only_valid_imported_artist_links(self):
        imported_url = (
            "https://www.artprice.com/artist/28011/antoni-tapies/lots/pasts"
            "?idcategory=2&p=1&sort=datesale_desc"
        )
        artist = AuctionWatchArtist.objects.create(
            name="Antoni Tàpies",
            normalized_name="antoni tapies",
            artprice_url=imported_url,
        )
        linked_lot = watch_lot(
            source_lot_id="tapies-linked",
            artist="Antoni Tàpies",
            artist_watchlist_name="Antoni Tàpies",
            watchlist_artist=artist,
        )
        unlinked_lot = watch_lot(source_lot_id="artist-unlinked", artist="Unknown", artist_watchlist_name="Unknown")
        invalid_artist = AuctionWatchArtist.objects.create(
            name="Unsafe Artist",
            normalized_name="artist unsafe",
            artprice_url="https://artprice.com.evil.example/artist/1/unsafe",
        )
        invalid_lot = watch_lot(
            source_lot_id="artist-invalid",
            artist="Unsafe Artist",
            artist_watchlist_name="Unsafe Artist",
            watchlist_artist=invalid_artist,
        )
        self.client.force_login(self.staff)

        response = self.client.get(reverse("auction_calendar"), {"month": "2026-07"})

        details = {item["id"]: item for item in response.context["calendar_data"]["2026-07-25"]}
        self.assertEqual(details[linked_lot.pk]["artist_artprice_url"], imported_url)
        self.assertEqual(details[unlinked_lot.pk]["artist_artprice_url"], "")
        self.assertEqual(details[invalid_lot.pk]["artist_artprice_url"], "")
        self.assertContains(response, 'link.target = "_blank"')
        self.assertContains(response, 'link.rel = "noopener noreferrer"')
        self.assertContains(response, 'className = "lot-artist"')
        self.assertContains(response, "View ${lot.artist} on Artprice (opens in a new tab)")

    def test_calendar_distinguishes_current_bid_no_bids_and_unavailable(self):
        watch_lot(source_lot_id="current", current_bid=1700, bid_count=4)
        watch_lot(source_lot_id="none", current_bid=3800, bid_count=0)
        watch_lot(source_lot_id="unavailable", current_bid=None, bid_count=None)
        self.client.force_login(self.staff)

        response = self.client.get(reverse("auction_calendar"), {"month": "2026-07"})

        labels = {
            item["id"]: item["bid"]
            for item in response.context["calendar_data"]["2026-07-25"]
        }
        lots = {lot.source_lot_id: lot for lot in AuctionWatchLot.objects.all()}
        self.assertEqual(labels[lots["current"].pk], "Current bid: $1,700 · 4 bids")
        self.assertEqual(labels[lots["none"].pk], "Current bid: No bids")
        self.assertEqual(labels[lots["unavailable"].pk], "Current bid: N/A")
        self.assertContains(response, 'appendText(item, "p", "lot-bid", lot.bid)')

    def test_calendar_does_not_auto_load_images_from_untrusted_hosts(self):
        unsafe_lot = watch_lot(
            source_lot_id="unsafe-image",
            image_url="http://127.0.0.1/private-calendar-image.jpg",
        )
        self.client.force_login(self.staff)

        response = self.client.get(reverse("auction_calendar"), {"month": "2026-07"})

        details = {item["id"]: item for item in response.context["calendar_data"]["2026-07-25"]}
        self.assertEqual(details[unsafe_lot.pk]["images"], [])
        self.assertNotContains(response, "private-calendar-image.jpg")

    def test_invalid_month_falls_back_without_error(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("auction_calendar"), {"month": "not-a-month"})
        self.assertEqual(response.status_code, 200)

    def test_calendar_renders_the_shared_email_tray_panel(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("auction_calendar"), {"month": "2026-07"})
        self.assertContains(response, "Email Tray")
        self.assertContains(response, "Review &amp; Send")
        self.assertContains(response, "Gmail delivery is not ready")
        self.assertEqual(response.context["email_selected_count"], 0)

    def test_email_tray_pages_and_endpoints_are_staff_only(self):
        lot = watch_lot(artprice_url="https://www.artprice.com/artist/1/example/lots/pasts")
        ordinary = get_user_model().objects.create_user("email-ordinary", password="test-pass")
        self.client.force_login(ordinary)
        requests = (
            ("get", reverse("auction_email_tray"), {}),
            ("post", reverse("auction_email_lot_selection", args=(lot.pk,)), {"selected": "true"}),
            ("post", reverse("auction_email_lot_remove", args=(lot.pk,)), {}),
            ("post", reverse("auction_email_tray_clear"), {}),
            ("post", reverse("auction_email_send"), {"recipients": "jeremy"}),
            ("post", reverse("auction_email_retry"), {"recipients": "jeremy"}),
        )
        for method, endpoint, data in requests:
            response = getattr(self.client, method)(endpoint, data)
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


@override_settings(CALENDAR_TIME_ZONE="America/Los_Angeles")
class AuctionEmailTraySelectionTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user("email-admin", password="test-pass", is_staff=True)
        self.other_staff = get_user_model().objects.create_user(
            "email-admin-two", password="test-pass", is_staff=True
        )
        self.artprice_url = "https://www.artprice.com/artist/1/example/lots/pasts"
        self.lot = watch_lot()
        self.client.force_login(self.staff)

    def save_artprice(self):
        return self.client.post(
            reverse("auction_lot_artprice_link", args=(self.lot.pk,)),
            {"artprice_url": self.artprice_url},
        )

    def select(self, selected=True):
        return self.client.post(
            reverse("auction_email_lot_selection", args=(self.lot.pk,)),
            {"selected": "true" if selected else "false"},
        )

    def test_checkbox_is_disabled_without_artprice_and_saving_enables_without_selecting(self):
        response = self.client.get(reverse("auction_calendar"), {"month": "2026-07"})
        lot_data = response.context["calendar_data"]["2026-07-25"][0]
        self.assertEqual(lot_data["artprice_url"], "")
        self.assertFalse(lot_data["email_tray_selected"])
        self.assertContains(response, "Include in next email")
        self.assertContains(response, "trayCheckbox.disabled = !lot.artprice_url")

        saved = self.save_artprice()

        self.assertEqual(saved.status_code, 200)
        self.assertFalse(saved.json()["email_tray_selected"])
        self.assertFalse(AuctionEmailBatchItem.objects.exists())
        response = self.client.get(reverse("auction_calendar"), {"month": "2026-07"})
        lot_data = response.context["calendar_data"]["2026-07-25"][0]
        self.assertEqual(lot_data["artprice_url"], self.artprice_url)
        self.assertFalse(lot_data["email_tray_selected"])

    def test_select_and_deselect_persist_and_record_selecting_staff(self):
        self.save_artprice()
        selected = self.select()

        self.assertEqual(selected.status_code, 200)
        self.assertEqual(selected.json()["selected_count"], 1)
        item = AuctionEmailBatchItem.objects.select_related("batch").get()
        self.assertEqual(item.selected_by, self.staff)
        self.assertTrue(item.batch.is_active)

        response = self.client.get(reverse("auction_calendar"), {"month": "2026-07"})
        self.assertTrue(response.context["calendar_data"]["2026-07-25"][0]["email_tray_selected"])
        self.client.force_login(self.other_staff)
        response = self.client.get(reverse("auction_email_tray"))
        self.assertContains(response, self.staff.username)
        self.assertEqual(response.context["items"][0], item)

        deselected = self.select(False)
        self.assertEqual(deselected.json()["selected_count"], 0)
        self.assertFalse(AuctionEmailBatchItem.objects.exists())

    def test_removing_artprice_link_removes_selected_lot(self):
        self.save_artprice()
        self.select()

        response = self.client.post(
            reverse("auction_lot_artprice_link", args=(self.lot.pk,)),
            {"artprice_url": ""},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["email_tray_selected"])
        self.assertEqual(response.json()["selected_count"], 0)
        self.assertFalse(AuctionEmailBatchItem.objects.exists())

    def test_selection_requires_saved_artprice_and_all_mutations_require_csrf(self):
        response = self.select()
        self.assertEqual(response.status_code, 400)
        self.assertFalse(AuctionEmailBatchItem.objects.exists())

        self.save_artprice()
        self.select()
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.staff)
        mutations = (
            (reverse("auction_email_lot_selection", args=(self.lot.pk,)), {"selected": "false"}),
            (reverse("auction_email_lot_remove", args=(self.lot.pk,)), {}),
            (reverse("auction_email_tray_clear"), {}),
            (reverse("auction_email_send"), {"recipients": "jeremy"}),
            (reverse("auction_email_retry"), {"recipients": "jeremy"}),
        )
        for endpoint, data in mutations:
            with self.subTest(endpoint=endpoint):
                self.assertEqual(csrf_client.post(endpoint, data).status_code, 403)


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
            "current_bid": 10000,
            "bid_count": 4,
            "lot_url": "https://www.invaluable.com/auction-lot/rufino-tamayo-galaxia",
            "sale_url": "https://www.invaluable.com/catalog/example",
            "image_url": "https://image.invaluable.com/housePhotos/Bonhams/galaxia.jpg",
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
        self.assertEqual(lot.current_bid, Decimal("10000.00"))
        self.assertEqual(lot.bid_count, 4)
        self.assertEqual(lot.image_url, "https://image.invaluable.com/housePhotos/Bonhams/galaxia.jpg")
        self.assertTrue(lot.active)
        lot.artprice_url = "https://www.artprice.com/artist/1/example/lots/pasts"
        lot.save(update_fields=("artprice_url",))
        analysis = stored_analysis(lot)
        analysis_pk = analysis.pk
        batch = AuctionEmailBatch.objects.create()
        tray_item = AuctionEmailBatchItem.objects.create(batch=batch, lot=lot)

        response = self.client.post(
            self.endpoint,
            data=json.dumps(
                self._payload(
                    title="Galaxia (updated)",
                    current_bid=3800,
                    bid_count=0,
                    status="ended",
                )
            ),
            content_type="application/json",
            HTTP_X_API_KEY="sync-test-key",
        )
        lot.refresh_from_db()
        self.assertEqual(response.json()["updated"], 1)
        self.assertEqual(response.json()["ended"], 1)
        self.assertEqual(lot.title, "Galaxia (updated)")
        self.assertEqual(lot.current_bid, Decimal("3800.00"))
        self.assertEqual(lot.bid_count, 0)
        self.assertFalse(lot.active)
        self.assertEqual(lot.artprice_url, "https://www.artprice.com/artist/1/example/lots/pasts")
        analysis.refresh_from_db()
        self.assertEqual(analysis.pk, analysis_pk)
        self.assertEqual(analysis.lot, lot)
        self.assertEqual(analysis.expected_resale_hammer, Decimal("1205.00"))
        tray_item.refresh_from_db()
        self.assertEqual(tray_item.lot, lot)
        self.assertNotIn("reminders", response.json())

    @patch.dict(os.environ, {"CATALOG_API_KEY": "sync-test-key"}, clear=False)
    def test_artist_link_sync_is_persistent_idempotent_and_preserves_manual_lot_link(self):
        first_url = "https://www.artprice.com/artist/27973/rufino-tamayo/lots/pasts?idcategory[]=2"
        updated_url = "http://artprice.com/artist/27973/rufino-tamayo/lots/pasts?idcategory=2&p=1"
        payload = self._payload()
        payload["artist_links"] = [{"name": "TAMAYO, RUFINO", "artprice_url": first_url}]

        response = self.client.post(
            self.endpoint,
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_X_API_KEY="sync-test-key",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["artist_links"], 1)
        self.assertEqual(AuctionWatchArtist.objects.count(), 1)
        artist = AuctionWatchArtist.objects.get()
        lot = AuctionWatchLot.objects.get()
        self.assertEqual(artist.artprice_url, first_url)
        self.assertEqual(lot.watchlist_artist, artist)

        manual_url = "https://www.artprice.com/artist/27973/rufino-tamayo/lots/pasts?manual=1"
        lot.artprice_url = manual_url
        lot.save(update_fields=("artprice_url",))
        payload["artist_links"] = [{"name": "Rufino Tamayo", "artprice_url": updated_url}]

        response = self.client.post(
            self.endpoint,
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_X_API_KEY="sync-test-key",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(AuctionWatchArtist.objects.count(), 1)
        artist.refresh_from_db()
        lot.refresh_from_db()
        self.assertEqual(artist.artprice_url, updated_url)
        self.assertEqual(lot.watchlist_artist, artist)
        self.assertEqual(lot.artprice_url, manual_url)

    @patch.dict(os.environ, {"CATALOG_API_KEY": "sync-test-key"}, clear=False)
    def test_artist_link_sync_rejects_unsafe_or_non_artist_urls_atomically(self):
        invalid_urls = (
            "https://artprice.com.evil.example/artist/27973/rufino-tamayo",
            "https://user:password@www.artprice.com/artist/27973/rufino-tamayo",
            "ftp://www.artprice.com/artist/27973/rufino-tamayo",
            "https://www.artprice.com/search?q=tamayo",
        )
        for invalid_url in invalid_urls:
            with self.subTest(invalid_url=invalid_url):
                payload = self._payload()
                payload["artist_links"] = [{"name": "Rufino Tamayo", "artprice_url": invalid_url}]
                response = self.client.post(
                    self.endpoint,
                    data=json.dumps(payload),
                    content_type="application/json",
                    HTTP_X_API_KEY="sync-test-key",
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(AuctionWatchArtist.objects.count(), 0)
                self.assertEqual(AuctionWatchLot.objects.count(), 0)

    @patch.dict(os.environ, {"CATALOG_API_KEY": "sync-test-key"}, clear=False)
    def test_successful_sync_has_no_reminder_dispatch_or_result(self):
        response = self.client.post(
            self.endpoint,
            data=json.dumps(self._payload()),
            content_type="application/json",
            HTTP_X_API_KEY="sync-test-key",
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("reminders", response.json())
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

        bad_bid_count = self._payload(source_lot_id="bad-bid-count", bid_count=-1)
        response = self.client.post(
            self.endpoint,
            data=json.dumps(bad_bid_count),
            content_type="application/json",
            HTTP_X_API_KEY="sync-test-key",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(AuctionWatchLot.objects.filter(source_lot_id="bad-bid-count").exists())

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


@override_settings(
    CALENDAR_TIME_ZONE="America/Los_Angeles",
    SECONDSTATE_PUBLIC_URL="https://secondstate.art",
    AUCTION_EMAIL_SENDING_ENABLED=True,
    AUCTION_EMAIL_SENDER="jeremy@secondstate.art",
    AUCTION_EMAIL_RECIPIENT_JEREMY="jeremy@secondstate.art",
    AUCTION_EMAIL_RECIPIENT_OLIVER="oliver@secondstate.art",
    AUCTION_EMAIL_RECIPIENT_ALEX="alex@secondstate.art",
    GOOGLE_GMAIL_CLIENT_ID="test-client.apps.googleusercontent.com",
    GOOGLE_GMAIL_CLIENT_SECRET="test-client-secret",
    GOOGLE_GMAIL_REFRESH_TOKEN="test-refresh-token",
)
class AuctionEmailBatchTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user("sender", password="test-pass", is_staff=True)
        self.client.force_login(self.staff)

    def selected_batch(self, *lots):
        if not lots:
            lots = (
                watch_lot(
                    artprice_url="https://www.artprice.com/artist/1/example/lots/pasts",
                ),
            )
        batch = AuctionEmailBatch.objects.create()
        for lot in lots:
            AuctionEmailBatchItem.objects.create(batch=batch, lot=lot, selected_by=self.staff)
        return batch, list(lots)

    def test_email_contents_order_grouping_unicode_escaping_and_multipart(self):
        later = watch_lot(
            source_lot_id="later",
            artist="Joan Miró",
            artist_watchlist_name="Joan Miró",
            title='<Study & "Blue">',
            auction_house="Phillips",
            sale_title="Evening Editions",
            lot_number="9",
            event_at=datetime(2026, 8, 7, 12, 0, tzinfo=CALENDAR_ZONE),
            artprice_url="https://www.artprice.com/artist/2/miro/lots/pasts",
        )
        second = watch_lot(
            source_lot_id="second",
            artist="Zao Wou-Ki",
            artist_watchlist_name="Zao Wou-Ki",
            title="Composition",
            auction_house="Bonhams",
            lot_number="12",
            event_at=datetime(2026, 8, 6, 13, 0, tzinfo=CALENDAR_ZONE),
            artprice_url="https://www.artprice.com/artist/3/zao/lots/pasts",
        )
        first = watch_lot(
            source_lot_id="first",
            artist="Alex Katz",
            artist_watchlist_name="Alex Katz",
            title="Morning",
            auction_house="Bonhams",
            lot_number="2",
            event_at=datetime(2026, 8, 6, 13, 0, tzinfo=CALENDAR_ZONE),
            artprice_url="https://www.artprice.com/artist/4/katz/lots/pasts",
        )

        email = compose_auction_email([later, second, first])

        self.assertEqual(email.subject, "SecondState — 3 selected auction lots · Aug 6–7")
        self.assertEqual(email.lot_count, 3)
        self.assertEqual(email.groups[0]["houses"][0]["name"], "Bonhams")
        self.assertEqual([lot["artist"] for lot in email.groups[0]["houses"][0]["lots"]], ["Alex Katz", "Zao Wou-Ki"])
        self.assertLess(email.text_body.index("Alex Katz"), email.text_body.index("Zao Wou-Ki"))
        self.assertLess(email.text_body.index("Zao Wou-Ki"), email.text_body.index("Joan Miró"))
        self.assertIn("https://secondstate.art/calendar/", email.text_body)
        self.assertIn("Joan Miró", email.html_body)
        self.assertIn("&lt;Study &amp; &quot;Blue&quot;&gt;", email.html_body)
        self.assertNotIn('<Study & "Blue">', email.html_body)

        message = build_mime_message(
            subject=email.subject,
            text_body=email.text_body,
            html_body=email.html_body,
            recipients=["jeremy@secondstate.art"],
        )
        self.assertEqual(message["From"], "jeremy@secondstate.art")
        self.assertEqual(message["To"], "jeremy@secondstate.art")
        self.assertEqual([part.get_content_type() for part in message.iter_parts()], ["text/plain", "text/html"])

    @patch("secondstateapp.calendar_views.send_auction_email", return_value="gmail-message-123")
    def test_success_archives_batch_records_metadata_and_clears_active_tray(self, sender):
        batch, lots = self.selected_batch()

        response = self.client.post(
            reverse("auction_email_send"),
            {"recipients": ["jeremy", "alex"], "recipient_address": "attacker@example.com", "month": "2026-07"},
        )

        self.assertRedirects(response, "/calendar/?month=2026-07", fetch_redirect_response=False)
        sender.assert_called_once()
        self.assertEqual(sender.call_args.kwargs["recipients"], ["jeremy@secondstate.art", "alex@secondstate.art"])
        batch.refresh_from_db()
        self.assertEqual(batch.status, AuctionEmailBatch.Status.SENT)
        self.assertFalse(batch.is_active)
        self.assertEqual(batch.requested_by, self.staff)
        self.assertEqual(batch.recipient_keys, ["jeremy", "alex"])
        self.assertEqual(batch.gmail_message_id, "gmail-message-123")
        self.assertEqual(batch.attempt_count, 1)
        self.assertIsNotNone(batch.attempted_at)
        self.assertIsNotNone(batch.sent_at)
        self.assertTrue(batch.subject_snapshot)
        self.assertIn("Joan Miró", batch.html_body_snapshot)
        item = batch.items.get()
        self.assertEqual(item.lot_snapshot["title"], lots[0].title)
        self.assertFalse(AuctionEmailBatch.objects.filter(is_active=True).exists())

        original_subject = batch.subject_snapshot
        lots[0].title = "Changed after send"
        lots[0].save(update_fields=("title",))
        batch.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual(batch.subject_snapshot, original_subject)
        self.assertNotEqual(item.lot_snapshot["title"], lots[0].title)

        calendar = self.client.get(reverse("auction_calendar"), {"month": "2026-07"})
        self.assertEqual(calendar.context["email_selected_count"], 0)
        self.assertEqual(calendar.context["email_last_sent_batch"], batch)

    @patch("secondstateapp.calendar_views.send_auction_email")
    def test_recipient_allowlist_empty_recipient_and_empty_tray_are_rejected(self, sender):
        batch, _lots = self.selected_batch()

        tampered = self.client.post(reverse("auction_email_send"), {"recipients": "attacker@example.com"})
        self.assertEqual(tampered.status_code, 302)
        batch.refresh_from_db()
        self.assertEqual(batch.status, AuctionEmailBatch.Status.DRAFT)

        empty_recipients = self.client.post(reverse("auction_email_send"), {})
        self.assertEqual(empty_recipients.status_code, 302)
        batch.items.all().delete()
        empty_tray = self.client.post(reverse("auction_email_send"), {"recipients": "jeremy"})
        self.assertEqual(empty_tray.status_code, 302)
        sender.assert_not_called()

    @patch("secondstateapp.calendar_views.send_auction_email")
    def test_failed_batch_is_preserved_and_requires_deliberate_retry(self, sender):
        batch, _lots = self.selected_batch()
        sender.side_effect = RuntimeError("failure included test-refresh-token")

        self.client.post(reverse("auction_email_send"), {"recipients": ["jeremy", "oliver"]})

        batch.refresh_from_db()
        self.assertEqual(batch.status, AuctionEmailBatch.Status.FAILED)
        self.assertTrue(batch.is_active)
        self.assertEqual(batch.items.count(), 1)
        self.assertIn("[redacted]", batch.failure_summary)
        self.assertNotIn("test-refresh-token", batch.failure_summary)
        sender.reset_mock()
        sender.side_effect = None
        sender.return_value = "gmail-retry-456"

        self.client.post(reverse("auction_email_send"), {"recipients": "jeremy"})
        sender.assert_not_called()
        self.client.post(reverse("auction_email_retry"), {"recipients": ["jeremy", "oliver"]})

        sender.assert_called_once()
        batch.refresh_from_db()
        self.assertEqual(batch.status, AuctionEmailBatch.Status.SENT)
        self.assertEqual(batch.gmail_message_id, "gmail-retry-456")
        self.assertEqual(batch.attempt_count, 2)

    @patch("secondstateapp.calendar_views.send_auction_email")
    def test_sending_state_blocks_duplicate_send_retry_and_tray_mutation(self, sender):
        batch, lots = self.selected_batch()
        batch.status = AuctionEmailBatch.Status.SENDING
        batch.save(update_fields=("status", "updated_at"))

        self.client.post(reverse("auction_email_send"), {"recipients": "jeremy"})
        self.client.post(reverse("auction_email_retry"), {"recipients": "jeremy"})
        mutation = self.client.post(
            reverse("auction_email_lot_selection", args=(lots[0].pk,)),
            {"selected": "false"},
        )

        self.assertEqual(mutation.status_code, 409)
        sender.assert_not_called()
        batch.refresh_from_db()
        self.assertEqual(batch.status, AuctionEmailBatch.Status.SENDING)
        self.assertEqual(batch.items.count(), 1)

    @override_settings(AUCTION_EMAIL_SENDING_ENABLED=False)
    @patch("secondstateapp.calendar_views.send_auction_email")
    def test_disabled_delivery_keeps_preview_available_and_refuses_provider(self, sender):
        batch, _lots = self.selected_batch()

        review = self.client.get(reverse("auction_email_tray"))
        response = self.client.post(reverse("auction_email_send"), {"recipients": "jeremy"})

        self.assertEqual(review.status_code, 200)
        self.assertContains(review, "Message preview")
        self.assertContains(review, "Gmail delivery is not ready")
        self.assertEqual(response.status_code, 302)
        sender.assert_not_called()
        batch.refresh_from_db()
        self.assertEqual(batch.status, AuctionEmailBatch.Status.DRAFT)

    @override_settings(GOOGLE_GMAIL_REFRESH_TOKEN="")
    @patch("secondstateapp.calendar_views.send_auction_email")
    def test_incomplete_configuration_refuses_provider(self, sender):
        batch, _lots = self.selected_batch()
        self.client.post(reverse("auction_email_send"), {"recipients": "jeremy"})
        sender.assert_not_called()
        batch.refresh_from_db()
        self.assertEqual(batch.status, AuctionEmailBatch.Status.DRAFT)

    def test_review_uses_only_fixed_recipient_keys_and_tray_can_remove_and_clear(self):
        first = watch_lot(
            source_lot_id="remove-one",
            artprice_url="https://www.artprice.com/artist/1/one/lots/pasts",
        )
        second = watch_lot(
            source_lot_id="remove-two",
            artprice_url="https://www.artprice.com/artist/2/two/lots/pasts",
        )
        batch, _lots = self.selected_batch(first, second)

        review = self.client.get(reverse("auction_email_tray"))
        for key, name, address in (
            ("jeremy", "Jeremy", "jeremy@secondstate.art"),
            ("oliver", "Oliver", "oliver@secondstate.art"),
            ("alex", "Alex", "alex@secondstate.art"),
        ):
            self.assertContains(review, f'value="{key}"')
            self.assertContains(review, name)
            self.assertContains(review, address)
        self.assertNotContains(review, 'input type="email"')

        self.client.post(reverse("auction_email_lot_remove", args=(first.pk,)))
        self.assertEqual(batch.items.count(), 1)
        self.client.post(reverse("auction_email_tray_clear"))
        self.assertEqual(batch.items.count(), 0)

    def test_scheduled_twilio_command_is_retired(self):
        self.assertNotIn("send_auction_reminders", get_commands())


@override_settings(
    AUCTION_EMAIL_SENDER="jeremy@secondstate.art",
    GOOGLE_GMAIL_CLIENT_ID="test-client.apps.googleusercontent.com",
    GOOGLE_GMAIL_CLIENT_SECRET="test-client-secret",
    GOOGLE_GMAIL_REFRESH_TOKEN="test-refresh-token",
)
class GmailProviderTests(SimpleTestCase):
    @patch("googleapiclient.discovery.build")
    def test_provider_sends_one_urlsafe_multipart_message_as_the_oauth_user(self, build):
        execute = build.return_value.users.return_value.messages.return_value.send.return_value.execute
        execute.return_value = {"id": "gmail-provider-id"}

        message_id = send_auction_email(
            subject="SecondState — 1 selected auction lot · Aug 6",
            text_body="Joan Miró\n",
            html_body="<p>Joan Miró</p>",
            recipients=["jeremy@secondstate.art"],
        )

        self.assertEqual(message_id, "gmail-provider-id")
        build.assert_called_once_with("gmail", "v1", credentials=build.call_args.kwargs["credentials"], cache_discovery=False)
        send = build.return_value.users.return_value.messages.return_value.send
        self.assertEqual(send.call_args.kwargs["userId"], "me")
        encoded = send.call_args.kwargs["body"]["raw"]
        decoded = base64.urlsafe_b64decode(encoded.encode("ascii"))
        self.assertIn(b'multipart/alternative', decoded)
        self.assertIn(b'jeremy@secondstate.art', decoded)


@override_settings(
    AUCTION_EMAIL_SENDER="jeremy@secondstate.art",
    GOOGLE_GMAIL_CLIENT_ID="test-client.apps.googleusercontent.com",
    GOOGLE_GMAIL_CLIENT_SECRET="test-client-secret",
)
class AuthorizeAuctionGmailCommandTests(SimpleTestCase):
    @patch("google_auth_oauthlib.flow.InstalledAppFlow.from_client_config")
    def test_command_requests_only_gmail_send_and_prints_without_writing(self, from_client_config):
        flow = from_client_config.return_value
        flow.run_local_server.return_value = SimpleNamespace(refresh_token="test-command-refresh-token")
        stdout = StringIO()

        call_command("authorize_auction_gmail", stdout=stdout)

        self.assertEqual(from_client_config.call_args.kwargs["scopes"], [GMAIL_SEND_SCOPE])
        self.assertEqual(flow.run_local_server.call_args.kwargs["login_hint"], "jeremy@secondstate.art")
        self.assertEqual(flow.run_local_server.call_args.kwargs["access_type"], "offline")
        self.assertIn("GOOGLE_GMAIL_REFRESH_TOKEN=", stdout.getvalue())
        self.assertIn("test-command-refresh-token", stdout.getvalue())


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


class DesktopCalendarSyncTests(SimpleTestCase):
    def test_sync_uploads_only_normalized_calendar_fields(self):
        lot = NormalizedLot(
            source="Invaluable",
            source_lot_id="lot-1",
            artist="Joan Miró",
            artist_watchlist_name="Joan Miró",
            title="Lithograph",
            end_at="2026-07-25T13:00:00-07:00",
            current_bid=1700,
            bid_count=4,
            image_url="https://images.example/lot-primary.jpg",
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
                },
            )
        )

        result = sync_watchlist_lots(
            [lot],
            base_url="https://secondstate.art",
            api_key="catalog-key",
            artist_artprice_links={
                "Joan Miró": "https://www.artprice.com/artist/19928/joan-miro/lots/pasts?idcategory=2&p=1",
                "MIRO, JOAN": "https://www.artprice.com/artist/19928/joan-miro/lots/pasts?idcategory=2&p=1",
            },
            session=session,
        )

        self.assertEqual(result.created, 1)
        url, request = session.calls[0]
        self.assertEqual(url, "https://secondstate.art/calendar/sync/")
        self.assertEqual(request["headers"]["X-API-KEY"], "catalog-key")
        sent_lot = request["json"]["lots"][0]
        self.assertEqual(sent_lot["image_url"], "https://images.example/lot-primary.jpg")
        self.assertNotIn("ambiguities", sent_lot)
        self.assertNotIn("content_hash", sent_lot)
        self.assertEqual(sent_lot["current_bid"], 1700)
        self.assertEqual(sent_lot["bid_count"], 4)
        self.assertEqual(
            request["json"]["artist_links"],
            [
                {
                    "name": "Joan Miró",
                    "artprice_url": "https://www.artprice.com/artist/19928/joan-miro/lots/pasts?idcategory=2&p=1",
                }
            ],
        )
        self.assertEqual(
            result.summary(),
            "Website calendar synced: 1 lots (1 new, 0 updated, 0 ended).",
        )

    def test_remote_plain_http_is_rejected(self):
        with self.assertRaises(CalendarSyncError):
            sync_watchlist_lots([], base_url="http://secondstate.art", api_key="key")
