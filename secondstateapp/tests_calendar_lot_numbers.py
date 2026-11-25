from datetime import datetime, timezone
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from .calendar_duplicates import fingerprint
from .calendar_lot_numbers import calendar_lot_number
from .models import AuctionWatchLot
from .tests_calendar import watch_lot


def leger_values(**changes):
    return {
        "source": "Drouot", "source_lot_id": "36007953",
        "auction_house": "Quai des Enchères", "lot_number": "97",
        "event_at": datetime(2026, 11, 20, 13, 30, tzinfo=timezone.utc),
        "sale_url": "https://drouot.com/en/v/187811",
        "lot_url": "https://drouot.com/en/l/36007953-fernand-leger-1881-1955-couple-lithograph-signed-in-the",
        **changes,
    }


def dali_values(**changes):
    return {
        "source": "Drouot", "source_lot_id": "36035570",
        "auction_house": "Les Andelys Enchères", "lot_number": "601",
        "event_at": datetime(2026, 12, 12, 12, tzinfo=timezone.utc),
        "sale_url": "https://drouot.com/en/v/188346",
        "lot_url": "https://drouot.com/en/l/36035570-salvador-dali-1904-1989-the-lion-signed-and-numbered-115-195",
        **changes,
    }


class CalendarLotNumberTests(SimpleTestCase):
    def test_ivoire_troyes_picasso_displays_its_published_suffix(self):
        lot = SimpleNamespace(
            source="Drouot", source_lot_id="35825863", auction_house="Ivoire Troyes - Boisseau-Pomez",
            lot_number="106", event_at=datetime(2026, 11, 26, 8, tzinfo=timezone.utc),
            sale_url="https://drouot.com/en/v/187807", lot_url="https://drouot.com/en/l/35825863",
        )
        self.assertEqual(calendar_lot_number(lot), "106-1")
        self.assertEqual(lot.lot_number, "106")

    def test_artcurial_pinocchio_retains_the_published_suffix(self):
        lot = SimpleNamespace(
            source="Drouot", source_lot_id="35815049", auction_house="Artcurial", lot_number="75",
            event_at=datetime(2026, 11, 24, 15, tzinfo=timezone.utc),
            sale_url="https://drouot.com/en/v/187761", lot_url="https://drouot.com/fr/l/35815049",
        )
        self.assertEqual(calendar_lot_number(lot), "75-b")
        self.assertEqual(lot.lot_number, "75")
        lot.sale_url = "https://drouot.com/en/v/187762"
        self.assertEqual(calendar_lot_number(lot), "75")

    def test_verified_suffix_is_display_only(self):
        lot = SimpleNamespace(**leger_values())
        before = vars(lot).copy()
        self.assertEqual(calendar_lot_number(lot), "97-1")
        self.assertEqual(vars(lot), before)

    def test_neighbors_and_changed_source_facts_keep_their_numbers(self):
        cases = (
            {"source_lot_id": "35879216", "lot_url": "https://drouot.com/en/l/35879216-joan-miro"},
            {"source": "Invaluable"}, {"auction_house": "Another house"},
            {"lot_number": "98"}, {"lot_number": "97-2"}, {"lot_number": "97-1"},
            {"event_at": datetime(2026, 11, 21, 13, 30, tzinfo=timezone.utc)},
            {"event_at": datetime(2026, 11, 20, 13, 30)}, {"event_at": None},
            {"sale_url": "https://drouot.com/en/v/187812"}, {"sale_url": ""},
            {"lot_url": "https://drouot.com/en/l/36007954-fernand-leger"},
            {"lot_url": "https://drouot.com.example/en/l/36007953"},
            {"sale_url": "https://drouot.com/en/v/1878110"},
        )
        for changes in cases:
            with self.subTest(changes=changes):
                lot = SimpleNamespace(**leger_values(**changes))
                self.assertEqual(calendar_lot_number(lot), lot.lot_number)

    def test_sale_date_uses_paris_and_source_urls_accept_language_and_slug(self):
        lot = SimpleNamespace(**leger_values(
            event_at=datetime(2026, 11, 19, 23, 30, tzinfo=timezone.utc),
            sale_url="https://drouot.com/fr/v/187811-arts-decoratifs-du-xxe-design/",
            lot_url="https://drouot.com/fr/l/36007953",
        ))
        self.assertEqual(calendar_lot_number(lot), "97-1")
        lot.event_at = datetime(2026, 11, 20, 23, 30, tzinfo=timezone.utc)
        self.assertEqual(calendar_lot_number(lot), "97")

    def test_lion_suffix_preserves_raw_number_and_uses_the_bound_paris_sale_date(self):
        lot = SimpleNamespace(**dali_values())
        before = vars(lot).copy()
        self.assertEqual(calendar_lot_number(lot), "601-1")
        self.assertEqual(vars(lot), before)
        lot.event_at = datetime(2026, 12, 11, 23, 30, tzinfo=timezone.utc)
        lot.sale_url = "https://drouot.com/fr/v/188346-tableaux/"
        lot.lot_url = "https://drouot.com/fr/l/36035570"
        self.assertEqual(calendar_lot_number(lot), "601-1")
        lot.event_at = datetime(2026, 12, 12, 23, 30, tzinfo=timezone.utc)
        self.assertEqual(calendar_lot_number(lot), "601")

    def test_lion_correction_rejects_companion_and_changed_sale_identities(self):
        cases = (
            {"source_lot_id": "36035569", "lot_url": "https://drouot.com/en/l/36035569-salvador-dali"},
            {"source": "Invaluable"}, {"auction_house": "Another house"},
            {"lot_number": "602"}, {"lot_number": "601-1"}, {"lot_number": "601-2"},
            {"event_at": datetime(2026, 12, 13, 12, tzinfo=timezone.utc)},
            {"event_at": datetime(2026, 12, 12, 12)}, {"event_at": None},
            {"sale_url": "https://drouot.com/en/v/188347"}, {"sale_url": ""},
            {"sale_url": "https://drouot.com/en/v/1883460"},
            {"lot_url": "https://drouot.com/en/l/36035569-salvador-dali"},
            {"lot_url": "https://drouot.com.example/en/l/36035570"},
        )
        for changes in cases:
            with self.subTest(changes=changes):
                lot = SimpleNamespace(**dali_values(**changes))
                self.assertEqual(calendar_lot_number(lot), lot.lot_number)


@override_settings(CALENDAR_TIME_ZONE="America/Los_Angeles")
class CalendarLotNumberPayloadTests(TestCase):
    def test_shared_views_preserve_both_works_source_fingerprints_and_house_scope(self):
        self.client.force_login(get_user_model().objects.create_user("number-admin", is_staff=True))
        leger = watch_lot(**leger_values(), artist="Fernand Léger", artist_watchlist_name="Fernand Léger", title="Couple")
        miro = watch_lot(**leger_values(source_lot_id="35879216", lot_url="https://drouot.com/en/l/35879216-joan-miro"),
                         artist="Joan Miró", artist_watchlist_name="Joan Miró", title="El Innocente")
        before = {lot.pk: AuctionWatchLot.objects.filter(pk=lot.pk).values().get() for lot in (leger, miro)}
        fingerprints = {lot.pk: fingerprint(lot) for lot in (leger, miro)}
        for view in ("calendar", "catalog", "oliver-calendar", "oliver", "research"):
            with self.subTest(view=view):
                response = self.client.get(reverse("auction_calendar"), {
                    "month": "2026-11", "day": "2026-11-20", "view": view, "lot": leger.pk,
                })
                self.assertEqual(response.status_code, 200)
                lots = {lot["id"]: lot for lot in response.context["calendar_data"]["2026-11-20"]}
                self.assertEqual(set(lots), {leger.pk, miro.pk})
                self.assertEqual(lots[leger.pk]["lot_number"], "97-1")
                self.assertEqual(lots[leger.pk]["arrival_lot_number"], "97")
                self.assertEqual(lots[miro.pk]["lot_number"], "97")
                self.assertNotIn("arrival_lot_number", lots[miro.pk])
                self.assertFalse(lots[leger.pk]["oliver_house"])
        for lot in (leger, miro):
            lot.refresh_from_db()
            self.assertEqual(AuctionWatchLot.objects.filter(pk=lot.pk).values().get(), before[lot.pk])
            self.assertEqual(fingerprint(lot), fingerprints[lot.pk])

    def test_lion_and_pantagruel_remain_distinct_in_shared_view_payloads(self):
        self.client.force_login(get_user_model().objects.create_user("dali-number-admin", is_staff=True))
        lion = watch_lot(**dali_values(), artist="Salvador Dalí", artist_watchlist_name="Salvador Dalí",
                         title="The Lion. Signed and numbered 115/195 lithograph on watermarked paper. 75 x 54 cm")
        pantagruel = watch_lot(**dali_values(
            source_lot_id="36035569",
            lot_url="https://drouot.com/en/l/36035569-salvador-dali-1904-1989-pantagruels-humorous-dreams-1973",
        ), artist="Salvador Dalí", artist_watchlist_name="Salvador Dalí",
            title="Pantagruel’s Humorous Dreams, 1973. Lithograph on Japanese paper, artist’s proof marked EA. 76 x 54 cm")
        before = {lot.pk: AuctionWatchLot.objects.filter(pk=lot.pk).values().get() for lot in (lion, pantagruel)}
        fingerprints = {lot.pk: fingerprint(lot) for lot in (lion, pantagruel)}
        for view in ("calendar", "catalog", "oliver-calendar", "oliver", "research"):
            with self.subTest(view=view):
                response = self.client.get(reverse("auction_calendar"), {
                    "month": "2026-12", "day": "2026-12-12", "view": view, "lot": lion.pk,
                })
                self.assertEqual(response.status_code, 200)
                lots = {lot["id"]: lot for lot in response.context["calendar_data"]["2026-12-12"]}
                self.assertEqual(set(lots), {lion.pk, pantagruel.pk})
                self.assertEqual(lots[lion.pk]["lot_number"], "601-1")
                self.assertEqual(lots[lion.pk]["arrival_lot_number"], "601")
                self.assertEqual(lots[pantagruel.pk]["lot_number"], "601")
                self.assertNotIn("arrival_lot_number", lots[pantagruel.pk])
                self.assertFalse(lots[lion.pk]["oliver_house"])
        for lot in (lion, pantagruel):
            lot.refresh_from_db()
            self.assertEqual(AuctionWatchLot.objects.filter(pk=lot.pk).values().get(), before[lot.pk])
            self.assertEqual(fingerprint(lot), fingerprints[lot.pk])
