"""Saved audit lots belong to their current sale day, independently of tracked artists."""

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
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

    def test_collection_uses_the_calendar_local_sale_day_without_changing_daily_tracked_view(self):
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

        selected_day = {"day": "2026-11-23", "house": "Unrelated house", "hide_attributed": "1"}
        response = self.client.get(self.url, selected_day)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["day"], "2026-11-23")
        self.assertEqual((data["total"], data["page"], data["pages"]), (1, 1, 1))
        self.assertEqual([row["id"] for row in data["lots"]], [aguttes.pk])
        next_sale = self.client.get(self.url, {"day": "2026-11-26"}).json()
        self.assertEqual([row["id"] for row in next_sale["lots"]], [base_zero.pk])
        empty_day = self.client.get(self.url, {"day": "2026-11-24"}).json()
        self.assertEqual(empty_day["day"], "2026-11-24")
        self.assertEqual((empty_day["total"], empty_day["pages"], empty_day["lots"]), (0, 1, []))
        all_dates = self.client.get(self.url).json()
        self.assertEqual([row["id"] for row in all_dates["lots"]], [aguttes.pk, base_zero.pk])
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

    def test_saved_card_matches_the_regular_card_and_its_actions_target_the_off_watchlist_lot(self):
        lot = watch_lot(
            source_lot_id="207302212", artist="An off-watchlist artist", artist_watchlist_name="",
            image_url="https://image.invaluable.com/housePhotos/Example/print.jpg",
            artprice_url="https://www.artprice.com/artist/1/example/lots/pasts",
            current_bid=1500, bid_count=3,
        )
        day = {"day": "2026-07-25"}
        row, = self.client.get(self.url, day).json()["lots"]
        dossier = self.client.get(row["research_url"])
        self.assertEqual(dossier.status_code, 200)
        self.assertEqual([card["id"] for card in dossier.context["calendar_data"][day["day"]]], [lot.pk])
        for action in ("email_tray_update_url", "research_queue_update_url"):
            with self.subTest(action=action):
                result = self.client.post(row[action], {"selected": "true"})
                self.assertEqual(result.status_code, 200)
                self.assertTrue(result.json()["selected"])

        saved, = self.client.get(self.url, day).json()["lots"]
        regular, = self.client.get(reverse("auction_calendar_day_lots"), {**day, "artists": "all"}).json()["lots"]
        self.assertTrue(saved["email_tray_selected"])
        self.assertTrue(saved["research_queue_selected"])
        self.assertEqual(saved["research_queue_status"], "queued")
        self.assertEqual(saved["images"], [lot.image_url])
        for field, value in regular.items():
            with self.subTest(field=field):
                self.assertEqual(saved[field], value)
        self.assertEqual(self.client.get(reverse("auction_calendar_day_lots"), day).json()["lots"], [])

    def test_saved_card_keeps_its_verified_house_image_for_the_regular_renderer(self):
        watch_lot(source="Drouot", source_lot_id="35868096", auction_house="Kiefer", lot_number="2917",
                  image_url="", artist="An off-watchlist artist", artist_watchlist_name="")
        row, = self.client.get(self.url, {"day": "2026-07-25"}).json()["lots"]
        self.assertEqual(row["image_url"], "https://www.kiefer.de/Abbildungen/146/146-2917-01.jpg")
        self.assertEqual(row["images"], [row["image_url"]])
        self.assertEqual(row["image_urls"], row["images"])

    def test_converging_supersession_chains_show_the_saved_survivor_on_its_current_sale_day_once(self):
        survivor = watch_lot(source_lot_id="verified-replacement", title="Current saved title",
                             event_at=datetime(2026, 7, 26, 17, tzinfo=timezone.utc))
        middle = watch_lot(source_lot_id="older-replacement", superseded_by=survivor)
        watch_lot(source="Drouot", source_lot_id="35991044", superseded_by=middle)
        watch_lot(source="Invaluable", source_lot_id="207302212", superseded_by=survivor)

        data = self.client.get(self.url, {"day": "2026-07-26"}).json()
        self.assertEqual(data["total"], 1)
        self.assertEqual([r["id"] for r in data["lots"]], [survivor.pk])
        self.assertEqual(data["lots"][0]["title"], survivor.title)
        self.assertEqual(self.client.get(self.url, {"day": "2026-07-25"}).json()["total"], 0)
        self.assertEqual(AuctionWatchLot.objects.filter(superseded_by__isnull=False).count(), 3)
        response = self.client.get(reverse("auction_calendar"), {"day": "2026-07-26"})
        counts = {day["iso"]: day["random_lots_count"] for week in response.context["weeks"] for day in week}
        self.assertEqual((counts["2026-07-25"], counts["2026-07-26"]), (0, 1))

    def test_calendar_and_catalog_offer_random_lots_even_on_a_day_without_saved_or_tracked_lots(self):
        watch_lot(source_lot_id="207302212", artist="", artist_watchlist_name="",
                  event_at=datetime(2026, 11, 23, 20, tzinfo=timezone.utc))
        response = self.client.get(reverse("auction_calendar"), {"day": "2026-11-24", "view": "catalog"})
        dom = BeautifulSoup(response.content, "html.parser")
        houses = dom.select_one("#day-gallery-house-filters")
        trigger = houses.find_next_sibling("button")
        self.assertEqual(trigger.select_one(".day-gallery-filter-name").get_text(strip=True), "Random Lots")
        self.assertEqual(trigger.select_one(".day-gallery-filter-count").get_text(strip=True), "0")
        panel = dom.find(id=trigger["aria-controls"])
        self.assertEqual(panel["data-url"], self.url)
        self.assertTrue(panel.has_attr("hidden"))
        self.assertEqual(response.context["random_lots_count"], 0)
        cells = dom.select(".calendar-grid .calendar-day")
        self.assertGreaterEqual(len(cells), 28)
        for cell in cells:
            day = cell.select_one(".calendar-day-select")["data-calendar-day"]
            link = cell.select_one(".day-random-lots-link")
            with self.subTest(day=day):
                self.assertIsNotNone(link)
                self.assertFalse(link.find_parent("button"))
                params = parse_qs(urlsplit(link["href"]).query)
                self.assertEqual(params["day"], [day])
                self.assertEqual(params["collection"], ["random"])
                self.assertEqual(params["view"], ["catalog"])
                self.assertIn("Random Lots", link.get_text(" ", strip=True))
                self.assertIn("1" if day == "2026-11-23" else "0", link.get_text(" ", strip=True))

    def test_empty_collection_and_page_limits(self):
        empty = self.client.get(self.url).json()
        self.assertEqual((empty["total"], empty["pages"], empty["lots"]), (0, 1, []))
        self.assertEqual(self.client.get(self.url, {"page": "0"}).status_code, 400)
        self.assertEqual(self.client.get(self.url, {"page": "invalid"}).status_code, 400)
        self.assertEqual(self.client.get(self.url, {"page": "2"}).status_code, 404)
        for invalid in ("", "not-a-date", "2026-02-30"):
            with self.subTest(day=invalid):
                self.assertEqual(self.client.get(self.url, {"day": invalid}).status_code, 400)

    def test_facet_counts_cover_the_full_day_and_filtered_usd_pages_match_the_cards(self):
        params = {"day": "2026-07-25", "facets": "1"}
        common = []
        for number in range(1, 27):
            common.append(watch_lot(
                source_lot_id=f"facet-common-{number}", random_lot=True,
                artist_watchlist_name="", artist="Joan Miró" if number % 2 else "Miró, Joan",
                auction_house="Gallery &amp; Sons", lot_number=str(number), estimate_low=number,
            ).pk)
        rare = watch_lot(source_lot_id="facet-rare", random_lot=True,
                         artist_watchlist_name="", artist="After Andy Warhol", auction_house="Zephyr")
        watch_lot(source_lot_id="facet-direct", random_lot=True,
                  artist_watchlist_name="Andy Warhol", artist="Catalog spelling", auction_house="Zephyr")
        later = datetime(2026, 7, 26, 17, tzinfo=timezone.utc)
        watch_lot(source_lot_id="facet-other-day", random_lot=True,
                  artist_watchlist_name="", artist="Other artist", auction_house="Other house", event_at=later)
        watch_lot(source_lot_id="facet-unsaved", artist_watchlist_name="", artist="Unsaved artist")

        response = self.client.get(self.url, params).json()
        self.assertEqual((response["day_total"], response["total"], response["pages"]), (28, 28, 2))
        self.assertNotIn(rare.pk, [card["id"] for card in response["lots"]])
        self.assertEqual(response["facets"]["houses"], [
            {"key": "gallery & sons", "label": "Gallery & Sons", "count": 26},
            {"key": "zephyr", "label": "Zephyr", "count": 2},
        ])
        self.assertEqual({(row["key"], row["label"], row["count"]) for row in response["facets"]["artists"]}, {
            ("miró, joan", "Miró, Joan", 26),
            ("after warhol, andy", "After Warhol, Andy", 1),
            ("warhol, andy", "Warhol, Andy", 1),
        })
        # Reading facet labels for positions beyond page one should use the
        # same database round trips as loading just the first page of cards.
        with CaptureQueriesContext(connection) as card_queries:
            self.client.get(self.url, {"day": params["day"]})
        with self.assertNumQueries(len(card_queries)):
            self.client.get(self.url, params)
        rare_rows = self.client.get(self.url, {**params, "collection_artist": "after warhol, andy"}).json()
        self.assertEqual([row["id"] for row in rare_rows["lots"]], [rare.pk])
        self.assertEqual(rare_rows["facets"]["houses"], [{"key": "zephyr", "label": "Zephyr", "count": 1}])

        filtered = {
            **params, "collection_house": "gallery & sons", "collection_artist": "miró, joan",
            "sort": "estimate-desc",
        }
        expected = list(reversed(common))
        for page, ids in enumerate((expected[:24], expected[24:]), start=1):
            with self.subTest(page=page):
                options = {**filtered, "page": page}
                cards = self.client.get(self.url, options).json()
                prices = self.client.get(self.url, {**options, "prices": "usd"}).json()
                self.assertEqual((cards["total"], cards["day_total"], prices["total"]), (26, 28, 26))
                self.assertEqual([row["id"] for row in cards["lots"]], ids)
                self.assertEqual([row["id"] for row in prices["lots"]], ids)
                self.assertNotIn("facets", prices)
        next_day = self.client.get(self.url, {"day": "2026-07-26", "facets": "1"}).json()
        self.assertEqual(next_day["day_total"], 1)
        self.assertEqual(next_day["facets"]["artists"], [{"key": "other artist", "label": "Other artist", "count": 1}])

    def test_facets_keep_disjoint_selections_and_count_the_uncredited_survivor_once(self):
        today = {"day": "2026-07-25", "facets": "1"}
        survivor = watch_lot(source_lot_id="facet-survivor", artist="", artist_watchlist_name="", auction_house="")
        older_day = datetime(2026, 7, 24, 17, tzinfo=timezone.utc)
        middle = watch_lot(source_lot_id="facet-middle", superseded_by=survivor, event_at=older_day)
        watch_lot(source_lot_id="facet-donor-one", random_lot=True, superseded_by=middle, event_at=older_day)
        watch_lot(source_lot_id="facet-donor-two", random_lot=True, superseded_by=survivor, event_at=older_day)
        watch_lot(source_lot_id="facet-credited", random_lot=True, artist_watchlist_name="", artist="Artist A",
                  auction_house="House A")

        data = self.client.get(self.url, {
            **today, "collection_artist": "unknown artist", "collection_house": "invaluable",
        }).json()
        self.assertEqual((data["day_total"], data["total"]), (2, 1))
        self.assertEqual([(r["id"], r["artist"], r["auction_house"]) for r in data["lots"]],
                         [(survivor.pk, "Unknown artist", "Invaluable")])
        self.assertEqual(data["facets"]["artists"], [{"key": "unknown artist", "label": "Unknown artist", "count": 1}])
        self.assertEqual(data["facets"]["houses"], [{"key": "invaluable", "label": "Invaluable", "count": 1}])

        disjoint = self.client.get(self.url, {
            **today, "collection_artist": "unknown artist", "collection_house": "house a",
        }).json()
        self.assertEqual((disjoint["day_total"], disjoint["total"], disjoint["lots"]), (2, 0, []))
        self.assertEqual({row["key"]: row["count"] for row in disjoint["facets"]["houses"]},
                         {"invaluable": 1, "house a": 0})
        self.assertEqual({row["key"]: row["count"] for row in disjoint["facets"]["artists"]},
                         {"artist a": 1, "unknown artist": 0})
        stale = self.client.get(self.url, {**today, "collection_artist": "no such artist"}).json()
        self.assertEqual((stale["day_total"], stale["total"], stale["facets"]["houses"]), (2, 0, []))
        self.assertNotIn("no such artist", [row["key"] for row in stale["facets"]["artists"]])
        yesterday = self.client.get(self.url, {"day": "2026-07-24", "facets": "1"}).json()
        self.assertEqual((yesterday["day_total"], yesterday["facets"]), (0, {"houses": [], "artists": []}))

    def test_catalog_artist_and_house_order_across_sale_days(self):
        warhol = watch_lot(source_lot_id="sort-warhol", random_lot=True, artist="After Andy Warhol",
                           artist_watchlist_name="", auction_house="Zephyr", lot_number="1")
        later = datetime(2026, 7, 26, 17, tzinfo=timezone.utc)
        miro = watch_lot(source_lot_id="sort-miro", random_lot=True, artist="Unresolved catalogue spelling",
                         artist_watchlist_name="Joan Miró", auction_house="Aster", lot_number="10", event_at=later)
        monet = watch_lot(source_lot_id="sort-monet", random_lot=True, artist="Claude Monet",
                          artist_watchlist_name="", auction_house="Aster", lot_number="2a", event_at=later)
        expectations = (
            ({}, [warhol.pk, monet.pk, miro.pk]),
            ({"sort": "catalog"}, [warhol.pk, monet.pk, miro.pk]),
            ({"sort": "artist"}, [miro.pk, monet.pk, warhol.pk]),
            ({"sort": "house"}, [monet.pk, miro.pk, warhol.pk]),
        )
        for params, expected in expectations:
            with self.subTest(params=params):
                rows = self.client.get(self.url, params).json()["lots"]
                self.assertEqual([row["id"] for row in rows], expected)

    def test_estimates_use_usd_before_paging_and_prices_follow_the_same_sorted_page(self):
        estimates = {
            1: ("USD", 1000, 1100),
            2: ("EUR", 100, 2000),  # $200, tied with the later USD lots.
            3: ("USD", 125, 9000),  # The high estimate cannot override a positive low.
            4: ("USD", None, 700),
            5: ("USD", None, None),
            6: ("XYZ", 10000, 20000),  # No USD quote.
            7: ("USD", 0, 450),
        }
        by_number = {}
        for number in range(31, 0, -1):
            currency, low, high = estimates.get(number, ("USD", 200, 250))
            by_number[number] = watch_lot(
                source_lot_id=f"sort-estimate-{number}", random_lot=True, lot_number=str(number),
                currency=currency, estimate_low=low, estimate_high=high, current_bid=20000,
            ).pk

        tied = [2, *range(8, 32)]
        orders = {
            "estimate-asc": [3, *tied, 7, 4, 1, 5, 6],
            "estimate-desc": [1, 4, 7, *tied, 3, 5, 6],
        }
        quotes = {"EUR": {"date": "2026-07-24", "rate": "2"}}
        with patch("secondstateapp.currency._usd_quote", side_effect=quotes.get):
            for sort, numbers in orders.items():
                expected_ids = [by_number[number] for number in numbers]
                price_by_id = {}
                for page, expected in enumerate((expected_ids[:24], expected_ids[24:]), start=1):
                    with self.subTest(sort=sort, page=page):
                        params = {"day": "2026-07-25", "sort": sort, "page": page}
                        cards = self.client.get(self.url, params).json()
                        prices = self.client.get(self.url, {**params, "prices": "usd"}).json()
                        price_by_id.update({row["id"]: row for row in prices["lots"]})
                        for payload in (cards, prices):
                            self.assertEqual((payload["total"], payload["pages"], payload["page"]), (31, 2, page))
                            self.assertEqual([row["id"] for row in payload["lots"]], expected)
                self.assertEqual(price_by_id[by_number[2]]["estimate_low"]["usd_amount"], "200.00")
                self.assertIsNone(price_by_id[by_number[6]]["estimate_low"])

    def test_paging_uses_natural_lot_numbers_and_returns_each_saved_identity_once(self):
        path = Path(__file__).with_name("data") / "random_lots.json"
        source_ids = json.loads(path.read_text(encoding="utf-8"))["source_lot_ids"]["Drouot"][:26]
        numbers = ["1", "2", "2a", "2b", *map(str, range(3, 24))]
        for source_id, number in reversed(list(zip(source_ids[:25], numbers, strict=True))):
            artist = "Alexander Calder" if number == "23" else "Joan Miró"
            watch_lot(source="Drouot", source_lot_id=source_id, lot_number=number, currency="EUR",
                      artist=artist, artist_watchlist_name="")
        next_day = watch_lot(source="Drouot", source_lot_id=source_ids[25], lot_number="1",
                             auction_house="Aster", event_at=datetime(2026, 7, 26, 17, tzinfo=timezone.utc))

        first = self.client.get(self.url, {"day": "2026-07-25"}).json()
        second = self.client.get(self.url, {"day": "2026-07-25", "page": 2}).json()
        self.assertEqual(self.client.get(self.url, {"day": "2026-07-26", "page": 2}).status_code, 404)
        self.assertEqual((first["total"], first["pages"], second["page"]), (25, 2, 2))
        self.assertEqual(len(first["lots"]), 24)
        self.assertEqual(len(second["lots"]), 1)
        rows = first["lots"] + second["lots"]
        self.assertEqual([r["lot_number"] for r in rows], numbers)
        self.assertEqual(len({r["id"] for r in rows}), 25)
        catalog_ids = [r["id"] for r in rows]
        for params, expected in (
            ({"day": "2026-07-25", "sort": "artist"}, [catalog_ids[-1], *catalog_ids[:-1]]),
            ({"sort": "house"}, [next_day.pk, *catalog_ids]),
        ):
            with self.subTest(params=params):
                for page, page_ids in enumerate((expected[:24], expected[24:]), start=1):
                    ordered = self.client.get(self.url, {**params, "page": page}).json()["lots"]
                    self.assertEqual([r["id"] for r in ordered], page_ids)

        with patch("secondstateapp.currency._usd_quote", return_value={"date": "2026-07-24", "rate": "1.2"}):
            prices = self.client.get(self.url, {"day": "2026-07-25", "page": 2, "prices": "usd"}).json()
        self.assertEqual((prices["day"], prices["page"], prices["total"]), ("2026-07-25", 2, 25))
        price, = prices["lots"]
        self.assertEqual(price["id"], rows[-1]["id"])
        self.assertEqual(price["estimate_low"]["usd_amount"], "2400.00")
        self.assertEqual(price["estimate_high"]["usd_amount"], "3600.00")

    def test_unsafe_saved_links_are_not_returned_to_the_gallery(self):
        watch_lot(source_lot_id="207302212", lot_url="javascript:alert(1)", sale_url="data:text/html,test",
                  image_url="data:text/html,test")
        row = self.client.get(self.url).json()["lots"][0]
        self.assertFalse(row["lot_url"])
        self.assertFalse(row["url"])
        self.assertFalse(row["image_url"])
        self.assertEqual(row["images"], [])

    def test_collection_requires_staff(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.client.force_login(get_user_model().objects.create_user("collection-visitor"))
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.post(self.url).status_code, 405)
