"""Verified timed-sale grouping must not alter individual auction lots."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from .calendar_sales import verified_sale
from .calendar_views import _group_lots, _sale_identity
from .models import AuctionBidBoardAnalysis, AuctionEmailBatch, AuctionEmailBatchItem, AuctionWatchLot
from .research_queue_models import ResearchQueueItem
from .tests_calendar import CALENDAR_ZONE, stored_analysis, watch_lot


SALE_START = datetime(2026, 11, 8, 19, tzinfo=timezone.utc)
FIRST_CLOSE = SALE_START + timedelta(minutes=1)
LAST_CLOSE = datetime(2026, 11, 9, 2, 20, 30, tzinfo=timezone.utc)
IMAGE = "https://image.invaluable.com/housePhotos/Alyes/39/821739/H21147-LkdhowuDUwqe0i.jpg"
LOT_LINK = "https://www.invaluable.com/auction-lot/pierre-soulages-lithograph-no-36-1976-3-c-be417bafc3"


def alyes_values(identity, **changes):
    values = {
        "source": "Invaluable", "source_lot_id": identity,
        "auction_house": "Alyes Auctions", "sale_title": "", "sale_url": "",
        "artist": "Pierre Soulages", "artist_watchlist_name": "Pierre Soulages",
        "title": "Lithograph No. 36", "lot_number": "3",
        "image_url": IMAGE, "lot_url": LOT_LINK, "event_at": FIRST_CLOSE,
        "active": True,
    }
    values.update(changes)
    return values


class VerifiedTimedSaleGroupingTests(SimpleTestCase):
    def lot(self, identity="first", **changes):
        return AuctionWatchLot(**alyes_values(identity, **changes))

    def test_combined_mallet_catalog_lists_both_represented_sessions_in_pacific_time(self):
        fields = dict(source="Drouot", sale_url="https://drouot.com/en/v/188574", auction_house="Mallet Auction")
        early = self.lot("early", **fields, lot_number="1019", event_at=datetime(2026, 12, 10, 3, tzinfo=timezone.utc))
        late = self.lot("late", **fields, lot_number="62", event_at=datetime(2026, 12, 10, 6, tzinfo=timezone.utc))
        group, = _group_lots([late, early], CALENDAR_ZONE)
        self.assertEqual(group["time_label"], "7:00 PM and 10:00 PM")
        self.assertEqual(group["sort_at"], early.event_at)
        self.assertEqual(group["lot_count"], 2)
        self.assertEqual(_group_lots([late], CALENDAR_ZONE)[0]["time_label"], "10:00 PM")

    def test_staggered_closings_across_utc_midnight_form_one_sale_at_its_published_start(self):
        first = self.lot()
        last = self.lot("last", event_at=LAST_CLOSE)
        original = [(lot.event_at, lot.sale_url, lot.lot_url, lot.image_url) for lot in (first, last)]

        # Deliberately reverse input order: the first supplied lot is not the sale start.
        groups = _group_lots([last, first], CALENDAR_ZONE)

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["lot_count"], 2)
        self.assertEqual(groups[0]["time_label"], "11:00 AM")
        self.assertEqual(groups[0]["sort_at"], SALE_START)
        self.assertEqual(groups[0]["sale_url"], "")
        self.assertEqual(groups[0]["sale_title"], "")
        self.assertEqual([(lot.event_at, lot.sale_url, lot.lot_url, lot.image_url) for lot in (first, last)], original)

    def test_explicit_distinct_sale_urls_take_precedence_over_image_catalog(self):
        lots = [
            self.lot("known-one", sale_url="https://www.invaluable.com/catalog/ONE"),
            self.lot("known-two", sale_url="https://www.invaluable.com/catalog/TWO"),
            self.lot("missing-url"),
        ]

        groups = _group_lots(lots, CALENDAR_ZONE)

        self.assertEqual(len(groups), 3)
        self.assertEqual({group["sale_url"] for group in groups}, {
            "https://www.invaluable.com/catalog/ONE", "https://www.invaluable.com/catalog/TWO", "",
        })
        self.assertIsNone(verified_sale(lots[0]))
        self.assertIsNone(verified_sale(lots[1]))

    def test_unverified_source_house_date_and_catalog_keep_timestamp_fallback(self):
        changes = (
            {"source": "Drouot"},
            {"auction_house": "Alyes Auctions Partners"},
            {"event_at": FIRST_CLOSE + timedelta(days=1)},
            {"image_url": ""},
            {"image_url": IMAGE.replace("821739", "821740")},
            {"image_url": IMAGE.replace("/Alyes/", "/AnotherHouse/")},
            {"image_url": IMAGE.replace("/39/", "/40/")},
            {"image_url": IMAGE.replace("H21147-", "H21148-")},
            {"image_url": IMAGE + "/other.jpg"},
            {"image_url": IMAGE.replace("image.invaluable.com", "image.invaluable.com.example.test")},
            {"image_url": IMAGE.replace("https://", "https://other.example@")},
            {"image_url": IMAGE.replace("image.invaluable.com", "image.invaluable.com:8443")},
            {"image_url": "https://[invalid"},
            {"lot_url": LOT_LINK.replace("www.invaluable.com", "www.invaluable.com.example.test")},
            {"lot_url": "https://www.invaluable.com/auction-house/alyes"},
            {"lot_url": LOT_LINK.replace("https://", "https://other.example@")},
        )
        for change in changes:
            with self.subTest(change=change):
                first = self.lot(**change)
                later = self.lot("later", **{**change, "event_at": first.event_at + timedelta(minutes=1)})
                self.assertIsNone(verified_sale(first))
                self.assertNotEqual(_sale_identity(first), _sale_identity(later))
                self.assertEqual(len(_group_lots([first, later], CALENDAR_ZONE)), 2)

    def test_unknown_or_all_day_time_does_not_receive_a_verified_sale_start(self):
        for change in ({"event_at": None}, {"is_all_day": True}, {"event_at": datetime(2026, 11, 8, 19)}):
            with self.subTest(change=change):
                self.assertIsNone(verified_sale(self.lot(**change)))

    def test_196_watched_lots_do_not_crowd_13_other_auctions_out_of_the_sale_count(self):
        lots = [self.lot(str(index), event_at=FIRST_CLOSE + timedelta(minutes=index)) for index in range(196)]
        lots += [self.lot(f"other-{index}", auction_house=f"Other house {index}",
                          sale_url=f"https://www.invaluable.com/catalog/other-{index}") for index in range(13)]

        groups = _group_lots(lots, CALENDAR_ZONE)

        self.assertEqual(len(groups), 14)
        self.assertEqual(sum(group["lot_count"] for group in groups), 209)
        self.assertEqual(next(group for group in groups if group["auction_house"] == "Alyes Auctions")["lot_count"], 196)


@override_settings(CALENDAR_TIME_ZONE="America/Los_Angeles", AUCTION_EMAIL_SENDING_ENABLED=False)
class TimedSaleCalendarViewTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user("timed-sale-admin", is_staff=True)
        self.client.force_login(self.staff)
        clock = patch("secondstateapp.calendar_views.timezone.now", return_value=SALE_START - timedelta(days=1))
        clock.start()
        self.addCleanup(clock.stop)

    def test_november_22_alyes_catalog_groups_linked_and_unlinked_lots_at_the_first_closing(self):
        day = "2026-11-22"
        catalog_url = "https://www.invaluable.com/catalog/y4fscaz8rx"
        source = {"auction_house": "Alyes Auctions", "sale_title": ""}
        first = watch_lot(
            **source, source_lot_id="207555685", lot_number="1", sale_url="",
            artist="Keith Haring", artist_watchlist_name="Keith Haring",
            title="Keith Haring - Self Portrait, Palladium Invitation, 1985",
            lot_url="https://www.invaluable.com/auction-lot/keith-haring-self-portrait-palladium-invitation-1985-1-c-80f795d7f9",
            image_url="https://image.invaluable.com/housePhotos/Alyes/94/822594/H21147-LsKCac25rGbM6C.jpg",
            event_at=datetime(2026, 11, 22, 20, tzinfo=timezone.utc),
        )
        last = watch_lot(
            **source, source_lot_id="207556670", lot_number="997", sale_url=catalog_url,
            artist="Takashi Murakami", artist_watchlist_name="Takashi Murakami",
            title="Takashi Murakami - Jigsaw Puzzle 108 Bonno",
            lot_url="https://www.invaluable.com/auction-lot/takashi-murakami-jigsaw-puzzle-108-bonno-997-c-5dad25890c",
            image_url="https://image.invaluable.com/housePhotos/Alyes/94/822594/H21147-LviZMT8SH2Lweb.jpg",
            event_at=datetime(2026, 11, 23, 4, 10, tzinfo=timezone.utc),
        )

        response = self.client.get(reverse("auction_calendar"), {"day": day, "view": "catalog"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["calendar_sales_data"][day], [{
            "auction_house": "Alyes Auctions", "sale_title": "Street, Pop & Pokémon: Contemporary Art Auction",
            "lot_count": 2, "time_label": "12:00 PM", "sale_url": catalog_url,
        }])
        self.assertEqual(response.context["oliver_calendar_sales_data"][day], [])

        cards = {card["id"]: card for card in response.context["calendar_data"][day]}
        self.assertEqual(set(cards), {first.pk, last.pk})
        for lot, clock in ((first, "12:00 PM"), (last, "8:10 PM")):
            card = cards[lot.pk]
            self.assertEqual(card["time"], clock)
            self.assertEqual(card["arrival_schedule"], {
                "kind": "published_closing", "at": lot.event_at.isoformat(), "source_url": lot.lot_url,
            })
        first.refresh_from_db()
        self.assertEqual(first.sale_url, "")

    def test_grid_day_list_and_upcoming_share_one_sale_without_changing_lots_or_saved_work(self):
        first = watch_lot(**alyes_values("first", artist="Pierre Soulages (after)", won_by_us=True,
                                       artprice_url="https://www.artprice.com/artist/26343/pierre-soulages/lots/pasts"))
        last = watch_lot(**alyes_values("last", event_at=LAST_CLOSE))
        partner = watch_lot(source_lot_id="partner", auction_house="Bonhams", event_at=FIRST_CLOSE,
                            sale_url="https://www.invaluable.com/catalog/partner")
        batch = AuctionEmailBatch.objects.create()
        AuctionEmailBatchItem.objects.create(batch=batch, lot=first, selected_by=self.staff)
        ResearchQueueItem.objects.create(lot=last, selected=True, note="Retain research note")
        stored_analysis(first, created_by=self.staff)
        AuctionBidBoardAnalysis.objects.create(lot=last, assumptions={"retained": True}, selected_ids=["source-1"])
        models = (AuctionWatchLot, AuctionEmailBatchItem, ResearchQueueItem, AuctionBidBoardAnalysis)
        before = {model: list(model.objects.order_by("pk").values()) for model in models}
        analysis_before = list(first.max_bid_analysis.__class__.objects.values())

        response = self.client.get(reverse("auction_calendar"), {"month": "2026-11", "day": "2026-11-08"})

        self.assertEqual(response.status_code, 200)
        context = response.context
        day = next(day for week in context["weeks"] for day in week if day["iso"] == "2026-11-08")
        self.assertEqual((day["lot_count"], day["sale_count"], day["more_count"]), (3, 2, 0))
        self.assertEqual((day["oliver_lot_count"], day["oliver_sale_count"]), (1, 1))
        sales = context["calendar_sales_data"]["2026-11-08"]
        self.assertEqual([(sale["auction_house"], sale["lot_count"]) for sale in sales], [("Alyes Auctions", 2), ("Bonhams", 1)])
        self.assertEqual(sales[0]["time_label"], "11:00 AM")
        self.assertEqual([sale["auction_house"] for sale in context["upcoming_groups"]], ["Alyes Auctions", "Bonhams"])
        self.assertEqual(context["upcoming_groups"][0]["lot_count"], 2)
        self.assertEqual(context["upcoming_groups"][0]["date_iso"], "2026-11-08")
        self.assertEqual([sale["auction_house"] for sale in context["oliver_upcoming_groups"]], ["Bonhams"])
        self.assertEqual([sale["lot_count"] for sale in context["oliver_calendar_sales_data"]["2026-11-08"]], [1])
        self.assertNotIn("2026-11-09", context["calendar_data"])
        payload = {lot["id"]: lot for lot in context["calendar_data"]["2026-11-08"]}
        self.assertEqual(set(payload), {first.pk, last.pk, partner.pk})
        self.assertEqual([payload[lot.pk]["time"] for lot in (first, last)], ["11:01 AM", "6:20 PM"])
        for lot in (first, last):
            self.assertEqual(datetime.fromisoformat(payload[lot.pk]["event_at"]), lot.event_at)
            self.assertEqual(payload[lot.pk]["lot_url"], lot.lot_url)
            self.assertEqual(payload[lot.pk]["sale_url"], "")
            self.assertEqual(payload[lot.pk]["artprice_url"], lot.artprice_url)
        self.assertTrue(payload[first.pk]["won_by_us"])
        self.assertTrue(payload[first.pk]["email_tray_selected"])
        self.assertEqual(payload[first.pk]["attribution_label"], "After")
        self.assertTrue(payload[last.pk]["research_queue_selected"])
        for model in models:
            self.assertEqual(list(model.objects.order_by("pk").values()), before[model])
        self.assertEqual(list(first.max_bid_analysis.__class__.objects.values()), analysis_before)


@override_settings(CALENDAR_TIME_ZONE="America/Los_Angeles", AUCTION_EMAIL_SENDING_ENABLED=False)
class CrossProviderCatalogViewTests(TestCase):
    start = datetime(2026, 12, 3, 10, tzinfo=timezone.utc)

    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user("catalog-staff", is_staff=True))
        clock = patch("secondstateapp.calendar_views.timezone.now", return_value=self.start - timedelta(days=1))
        clock.start()
        self.addCleanup(clock.stop)

    def invaluable(self, number, catalog="822832", **changes):
        values = dict(
            auction_house="Artcurial", sale_title="", sale_url="", lot_number=str(number),
            source_lot_id=str(207000000 + number), event_at=self.start,
            image_url=f"https://image.invaluable.com/housePhotos/Artcurial/32/{catalog}/H0900-L{number}.jpg",
            lot_url=f"https://www.invaluable.com/auction-lot/print-{number}-c-{number:010x}",
        )
        return watch_lot(**{**values, **changes})

    def drouot(self, number, catalog="188405", survivor=None, **changes):
        source_id = str(36000000 + number)
        values = dict(
            source="Drouot", source_lot_id=source_id, auction_house="Artcurial", sale_title="",
            event_at=self.start, lot_number=str(number), lot_url=f"https://drouot.com/en/l/{source_id}-print",
            sale_url=f"https://drouot.com/en/v/{catalog}", superseded_by=survivor, active=survivor is None,
        )
        return watch_lot(**{**values, **changes})

    def data(self, day="2026-12-03"):
        response = self.client.get(reverse("auction_calendar"), {"day": day, "view": "catalog"})
        self.assertEqual(response.status_code, 200)
        return response.context

    def test_verified_catalog_is_counted_once_across_both_scopes_and_upcoming(self):
        survivor = self.invaluable(25)
        hidden = self.drouot(25, survivor=survivor)
        other_invaluable = self.invaluable(26)
        other_drouot = self.drouot(27)
        self.invaluable(28, catalog="822899")
        self.drouot(29, catalog="188499")
        before = list(AuctionWatchLot.objects.order_by("pk").values())

        day = "2026-12-03"
        context = self.data(day)
        for key in ("calendar_sales_data", "oliver_calendar_sales_data", "upcoming_groups", "oliver_upcoming_groups"):
            with self.subTest(key=key):
                groups = context[key][day] if key.endswith("_data") else context[key]
                self.assertCountEqual([group["lot_count"] for group in groups], [3, 1, 1])
                joined, = [group for group in groups if group["lot_count"] == 3]
                self.assertEqual(joined["sale_url"], other_drouot.sale_url)
        lots = {lot["id"]: lot for lot in context["calendar_data"][day]}
        self.assertEqual(len(lots), 5)
        self.assertNotIn(hidden.pk, lots)
        for lot in (survivor, other_invaluable, other_drouot):
            self.assertEqual(lots[lot.pk]["lot_url"], lot.lot_url)
        self.assertEqual(list(AuctionWatchLot.objects.order_by("pk").values()), before)

    def test_conflicting_catalog_evidence_keeps_two_drouot_catalogs_distinct(self):
        self.drouot(25, survivor=self.invaluable(25))
        self.drouot(26, catalog="188499", survivor=self.invaluable(26))
        self.invaluable(27)
        self.drouot(28)
        self.drouot(29, catalog="188499")

        sales = self.data()["calendar_sales_data"]["2026-12-03"]
        self.assertCountEqual([sale["lot_count"] for sale in sales], [3, 1, 1])

    def test_unrelated_explicit_catalog_and_mismatched_lot_number_keep_their_own_groups(self):
        self.drouot(25, survivor=self.invaluable(25))
        self.drouot(26)
        self.invaluable(27, sale_url="https://www.invaluable.com/catalog/zls47cuze8")
        self.invaluable(28, lot_url="https://www.invaluable.com/auction-lot/print-300-c-a0a0a0a0a0")

        sales = self.data()["calendar_sales_data"]["2026-12-03"]
        counts = {sale["sale_url"]: sale["lot_count"] for sale in sales}
        self.assertEqual(counts, {
            "https://drouot.com/en/v/188405": 2,
            "https://www.invaluable.com/catalog/zls47cuze8": 1,
            "": 1,
        })

    def test_changed_number_or_source_link_cannot_identify_a_catalog(self):
        first = self.invaluable(25)
        self.drouot(27, survivor=first)
        second = self.invaluable(26)
        self.drouot(26, survivor=second, lot_url="https://drouot.com/en/l/36999999-different-print")
        self.drouot(30)

        sales = self.data()["calendar_sales_data"]["2026-12-03"]
        self.assertEqual({sale["sale_url"]: sale["lot_count"] for sale in sales}, {
            "https://drouot.com/en/v/188405": 1, "": 2,
        })

    def test_mixed_mallet_catalog_preserves_both_represented_start_times(self):
        house = {"auction_house": "Mallet Auction"}
        for number, start_hour, photo in ((1019, 3, "47/823047"), (62, 6, "51/823051")):
            start = datetime(2026, 12, 10, start_hour, tzinfo=timezone.utc)
            inv = self.invaluable(
                number, **house, event_at=start,
                image_url=f"https://image.invaluable.com/housePhotos/malletauctionjapan/{photo}/H3876-L{number}.jpg",
            )
            self.drouot(number, "188574", survivor=inv, **house, event_at=start)
            self.drouot(number + 1, "188574", **house, event_at=start)

        group, = self.data("2026-12-09")["calendar_sales_data"]["2026-12-09"]
        self.assertEqual((group["lot_count"], group["time_label"]), (4, "7:00 PM and 10:00 PM"))

    def test_lempertz_day_sales_retain_their_own_catalogs_and_start_times(self):
        for number, start_hour, photo in ((201, 10, "82/821482"), (437, 13, "83/821483")):
            session = {"auction_house": "Lempertz", "event_at": datetime(2026, 12, 5, start_hour, tzinfo=timezone.utc)}
            inv = self.invaluable(
                number, **session,
                image_url=f"https://image.invaluable.com/housePhotos/Lempertz/{photo}/H0684-L{number}.jpg",
            )
            self.drouot(number, "187112", survivor=inv, **session)
            self.drouot(number + 1, "187112", **session)

        sales = self.data("2026-12-05")["calendar_sales_data"]["2026-12-05"]
        self.assertEqual([(sale["lot_count"], sale["time_label"]) for sale in sales], [(2, "2:00 AM"), (2, "5:00 AM")])
        self.assertEqual([sale["sale_url"] for sale in sales], [
            "https://www.lempertz.com/en/catalogues/detail/1303-1-day-sale-modern-art.html",
            "https://www.lempertz.com/en/catalogues/detail/1303-2-day-sale-contemporary-art.html",
        ])

    def test_published_catalogs_combine_distinct_lots_without_a_common_watched_lot(self):
        cases = [
            ("2026-11-25T14:00:00+00:00", "Il Ponte", "Il Ponte Auction House",
             "188002", 224, 282, "ilPonte/86/822386/H0611"),
            ("2026-12-02T17:00:00+00:00", "Piasa", "Piasa",
             "188158", 65, 35, "Piasa/91/818591/H0837"),
            ("2026-12-11T15:00:00+00:00", "Accademia Fine Art", "Accademia Fine Art",
             "188578", 311, 350, "Accademia/60/823060/H4638"),
        ]
        for clock, drouot_house, inv_house, catalog, drouot_number, inv_number, photo in cases:
            with self.subTest(sale=drouot_house):
                when = datetime.fromisoformat(clock)
                self.drouot(drouot_number, catalog, auction_house=drouot_house, event_at=when)
                inv = self.invaluable(
                    inv_number, auction_house=inv_house, event_at=when,
                    image_url=f"https://image.invaluable.com/housePhotos/{photo}-L{inv_number}.jpg",
                )
                self.invaluable(
                    inv_number + 1, auction_house=inv_house, event_at=when,
                    image_url=inv.image_url.replace(photo, photo.replace("H", "H00")),
                )
                day = when.date().isoformat()
                context = self.data(day)
                sales = context["calendar_sales_data"][day]
                self.assertCountEqual([sale["lot_count"] for sale in sales], [2, 1])
                published, = [sale for sale in sales if sale["lot_count"] == 2]
                self.assertTrue(published["sale_url"])
                self.assertTrue(published["sale_title"])
                self.assertEqual(len(context["calendar_data"][day]), 3)
