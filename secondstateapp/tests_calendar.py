import base64
import json
import os
import re
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
    ArtpriceAnalysisError,
    analyze_artprice_comparables,
    analyze_artprice_html,
    calculate_bid_rows,
    choose_resale_value,
    extract_preloaded_state,
    money_to_decimal,
    parse_auction_results,
)
from secondstateapp.auction_email import GMAIL_SEND_SCOPE, build_mime_message, compose_auction_email, send_auction_email
from secondstateapp.calendar_views import _selected_resale_ids, _uploaded_artprice_html
from secondstateapp.liveart_client import LiveArtAPIError
from secondstateapp.models import (
    AuctionEmailBatch,
    AuctionEmailBatchItem,
    AuctionMaxBidAnalysis,
    AuctionWatchArtist,
    AuctionWatchLot,
    LiveArtResaleAnalysis,
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


def liveart_page(items, *, data_units=3):
    return SimpleNamespace(
        items=items,
        has_more=False,
        total_count=len(items),
        retrieved_at="2026-10-12T12:00:00+00:00",
        data_units=data_units,
        request_id="mock-request",
        remaining_data_units=Decimal("990"),
        limit=20,
        offset=0,
    )


def liveart_lot(
    lot_id,
    *,
    sale_id="sale-2026",
    lot_num="25",
    sale_date="2026-07-25T13:30:00-07:00",
    artist_id="artist-miro",
    artist="Joan Miró",
    title="Jeune fille aux papillons",
    medium="Lithograph",
    category_id=2,
    status="sold",
    hammer_usd=1205,
    original_hammer=1205,
    currency="USD",
):
    return {
        "id": lot_id,
        "sale_id": sale_id,
        "lot_num": lot_num,
        "status": status,
        "lot_url": f"https://www.liveart.ai/lot/{lot_id}",
        "auction_house_name": "Bonhams",
        "sale": {"id": sale_id, "start_datetime": sale_date},
        "artwork": {
            "id": f"artwork-{lot_id}",
            **({"category_id": category_id} if category_id is not None else {}),
            "name": title,
            "artist_id": artist_id,
            "artist": {"id": artist_id, "name": artist},
            "materials": medium,
            "markings": "Signed and numbered 25/100",
            "measurements_height_cm": 50,
            "measurements_width_cm": 40,
        },
        "price": {
            "currency": currency,
            "hammer": original_hammer,
            "hammer_usd": hammer_usd,
        },
    }


def liveart_artwork(
    artwork_id="artwork-miro",
    *,
    artist_id="artist-miro",
    artist="Joan Miró",
    title="Jeune fille aux papillons",
    medium="Lithograph",
    category_id=2,
):
    return {
        "id": artwork_id,
        "artist_id": artist_id,
        "artist": {"id": artist_id, "name": artist},
        "description": {
            "name": title,
            **({"category_id": category_id} if category_id is not None else {}),
            "artist_id": artist_id,
            "artist": {"id": artist_id, "name": artist},
            "materials": medium,
            "markings": "Signed and numbered 25/100",
            "measurements_height_cm": 50,
            "measurements_width_cm": 40,
        },
    }


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
                "auctioneerName": "Dawson's",
                "number": "42",
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

    def test_same_title_date_and_price_at_distinct_sales_are_not_duplicates(self):
        common = {
            "title": "Related print", "price": "$ 1,266",
            "saleDtStart": "26 Mar 2026", "lotstatus": 1,
        }
        records = parse_auction_results(artprice_html([
            {**common, "auctioneerName": "Dawson's", "number": "42"},
            {**common, "auctioneerName": "Dawson's", "number": "43"},
            {**common, "auctioneerName": "Another House", "number": "42"},
        ]))
        self.assertEqual(len(records), 3)

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
        self.assertContains(response, "Saved Artprice HTML")
        self.assertContains(response, "Add HTML files")
        self.assertContains(response, "Find LiveArt sales")
        self.assertContains(response, "Resale Bid Analysis")
        self.assertContains(response, 'appendArtpriceEditor(workflow, lot, actionLinks, {idPrefix: "browser"})')
        self.assertContains(response, 'appendArtpriceAnalysis(workflow, lot, {idPrefix: "browser", quick: true})')
        self.assertContains(response, 'event.target.closest(".artprice-form, .artprice-analysis")')
        self.assertContains(response, 'id="day-lot-browser"')
        self.assertContains(response, 'id="day-lot-browser-launch"')
        self.assertContains(response, 'id="lot-browser-previous"')
        self.assertContains(response, 'id="lot-browser-next"')
        self.assertContains(response, 'image.referrerPolicy = "no-referrer"')
        self.assertContains(response, "moveLotBrowser(-1)")
        self.assertEqual(response.context["weeks"][0][0]["date"].weekday(), 0)

    def test_gallery_catalog_is_available_beside_the_calendar_and_lot_browser(self):
        watch_lot()
        self.client.force_login(self.staff)

        response = self.client.get(reverse("auction_calendar"), {"month": "2026-07"})

        self.assertEqual(response.status_code, 200)
        for element_id in (
            "calendar-view-toggle",
            "catalog-view-toggle",
            "calendar-layout",
            "day-gallery-catalog",
            "day-gallery-grid",
            "day-lot-browser",
            "day-lot-browser-launch",
        ):
            with self.subTest(element_id=element_id):
                self.assertContains(response, f'id="{element_id}"')

    def test_research_concepts_use_a_linkable_day_and_existing_lot_endpoints(self):
        lot = watch_lot()
        self.client.force_login(self.staff)

        response = self.client.get(reverse("auction_calendar"), {
            "view": "research", "day": "2026-07-25", "lot": str(lot.pk), "look": "bidboard",
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["month_title"], "July 2026")
        self.assertEqual(response.context["calendar_data"]["2026-07-25"][0]["id"], lot.pk)
        for element_id in (
            "research-view-toggle", "day-research-workspace", "research-lot-card",
            "research-lot-search", "research-previous", "research-next",
        ):
            with self.subTest(element_id=element_id):
                self.assertContains(response, f'id="{element_id}"')
        for look in ("dossier", "workbench", "bidboard"):
            self.assertContains(response, f'data-research-look="{look}"')
        self.assertContains(response, "calendar_concepts.css")
        self.assertContains(response, 'idPrefix: "research", quick: true, workspace: true,')
        self.assertEqual(
            response.context["calendar_data"]["2026-07-25"][0]["liveart_analysis_url"],
            reverse("auction_lot_liveart_analysis", args=(lot.pk,)),
        )

    def test_gallery_catalog_receives_the_selected_day_lots_from_multiple_houses(self):
        artist_url = "https://www.artprice.com/artist/15155/alex-katz/lots/pasts?idcategory=2"
        artist = AuctionWatchArtist.objects.create(
            name="Alex Katz",
            normalized_name="alex katz",
            artprice_url=artist_url,
        )
        image_url = "https://image.invaluable.com/housePhotos/Bonhams/catalog-lot.jpg"
        linked_lot = watch_lot(
            source_lot_id="catalog-heritage",
            auction_house="Heritage Auctions",
            artist="Alex Katz",
            artist_watchlist_name="Alex Katz",
            watchlist_artist=artist,
            image_url=image_url,
        )
        second_house_lot = watch_lot(
            source_lot_id="catalog-chiswick",
            auction_house="Chiswick Auctions",
            artist="David Hockney",
            artist_watchlist_name="David Hockney",
            image_url="",
        )
        next_day_lot = watch_lot(
            source_lot_id="catalog-next-day",
            auction_house="Bonhams",
            event_at=datetime(2026, 7, 26, 13, 30, tzinfo=CALENDAR_ZONE),
        )
        self.client.force_login(self.staff)

        response = self.client.get(reverse("auction_calendar"), {"month": "2026-07"})

        match = re.search(
            r'<script id="auction-calendar-data" type="application/json">(.*?)</script>',
            response.content.decode(),
            flags=re.DOTALL,
        )
        self.assertIsNotNone(match)
        rendered_days = json.loads(match.group(1))
        selected_day = {lot["id"]: lot for lot in rendered_days["2026-07-25"]}
        self.assertEqual(set(selected_day), {linked_lot.pk, second_house_lot.pk})
        self.assertEqual(selected_day[linked_lot.pk]["auction_house"], "Heritage Auctions")
        self.assertEqual(selected_day[linked_lot.pk]["artist_artprice_url"], artist_url)
        self.assertEqual(selected_day[linked_lot.pk]["images"], [image_url])
        self.assertEqual(selected_day[second_house_lot.pk]["auction_house"], "Chiswick Auctions")
        self.assertEqual(selected_day[second_house_lot.pk]["artist_artprice_url"], "")
        self.assertEqual(selected_day[second_house_lot.pk]["images"], [])
        self.assertEqual([lot["id"] for lot in rendered_days["2026-07-26"]], [next_day_lot.pk])

    def test_selected_day_lists_every_distinct_sale_before_lot_browser(self):
        sale_titles = [
            "Modern Prints & Works on Paper: A Particularly Long Morning Session",
            "Modern Prints: Afternoon Session",
            "Postwar Editions",
            "Evening Session",
            "Evening Session",
        ]
        sale_urls = [f"https://www.invaluable.com/catalog/sale-{index}" for index in range(5)]
        for index, (sale_title, sale_url) in enumerate(zip(sale_titles, sale_urls)):
            watch_lot(
                source_lot_id=f"sale-{index}-lot-1",
                auction_house="Bonhams",
                sale_title=sale_title,
                sale_url=sale_url,
                event_at=datetime(2026, 7, 25, 9 + index, tzinfo=CALENDAR_ZONE),
            )
        watch_lot(
            source_lot_id="sale-0-lot-2",
            auction_house="Bonhams",
            sale_title=sale_titles[0],
            sale_url=sale_urls[0],
            event_at=datetime(2026, 7, 25, 9, tzinfo=CALENDAR_ZONE),
        )
        self.client.force_login(self.staff)

        response = self.client.get(reverse("auction_calendar"), {"month": "2026-07"})

        sales = response.context["calendar_sales_data"]["2026-07-25"]
        self.assertEqual(len(sales), 5)
        self.assertEqual([sale["sale_title"] for sale in sales], sale_titles)
        self.assertEqual([sale["auction_house"] for sale in sales], ["Bonhams"] * 5)
        self.assertEqual([sale["lot_count"] for sale in sales], [2, 1, 1, 1, 1])
        self.assertEqual([sale["time_label"] for sale in sales], [
            "9:00 AM", "10:00 AM", "11:00 AM", "12:00 PM", "1:00 PM",
        ])
        self.assertEqual([sale["sale_url"] for sale in sales], sale_urls)
        self.assertEqual(len(response.context["calendar_data"]["2026-07-25"]), 6)
        day = next(
            day for week in response.context["weeks"] for day in week
            if day["iso"] == "2026-07-25"
        )
        self.assertEqual(len(day["event_groups"]), 3)
        self.assertEqual(day["more_count"], 2)
        self.assertNotIn("2026-07-24", response.context["calendar_sales_data"])

        html = response.content.decode()
        self.assertIn('<script id="auction-calendar-sales-data" type="application/json">', html)
        self.assertContains(response, "Auctions Happening This Day")
        self.assertContains(response, "Suggested Lots")
        self.assertContains(response, "+2 more auctions")
        self.assertContains(
            response,
            '<span class="event-title">Modern Prints &amp; Works on Paper: A Particularly Long Morning Session</span>',
            html=True,
        )
        self.assertLess(html.index('id="selected-day-title"'), html.index('id="selected-day-sales"'))
        self.assertLess(html.index('id="selected-day-sales"'), html.index('id="suggested-lots-heading"'))
        self.assertLess(html.index('id="suggested-lots-heading"'), html.index('id="day-lot-browser-launch"'))

    def test_selected_day_uses_available_metadata_from_all_lots_in_a_sale(self):
        watch_lot(source_lot_id="sparse-metadata", sale_title="", auction_house="")
        watch_lot(source_lot_id="complete-metadata")
        self.client.force_login(self.staff)

        response = self.client.get(reverse("auction_calendar"), {"month": "2026-07"})

        sales = response.context["calendar_sales_data"]["2026-07-25"]
        self.assertEqual(len(sales), 1)
        self.assertEqual(sales[0]["sale_title"], "Modern Prints")
        self.assertEqual(sales[0]["auction_house"], "Bonhams")
        self.assertEqual(sales[0]["lot_count"], 2)

    def test_selected_day_groups_url_less_sales_without_using_a_lot_link(self):
        watch_lot(source_lot_id="no-sale-url-1", sale_url="")
        watch_lot(source_lot_id="no-sale-url-2", sale_url="")
        watch_lot(
            source_lot_id="no-sale-url-later-session",
            sale_url="",
            event_at=datetime(2026, 7, 25, 16, tzinfo=CALENDAR_ZONE),
        )
        self.client.force_login(self.staff)

        response = self.client.get(reverse("auction_calendar"), {"month": "2026-07"})

        sales = response.context["calendar_sales_data"]["2026-07-25"]
        self.assertEqual(len(sales), 2)
        self.assertEqual([sale["lot_count"] for sale in sales], [2, 1])
        self.assertEqual([sale["sale_url"] for sale in sales], ["", ""])
        self.assertEqual([sale["time_label"] for sale in sales], ["1:30 PM", "4:00 PM"])

    def test_selected_day_sales_follow_local_midnight_instead_of_utc_date(self):
        watch_lot(
            source_lot_id="before-local-midnight",
            sale_title="Late Auction",
            sale_url="https://www.invaluable.com/catalog/late-auction",
            event_at=datetime(2026, 7, 25, 6, 59, tzinfo=ZoneInfo("UTC")),
        )
        watch_lot(
            source_lot_id="at-local-midnight",
            sale_title="Midnight Auction",
            sale_url="https://www.invaluable.com/catalog/midnight-auction",
            event_at=datetime(2026, 7, 25, 7, tzinfo=ZoneInfo("UTC")),
        )
        self.client.force_login(self.staff)

        response = self.client.get(reverse("auction_calendar"), {"month": "2026-07"})

        sales = response.context["calendar_sales_data"]
        self.assertEqual([sale["sale_title"] for sale in sales["2026-07-24"]], ["Late Auction"])
        self.assertEqual([sale["sale_title"] for sale in sales["2026-07-25"]], ["Midnight Auction"])
        self.assertEqual(sales["2026-07-24"][0]["time_label"], "11:59 PM")
        self.assertEqual(sales["2026-07-25"][0]["time_label"], "12:00 AM")

    def test_selected_day_sale_data_includes_upcoming_date_outside_displayed_month(self):
        watch_lot(
            source_lot_id="august-upcoming",
            sale_title="August Auction",
            sale_url="https://www.invaluable.com/catalog/august-auction",
            event_at=datetime(2026, 8, 3, 14, tzinfo=CALENDAR_ZONE),
        )
        self.client.force_login(self.staff)

        with patch(
            "secondstateapp.calendar_views.timezone.now",
            return_value=datetime(2026, 7, 20, 12, tzinfo=CALENDAR_ZONE),
        ):
            response = self.client.get(reverse("auction_calendar"), {"month": "2026-07"})

        self.assertIn("2026-08-03", response.context["calendar_data"])
        self.assertEqual(
            response.context["calendar_sales_data"]["2026-08-03"][0]["sale_title"],
            "August Auction",
        )
        self.assertNotIn("2026-08-04", response.context["calendar_sales_data"])

    def test_upcoming_selected_day_includes_ended_sales_like_the_month_grid(self):
        watch_lot(
            source_lot_id="august-upcoming",
            sale_title="August Auction",
            sale_url="https://www.invaluable.com/catalog/august-auction",
            event_at=datetime(2026, 8, 3, 14, tzinfo=CALENDAR_ZONE),
        )
        watch_lot(
            source_lot_id="august-ended",
            sale_title="August Morning Auction",
            sale_url="https://www.invaluable.com/catalog/august-morning-auction",
            event_at=datetime(2026, 8, 3, 9, tzinfo=CALENDAR_ZONE),
            active=False,
        )
        self.client.force_login(self.staff)

        with patch(
            "secondstateapp.calendar_views.timezone.now",
            return_value=datetime(2026, 8, 3, 12, tzinfo=CALENDAR_ZONE),
        ):
            outside_grid = self.client.get(reverse("auction_calendar"), {"month": "2026-07"})
            inside_grid = self.client.get(reverse("auction_calendar"), {"month": "2026-08"})

        sales = outside_grid.context["calendar_sales_data"]["2026-08-03"]
        self.assertEqual(len(sales), 2)
        self.assertEqual(sales, inside_grid.context["calendar_sales_data"]["2026-08-03"])
        self.assertEqual(
            outside_grid.context["calendar_data"]["2026-08-03"],
            inside_grid.context["calendar_data"]["2026-08-03"],
        )

    def test_adjacent_month_grid_day_has_complete_selected_day_data(self):
        watch_lot(
            source_lot_id="june-adjacent",
            sale_title="June Fine Prints",
            sale_url="https://www.invaluable.com/catalog/june-fine-prints",
            event_at=datetime(2026, 6, 30, 10, tzinfo=CALENDAR_ZONE),
        )
        self.client.force_login(self.staff)

        with patch(
            "secondstateapp.calendar_views.timezone.now",
            return_value=datetime(2026, 7, 20, 12, tzinfo=CALENDAR_ZONE),
        ):
            response = self.client.get(reverse("auction_calendar"), {"month": "2026-07"})

        grid_day = next(
            day for week in response.context["weeks"] for day in week
            if day["iso"] == "2026-06-30"
        )
        self.assertFalse(grid_day["in_month"])
        self.assertEqual(grid_day["lot_count"], 1)
        self.assertEqual(grid_day["event_groups"][0]["sale_title"], "June Fine Prints")
        self.assertEqual(len(response.context["calendar_data"]["2026-06-30"]), 1)
        self.assertEqual(
            response.context["calendar_sales_data"]["2026-06-30"][0]["sale_title"],
            "June Fine Prints",
        )

    def test_out_of_month_upcoming_day_is_complete_beyond_upcoming_query_limit(self):
        event_at = datetime(2026, 8, 3, 14, tzinfo=CALENDAR_ZONE)
        AuctionWatchLot.objects.bulk_create([
            AuctionWatchLot(
                source="Invaluable",
                source_lot_id=f"august-lot-{index}",
                artist="Joan Miró",
                title=f"Artwork {index}",
                auction_house="Bonhams",
                sale_title="August Auction",
                sale_url="https://www.invaluable.com/catalog/august-auction",
                event_at=event_at,
                active=True,
            )
            for index in range(1001)
        ])
        watch_lot(
            source_lot_id="august-later-auction",
            sale_title="August Evening Auction",
            sale_url="https://www.invaluable.com/catalog/august-evening-auction",
            event_at=datetime(2026, 8, 3, 18, tzinfo=CALENDAR_ZONE),
        )
        self.client.force_login(self.staff)

        with patch(
            "secondstateapp.calendar_views.timezone.now",
            return_value=datetime(2026, 7, 20, 12, tzinfo=CALENDAR_ZONE),
        ):
            response = self.client.get(reverse("auction_calendar"), {"month": "2026-07"})

        self.assertEqual(len(response.context["calendar_data"]["2026-08-03"]), 1002)
        self.assertEqual(
            response.context["calendar_sales_data"]["2026-08-03"][0]["lot_count"],
            1001,
        )
        self.assertEqual(
            [sale["sale_title"] for sale in response.context["calendar_sales_data"]["2026-08-03"]],
            ["August Auction", "August Evening Auction"],
        )

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

    def test_react_store_upload_uses_hammer_and_exposes_saved_comp_for_resale(self):
        self.client.force_login(self.staff)
        source_path = "/artist/1/joan-miro/print-multiple/1234/jeune-fille"
        state = {
            "preferences": {"currency": "USD"},
            "dbEntities": {"lots": {"1234": {
                "id": 1234,
                "title": self.lot.title,
                "artistOrAssociation": "Joan Miró",
                "category": "Print-Multiple",
                "technique": "Lithograph in colors",
                "numberAndEdition": "25/100",
                "dimension": "50 x 40 cm",
                "price": "$ 4,200",
                "priceWithTaxes": "$ 5,334",
                "saleDtStart": "29 Jan 2025",
                "auctioneerName": "Rago",
                "number": 222,
                "lotstatus": 1,
                "url": source_path,
            }}},
        }
        html = (
            '<script data-js-react-on-rails-store="artpriceStore" type="application/json">'
            f"{json.dumps(state)}</script>"
        )
        upload = SimpleUploadedFile("artprice-react.html", html.encode("utf-8"))

        uploaded = self.analyze(upload=upload)

        self.assertEqual(uploaded.status_code, 200)
        comparable = uploaded.json()["analysis"]["comparables"][0]
        self.assertEqual(comparable["hammer_price"], "4200.00")
        self.assertEqual(comparable["provider_id"], "1234")
        self.assertEqual(comparable["artist"], "Joan Miró")
        self.assertEqual(comparable["medium"], "Lithograph in colors")
        self.assertEqual(comparable["edition"], "25/100")
        self.assertEqual(comparable["size"], "50 x 40 cm")
        self.assertEqual(comparable["provider_url"], f"https://www.artprice.com{source_path}")
        combined = self.client.get(
            reverse("auction_lot_liveart_analysis", args=(self.lot.pk,))
        ).json()["analysis"]
        candidate = next(item for item in combined["candidates"] if item["provider"] == "Artprice")
        self.assertEqual(candidate["hammer_usd"], "4200.00")
        self.assertEqual(candidate["source_url"], f"https://www.artprice.com{source_path}")
        self.assertNotEqual(candidate["hammer_usd"], "5334.00")

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
        self.assertIn("results data", missing_marker.json()["error"].lower())

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


class AuctionLiveArtAnalysisViewTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user(
            "liveart-admin", password="test-pass", is_staff=True
        )
        self.lot = watch_lot()
        self.research_url = reverse("auction_lot_liveart_research", args=(self.lot.pk,))
        self.analysis_url = reverse("auction_lot_liveart_analysis", args=(self.lot.pk,))
        self.subject = liveart_artwork()
        self.comp = liveart_lot(
            "sold-comp",
            sale_id="sale-2025",
            lot_num="72",
            sale_date="2025-06-12T12:00:00-04:00",
            hammer_usd=1205,
            original_hammer=1000,
            currency="EUR",
        )
        self.comp["artwork_id"] = self.subject["id"]
        self.comp["artwork"]["id"] = self.subject["id"]

    def stored_artprice(self, *, hammer="2000.00", title=None):
        analysis = stored_analysis(self.lot, created_by=self.staff)
        analysis.comparables = [{
            "sale_date": "26 Mar 2026",
            "hammer_price": hammer,
            "auction_house": "Dawson's",
            "artist": self.lot.artist,
            "title": title or self.lot.title,
            "lot_number": "42",
            "estimate_low": "1000.00",
            "estimate_high": "2500.00",
        }]
        analysis.save(update_fields=("comparables",))
        return analysis

    @staticmethod
    def assumptions(**overrides):
        values = {
            "inbound_shipping": "200",
            "target_profit": "100",
            "seller_commission_pct": "10",
            "outbound_shipping": "50",
            "other_resale_costs": "25",
            "premium_min": "23",
            "premium_max": "25",
        }
        values.update(overrides)
        return values

    def mock_client(self, client_class, *, lots=None):
        client = client_class.return_value
        client.get_usage.return_value = {"data_units_remaining": 990}
        client.list_artists.return_value = liveart_page([{"id": "artist-miro", "name": "Joan Miró"}])
        client.list_artworks.return_value = liveart_page([self.subject])
        client.list_lots.return_value = liveart_page([self.comp] if lots is None else lots)
        return client

    def save(self, selected_ids, *, research_id=None, **assumption_overrides):
        payload = {
            "action": "save",
            "selected_ids": selected_ids,
            "assumptions": self.assumptions(**assumption_overrides),
        }
        if research_id is not None:
            payload["research_id"] = research_id
        return self.client.post(
            self.analysis_url,
            data=json.dumps(payload),
            content_type="application/json",
        )

    def research(self, **payload):
        return self.client.post(
            self.research_url,
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_research_and_saved_analysis_are_staff_only_and_calendar_never_calls_liveart(self):
        with patch("secondstateapp.calendar_views.LiveArtClient") as client_class:
            for endpoint, method in (
                (self.research_url, "post"),
                (self.analysis_url, "get"),
                (self.analysis_url, "post"),
            ):
                with self.subTest(endpoint=endpoint, method=method):
                    response = getattr(self.client, method)(endpoint)
                    self.assertEqual(response.status_code, 302)
                    self.assertIn("login", response.url)

            ordinary = get_user_model().objects.create_user("liveart-reader", password="test-pass")
            self.client.force_login(ordinary)
            for endpoint, method in (
                (self.research_url, "post"),
                (self.analysis_url, "get"),
                (self.analysis_url, "post"),
            ):
                with self.subTest(endpoint=endpoint, method=method):
                    response = getattr(self.client, method)(endpoint)
                    self.assertEqual(response.status_code, 302)
                    self.assertIn("login", response.url)

            self.client.force_login(self.staff)
            calendar = self.client.get(reverse("auction_calendar"), {"month": "2026-07"})
            self.assertEqual(calendar.status_code, 200)
            detail = calendar.context["calendar_data"]["2026-07-25"][0]
            self.assertEqual(detail["liveart_research_url"], self.research_url)
            self.assertEqual(detail["liveart_analysis_url"], self.analysis_url)
            self.assertNotIn("candidates", detail)
            self.assertNotIn("subject_match", detail)
            self.assertEqual(self.client.get(self.analysis_url).json(), {"ok": True, "analysis": None})
            client_class.assert_not_called()

    def test_research_finds_artwork_without_auction_match_and_shows_verified_hammers(self):
        missing_hammer = liveart_lot(
            "missing-hammer",
            sale_id="sale-2024",
            sale_date="2024-03-02T12:00:00-05:00",
            hammer_usd=None,
            original_hammer=3200,
            currency="GBP",
        )
        different_artist = liveart_lot(
            "different-artist",
            sale_id="sale-2023",
            sale_date="2023-02-01T12:00:00-05:00",
            artist_id="artist-other",
            artist="Other Artist",
            hammer_usd=9000,
        )
        self.client.force_login(self.staff)
        with patch("secondstateapp.calendar_views.LiveArtClient") as client_class:
            client = self.mock_client(
                client_class,
                lots=[self.comp, missing_hammer, different_artist],
            )
            client.list_artworks.return_value = liveart_page(
                [self.subject], data_units=Decimal("3.5")
            )
            response = self.research()

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["subject_match"]["id"], "artwork-miro")
        candidates = {item["id"]: item for item in payload["candidates"]}
        self.assertIn("sold-comp", candidates)
        self.assertTrue(candidates["sold-comp"]["credible"])
        self.assertEqual(candidates["sold-comp"]["match_type"], "exact_work")
        self.assertEqual(candidates["sold-comp"]["hammer_usd"], "1205.00")
        self.assertEqual(candidates["sold-comp"]["original_currency"], "EUR")
        self.assertEqual(candidates["sold-comp"]["original_hammer"], "1000")
        self.assertEqual(candidates["sold-comp"]["provider_id"], "sold-comp")
        self.assertEqual(candidates["sold-comp"]["lot_url"], "https://www.liveart.ai/lot/sold-comp")
        self.assertEqual(candidates["sold-comp"]["edition"], "25/100")
        self.assertEqual(candidates["sold-comp"]["signature"], "signed (method unspecified)")
        self.assertEqual(candidates["sold-comp"]["size"], "50 × 40 cm")
        self.assertEqual(
            set(candidates["sold-comp"]["differences"]),
            {"medium", "edition", "signature", "size", "condition"},
        )
        self.assertNotEqual(candidates["sold-comp"]["hammer_usd"], "1000.00")
        self.assertFalse(candidates["missing-hammer"]["credible"])
        self.assertIsNone(candidates["missing-hammer"]["hammer_usd"])
        self.assertIn("hammer_usd", candidates["missing-hammer"]["missing_data"])
        self.assertFalse(candidates.get("different-artist", {}).get("credible", False))
        self.assertTrue(payload["retrieved_at"])
        self.assertEqual(payload["data_units_spent"], 12.5)
        client.list_sales.assert_not_called()
        client.list_artists.assert_called_once()
        client.list_artworks.assert_called_once()
        self.assertEqual(client.list_artists.call_args.kwargs["q"], "Joan Miró")
        self.assertEqual(client.list_artworks.call_args.kwargs["search"], self.lot.title)
        self.assertEqual(client.list_artworks.call_args.kwargs["category_id"], 2)
        self.assertLessEqual(client.list_lots.call_count, 2)
        self.assertLessEqual(
            client.list_artists.call_count + client.list_artworks.call_count + client.list_lots.call_count,
            4,
        )
        client.similar.assert_not_called()
        for call in client.list_lots.call_args_list:
            self.assertEqual(call.kwargs["status"], "sold")
            self.assertEqual(call.kwargs["category_id"], 2)
            self.assertLessEqual(call.kwargs["limit"], 10)
            self.assertNotIn("auction_house_id", call.kwargs)
            self.assertNotIn("sale_datetime__gte", call.kwargs)
            self.assertNotIn("lot_num", call.kwargs)
        self.assertTrue(any("artwork_id" in call.kwargs for call in client.list_lots.call_args_list))
        self.assertTrue(any("artist_id" in call.kwargs for call in client.list_lots.call_args_list))
        saved = self.save(["sold-comp"], research_id=payload["research_id"])
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["analysis"]["data_units_spent"], 12.5)
        self.assertEqual(LiveArtResaleAnalysis.objects.get(lot=self.lot).data_units_spent, Decimal("12.5"))

    def test_exact_work_history_and_related_sold_works_are_distinct(self):
        related = liveart_lot(
            "related-print",
            sale_id="sale-2024",
            lot_num="417",
            sale_date="2024-05-03T12:00:00-04:00",
            title="Another butterfly lithograph",
            hammer_usd=1800,
        )
        self.client.force_login(self.staff)
        with patch("secondstateapp.calendar_views.LiveArtClient") as client_class:
            client = self.mock_client(client_class)
            client.list_lots.side_effect = lambda **filters: liveart_page(
                [self.comp] if "artwork_id" in filters else [related]
            )
            response = self.research()

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        candidates = {item["id"]: item for item in payload["candidates"]}
        self.assertEqual(candidates["sold-comp"]["match_type"], "exact_work")
        self.assertEqual(candidates["related-print"]["match_type"], "related_work")
        self.assertTrue(candidates["related-print"]["credible"])
        self.assertFalse(candidates["related-print"]["selected"])
        self.assertEqual(candidates["related-print"]["hammer_usd"], "1800.00")
        self.assertEqual(payload["selected_ids"], ["sold-comp"])

        saved = self.save(["sold-comp", "related-print"], research_id=payload["research_id"])
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(
            saved.json()["analysis"]["selected_ids"], ["sold-comp", "related-print"]
        )
        self.assertEqual(LiveArtResaleAnalysis.objects.count(), 1)

    def test_saved_artprice_html_comp_and_liveart_comp_share_resale_scenarios(self):
        artprice = self.stored_artprice()
        original_artprice_pk = artprice.pk
        original_artprice_comparables = artprice.comparables
        self.client.force_login(self.staff)
        with patch("secondstateapp.calendar_views.LiveArtClient") as client_class:
            self.mock_client(client_class)
            research = self.research()

        self.assertEqual(research.status_code, 200)
        payload = research.json()
        artprice_candidates = [
            item for item in payload["candidates"] if item["provider"] == "Artprice"
        ]
        self.assertEqual(len(artprice_candidates), 1)
        artprice_comp = artprice_candidates[0]
        self.assertTrue(artprice_comp["id"].startswith("artprice:"))
        self.assertEqual(artprice_comp["match_type"], "artprice_html")
        self.assertEqual(artprice_comp["source_filename"], "saved-results.html")
        self.assertIsNone(artprice_comp["source_url"])
        self.assertEqual(artprice_comp["hammer_usd"], "2000.00")
        self.assertEqual(artprice_comp["status"], "sold")
        self.assertTrue(artprice_comp["credible"])
        self.assertTrue(artprice_comp["selected"])
        self.assertIn(artprice_comp["id"], payload["selected_ids"])
        self.assertIn("sold-comp", {item["id"] for item in payload["candidates"]})

        saved = self.save(["sold-comp", artprice_comp["id"]], research_id=payload["research_id"])
        self.assertEqual(saved.status_code, 200)
        combined = saved.json()["analysis"]
        self.assertEqual(combined["selected_ids"], ["sold-comp", artprice_comp["id"]])
        typical = next(item for item in combined["scenarios"] if item["name"] == "typical")
        self.assertEqual(typical["resale_hammer"], "1602.50")
        self.assertEqual(typical["selected_comp_count"], 2)
        self.assertEqual(self.client.get(self.analysis_url).json()["analysis"], combined)
        artprice.refresh_from_db()
        self.assertEqual(artprice.pk, original_artprice_pk)
        self.assertEqual(artprice.comparables, original_artprice_comparables)

    def test_saved_artprice_comp_can_be_selected_without_liveart_request(self):
        artprice = self.stored_artprice()
        self.client.force_login(self.staff)
        with patch("secondstateapp.calendar_views.LiveArtClient") as client_class:
            initial = self.client.get(self.analysis_url)
            self.assertEqual(initial.status_code, 200)
            pool = initial.json()["analysis"]
            artprice_comp = next(
                item for item in pool["candidates"] if item["provider"] == "Artprice"
            )
            self.assertEqual(artprice_comp["hammer_usd"], "2000.00")
            self.assertTrue(artprice_comp["selected"])
            self.assertEqual(pool["source_summary"]["artprice_included_count"], 1)
            self.assertEqual(pool["source_summary"]["artprice_source_filename"], "saved-results.html")
            saved = self.save([artprice_comp["id"]])
            client_class.assert_not_called()

        self.assertEqual(saved.status_code, 200)
        combined = saved.json()["analysis"]
        self.assertEqual(combined["selected_ids"], [artprice_comp["id"]])
        self.assertEqual(
            next(item for item in combined["scenarios"] if item["name"] == "typical")["resale_hammer"],
            "2000.00",
        )
        self.assertEqual(LiveArtResaleAnalysis.objects.get(lot=self.lot).selected_ids, [artprice_comp["id"]])
        artprice.refresh_from_db()
        self.assertEqual(artprice.currency, "USD")
        self.assertEqual(artprice.comparables[0]["hammer_price"], "2000.00")

    def test_legacy_liveart_only_save_shows_existing_artprice_pool_on_get(self):
        self.stored_artprice()
        LiveArtResaleAnalysis.objects.create(
            lot=self.lot,
            subject_match={"id": "artwork-miro", "artwork_id": "artwork-miro"},
            candidates=[{
                "id": "sold-comp",
                "provider": "LiveArt",
                "status": "sold",
                "credible": True,
                "selected": True,
                "hammer_usd": "1205.00",
            }],
            selected_ids=["sold-comp"],
            assumptions=self.assumptions(),
            retrieved_at=datetime(2026, 10, 12, tzinfo=ZoneInfo("UTC")),
            created_by=self.staff,
        )
        self.client.force_login(self.staff)
        with patch("secondstateapp.calendar_views.LiveArtClient") as client_class:
            response = self.client.get(self.analysis_url)
            client_class.assert_not_called()

        self.assertEqual(response.status_code, 200)
        analysis = response.json()["analysis"]
        artprice_comp = next(
            item for item in analysis["candidates"] if item["provider"] == "Artprice"
        )
        self.assertEqual(analysis["selected_ids"], ["sold-comp", artprice_comp["id"]])
        self.assertEqual(
            {item["provider"] for item in analysis["candidates"]},
            {"LiveArt", "Artprice"},
        )
        self.assertTrue(artprice_comp["selected"])
        self.assertEqual(analysis["source_summary"]["artprice_included_count"], 1)
        stored = LiveArtResaleAnalysis.objects.get(lot=self.lot)
        self.assertEqual(stored.selected_ids, analysis["selected_ids"])
        self.assertEqual(stored.source_summary, analysis["source_summary"])

    def test_deliberate_artprice_deselection_survives_get_recalculation_and_research(self):
        self.stored_artprice()
        self.client.force_login(self.staff)
        preview = self.client.get(self.analysis_url).json()["analysis"]
        artprice_id = next(item["id"] for item in preview["candidates"] if item["provider"] == "Artprice")
        self.assertIn(artprice_id, preview["selected_ids"])

        saved = self.save([])
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["analysis"]["selected_ids"], [])
        after_get = self.client.get(self.analysis_url).json()["analysis"]
        self.assertEqual(after_get["selected_ids"], [])
        self.assertEqual(after_get["source_summary"]["artprice_eligible_count"], 1)
        self.assertEqual(after_get["source_summary"]["artprice_selected_count"], 0)
        self.assertEqual(after_get["source_summary"]["artprice_included_count"], 0)

        recalculated = self.client.post(
            reverse("auction_lot_artprice_analysis", args=(self.lot.pk,)),
            {"action": "recalculate", "method": "mean"},
        )
        self.assertEqual(recalculated.status_code, 200)
        self.assertEqual(self.client.get(self.analysis_url).json()["analysis"]["selected_ids"], [])

        with patch("secondstateapp.calendar_views.LiveArtClient") as client_class:
            self.mock_client(client_class)
            research = self.research()
        self.assertEqual(research.status_code, 200)
        self.assertNotIn(artprice_id, research.json()["selected_ids"])
        self.assertEqual(self.save(research.json()["selected_ids"], research_id=research.json()["research_id"]).status_code, 200)
        refreshed = self.client.get(self.analysis_url).json()["analysis"]
        self.assertNotIn(artprice_id, refreshed["selected_ids"])
        self.assertEqual(refreshed["source_summary"]["artprice_included_count"], 0)

    def test_legacy_partial_artprice_selection_is_preserved(self):
        artprice = self.stored_artprice()
        artprice.comparables.append({
            **artprice.comparables[0], "sale_date": "25 Mar 2026", "hammer_price": "2500.00", "lot_number": "43",
        })
        artprice.sold_records_count = 2
        artprice.save(update_fields=("comparables", "sold_records_count"))
        self.client.force_login(self.staff)
        preview = self.client.get(self.analysis_url).json()["analysis"]
        first_id = preview["candidates"][0]["id"]
        LiveArtResaleAnalysis.objects.create(
            lot=self.lot,
            candidates=preview["candidates"],
            selected_ids=[first_id],
            assumptions=self.assumptions(),
            retrieved_at=datetime(2026, 10, 12, tzinfo=ZoneInfo("UTC")),
            created_by=self.staff,
        )
        saved = self.client.get(self.analysis_url).json()["analysis"]
        self.assertEqual(saved["selected_ids"], [first_id])
        self.assertEqual(saved["source_summary"]["artprice_eligible_count"], 2)
        self.assertEqual(saved["source_summary"]["artprice_selected_count"], 1)

    def test_default_artprice_selection_respects_existing_25_comp_limit(self):
        liveart = [
            {"id": f"live-{index}", "provider": "LiveArt", "status": "sold", "credible": True}
            for index in range(25)
        ]
        artprice = {
            "id": "artprice:one", "provider": "Artprice", "status": "sold", "credible": True,
            "artist": self.lot.artist,
        }
        selected = _selected_resale_ids(
            [*liveart, artprice], [item["id"] for item in liveart], initialize_artprice=True,
        )
        self.assertEqual(len(selected), 25)
        self.assertNotIn(artprice["id"], selected)

    def test_missing_artprice_artist_requires_manual_selection(self):
        artprice = self.stored_artprice()
        artprice.comparables[0].pop("artist")
        artprice.save(update_fields=("comparables",))
        self.client.force_login(self.staff)
        preview = self.client.get(self.analysis_url).json()["analysis"]
        candidate = next(item for item in preview["candidates"] if item["provider"] == "Artprice")
        self.assertTrue(candidate["credible"])
        self.assertEqual(preview["selected_ids"], [])
        self.assertEqual(preview["source_summary"]["artprice_eligible_count"], 0)
        saved = self.save([candidate["id"]])
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["analysis"]["source_summary"]["artprice_included_count"], 1)

    def test_extreme_saved_hammer_preview_explains_unestimable_bid(self):
        self.stored_artprice(hammer="1000000000000.00")
        self.client.force_login(self.staff)
        response = self.client.get(self.analysis_url)
        self.assertEqual(response.status_code, 200)
        preview = response.json()["analysis"]
        self.assertEqual(preview["scenarios"], [])
        self.assertIn("supported range", preview["source_summary"]["calculation_error"])
        self.assertEqual(self.save(preview["selected_ids"]).status_code, 400)

    def test_artprice_upload_and_recalculation_roll_back_if_resale_refresh_fails(self):
        artprice = self.stored_artprice()
        original_comparables = artprice.comparables
        self.client.force_login(self.staff)
        with patch(
            "secondstateapp.calendar_views._refresh_saved_resale_from_artprice",
            side_effect=ArtpriceAnalysisError("Combined resale calculation failed."),
        ):
            upload = self.client.post(
                reverse("auction_lot_artprice_analysis", args=(self.lot.pk,)),
                {"action": "analyze", "artprice_html": artprice_upload(
                    "replacement.html", lots=[{
                        "id": "replacement", "title": self.lot.title, "price": "$ 3,000",
                        "saleDtStart": "4 Apr 2026", "auctioneerName": "Replacement House",
                        "artistOrAssociation": self.lot.artist, "lotstatus": 1,
                    }],
                )},
            )
            recalculate = self.client.post(
                reverse("auction_lot_artprice_analysis", args=(self.lot.pk,)),
                {"action": "recalculate", "method": "mean"},
            )
        self.assertEqual(upload.status_code, 400)
        self.assertEqual(recalculate.status_code, 400)
        artprice.refresh_from_db()
        self.assertEqual(artprice.comparables, original_comparables)
        self.assertEqual(artprice.source_filename, "saved-results.html")
        self.assertEqual(artprice.resale_method, "median")

    def test_non_usd_or_missing_artprice_hammer_cannot_enter_scenarios(self):
        artprice = self.stored_artprice()
        self.client.force_login(self.staff)
        with patch("secondstateapp.calendar_views.LiveArtClient") as client_class:
            for currency, hammer in (("EUR", "2000.00"), ("USD", None), ("USD", "-5"), ("USD", "NaN")):
                with self.subTest(currency=currency, hammer=hammer):
                    artprice.currency = currency
                    artprice.comparables[0]["hammer_price"] = hammer
                    artprice.comparables[0]["priceWithTaxes"] = "9999.00"
                    artprice.save(update_fields=("currency", "comparables"))
                    response = self.client.get(self.analysis_url)
                    self.assertEqual(response.status_code, 200)
                    analysis = response.json()["analysis"]
                    candidates = analysis["candidates"] if analysis else []
                    self.assertFalse(any(
                        item["provider"] == "Artprice" and item["credible"]
                        for item in candidates
                    ))
                    self.assertEqual(analysis["scenarios"] if analysis else [], [])
                    for candidate in candidates:
                        if candidate["provider"] == "Artprice":
                            self.assertEqual(self.save([candidate["id"]]).status_code, 400)
            client_class.assert_not_called()

    def test_artprice_artist_conflict_and_unsafe_link_are_review_only(self):
        artprice = self.stored_artprice()
        artprice.comparables[0]["artist"] = "Other Artist"
        artprice.comparables[0]["provider_url"] = "https://evil.example/artist/1/lot"
        artprice.save(update_fields=("comparables",))
        self.client.force_login(self.staff)

        response = self.client.get(self.analysis_url)

        self.assertEqual(response.status_code, 200)
        candidate = next(
            item for item in response.json()["analysis"]["candidates"]
            if item["provider"] == "Artprice"
        )
        self.assertFalse(candidate["credible"])
        self.assertIsNone(candidate["source_url"])
        self.assertIn("Artprice artist differs", " ".join(candidate["exclusion_reasons"]))
        self.assertEqual(self.save([candidate["id"]]).status_code, 400)
        self.assertFalse(LiveArtResaleAnalysis.objects.exists())

    def test_replacing_artprice_html_removes_stale_selected_comp(self):
        artprice = self.stored_artprice()
        self.client.force_login(self.staff)
        first_pool = self.client.get(self.analysis_url).json()["analysis"]
        old_id = next(
            item["id"] for item in first_pool["candidates"] if item["provider"] == "Artprice"
        )
        self.assertEqual(self.save([old_id]).status_code, 200)
        original_artprice_pk = artprice.pk

        replacement = artprice_upload("replacement.html", lots=[{
            "id": "new-sale",
            "title": self.lot.title,
            "price": "$ 3,000",
            "saleDtStart": "4 Apr 2026",
            "auctioneerName": "Replacement House",
            "artistOrAssociation": self.lot.artist,
            "lotstatus": 1,
        }])
        with patch("secondstateapp.calendar_views.LiveArtClient") as client_class:
            uploaded = self.client.post(
                reverse("auction_lot_artprice_analysis", args=(self.lot.pk,)),
                {"action": "analyze", "artprice_html": replacement},
            )
            refreshed = self.client.get(self.analysis_url)
            client_class.assert_not_called()

        self.assertEqual(uploaded.status_code, 200)
        self.assertEqual(refreshed.status_code, 200)
        combined = refreshed.json()["analysis"]
        new_comp = next(
            item for item in combined["candidates"] if item["provider"] == "Artprice"
        )
        self.assertNotEqual(new_comp["id"], old_id)
        self.assertEqual(new_comp["hammer_usd"], "3000.00")
        self.assertNotIn(old_id, {item["id"] for item in combined["candidates"]})
        self.assertNotIn(old_id, combined["selected_ids"])
        self.assertIn(new_comp["id"], combined["selected_ids"])
        self.assertEqual(combined["source_summary"]["artprice_included_count"], 1)
        self.assertEqual(
            next(item for item in combined["scenarios"] if item["name"] == "typical")["resale_hammer"],
            "3000.00",
        )
        artprice.refresh_from_db()
        self.assertEqual(artprice.pk, original_artprice_pk)
        self.assertEqual(artprice.comparables[0]["hammer_price"], "3000.00")

        self.assertEqual(self.save([new_comp["id"]]).status_code, 200)
        recalculated = self.client.post(
            reverse("auction_lot_artprice_analysis", args=(self.lot.pk,)),
            {"action": "recalculate", "method": "mean"},
        )
        self.assertEqual(recalculated.status_code, 200)
        after_recalculate = self.client.get(self.analysis_url).json()["analysis"]
        self.assertEqual(after_recalculate["selected_ids"], [new_comp["id"]])
        self.assertEqual(
            next(item for item in after_recalculate["scenarios"] if item["name"] == "typical")["resale_hammer"],
            "3000.00",
        )

        deleted = self.client.post(
            reverse("auction_lot_artprice_analysis", args=(self.lot.pk,)),
            {"action": "delete"},
        )
        self.assertEqual(deleted.status_code, 200)
        after_delete = self.client.get(self.analysis_url).json()["analysis"]
        self.assertEqual(after_delete["selected_ids"], [])
        self.assertFalse(any(item["provider"] == "Artprice" for item in after_delete["candidates"]))
        self.assertEqual(after_delete["scenarios"], [])
        self.assertFalse(AuctionMaxBidAnalysis.objects.filter(lot=self.lot).exists())

    def test_related_sales_remain_available_when_exact_artwork_is_missing(self):
        related = liveart_lot(
            "related-only",
            sale_id="sale-2024",
            sale_date="2024-02-01T12:00:00-05:00",
            title="Butterfly composition",
            hammer_usd=1700,
        )
        self.client.force_login(self.staff)
        with patch("secondstateapp.calendar_views.LiveArtClient") as client_class:
            client = self.mock_client(client_class)
            client.list_artworks.return_value = liveart_page([])
            client.list_lots.return_value = liveart_page([related])
            response = self.research()

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIsNone(payload["subject_match"])
        self.assertEqual(payload["subject_matches"], [])
        self.assertEqual(payload["candidates"][0]["match_type"], "related_work")
        self.assertEqual(payload["candidates"][0]["hammer_usd"], "1700.00")
        self.assertEqual(payload["selected_ids"], [])

    def test_research_only_needs_calendar_artist_and_title(self):
        self.lot.auction_house = ""
        self.lot.event_at = None
        self.lot.lot_number = ""
        self.lot.save(update_fields=("auction_house", "event_at", "lot_number"))
        self.client.force_login(self.staff)
        with patch("secondstateapp.calendar_views.LiveArtClient") as client_class:
            client = self.mock_client(client_class)
            response = self.research()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["subject_match"]["id"], "artwork-miro")
        self.assertEqual(response.json()["candidates"][0]["id"], "sold-comp")
        for call in client.list_lots.call_args_list:
            self.assertNotIn("lot_num", call.kwargs)
            self.assertNotIn("sale_datetime__gte", call.kwargs)

    def test_research_matches_artist_when_calendar_name_contains_birth_year(self):
        self.lot.artist = "Alexander (1898) Calder"
        self.lot.artist_watchlist_name = "Alexander Calder"
        self.lot.title = "Nez et oreilles tres gais"
        self.lot.save(update_fields=("artist", "artist_watchlist_name", "title"))
        artwork = liveart_artwork(
            "calder-artwork", artist_id="artist-calder", artist="Alexander Calder",
            title=self.lot.title,
        )
        sale = liveart_lot(
            "calder-sale", artist_id="artist-calder", artist="Alexander Calder",
            title=self.lot.title, hammer_usd=3600,
        )
        sale["artwork_id"] = artwork["id"]
        sale["artwork"]["id"] = artwork["id"]
        self.client.force_login(self.staff)
        with patch("secondstateapp.calendar_views.LiveArtClient") as client_class:
            client = self.mock_client(client_class, lots=[sale])
            client.list_artists.return_value = liveart_page([
                {"id": "artist-unrelated", "name": "Alexander Smith"},
                {"id": "artist-calder", "name": "Alexander Calder"},
            ])
            client.list_artworks.return_value = liveart_page([artwork])
            response = self.research()

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["subject_match"]["id"], artwork["id"])
        self.assertEqual(payload["candidates"][0]["id"], sale["id"])
        self.assertTrue(payload["candidates"][0]["credible"])
        self.assertEqual(payload["candidates"][0]["hammer_usd"], "3600.00")
        client.list_artists.assert_called_once_with(q="Alexander Calder", limit=3)
        client.list_artworks.assert_called_once_with(
            artist_id="artist-calder", search=self.lot.title, category_id=2, limit=5,
        )

    def test_research_does_not_accept_unrelated_artist_with_year_in_calendar_name(self):
        self.lot.artist = "Alexander (1898) Calder"
        self.lot.artist_watchlist_name = "Alexander Calder"
        self.lot.save(update_fields=("artist", "artist_watchlist_name"))
        self.client.force_login(self.staff)
        with patch("secondstateapp.calendar_views.LiveArtClient") as client_class:
            client = self.mock_client(client_class)
            client.list_artists.return_value = liveart_page([
                {"id": "artist-unrelated", "name": "Alexander Smith"},
            ])
            response = self.research()

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIsNone(payload["subject_match"])
        self.assertEqual(payload["candidates"], [])
        self.assertIn("No LiveArt artist matched", payload["message"])
        client.list_artworks.assert_not_called()
        client.list_lots.assert_not_called()

    def test_research_can_search_translated_title_and_verify_original_title(self):
        self.lot.artist = "Alexander (1898) Calder"
        self.lot.artist_watchlist_name = "Alexander Calder"
        self.lot.title = "Nez et oreilles tres gais"
        self.lot.save(update_fields=("artist", "artist_watchlist_name", "title"))
        artwork = liveart_artwork(
            "calder-artwork", artist_id="artist-calder", artist="Alexander Calder",
            title="Nez et oreilles tres gais",
        )
        self.client.force_login(self.staff)
        with patch("secondstateapp.calendar_views.LiveArtClient") as client_class:
            client = self.mock_client(client_class, lots=[])
            client.list_artists.return_value = liveart_page([
                {"id": "artist-calder", "name": "Alexander Calder"},
            ])
            client.list_artworks.return_value = liveart_page([artwork])
            response = self.research(search_title="Very Gay Nose and Ears")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["subject_match"]["id"], artwork["id"])
        client.list_artworks.assert_called_once_with(
            artist_id="artist-calder", search="Very Gay Nose and Ears", category_id=2, limit=5,
        )

    def test_research_verifies_french_title_in_bilingual_liveart_artwork(self):
        self.lot.artist = "Alexander (1898) Calder"
        self.lot.title = "Nez et oreilles tres gais"
        self.lot.save(update_fields=("artist", "title"))
        artwork = liveart_artwork(
            "calder-bilingual", artist_id="artist-calder", artist="Alexander Calder",
            title="Nez et oreilles très gais (Very Gay Nose and Ears)",
        )
        self.client.force_login(self.staff)
        with patch("secondstateapp.calendar_views.LiveArtClient") as client_class:
            client = self.mock_client(client_class, lots=[])
            client.list_artists.return_value = liveart_page([
                {"id": "artist-calder", "name": "Alexander Calder"},
            ])
            client.list_artworks.return_value = liveart_page([artwork])
            response = self.research(search_title="Very Gay Nose and Ears")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["subject_match"]["id"], artwork["id"])
        self.assertEqual(response.json()["subject_match"]["matched_title"], self.lot.title)

    def test_damaged_french_title_needs_manual_choice_before_history_is_used(self):
        self.lot.artist = "Alexander (1898) Calder"
        self.lot.title = "Nez et oreilles tres gais"
        self.lot.save(update_fields=("artist", "title"))
        damaged_title = "Nez et oreilles tr\ufffds gais (Very Gay Nose and Ears)"
        artwork = liveart_artwork(
            "calder-damaged", artist_id="artist-calder", artist="Alexander Calder",
            title=damaged_title,
        )
        sale = liveart_lot(
            "calder-damaged-sale", artist_id="artist-calder", artist="Alexander Calder",
            title=damaged_title, hammer_usd=3600,
        )
        sale["artwork_id"] = artwork["id"]
        sale["artwork"]["id"] = artwork["id"]
        self.client.force_login(self.staff)
        with patch("secondstateapp.calendar_views.LiveArtClient") as client_class:
            client = self.mock_client(client_class, lots=[sale])
            client.list_artists.return_value = liveart_page([
                {"id": "artist-calder", "name": "Alexander Calder"},
            ])
            client.list_artworks.return_value = liveart_page([artwork])
            first = self.research(search_title="Very Gay Nose and Ears")
            self.assertEqual(first.status_code, 200)
            first_payload = first.json()
            self.assertIsNone(first_payload["subject_match"])
            self.assertTrue(first_payload["requires_subject_choice"])
            self.assertFalse(first_payload["subject_matches"][0]["verified"])
            self.assertTrue(first_payload["subject_matches"][0]["can_choose"])
            self.assertFalse(any(
                call.kwargs.get("artwork_id") == artwork["id"]
                for call in client.list_lots.call_args_list
            ))

            chosen = self.research(
                search_title="Very Gay Nose and Ears", subject_id=artwork["id"],
            )

        self.assertEqual(chosen.status_code, 200)
        payload = chosen.json()
        self.assertTrue(payload["subject_match"]["chosen_manually"])
        self.assertFalse(payload["subject_match"]["verified"])
        self.assertEqual(payload["candidates"][0]["id"], sale["id"])
        self.assertEqual(payload["candidates"][0]["hammer_usd"], "3600.00")
        self.assertFalse(payload["candidates"][0]["selected"])
        self.assertEqual(payload["selected_ids"], [])
        self.assertTrue(any(
            call.kwargs.get("artwork_id") == artwork["id"]
            for call in client.list_lots.call_args_list
        ))

    def test_search_title_does_not_verify_an_unrelated_artwork(self):
        self.lot.artist = "Alexander (1898) Calder"
        self.lot.title = "Nez et oreilles tres gais"
        self.lot.save(update_fields=("artist", "title"))
        sale = liveart_lot(
            "blue-dots-sale", artist_id="artist-calder", artist="Alexander Calder",
            title="Blue Dots", hammer_usd=2400,
        )
        sale["artwork_id"] = "unrelated-work"
        sale["artwork"]["id"] = "unrelated-work"
        self.client.force_login(self.staff)
        with patch("secondstateapp.calendar_views.LiveArtClient") as client_class:
            client = self.mock_client(client_class, lots=[sale])
            client.list_artists.return_value = liveart_page([
                {"id": "artist-calder", "name": "Alexander Calder"},
            ])
            client.list_artworks.return_value = liveart_page([
                liveart_artwork(
                    "unrelated-work", artist_id="artist-calder", artist="Alexander Calder",
                    title="Blue Dots",
                ),
            ])
            response = self.research(search_title="Blue Dots")
            chosen = self.research(search_title="Blue Dots", subject_id="unrelated-work")

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["subject_match"])
        self.assertFalse(response.json()["subject_matches"][0]["verified"])
        self.assertTrue(response.json()["subject_matches"][0]["can_choose"])
        self.assertTrue(response.json()["requires_subject_choice"])
        self.assertEqual(response.json()["selected_ids"], [])
        self.assertEqual(chosen.status_code, 200)
        chosen_payload = chosen.json()
        self.assertTrue(chosen_payload["subject_match"]["chosen_manually"])
        self.assertFalse(chosen_payload["subject_match"]["verified"])
        self.assertEqual(chosen_payload["candidates"][0]["match_type"], "exact_work")
        self.assertFalse(chosen_payload["candidates"][0]["selected"])
        self.assertEqual(chosen_payload["selected_ids"], [])
        self.assertTrue(any(
            call.kwargs.get("artwork_id") == "unrelated-work"
            for call in client.list_lots.call_args_list
        ))

    def test_multiple_matching_artworks_can_be_chosen_for_exact_history(self):
        alternative = liveart_artwork("another-impression")
        self.client.force_login(self.staff)
        with patch("secondstateapp.calendar_views.LiveArtClient") as client_class:
            client = self.mock_client(client_class)
            client.list_artworks.return_value = liveart_page([self.subject, alternative])
            first = self.research()
            self.assertEqual(first.status_code, 200)
            self.assertTrue(first.json()["requires_subject_choice"])
            self.assertIsNone(first.json()["subject_match"])
            self.assertEqual(len(first.json()["subject_matches"]), 2)
            self.assertIn("sold-comp", {item["id"] for item in first.json()["candidates"]})

            chosen = self.research(subject_id="artwork-miro")
            self.assertEqual(chosen.status_code, 200)
            self.assertEqual(chosen.json()["subject_match"]["id"], "artwork-miro")
            self.assertTrue(any(
                call.kwargs.get("artwork_id") == "artwork-miro"
                for call in client.list_lots.call_args_list
            ))
            rejected = self.research(subject_id="unknown-artwork")
            self.assertEqual(rejected.status_code, 400)

    def test_research_rejects_missing_artist_or_title_without_api_calls(self):
        self.client.force_login(self.staff)
        original = {
            "artist": self.lot.artist,
            "artist_watchlist_name": self.lot.artist_watchlist_name,
            "title": self.lot.title,
        }
        with patch("secondstateapp.calendar_views.LiveArtClient") as client_class:
            for fields in ({"artist": "", "artist_watchlist_name": ""}, {"title": ""}):
                with self.subTest(fields=fields):
                    for name, value in original.items():
                        setattr(self.lot, name, value)
                    for name, value in fields.items():
                        setattr(self.lot, name, value)
                    self.lot.save(update_fields=list(original))
                    response = self.research()
                    self.assertEqual(response.status_code, 400)
            client_class.assert_not_called()

    def test_unrelated_artwork_is_not_verified_or_usable_as_comp(self):
        wrong_lot = liveart_lot("wrong-lot", lot_num="999", artist="Other Artist")
        self.client.force_login(self.staff)
        with patch("secondstateapp.calendar_views.LiveArtClient") as client_class:
            client = self.mock_client(client_class, lots=[wrong_lot])
            client.list_artworks.return_value = liveart_page(
                [liveart_artwork(
                    "wrong-artwork", artist_id="artist-other",
                    artist="Other Artist", title="Other Work",
                )]
            )
            response = self.research()

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIsNone(payload["subject_match"])
        self.assertFalse(any(item["credible"] for item in payload["candidates"]))
        self.assertFalse(payload["subject_matches"][0]["verified"])

    @patch.dict(os.environ, {"LIVEART_API_KEY": ""}, clear=False)
    def test_missing_api_key_fails_without_requesting_liveart(self):
        self.client.force_login(self.staff)
        with patch("secondstateapp.liveart_client.requests.Session") as session_class:
            response = self.research()

        self.assertEqual(response.status_code, 503)
        self.assertIn("LIVEART_API_KEY", response.json()["error"])
        session_class.assert_not_called()
        self.assertFalse(LiveArtResaleAnalysis.objects.exists())

    def test_rate_limit_returns_retry_after_without_mutating_saved_analysis(self):
        self.client.force_login(self.staff)
        with patch("secondstateapp.calendar_views.LiveArtClient") as client_class:
            client = self.mock_client(client_class)
            failure = LiveArtAPIError(
                "LiveArt rate limit reached; please try again later.",
                status_code=429,
                retry_after=3,
            )
            client.list_sales.side_effect = failure
            client.list_lots.side_effect = failure
            response = self.research()

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response["Retry-After"], "3")
        self.assertFalse(LiveArtResaleAnalysis.objects.exists())

    def test_selected_comps_save_independently_of_artprice_and_recalculate_without_api(self):
        self.client.force_login(self.staff)
        artprice = stored_analysis(self.lot, created_by=self.staff)
        original_artprice_pk = artprice.pk
        original_artprice_comps = artprice.comparables

        with patch("secondstateapp.calendar_views.LiveArtClient") as client_class:
            client = self.mock_client(client_class)
            research = self.research()
            self.assertEqual(research.status_code, 200)
            initial_request_count = client.list_lots.call_count
            saved = self.save(["sold-comp"])
            self.assertEqual(client.list_lots.call_count, initial_request_count)

        self.assertEqual(saved.status_code, 200)
        analysis = saved.json()["analysis"]
        self.assertEqual(analysis["selected_ids"], ["sold-comp"])
        self.assertFalse(analysis["no_credible_comps"])
        self.assertEqual(len(analysis["scenarios"]), 3)
        self.assertEqual(
            {item["name"] for item in analysis["scenarios"]},
            {"downside", "typical", "upside"},
        )
        scenarios = {item["name"]: item for item in analysis["scenarios"]}
        self.assertEqual(
            [scenarios[name]["resale_hammer"] for name in ("downside", "typical", "upside")],
            ["964.00", "1205.00", "1325.50"],
        )
        self.assertEqual(scenarios["typical"]["bid_rows"][0], {
            "premium_pct": 23,
            "break_even_max_bid": "658.13",
            "target_profit_max_bid": "576.83",
        })
        self.assertIn("estimates", scenarios["typical"]["estimate_notice"])
        liveart = LiveArtResaleAnalysis.objects.get(lot=self.lot)
        self.assertEqual(liveart.created_by, self.staff)
        artprice.refresh_from_db()
        self.assertEqual(artprice.pk, original_artprice_pk)
        self.assertEqual(artprice.comparables, original_artprice_comps)
        self.assertEqual(AuctionMaxBidAnalysis.objects.count(), 1)
        self.assertEqual(self.client.get(self.analysis_url).json()["analysis"], analysis)

        self.lot.artprice_url = "https://www.artprice.com/artist/1/example/lots/pasts"
        self.lot.save(update_fields=("artprice_url",))
        self.client.post(
            reverse("auction_email_lot_selection", args=(self.lot.pk,)),
            {"selected": "true"},
        )
        tray = self.client.get(reverse("auction_email_tray"))
        self.assertEqual(tray.status_code, 200)
        self.assertNotContains(tray, "sold-comp")
        self.assertNotContains(tray, "www.liveart.ai")

        recalculated = self.save(["sold-comp"], inbound_shipping="100", target_profit="250")
        self.assertEqual(recalculated.status_code, 200)
        liveart.refresh_from_db()
        self.assertEqual(LiveArtResaleAnalysis.objects.get(lot=self.lot).pk, liveart.pk)
        self.assertEqual(recalculated.json()["analysis"]["assumptions"]["target_profit"], "250.00")
        artprice.refresh_from_db()
        self.assertEqual(artprice.comparables, original_artprice_comps)

    def test_research_id_rejects_stale_snapshot_and_saves_current_snapshot(self):
        replacement = liveart_lot(
            "replacement-comp",
            sale_id="sale-2024",
            lot_num="82",
            sale_date="2024-04-12T12:00:00-04:00",
            hammer_usd=2000,
        )
        self.client.force_login(self.staff)
        with patch("secondstateapp.calendar_views.LiveArtClient") as client_class:
            client = self.mock_client(client_class)
            first = self.research()
            self.assertEqual(first.status_code, 200)
            client.list_lots.return_value = liveart_page([replacement])
            second = self.research()
            self.assertEqual(second.status_code, 200)

        first_id = first.json()["research_id"]
        second_id = second.json()["research_id"]
        self.assertNotEqual(first_id, second_id)
        stale = self.save(["sold-comp"], research_id=first_id)
        self.assertEqual(stale.status_code, 409)
        self.assertFalse(LiveArtResaleAnalysis.objects.exists())

        current = self.save(["replacement-comp"], research_id=second_id)
        self.assertEqual(current.status_code, 200)
        analysis = current.json()["analysis"]
        self.assertEqual(analysis["selected_ids"], ["replacement-comp"])
        self.assertEqual(
            next(item for item in analysis["scenarios"] if item["name"] == "typical")["resale_hammer"],
            "2000.00",
        )
        self.assertEqual(LiveArtResaleAnalysis.objects.get(lot=self.lot).selected_ids, ["replacement-comp"])

    def test_reload_edit_without_research_id_uses_saved_snapshot(self):
        replacement = liveart_lot(
            "unsaved-comp",
            sale_id="sale-2024",
            lot_num="82",
            sale_date="2024-04-12T12:00:00-04:00",
            hammer_usd=9000,
        )
        self.client.force_login(self.staff)
        with patch("secondstateapp.calendar_views.LiveArtClient") as client_class:
            client = self.mock_client(client_class)
            first = self.research()
            self.assertEqual(first.status_code, 200)
            saved = self.save(["sold-comp"], research_id=first.json()["research_id"])
            self.assertEqual(saved.status_code, 200)

            client.list_lots.return_value = liveart_page([replacement])
            unsaved = self.research()
            self.assertEqual(unsaved.status_code, 200)
            self.assertIn("unsaved-comp", {item["id"] for item in unsaved.json()["candidates"]})

        edited = self.save(["sold-comp"], target_profit="250")
        self.assertEqual(edited.status_code, 200)
        analysis = edited.json()["analysis"]
        self.assertEqual(analysis["selected_ids"], ["sold-comp"])
        self.assertEqual({item["id"] for item in analysis["candidates"]}, {"sold-comp"})
        self.assertEqual(
            next(item for item in analysis["scenarios"] if item["name"] == "typical")["resale_hammer"],
            "1205.00",
        )
        self.assertEqual(analysis["assumptions"]["target_profit"], "250.00")

    def test_unknown_data_units_stay_unknown_and_private_responses_are_not_cached(self):
        self.client.force_login(self.staff)
        empty_analysis = self.client.get(self.analysis_url)
        self.assertEqual(empty_analysis.status_code, 200)
        self.assertIn("no-store", empty_analysis["Cache-Control"])

        with patch("secondstateapp.calendar_views.LiveArtClient") as client_class:
            client = self.mock_client(client_class)
            client.list_lots.return_value = liveart_page([self.comp], data_units=None)
            research = self.research()

        self.assertEqual(research.status_code, 200)
        self.assertIn("no-store", research["Cache-Control"])
        self.assertIsNone(research.json()["data_units_spent"])
        saved = self.save(["sold-comp"], research_id=research.json()["research_id"])
        self.assertEqual(saved.status_code, 200)
        self.assertIn("no-store", saved["Cache-Control"])
        self.assertIsNone(saved.json()["analysis"]["data_units_spent"])
        self.assertIsNone(LiveArtResaleAnalysis.objects.get(lot=self.lot).data_units_spent)

    def test_no_credible_comps_save_without_a_bid_recommendation(self):
        missing_hammer = liveart_lot(
            "missing-hammer",
            sale_id="sale-2024",
            sale_date="2024-03-02T12:00:00-05:00",
            hammer_usd=None,
        )
        self.client.force_login(self.staff)
        with patch("secondstateapp.calendar_views.LiveArtClient") as client_class:
            self.mock_client(client_class, lots=[missing_hammer])
            self.assertEqual(self.research().status_code, 200)
        response = self.save([])

        self.assertEqual(response.status_code, 200)
        analysis = response.json()["analysis"]
        self.assertTrue(analysis["no_credible_comps"])
        self.assertEqual(analysis["selected_ids"], [])
        self.assertEqual(analysis["scenarios"], [])
        self.assertEqual(LiveArtResaleAnalysis.objects.count(), 1)

    def test_unknown_or_noncredible_comp_cannot_be_saved_as_verified_hammer(self):
        self.client.force_login(self.staff)
        with patch("secondstateapp.calendar_views.LiveArtClient") as client_class:
            self.mock_client(client_class)
            self.assertEqual(self.research().status_code, 200)

        for selected_ids in (["invented-id"], ["artwork-miro"]):
            with self.subTest(selected_ids=selected_ids):
                response = self.save(selected_ids)
                self.assertEqual(response.status_code, 400)
                self.assertFalse(LiveArtResaleAnalysis.objects.exists())

    def test_saved_liveart_comp_is_not_rendered_on_public_pages(self):
        private_marker = "PRIVATE_LIVEART_COMP_129873"
        LiveArtResaleAnalysis.objects.create(
            lot=self.lot,
            subject_match={"id": "subject-lot"},
            candidates=[{"id": private_marker, "hammer_usd": "1205.00"}],
            selected_ids=[private_marker],
            retrieved_at=datetime(2026, 10, 12, tzinfo=ZoneInfo("UTC")),
        )
        public_client = Client()
        for url in (
            reverse("home"),
            reverse("gallery"),
            reverse("public_profile", args=(self.staff.username,)),
        ):
            with self.subTest(url=url):
                response = public_client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertNotIn(private_marker, response.content.decode("utf-8"))

    def test_liveart_post_requires_csrf(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.staff)
        self.assertEqual(csrf_client.post(self.research_url).status_code, 403)
        self.assertEqual(csrf_client.post(self.analysis_url, {"action": "delete"}).status_code, 403)


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
        liveart = LiveArtResaleAnalysis.objects.create(
            lot=lot,
            subject_match={"id": "verified-subject"},
            candidates=[{"id": "verified-comp", "hammer_usd": "1205.00"}],
            selected_ids=["verified-comp"],
            assumptions={"target_profit": "100.00"},
            scenarios=[{"name": "typical", "resale_hammer": "1205.00"}],
            retrieved_at=datetime(2026, 7, 20, tzinfo=ZoneInfo("UTC")),
            data_units_spent=6,
        )
        liveart_pk = liveart.pk
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
        liveart.refresh_from_db()
        self.assertEqual(liveart.pk, liveart_pk)
        self.assertEqual(liveart.selected_ids, ["verified-comp"])
        self.assertEqual(liveart.scenarios[0]["resale_hammer"], "1205.00")
        tray_item.refresh_from_db()
        self.assertEqual(tray_item.lot, lot)
        self.assertNotIn("reminders", response.json())

    @patch.dict(os.environ, {"CATALOG_API_KEY": "sync-test-key"}, clear=False)
    def test_heritage_sale_sync_groups_prints_on_the_calendar_and_updates_in_place(self):
        sale_url = "https://fineart.ha.com/c/search/results.zx?dept=1544&mode=live&auction_name=8280"
        artprice_url = "https://www.artprice.com/artist/27973/rufino-tamayo/lots/pasts?idcategory=2"
        payload = self._payload(
            source="Heritage",
            source_lot_id="8280-65001",
            auction_house="Heritage Auctions",
            sale_title="2026 October 22 Prints & Multiples Signature Auction",
            lot_number="65001",
            end_at="2026-10-22T11:00:00-05:00",
            lot_url="https://fineart.ha.com/itm/prints-and-multiples/rufino-tamayo/a/8280-65001.s",
            sale_url=sale_url,
            image_url="https://dyn1.heritagestatic.com/ha?p=3-5-1-8-3-35183186&w=120&h=300&it=product",
        )
        second_lot = dict(
            payload["lots"][0],
            source_lot_id="8280-65002",
            lot_number="65002",
            artist="Joan Miró",
            artist_watchlist_name="Joan Miró",
            title="Lithograph",
            lot_url="https://fineart.ha.com/itm/prints-and-multiples/joan-miro/a/8280-65002.s",
        )
        payload["lots"].append(second_lot)
        payload["artist_links"] = [{"name": "TAMAYO, RUFINO", "artprice_url": artprice_url}]

        response = self.client.post(
            self.endpoint,
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_X_API_KEY="sync-test-key",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["created"], 2)
        saved_lot = AuctionWatchLot.objects.get(source="Heritage", source_lot_id="8280-65001")
        saved_pk = saved_lot.pk
        self.assertEqual(saved_lot.event_at.astimezone(CALENDAR_ZONE).hour, 9)
        self.assertEqual(saved_lot.watchlist_artist.artprice_url, artprice_url)
        self.assertEqual(saved_lot.artist_watchlist_name, "Rufino Tamayo")

        staff = get_user_model().objects.create_user("heritage-calendar-admin", is_staff=True)
        self.client.force_login(staff)
        calendar = self.client.get(reverse("auction_calendar"), {"month": "2026-10"})

        self.assertEqual(calendar.status_code, 200)
        details = calendar.context["calendar_data"]["2026-10-22"]
        self.assertEqual({item["artist"] for item in details}, {"Rufino Tamayo", "Joan Miró"})
        first_detail = next(item for item in details if item["id"] == saved_pk)
        self.assertEqual(first_detail["time"], "9:00 AM")
        self.assertEqual(first_detail["url"], payload["lots"][0]["lot_url"])
        self.assertEqual(first_detail["images"], [payload["lots"][0]["image_url"]])
        self.assertEqual(first_detail["artist_artprice_url"], artprice_url)
        day = next(
            day for week in calendar.context["weeks"] for day in week
            if day["iso"] == "2026-10-22"
        )
        self.assertEqual(len(day["event_groups"]), 1)
        self.assertEqual(day["event_groups"][0]["auction_house"], "Heritage Auctions")
        self.assertEqual(day["event_groups"][0]["lot_count"], 2)
        self.assertEqual(day["event_groups"][0]["url"], sale_url)

        payload["lots"][0].update(current_bid=12000, bid_count=5, status="changed")
        response = self.client.post(
            self.endpoint,
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_X_API_KEY="sync-test-key",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["created"], 0)
        self.assertEqual(response.json()["updated"], 2)
        saved_lot.refresh_from_db()
        self.assertEqual(saved_lot.pk, saved_pk)
        self.assertEqual(saved_lot.current_bid, Decimal("12000.00"))
        self.assertEqual(saved_lot.bid_count, 5)
        self.assertEqual(AuctionWatchLot.objects.count(), 2)

    @patch.dict(os.environ, {"CATALOG_API_KEY": "sync-test-key"}, clear=False)
    def test_heritage_date_only_sale_keeps_its_calendar_day(self):
        payload = self._payload(
            source="Heritage",
            source_lot_id="8280-65001",
            auction_house="Heritage Auctions",
            end_at="2026-10-22",
        )

        response = self.client.post(
            self.endpoint,
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_X_API_KEY="sync-test-key",
        )

        self.assertEqual(response.status_code, 200)
        lot = AuctionWatchLot.objects.get()
        self.assertTrue(lot.is_all_day)
        self.assertEqual(lot.event_at.astimezone(CALENDAR_ZONE).date().isoformat(), "2026-10-22")

        staff = get_user_model().objects.create_user("heritage-date-admin", is_staff=True)
        self.client.force_login(staff)
        response = self.client.get(reverse("auction_calendar"), {"month": "2026-10"})
        detail = response.context["calendar_data"]["2026-10-22"][0]
        self.assertEqual(detail["time"], "Time TBA")

    @patch.dict(os.environ, {"CATALOG_API_KEY": "sync-test-key"}, clear=False)
    def test_heritage_image_cdn_allowlist_rejects_lookalikes_and_insecure_urls(self):
        for image_url in (
            "https://dyn1.heritagestatic.com.evil.example/lot.jpg",
            "https://evilheritagestatic.com/lot.jpg",
            "http://dyn1.heritagestatic.com/lot.jpg",
            "https://user:password@dyn1.heritagestatic.com/lot.jpg",
        ):
            with self.subTest(image_url=image_url):
                response = self.client.post(
                    self.endpoint,
                    data=json.dumps(self._payload(source="Heritage", image_url=image_url)),
                    content_type="application/json",
                    HTTP_X_API_KEY="sync-test-key",
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(AuctionWatchLot.objects.get().image_url, "")

    @patch.dict(os.environ, {"CATALOG_API_KEY": "sync-test-key"}, clear=False)
    def test_heritage_and_invaluable_lot_ids_do_not_collide(self):
        payload = self._payload(source_lot_id="65001")
        payload["lots"].append(
            dict(payload["lots"][0], source="Heritage", auction_house="Heritage Auctions")
        )

        response = self.client.post(
            self.endpoint,
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_X_API_KEY="sync-test-key",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["created"], 2)
        self.assertEqual(AuctionWatchLot.objects.count(), 2)
        self.assertEqual(AuctionWatchArtist.objects.count(), 1)

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
