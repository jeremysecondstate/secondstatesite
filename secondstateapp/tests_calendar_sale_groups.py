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
