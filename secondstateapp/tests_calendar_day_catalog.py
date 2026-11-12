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

    def test_sale_location_choices_keep_all_source_records_available_for_research(self):
        domestic = watch_lot(source_lot_id="region-us", auction_house="DuMouchelles", location="Detroit, MI, US",
                             artist="After Pablo Picasso", artist_watchlist_name="Pablo Picasso")
        overseas = watch_lot(source_lot_id="region-overseas", auction_house="Bonhams", location="London, United Kingdom")
        unknown = watch_lot(source_lot_id="region-unknown", auction_house="Unverified Auction House", location="", currency="USD")
        originals = {lot.pk: lot.__class__.objects.filter(pk=lot.pk).values().get() for lot in (domestic, overseas, unknown)}

        response = self.client.get(reverse("auction_calendar"), {
            "month": "2026-07", "day": "2026-07-25", "view": "catalog",
            "sale_region": "us", "hide_attributed": "1",
        })

        self.assertEqual(response.status_code, 200)
        lots = {lot["id"]: lot for lot in response.context["calendar_data"]["2026-07-25"]}
        self.assertEqual(set(lots), set(originals), "Browsing choices must not remove source records from research data")
        self.assertEqual((lots[domestic.pk]["sale_region"], lots[domestic.pk]["sale_country"]), ("us", "US"))
        self.assertEqual(lots[domestic.pk]["attribution_label"], "After")
        self.assertEqual((lots[overseas.pk]["sale_region"], lots[overseas.pk]["sale_country"]), ("outside_us", "GB"))
        self.assertEqual((lots[unknown.pk]["sale_region"], lots[unknown.pk]["sale_country"]), ("unknown", ""))
        for lot in (domestic, overseas, unknown):
            self.assertEqual(lots[lot.pk]["lot_url"], lot.lot_url)
            self.assertEqual(lot.__class__.objects.filter(pk=lot.pk).values().get(), originals[lot.pk])

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

    def test_catalog_sections_can_collapse_without_hiding_primary_controls(self):
        watch_lot()
        response = self.client.get(reverse("auction_calendar"), {"month": "2026-07"})
        page = BeautifulSoup(response.content, "html.parser")
        for section_id in ("day-gallery-houses", "day-gallery-artists"):
            section = page.select_one(f"#{section_id}")
            self.assertEqual(section.name, "details")
            self.assertNotIn("open", section.attrs)
            self.assertIsNotNone(section.find("summary", recursive=False))
            self.assertIsNone(section.summary.select_one("button, select, input, a"))
        for control_id in ("day-gallery-filters", "day-gallery-sort", "day-gallery-send-launch"):
            self.assertIsNone(page.select_one(f"#{control_id}").find_parent("details"))
        self.assertEqual(page.select_one("#day-gallery-artists")["data-time-zone"], "America/Los_Angeles")
        self.assertIsNotNone(page.select_one('#day-gallery-artist-sort option[value="arrival_asc"]'))
        self.assertIn("Assumes the listed time is the sale start", page.select_one("#day-gallery-artists-note").get_text())

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
        calendar = page.select_one(".calendar-grid")
        self.assertEqual(calendar["role"], "group")
        self.assertEqual(calendar["aria-label"], "July 2026 Jeremy’s auction calendar")
        for iso_day in ("2026-07-25", "2026-07-26"):
            with self.subTest(day=iso_day):
                button = page.select_one(f'.calendar-day-select[data-calendar-day="{iso_day}"]')
                self.assertEqual(button.name, "button")
                self.assertEqual(button["type"], "button")
                cell = button.parent
                self.assertNotIn("role", cell.attrs)
                self.assertIs(cell.parent, calendar)
                link = cell.select_one(".day-catalog-link")
                self.assertIs(link.parent, cell)
                self.assertIs(button.find_next_sibling(), link)
                self.assertIsNone(button.select_one("a"))
                self.assertEqual(
                    parse_qs(urlsplit(link["href"]).query),
                    {"month": ["2026-07"], "day": [iso_day], "view": ["catalog"]},
                )
                self.assertIn("Jeremy’s Catalog", link.get_text())

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
