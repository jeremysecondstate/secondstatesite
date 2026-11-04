"""Oliver's month summaries use the same lots and explicit house registry."""

from datetime import datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import AuctionEmailBatch, AuctionEmailBatchItem, AuctionWatchLot
from .tests_calendar import CALENDAR_ZONE, watch_lot


@override_settings(CALENDAR_TIME_ZONE="America/Los_Angeles", AUCTION_EMAIL_SENDING_ENABLED=False)
class OliverMonthCalendarTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user("oliver-month-admin", is_staff=True)
        self.client.force_login(self.staff)
        clock = patch(
            "secondstateapp.calendar_views.timezone.now",
            return_value=datetime(2026, 7, 20, 12, tzinfo=CALENDAR_ZONE),
        )
        clock.start()
        self.addCleanup(clock.stop)

    def lot(self, identity, house="Bonhams", **changes):
        return watch_lot(source_lot_id=identity, auction_house=house, **changes)

    def calendar(self, **query):
        response = self.client.get(reverse("auction_calendar"), {
            "month": "2026-07", "view": "oliver-calendar", **query,
        })
        self.assertEqual(response.status_code, 200)
        return response.context

    def day(self, context, iso="2026-07-25"):
        return next(day for week in context["weeks"] for day in week if day["iso"] == iso)

    def test_scoped_groups_filter_lots_before_grouping_even_with_a_shared_sale_url(self):
        sale = "https://auction.example/sale/shared"
        partner = self.lot("partner", sale_url=sale, sale_title="Shared source sale")
        outsider = self.lot("outsider", "Another House", sale_url=sale, sale_title="Shared source sale")
        before = list(AuctionWatchLot.objects.order_by("pk").values())

        context = self.calendar()
        day = self.day(context)

        self.assertEqual((day["lot_count"], day["sale_count"]), (2, 1))
        self.assertEqual((day["oliver_lot_count"], day["oliver_sale_count"]), (1, 1))
        self.assertEqual(day["oliver_event_groups"][0]["auction_house"], "Bonhams")
        self.assertEqual(day["oliver_event_groups"][0]["lot_count"], 1)
        self.assertEqual(context["calendar_sales_data"]["2026-07-25"][0]["lot_count"], 2)
        self.assertEqual(context["oliver_calendar_sales_data"]["2026-07-25"][0]["lot_count"], 1)
        self.assertEqual({lot["id"] for lot in context["calendar_data"]["2026-07-25"]}, {partner.pk, outsider.pk})
        self.assertEqual(list(AuctionWatchLot.objects.order_by("pk").values()), before)

    def test_verified_aliases_are_included_without_merging_distinct_sale_sessions(self):
        eligible = [
            self.lot("rago", "Rago Arts and Auction Center", sale_url="https://auction.example/rago"),
            self.lot("bradford", "Bradford's", sale_url="https://auction.example/bradford"),
            self.lot("lama", "Los Angeles Modern Auctions", sale_url="https://auction.example/lama"),
            self.lot("second-rago", "Rago Auctions", sale_url="https://auction.example/second-rago"),
        ]
        outsider = self.lot("unverified-bonhams", "Bonhams Estate Partners", sale_url="https://auction.example/other")
        before = {lot.pk: lot.auction_house for lot in eligible + [outsider]}

        context = self.calendar()
        day = self.day(context)

        self.assertEqual((day["lot_count"], day["sale_count"]), (5, 5))
        self.assertEqual((day["oliver_lot_count"], day["oliver_sale_count"]), (4, 4))
        self.assertEqual(len(day["oliver_event_groups"]), 3)
        self.assertEqual(day["oliver_more_count"], 1)
        scoped_sales = context["oliver_calendar_sales_data"]["2026-07-25"]
        self.assertEqual(len(scoped_sales), 4)
        self.assertEqual({sale["sale_url"] for sale in scoped_sales}, {lot.sale_url for lot in eligible})
        self.assertEqual(dict(AuctionWatchLot.objects.values_list("pk", "auction_house")), before)

    def test_empty_and_nonpartner_days_have_no_oliver_month_events(self):
        self.lot("outsider-only", "Another House")

        context = self.calendar()

        for iso in ("2026-07-25", "2026-07-26"):
            with self.subTest(day=iso):
                day = self.day(context, iso)
                self.assertEqual(day["oliver_event_groups"], [])
                self.assertEqual((day["oliver_lot_count"], day["oliver_sale_count"], day["oliver_more_count"]), (0, 0, 0))
        self.assertEqual(context["oliver_calendar_sales_data"]["2026-07-25"], [])
        self.assertEqual(context["oliver_upcoming_groups"], [])

    def test_historical_lots_remain_while_superseded_copies_stay_excluded(self):
        survivor = self.lot("historical", active=False, sale_url="https://auction.example/historical")
        self.lot("superseded", active=False, superseded_by=survivor, sale_url="https://auction.example/copy")

        context = self.calendar()
        day = self.day(context)

        self.assertEqual((day["lot_count"], day["oliver_lot_count"]), (1, 1))
        self.assertTrue(day["oliver_event_groups"][0]["ended"])
        self.assertEqual([lot["id"] for lot in context["calendar_data"]["2026-07-25"]], [survivor.pk])
        self.assertEqual(len(context["oliver_calendar_sales_data"]["2026-07-25"]), 1)
        self.assertEqual(context["oliver_upcoming_groups"], [])

    def test_oliver_upcoming_is_scoped_before_the_all_house_lot_cap(self):
        outside_at = datetime(2026, 8, 3, 14, tzinfo=CALENDAR_ZONE)
        AuctionWatchLot.objects.bulk_create([
            AuctionWatchLot(
                source="Invaluable", source_lot_id=f"crowded-{index}", artist="Joan Miró",
                title=f"Unrelated artwork {index}", auction_house="Another House",
                sale_title="Crowded unrelated sale", sale_url="https://auction.example/crowded",
                event_at=outside_at, active=True,
            ) for index in range(1001)
        ])
        partner_at = datetime(2026, 8, 4, 14, tzinfo=CALENDAR_ZONE)
        partner = self.lot("later-partner", "Bradford's", event_at=partner_at,
                           sale_url="https://auction.example/later-partner", won_by_us=True)
        historical = self.lot("later-historical", "Bonhams", event_at=partner_at, active=False,
                              sale_url="https://auction.example/later-historical")
        outsider = self.lot("same-day-outsider", "Another House", event_at=partner_at,
                            sale_url="https://auction.example/same-day-outsider")
        batch = AuctionEmailBatch.objects.create()
        AuctionEmailBatchItem.objects.create(batch=batch, lot=partner, selected_by=self.staff)
        before = list(AuctionWatchLot.objects.filter(pk__in=[partner.pk, historical.pk, outsider.pk]).order_by("pk").values())

        context = self.calendar()

        self.assertEqual([sale["sale_url"] for sale in context["upcoming_groups"]], ["https://auction.example/crowded"])
        self.assertEqual([sale["sale_url"] for sale in context["oliver_upcoming_groups"]], [partner.sale_url])
        self.assertEqual(context["oliver_upcoming_groups"][0]["date_iso"], "2026-08-04")
        records = {lot["id"]: lot for lot in context["calendar_data"]["2026-08-04"]}
        self.assertEqual(set(records), {partner.pk, historical.pk, outsider.pk})
        self.assertTrue(records[partner.pk]["email_tray_selected"])
        self.assertTrue(records[partner.pk]["won_by_us"])
        self.assertEqual(records[partner.pk]["id"], partner.pk)
        self.assertEqual(len(context["calendar_sales_data"]["2026-08-04"]), 3)
        self.assertEqual(len(context["oliver_calendar_sales_data"]["2026-08-04"]), 2)
        self.assertEqual(context["initial_oliver_day"], "2026-08-04")
        self.assertEqual(list(AuctionWatchLot.objects.filter(pk__in=records).order_by("pk").values()), before)
        self.assertEqual(AuctionEmailBatchItem.objects.filter(batch=batch).count(), 1)

    def test_initial_oliver_day_uses_an_eligible_date_and_all_views_share_original_records(self):
        outsider = self.lot("earlier-outsider", "Another House", event_at=datetime(2026, 7, 22, 14, tzinfo=CALENDAR_ZONE))
        partner = self.lot("later-partner", "Phillips")

        for view in ("calendar", "catalog", "oliver", "oliver-calendar", "research"):
            with self.subTest(view=view):
                context = self.calendar(view=view)
                self.assertEqual(context["initial_day"], "2026-07-22")
                self.assertEqual(context["initial_oliver_day"], "2026-07-25")
                records = [lot for lots in context["calendar_data"].values() for lot in lots]
                self.assertEqual({lot["id"] for lot in records}, {outsider.pk, partner.pk})
                self.assertEqual(next(lot for lot in records if lot["id"] == outsider.pk)["auction_house"], "Another House")

    def test_scoped_upcoming_session_counts_use_the_complete_day_beyond_its_own_cap(self):
        event_at = datetime(2026, 8, 4, 14, tzinfo=CALENDAR_ZONE)
        sale_url = "https://auction.example/large-partner-session"
        AuctionWatchLot.objects.bulk_create([
            AuctionWatchLot(
                source="Invaluable", source_lot_id=f"large-partner-{index}",
                artist="Zao Wou-Ki" if index == 1000 else "Joan Miró",
                title=f"Partner artwork {index}", auction_house="Bonhams",
                sale_title="Large partner session", sale_url=sale_url,
                event_at=event_at, active=True,
            ) for index in range(1001)
        ])
        self.lot("large-session-ended", event_at=event_at, active=False, sale_url=sale_url)
        self.lot("large-session-outsider", "Another House", event_at=event_at, sale_url=sale_url)

        context = self.calendar()

        self.assertEqual(len(context["oliver_upcoming_groups"]), 1)
        group = context["oliver_upcoming_groups"][0]
        self.assertEqual(group["lot_count"], 1001)
        self.assertIn("Zao", group["artists"])
        self.assertNotIn("_calendar_sale_identity", group)
        self.assertEqual(len(context["calendar_data"]["2026-08-04"]), 1003)
        self.assertEqual(context["oliver_calendar_sales_data"]["2026-08-04"][0]["lot_count"], 1002)

