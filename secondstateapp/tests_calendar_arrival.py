from datetime import datetime, timezone
from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase

from .calendar_arrival import TIMETABLE_URL, published_lot_arrival
from .calendar_views import _lot_json
from .tests_calendar import CALENDAR_ZONE, watch_lot


def source_lot(**changes):
    values = dict(
        source="Drouot", source_lot_id="35448391", auction_house="Dobiaschofsky Auktionen",
        event_at=datetime(2026, 11, 6, 8, tzinfo=timezone.utc), is_all_day=False,
        lot_number="3466", sale_url="https://drouot.com/en/v/186532", lot_url="",
    )
    values.update(changes)
    return SimpleNamespace(**values)


class PublishedCalendarArrivalTests(SimpleTestCase):
    def test_provider_day_and_afternoon_timestamps_produce_the_same_published_block(self):
        drouot = source_lot()
        invaluable = source_lot(
            source="Invaluable", source_lot_id="206830807", auction_house="Dobiaschofsky Auktionen AG",
            sale_url="https://www.invaluable.com/catalog/A4TLQ5DFCI",
            event_at=datetime(2026, 11, 6, 13, tzinfo=timezone.utc),
        )
        before = [vars(lot).copy() for lot in (drouot, invaluable)]
        expected = published_lot_arrival(drouot)
        self.assertEqual(expected, published_lot_arrival(invaluable))
        self.assertEqual(expected["at"], "2026-11-06T13:30:00+00:00")
        self.assertEqual(expected["session_start_at"], "2026-11-06T13:00:00+00:00")
        self.assertEqual((expected["first_lot"], expected["last_lot"]), (3446, 3467))
        self.assertEqual(expected["source_url"], TIMETABLE_URL)
        self.assertEqual([vars(lot) for lot in (drouot, invaluable)], before)

    def test_official_block_boundaries_and_separate_sessions(self):
        for number, expected, session in (
            (3001, "08:00", "08:00"), (3030, "08:00", "08:00"),
            (3031, "08:15", "08:00"), (3290, "10:15", "08:00"),
            (3401, "13:00", "13:00"), (3445, "13:15", "13:00"),
            (3446, "13:30", "13:00"), (3587, "15:00", "13:00"),
            (3701, "17:00", "17:00"), (3903, "19:00", "17:00"),
        ):
            with self.subTest(number=number):
                result = published_lot_arrival(source_lot(lot_number=str(number)))
                self.assertEqual(result["at"], f"2026-11-06T{expected}:00+00:00")
                self.assertEqual(result["session_start_at"], f"2026-11-06T{session}:00+00:00")
        for number in ("3000", "3291", "3325", "3400", "3588", "3700", "3904", "5140", "", "3466/1", "3466-3467"):
            self.assertIsNone(published_lot_arrival(source_lot(lot_number=number)), number)
        self.assertEqual(published_lot_arrival(source_lot(lot_number="03466A"))["at"], "2026-11-06T13:30:00+00:00")

    def test_house_sale_provider_and_date_must_all_match(self):
        for changes in (
            {"auction_house": "Not Dobiaschofsky Auktionen"},
            {"auction_house": "Dobiaschofsky Auktionen affiliate"},
            {"sale_url": "https://drouot.com/en/v/186533"},
            {"sale_url": "https://drouot.com/en/v/1865320"},
            {"sale_url": "https://drouot.com.evil.test/en/v/186532"},
            {"sale_url": "https://example.test/en/v/186532"},
            {"sale_url": ""}, {"source": "Other"},
            {"event_at": datetime(2026, 11, 5, 8, tzinfo=timezone.utc)},
            {"event_at": datetime(2027, 11, 6, 8, tzinfo=timezone.utc)},
            {"event_at": datetime(2026, 11, 6, 8)},
            {"event_at": None}, {"is_all_day": True},
            {"source": "Invaluable", "sale_url": "https://www.invaluable.com/catalog/PMN86OUHA9"},
            {"source": "Invaluable", "sale_url": "https://www.invaluable.com/catalog/A4TLQ5DFCI", "lot_number": "3001"},
            {"source": "Invaluable", "sale_url": "https://www.invaluable.com/catalog/A4TLQ5DFCI", "lot_number": "3701"},
        ):
            with self.subTest(changes=changes):
                self.assertIsNone(published_lot_arrival(source_lot(**changes)))

    def test_verified_missing_sale_observations_require_provider_id_number_and_lot_link(self):
        for source_id, number, reference, expected in (
            ("206830784", "3443", "217ffff078", "13:15"),
            ("206830861", "3520", "f180321dbe", "14:15"),
        ):
            lot = source_lot(source="Invaluable", source_lot_id=source_id, lot_number=number,
                             sale_url="", lot_url=f"https://www.invaluable.com/auction-lot/catalogue-{number}-c-{reference}")
            self.assertEqual(published_lot_arrival(lot)["at"], f"2026-11-06T{expected}:00+00:00")
            lot.source_lot_id = "another-id"
            self.assertIsNone(published_lot_arrival(lot))
            lot.source_lot_id = source_id
            lot.lot_url += "changed"
            self.assertIsNone(published_lot_arrival(lot))


class CalendarArrivalPayloadTests(TestCase):
    def test_presentation_adds_schedule_without_rewriting_source_or_saved_state(self):
        lot = watch_lot(**vars(source_lot()), artist="Joan Miró", artist_watchlist_name="Joan Miró", won_by_us=True)
        lot.refresh_from_db()
        before = lot.__dict__.copy()
        payload = _lot_json(lot, CALENDAR_ZONE, selected_lot_ids={lot.pk})
        self.assertEqual(payload["arrival_schedule"]["at"], "2026-11-06T13:30:00+00:00")
        self.assertEqual(payload["event_at"], "2026-11-06T08:00:00+00:00")
        self.assertEqual(payload["lot_number"], "3466")
        self.assertTrue(payload["won_by_us"])
        self.assertTrue(payload["email_tray_selected"])
        lot.refresh_from_db()
        for field in ("event_at", "source", "source_lot_id", "lot_number", "sale_url", "won_by_us"):
            self.assertEqual(getattr(lot, field), before[field])
        unrelated = watch_lot(source_lot_id="other-arrival")
        unrelated.refresh_from_db()
        self.assertNotIn("arrival_schedule", _lot_json(unrelated, CALENDAR_ZONE))
