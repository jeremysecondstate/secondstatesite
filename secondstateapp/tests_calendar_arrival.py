from datetime import datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase, TestCase

from .calendar_arrival import (
    HERITAGE_8256_URL, TIMETABLE_URL, ZWAAN_117_TIMETABLE_URL,
    published_lot_arrival, sale_arrival_estimate,
)
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


def heritage_lot(**changes):
    return source_lot(**(dict(
        source_lot_id="35700126", auction_house="Heritage Auctions",
        event_at=datetime(2026, 11, 11, 16, 50, tzinfo=timezone.utc),
        lot_number="79087", sale_url="https://drouot.com/en/v/187633",
    ) | changes))


def zwaan_lot(**changes):
    return source_lot(**(dict(
        source="Invaluable", source_lot_id="207090363", auction_house="Veilinggebouw de Zwaan",
        event_at=datetime(2026, 11, 12, 9, tzinfo=timezone.utc),
        lot_number="6816", sale_url="",
        lot_url="https://www.invaluable.com/auction-lot/francisco-zuniga-1912-1998-6816-c-b76b923688",
    ) | changes))


def sothebys_lot(**changes):
    sale = "https://www.sothebys.com/en/buy/auction/2026/modern-contemporary-discoveries-de2640"
    return source_lot(**(dict(
        source="Sotheby's", source_lot_id="DE2640:37", auction_house="Sotheby's",
        event_at=datetime(2026, 11, 12, 13, 36, tzinfo=timezone.utc),
        lot_number="37", sale_url=sale, lot_url=sale + "/untitled?locale=en",
    ) | changes))


class SothebysClosingTests(SimpleTestCase):
    def test_observed_per_lot_closing_is_used_without_a_number_derived_offset(self):
        for number, minute in (("3", 3), ("37", 36), ("56", 54)):
            lot = sothebys_lot(lot_number=number, source_lot_id=f"DE2640:{number}",
                              event_at=datetime(2026, 11, 12, 13, minute, tzinfo=timezone.utc))
            before = vars(lot).copy()
            self.assertEqual(published_lot_arrival(lot), {
                "kind": "published_closing", "at": lot.event_at.isoformat(), "source_url": lot.lot_url,
            })
            self.assertIsNone(sale_arrival_estimate(lot))
            self.assertEqual(vars(lot), before)

    def test_published_closing_requires_this_source_sale_id_date_and_lot_link(self):
        sale = sothebys_lot().sale_url
        for changes in (
            {"source": "Invaluable"}, {"auction_house": "Sotheby's affiliate"},
            {"source_lot_id": "DE2641:37"}, {"source_lot_id": "DE2640:38"},
            {"lot_number": "37A"}, {"lot_number": ""}, {"is_all_day": True},
            {"event_at": None}, {"event_at": datetime(2026, 11, 12, 13, 36)},
            {"event_at": datetime(2026, 11, 13, 13, 36, tzinfo=timezone.utc)},
            {"sale_url": sale + "0"}, {"sale_url": ""},
            {"sale_url": sale.replace("https:", "http:")},
            {"sale_url": sale.replace("sothebys.com", "sothebys.com.evil.test")},
            {"sale_url": sale.replace("www.sothebys.com", "user@www.sothebys.com")},
            {"sale_url": sale.replace("www.sothebys.com", "www.sothebys.com:443")},
            {"lot_url": sale}, {"lot_url": sale + "/untitled/another-lot"},
            {"lot_url": sale.replace("de2640", "de2641") + "/untitled"},
            {"lot_url": sale.replace("sothebys.com", "sothebys.com.evil.test") + "/untitled"},
            {"lot_url": sale.replace("www.sothebys.com", "user@www.sothebys.com") + "/untitled"},
            {"lot_url": sale.replace("www.sothebys.com", "www.sothebys.com:443") + "/untitled"},
            {"lot_url": "https://[invalid"},
        ):
            with self.subTest(changes=changes):
                self.assertIsNone(published_lot_arrival(sothebys_lot(**changes)))


class ZwaanSessionArrivalTests(SimpleTestCase):
    def test_zuniga_uses_evening_session_with_default_pace_not_whole_day_number(self):
        lot = zwaan_lot()
        before = vars(lot).copy()
        self.assertEqual(sale_arrival_estimate(lot), {
            "kind": "session_estimate",
            "session_start_at": "2026-11-12T18:00:00+00:00",
            "first_lot": 6800, "last_lot": 7015, "lots_per_hour": 60,
            "source_url": ZWAAN_117_TIMETABLE_URL,
        })
        self.assertIsNone(published_lot_arrival(lot))
        self.assertEqual(vars(lot), before)

    def test_each_session_has_its_own_start_and_range_in_both_number_directions(self):
        for first, last, hour in ((6000, 6233, 9), (6400, 6586, 13), (6800, 7015, 18)):
            for number in (str(first), str(last), f"0{first}A"):
                with self.subTest(number=number):
                    lot = zwaan_lot(source="Drouot", auction_house="  DE ZWAAN\tAmsterdam ",
                                    sale_url="https://drouot.com/en/v/186921", lot_number=number)
                    result = sale_arrival_estimate(lot)
                    self.assertEqual(result["session_start_at"], f"2026-11-12T{hour:02d}:00:00+00:00")
                    self.assertEqual((result["first_lot"], result["last_lot"]), (first, last))
                    self.assertEqual(result["kind"], "session_estimate")
                    self.assertEqual(result["lots_per_hour"], 60)
        for number in ("5999", "6234", "6399", "6587", "6799", "7016", "6816/1", "6816-6817", ""):
            with self.subTest(number=number):
                self.assertIsNone(sale_arrival_estimate(zwaan_lot(
                    source="Drouot", sale_url="https://drouot.com/en/v/186921", lot_number=number)))

    def test_session_matching_requires_exact_house_provider_date_and_sale(self):
        for changes in (
            {"auction_house": "De Zwaan Amsterdam affiliate"}, {"auction_house": "De Zwaan"},
            {"source": "Other"}, {"is_all_day": True}, {"event_at": None},
            {"event_at": datetime(2026, 11, 12, 9)},
            {"event_at": datetime(2026, 11, 11, 9, tzinfo=timezone.utc)},
            {"event_at": datetime(2026, 11, 13, 9, tzinfo=timezone.utc)},
            {"event_at": datetime(2027, 11, 12, 9, tzinfo=timezone.utc)},
            {"source": "Drouot", "sale_url": ""},
            {"source": "Drouot", "sale_url": "https://drouot.com/en/v/186922"},
            {"source": "Drouot", "sale_url": "https://drouot.com/en/v/1869210"},
            {"source": "Drouot", "sale_url": "https://drouot.com.evil.test/en/v/186921"},
            {"source": "Drouot", "sale_url": "http://drouot.com/en/v/186921"},
            {"source": "Drouot", "sale_url": "https://[invalid"},
            {"sale_url": "https://www.invaluable.com/catalog/unrelated-sale"},
        ):
            with self.subTest(changes=changes):
                self.assertIsNone(sale_arrival_estimate(zwaan_lot(**changes)))
        self.assertIsNotNone(sale_arrival_estimate(zwaan_lot(
            event_at=datetime(2026, 11, 12, 10, tzinfo=ZoneInfo("Europe/Amsterdam")))))

    def test_missing_invaluable_sale_requires_scoped_id_number_and_source_link(self):
        for changes in (
            {"source_lot_id": "unknown"}, {"lot_number": "6817"},
            {"lot_url": ""},
            {"lot_url": "https://www.invaluable.com/auction-lot/francisco-zuniga-6816-c-wrong"},
            {"lot_url": "https://www.invaluable.com.evil.test/auction-lot/francisco-zuniga-6816-c-b76b923688"},
            {"lot_url": "http://www.invaluable.com/auction-lot/francisco-zuniga-6816-c-b76b923688"},
            {"lot_url": "https://[invalid"},
        ):
            with self.subTest(changes=changes):
                self.assertIsNone(sale_arrival_estimate(zwaan_lot(**changes)))

    def test_verified_catalogue_identifies_new_observations_without_borrowing_another_sale(self):
        for number, expected in (("6000", "09:00"), ("6400", "13:00"), ("6816", "18:00")):
            with self.subTest(number=number):
                lot = zwaan_lot(source_lot_id="new-catalogue-observation", lot_number=number,
                                sale_url="https://www.invaluable.com/catalog/9ESB0TMK4J/", lot_url="")
                self.assertEqual(sale_arrival_estimate(lot)["session_start_at"], f"2026-11-12T{expected}:00+00:00")
        for sale_url in ("https://www.invaluable.com/catalog/9ESB0TMK4J0",
                         "https://www.invaluable.com.evil.test/catalog/9ESB0TMK4J",
                         "http://www.invaluable.com/catalog/9ESB0TMK4J"):
            with self.subTest(sale_url=sale_url):
                self.assertIsNone(sale_arrival_estimate(zwaan_lot(sale_url=sale_url)))


class SaleArrivalEstimateTests(SimpleTestCase):
    def test_verified_heritage_sale_uses_official_session_and_pace(self):
        for number in ("79001", "79087", "79095", "79230", " 079087A "):
            with self.subTest(number=number):
                lot = heritage_lot(lot_number=number)
                before = vars(lot).copy()
                self.assertEqual(sale_arrival_estimate(lot), {
                    "session_start_at": "2026-11-11T17:00:00+00:00",
                    "first_lot": 79001, "last_lot": 79230, "lots_per_hour": 54,
                    "source_url": HERITAGE_8256_URL,
                })
                self.assertEqual(vars(lot), before)
                self.assertIsNone(published_lot_arrival(lot))

    def test_sale_identity_accepts_verified_url_forms_and_house_normalization(self):
        for url in (
            "https://drouot.com/en/v/187633", "https://www.drouot.com/fr/v/187633/",
            "https://drouot.com/v/187633/tiffany-lalique-art-glass?lang=en",
        ):
            with self.subTest(url=url):
                self.assertIsNotNone(sale_arrival_estimate(heritage_lot(
                    sale_url=url, auction_house="  HERITAGE\tAuctions ",
                    event_at=datetime(2026, 11, 11, 10, 50, tzinfo=ZoneInfo("America/Chicago")),
                )))

    def test_unverified_sales_sources_dates_and_numbers_do_not_receive_estimates(self):
        for changes in (
            {"auction_house": "Heritage Auctions affiliate"}, {"auction_house": "Heritage"},
            {"source": "Invaluable"}, {"source": "Heritage"},
            {"sale_url": "https://drouot.com/en/v/187634"},
            {"sale_url": "https://drouot.com/en/v/1876330"},
            {"sale_url": "https://drouot.com/en/v/187633/extra/path"},
            {"sale_url": "https://drouot.com.evil.test/en/v/187633"},
            {"sale_url": "https://drouot.com@evil.test/en/v/187633"},
            {"sale_url": "http://drouot.com/en/v/187633"},
            {"sale_url": "https://[invalid"}, {"sale_url": ""},
            {"event_at": datetime(2026, 11, 10, 17, tzinfo=timezone.utc)},
            {"event_at": datetime(2026, 11, 12, 17, tzinfo=timezone.utc)},
            {"event_at": datetime(2027, 11, 11, 17, tzinfo=timezone.utc)},
            {"event_at": datetime(2026, 11, 11, 17)},
            {"event_at": None}, {"is_all_day": True},
            {"lot_number": "79000"}, {"lot_number": "79231"}, {"lot_number": "80000"},
            {"lot_number": "79087/1"}, {"lot_number": "79087-79088"},
            {"lot_number": "79087.5"}, {"lot_number": ""},
        ):
            with self.subTest(changes=changes):
                self.assertIsNone(sale_arrival_estimate(heritage_lot(**changes)))


class PublishedCalendarArrivalTests(SimpleTestCase):
    def test_november_fifth_uses_the_published_morning_and_resumed_afternoon_blocks(self):
        for source, sale_url in (
            ("Drouot", "https://drouot.com/en/v/186531"),
            ("Invaluable", "https://www.invaluable.com/catalog/JS1Q8ZMLH2"),
        ):
            for number, expected, session in (
                (2001, "08:00", "08:00"), (2040, "08:15", "08:00"),
                (2057, "08:20", "08:00"), (2201, "08:25", "08:00"),
                (2268, "08:55", "08:00"), (2376, "09:40", "08:00"),
                (2442, "10:10", "08:00"), (2443, "13:00", "13:00"),
                (2472, "13:00", "13:00"), (2473, "13:15", "13:00"),
                (2531, "13:30", "13:00"), (2532, "13:45", "13:00"),
                (2589, "14:00", "13:00"), (2617, "14:15", "13:00"),
                (2804, "15:10", "13:00"), (2936, "15:30", "13:00"),
            ):
                with self.subTest(source=source, number=number):
                    lot = source_lot(source=source, sale_url=sale_url, lot_number=str(number),
                                     event_at=datetime(2026, 11, 5, 8, tzinfo=timezone.utc))
                    before = vars(lot).copy()
                    result = published_lot_arrival(lot)
                    self.assertIsNotNone(result)
                    self.assertEqual(result["at"], f"2026-11-05T{expected}:00+00:00")
                    self.assertEqual(result["session_start_at"], f"2026-11-05T{session}:00+00:00")
                    self.assertEqual(result["source_url"], TIMETABLE_URL)
                    self.assertEqual(vars(lot), before)

    def test_november_fifth_requires_its_own_sale_date_and_published_number_range(self):
        base = dict(source="Invaluable", sale_url="https://www.invaluable.com/catalog/JS1Q8ZMLH2",
                    source_lot_id="206829153", lot_number="2376",
                    event_at=datetime(2026, 11, 5, 8, tzinfo=timezone.utc))
        for changes in (
            {"sale_url": "https://www.invaluable.com/catalog/A4TLQ5DFCI"},
            {"sale_url": "https://www.invaluable.com.evil.test/catalog/JS1Q8ZMLH2"},
            {"source": "Drouot", "sale_url": "https://drouot.com/en/v/186532"},
            {"event_at": datetime(2026, 11, 6, 8, tzinfo=timezone.utc)},
            {"event_at": datetime(2027, 11, 5, 8, tzinfo=timezone.utc)},
            {"lot_number": "2058"}, {"lot_number": "2200"},
            {"lot_number": "2590"}, {"lot_number": "2937"}, {"lot_number": "3466"},
            {"sale_url": "", "source_lot_id": "206829045", "lot_number": "2268",
             "lot_url": "https://www.invaluable.com/auction-lot/dali-salvador-nach-after-normandie-2268-c-f0edf01163"},
            {"sale_url": "", "source_lot_id": "206830784", "lot_number": "3443",
             "lot_url": "https://www.invaluable.com/auction-lot/catalogue-3443-c-217ffff078"},
        ):
            with self.subTest(changes=changes):
                self.assertIsNone(published_lot_arrival(source_lot(**(base | changes))))

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
    def test_published_closing_payload_preserves_raw_credit_time_and_saved_work(self):
        lot = watch_lot(**vars(sothebys_lot()), artist="After Pablo Picasso",
                        artist_watchlist_name="Pablo Picasso", won_by_us=True)
        lot.refresh_from_db()
        before = {field.attname: getattr(lot, field.attname) for field in lot._meta.concrete_fields}
        payload = _lot_json(lot, CALENDAR_ZONE, selected_lot_ids={lot.pk},
                            research_queue_state={lot.pk: {"status": "queued"}})
        self.assertEqual(payload["arrival_schedule"], published_lot_arrival(lot))
        self.assertEqual(payload["event_at"], "2026-11-12T13:36:00+00:00")
        self.assertEqual(payload["time"], "5:36 AM")
        self.assertEqual(payload["attribution_label"], "After")
        self.assertTrue(payload["won_by_us"])
        self.assertTrue(payload["email_tray_selected"])
        self.assertTrue(payload["research_queue_selected"])
        self.assertEqual(payload["lot_url"], lot.lot_url)
        self.assertNotIn("arrival_estimate", payload)
        lot.refresh_from_db()
        self.assertEqual({field.attname: getattr(lot, field.attname) for field in lot._meta.concrete_fields}, before)

    def test_zwaan_session_preserves_raw_time_provenance_and_saved_selections(self):
        lot = watch_lot(**vars(zwaan_lot()), artist="Francisco Zúñiga",
                        artist_watchlist_name="Francisco Zúñiga", won_by_us=True,
                        artprice_url="https://www.artprice.com/artist/1/example/lots/pasts")
        lot.refresh_from_db()
        before = {f.attname: getattr(lot, f.attname) for f in lot._meta.concrete_fields}
        payload = _lot_json(lot, CALENDAR_ZONE, selected_lot_ids={lot.pk},
                            research_queue_state={lot.pk: {"status": "queued"}})
        self.assertEqual(payload["arrival_estimate"], sale_arrival_estimate(lot))
        self.assertEqual(payload["event_at"], "2026-11-12T09:00:00+00:00")
        self.assertEqual(payload["time"], "1:00 AM")
        self.assertEqual(payload["lot_number"], "6816")
        self.assertEqual(payload["artist"], "Zúñiga, Francisco")
        for field in ("artprice_url", "lot_url", "sale_url"):
            self.assertEqual(payload[field], getattr(lot, field))
        self.assertTrue(payload["won_by_us"])
        self.assertTrue(payload["email_tray_selected"])
        self.assertTrue(payload["research_queue_selected"])
        self.assertEqual(payload["research_queue_status"], "queued")
        self.assertNotIn("arrival_schedule", payload)
        lot.refresh_from_db()
        self.assertEqual({f.attname: getattr(lot, f.attname) for f in lot._meta.concrete_fields}, before)

    def test_official_sale_estimate_preserves_proxy_time_source_and_saved_state(self):
        lot = watch_lot(**vars(heritage_lot()), artist="Alphonse Mucha",
                        artist_watchlist_name="Alphonse Mucha", won_by_us=True,
                        artprice_url="https://www.artprice.com/artist/20603/alphonse-mucha/lots/pasts")
        lot.refresh_from_db()
        before = {f.attname: getattr(lot, f.attname) for f in lot._meta.concrete_fields}
        queue = {lot.pk: {"status": "queued"}}
        payload = _lot_json(lot, CALENDAR_ZONE, selected_lot_ids={lot.pk}, research_queue_state=queue)
        self.assertEqual(payload["arrival_estimate"], sale_arrival_estimate(lot))
        self.assertEqual(payload["event_at"], "2026-11-11T16:50:00+00:00")
        self.assertEqual(payload["time"], "8:50 AM")
        self.assertEqual(payload["lot_number"], "79087")
        self.assertEqual(payload["artist"], "Mucha, Alphonse")
        self.assertEqual(payload["artprice_url"], lot.artprice_url)
        self.assertEqual(payload["sale_url"], lot.sale_url)
        self.assertEqual(payload["lot_url"], lot.lot_url)
        self.assertTrue(payload["won_by_us"])
        self.assertTrue(payload["email_tray_selected"])
        self.assertTrue(payload["research_queue_selected"])
        self.assertEqual(payload["research_queue_status"], "queued")
        self.assertNotIn("arrival_schedule", payload)
        lot.refresh_from_db()
        self.assertEqual({f.attname: getattr(lot, f.attname) for f in lot._meta.concrete_fields}, before)
        unrelated = watch_lot(source_lot_id="other-sale-estimate")
        unrelated.refresh_from_db()
        self.assertNotIn("arrival_estimate", _lot_json(unrelated, CALENDAR_ZONE))

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
