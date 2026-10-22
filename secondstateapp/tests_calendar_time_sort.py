"""Calendar time sorting uses real instants and never invents times for TBA lots."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .calendar_views import _lot_json
from .tests_calendar import watch_lot


CALENDAR_ZONE = ZoneInfo("America/Los_Angeles")


@override_settings(CALENDAR_TIME_ZONE="America/Los_Angeles", AUCTION_EMAIL_SENDING_ENABLED=False)
class CalendarTimeSortTests(TestCase):
    def lot_payload(self, lot):
        # Match the view's ORM-loaded values (including Decimal price fields).
        lot.refresh_from_db()
        return _lot_json(lot, CALENDAR_ZONE)

    def test_timed_payload_preserves_the_instant_with_a_timezone(self):
        instant = datetime(2026, 10, 22, 9, 30, tzinfo=timezone.utc)
        lot = watch_lot(event_at=instant)

        payload = self.lot_payload(lot)

        parsed = datetime.fromisoformat(payload["event_at"])
        self.assertIsNotNone(parsed.utcoffset())
        self.assertEqual(parsed, instant)
        self.assertEqual(payload["time"], "2:30 AM")

    def test_real_midnight_remains_a_known_time(self):
        instant = datetime(2026, 10, 22, 0, 0, tzinfo=CALENDAR_ZONE)
        lot = watch_lot(event_at=instant, is_all_day=False)

        payload = self.lot_payload(lot)

        self.assertEqual(datetime.fromisoformat(payload["event_at"]), instant)
        self.assertEqual(payload["time"], "12:00 AM")

    def test_date_only_lot_has_no_sort_time_even_with_a_placeholder_timestamp(self):
        lot = watch_lot(
            event_at=datetime(2026, 10, 22, 0, 0, tzinfo=CALENDAR_ZONE),
            is_all_day=True,
        )

        payload = self.lot_payload(lot)

        self.assertIsNone(payload["event_at"])
        self.assertEqual(payload["time"], "Time TBA")
        lot.refresh_from_db()
        self.assertIsNotNone(lot.event_at, "display sorting must preserve the stored sale date")

    def test_missing_event_has_no_sort_time(self):
        lot = watch_lot(event_at=None)

        payload = self.lot_payload(lot)

        self.assertIsNone(payload["event_at"])
        self.assertEqual(payload["time"], "Time TBA")

    def test_ended_lot_retains_its_known_auction_time(self):
        instant = datetime(2026, 10, 22, 9, 0, tzinfo=timezone.utc)
        lot = watch_lot(event_at=instant, active=False)

        payload = self.lot_payload(lot)

        self.assertTrue(payload["ended"])
        self.assertEqual(datetime.fromisoformat(payload["event_at"]), instant)

    def test_calendar_renders_both_time_sorts_and_the_sortable_payload(self):
        staff = get_user_model().objects.create_user("time-sort-staff", is_staff=True)
        self.client.force_login(staff)
        instant = datetime(2026, 10, 22, 9, 0, tzinfo=timezone.utc)
        lot = watch_lot(event_at=instant)

        response = self.client.get(reverse("auction_calendar"), {"month": "2026-10", "day": "2026-10-22"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<option value="time_asc">Auction time: earliest first</option>', html=True)
        self.assertContains(response, '<option value="time_desc">Auction time: latest first</option>', html=True)
        payload = next(item for item in response.context["calendar_data"]["2026-10-22"] if item["id"] == lot.pk)
        self.assertEqual(datetime.fromisoformat(payload["event_at"]), instant)
