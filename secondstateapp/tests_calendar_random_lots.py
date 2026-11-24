"""The saved audit collection is independent of the day and tracked-artist filters."""

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import AuctionWatchLot
from .tests_calendar import watch_lot


@override_settings(CALENDAR_TIME_ZONE="America/Los_Angeles")
class CalendarRandomLotsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = get_user_model().objects.create_user("saved-collection-reviewer", is_staff=True)

    def setUp(self):
        self.url = reverse("auction_calendar_random_lots")
        self.client.force_login(self.staff)

    def test_collection_opens_other_days_without_changing_daily_tracked_view(self):
        # The first two source identities belong to the retained audit set.
        # The third was a tracked addition in the same audit.
        after_midnight_utc = datetime(2026, 11, 24, 3, tzinfo=timezone.utc)
        aguttes = watch_lot(source_lot_id="207302212", artist="", artist_watchlist_name="",
                            auction_house="Aguttes", event_at=after_midnight_utc)
        base_zero = watch_lot(source="Drouot", source_lot_id="35991044",
                              artist="Outside roster", artist_watchlist_name="",
                              auction_house="Base Zero", lot_number="1",
                              event_at=datetime(2026, 11, 26, 17, tzinfo=timezone.utc))
        tracked = watch_lot(source="Drouot", source_lot_id="36113097", event_at=after_midnight_utc)
        watch_lot(source="Drouot", source_lot_id=aguttes.source_lot_id, event_at=after_midnight_utc,
                  artist="Unrelated", artist_watchlist_name="")
        watch_lot(source_lot_id="unrelated-outside-roster", artist="Outside roster",
                  artist_watchlist_name="", event_at=after_midnight_utc)

        selected_day = {"day": "2026-11-24", "house": "Unrelated house", "hide_attributed": "1"}
        response = self.client.get(self.url, selected_day)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual((data["total"], data["page"], data["pages"]), (2, 1, 1))
        self.assertEqual([row["id"] for row in data["lots"]], [aguttes.pk, base_zero.pk])
        first = data["lots"][0]
        self.assertEqual(first["calendar_day"], "2026-11-23")
        self.assertEqual(first["auction_house"], "Aguttes")
        self.assertEqual(first["title"], aguttes.title)
        self.assertEqual(first["medium"], aguttes.medium)
        dossier = urlsplit(first["research_url"])
        self.assertEqual(dossier.path, reverse("auction_calendar"))
        query = parse_qs(dossier.query)
        self.assertEqual(query["day"], ["2026-11-23"])
        self.assertEqual(query["lot"], [str(aguttes.pk)])
        self.assertEqual(query["view"], ["research"])
        self.assertEqual(query["artists"], ["all"])

        daily = self.client.get(reverse("auction_calendar_day_lots"), {"day": "2026-11-23"}).json()
        visible_ids = {row["id"] for row in daily["lots"]}
        self.assertIn(tracked.pk, visible_ids)
        self.assertNotIn(aguttes.pk, visible_ids)
        self.assertEqual(AuctionWatchLot.objects.count(), 5)

    def test_converging_supersession_chains_show_the_saved_survivor_once(self):
        survivor = watch_lot(source_lot_id="verified-replacement", title="Current saved title")
        middle = watch_lot(source_lot_id="older-replacement", superseded_by=survivor)
        watch_lot(source="Drouot", source_lot_id="35991044", superseded_by=middle)
        watch_lot(source="Invaluable", source_lot_id="207302212", superseded_by=survivor)

        data = self.client.get(self.url).json()
        self.assertEqual(data["total"], 1)
        self.assertEqual([r["id"] for r in data["lots"]], [survivor.pk])
        self.assertEqual(data["lots"][0]["title"], survivor.title)
        self.assertEqual(AuctionWatchLot.objects.filter(superseded_by__isnull=False).count(), 3)

    def test_catalog_house_grid_exposes_collection_even_on_day_without_its_lots(self):
        watch_lot(source_lot_id="207302212", artist="", artist_watchlist_name="",
                  event_at=datetime(2026, 11, 23, 20, tzinfo=timezone.utc))
        response = self.client.get(reverse("auction_calendar"), {"day": "2026-11-24", "view": "catalog"})
        dom = BeautifulSoup(response.content, "html.parser")
        houses = dom.select_one("#day-gallery-house-filters")
        trigger = houses.find_next_sibling("button")
        self.assertEqual(trigger.select_one(".day-gallery-filter-name").get_text(strip=True), "Random Lots")
        self.assertEqual(trigger.select_one(".day-gallery-filter-count").get_text(strip=True), "1")
        panel = dom.find(id=trigger["aria-controls"])
        self.assertEqual(panel["data-url"], self.url)
        self.assertTrue(panel.has_attr("hidden"))

    def test_empty_collection_and_page_limits(self):
        empty = self.client.get(self.url).json()
        self.assertEqual((empty["total"], empty["pages"], empty["lots"]), (0, 1, []))
        self.assertEqual(self.client.get(self.url, {"page": "0"}).status_code, 400)
        self.assertEqual(self.client.get(self.url, {"page": "invalid"}).status_code, 400)
        self.assertEqual(self.client.get(self.url, {"page": "2"}).status_code, 404)

    def test_paging_uses_natural_lot_numbers_and_returns_each_saved_identity_once(self):
        path = Path(__file__).with_name("data") / "random_lots.json"
        source_ids = json.loads(path.read_text(encoding="utf-8"))["source_lot_ids"]["Drouot"][:25]
        numbers = ["1", "2", "2a", "2b", *map(str, range(3, 24))]
        for source_id, number in reversed(list(zip(source_ids, numbers, strict=True))):
            watch_lot(source="Drouot", source_lot_id=source_id, lot_number=number)

        first = self.client.get(self.url).json()
        second = self.client.get(self.url, {"page": 2}).json()
        self.assertEqual((first["total"], first["pages"], second["page"]), (25, 2, 2))
        self.assertEqual(len(first["lots"]), 24)
        self.assertEqual(len(second["lots"]), 1)
        rows = first["lots"] + second["lots"]
        self.assertEqual([r["lot_number"] for r in rows], numbers)
        self.assertEqual(len({r["id"] for r in rows}), 25)

    def test_unsafe_saved_links_are_not_returned_to_the_gallery(self):
        watch_lot(source_lot_id="207302212", lot_url="javascript:alert(1)", image_url="data:text/html,test")
        row = self.client.get(self.url).json()["lots"][0]
        self.assertFalse(row["lot_url"])
        self.assertFalse(row["image_url"])

    def test_collection_requires_staff(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.client.force_login(get_user_model().objects.create_user("collection-visitor"))
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.post(self.url).status_code, 405)
