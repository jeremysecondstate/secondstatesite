import json
from datetime import datetime
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .tests_calendar import CALENDAR_ZONE, watch_lot


@override_settings(
    CALENDAR_TIME_ZONE="America/Los_Angeles",
    AUCTION_EMAIL_SENDING_ENABLED=False,
)
class CalendarDayCatalogLinkTests(TestCase):
    def setUp(self):
        self.client.force_login(
            get_user_model().objects.create_user("day-catalog-admin", is_staff=True)
        )

    def test_catalog_price_sort_receives_numeric_estimates_and_missing_values(self):
        priced = watch_lot(
            source_lot_id="catalog-price-estimates",
            estimate_low=Decimal("900.25"),
            estimate_high=Decimal("1200.50"),
        )
        unpriced = watch_lot(
            source_lot_id="catalog-price-missing",
            estimate_low=None,
            estimate_high=None,
        )

        response = self.client.get(reverse("auction_calendar"), {"month": "2026-07"})
        page = BeautifulSoup(response.content, "html.parser")
        calendar_data = json.loads(page.select_one("#auction-calendar-data").string)
        lots = {lot["id"]: lot for lot in calendar_data["2026-07-25"]}

        self.assertEqual(lots[priced.pk]["estimate_low"], "900.25")
        self.assertEqual(lots[priced.pk]["estimate_high"], "1200.50")
        self.assertIsNone(lots[unpriced.pk]["estimate_low"])
        self.assertIsNone(lots[unpriced.pk]["estimate_high"])
        sort_options = {option["value"] for option in page.select("#day-gallery-sort option")}
        self.assertTrue({"price_asc", "price_desc"}.issubset(sort_options))

    def test_populated_day_links_below_sales_without_nesting_interactive_controls(self):
        for index in range(4):
            watch_lot(
                source_lot_id=f"day-catalog-{index}",
                sale_url=f"https://www.invaluable.com/catalog/sale-{index}",
            )
        watch_lot(
            source_lot_id="single-sale-day",
            event_at=datetime(2026, 7, 26, 9, tzinfo=CALENDAR_ZONE),
        )

        response = self.client.get(reverse("auction_calendar"), {"month": "2026-07"})
        page = BeautifulSoup(response.content, "html.parser")
        for iso_day in ("2026-07-25", "2026-07-26"):
            with self.subTest(day=iso_day):
                button = page.select_one(f'.calendar-day-select[data-calendar-day="{iso_day}"]')
                self.assertEqual(button.name, "button")
                self.assertEqual(button["type"], "button")
                cell = button.parent
                self.assertEqual(cell["role"], "gridcell")
                link = cell.select_one(".day-catalog-link")
                self.assertIs(link.parent, cell)
                self.assertIs(button.find_next_sibling(), link)
                self.assertIsNone(button.select_one("a"))
                self.assertEqual(
                    parse_qs(urlsplit(link["href"]).query),
                    {"month": ["2026-07"], "day": [iso_day], "view": ["catalog"]},
                )
                self.assertIn("Gallery Catalog", link.get_text())

        crowded_cell = page.select_one('[data-calendar-day="2026-07-25"]').parent
        self.assertEqual(crowded_cell.select_one(".more-events").get_text(), "+1 more auction")
        empty_cell = page.select_one('[data-calendar-day="2026-07-24"]').parent
        self.assertIsNone(empty_cell.select_one(".day-catalog-link"))

    def test_outside_month_catalog_link_preserves_visible_month_and_loads_requested_day(self):
        lot = watch_lot(event_at=datetime(2026, 6, 30, 9, tzinfo=CALENDAR_ZONE))
        response = self.client.get(reverse("auction_calendar"), {"month": "2026-07"})
        page = BeautifulSoup(response.content, "html.parser")
        cell = page.select_one('[data-calendar-day="2026-06-30"]').parent
        self.assertIn("is-outside", cell["class"])
        link = cell.select_one(".day-catalog-link")

        destination = self.client.get(reverse("auction_calendar") + link["href"])

        self.assertEqual(destination.status_code, 200)
        self.assertEqual(destination.context["month_value"], "2026-07")
        self.assertEqual(destination.wsgi_request.GET["day"], "2026-06-30")
        self.assertEqual(destination.wsgi_request.GET["view"], "catalog")
        self.assertEqual(destination.context["calendar_data"]["2026-06-30"][0]["id"], lot.pk)
