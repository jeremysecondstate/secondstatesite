from datetime import timedelta
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import patch

from django.apps import apps
from django.db import connection
from django.test import TestCase
from django.urls import reverse

from .calendar_closing_times_2026 import PUBLISHED_CLOSES, VERIFIED_AT
from .calendar_sales import calendar_event_at
from .models import AuctionWatchLot


def lot_fields(source_lot_id):
    rule = PUBLISHED_CLOSES[source_lot_id]
    return {
        "source": "Invaluable", "source_lot_id": source_lot_id, "auction_house": rule.house,
        "lot_number": rule.number, "lot_url": rule.lot_url, "image_url": rule.image_url,
        "sale_url": "", "is_all_day": False,
    }


class PublishedLotCloseTests(TestCase):
    @patch.dict("os.environ", {"CATALOG_API_KEY": "timed-lot-test"})
    def test_sync_corrects_both_older_observations_and_accepts_newer_source(self):
        endpoint = reverse("auction_calendar_sync")
        for observed, expected in (
            (VERIFIED_AT - timedelta(days=1), "published"),
            (VERIFIED_AT + timedelta(seconds=1), "previous"),
        ):
            observations = [
                {**lot_fields(identity), "end_at": rule.previous.isoformat(), "last_seen_at": observed.isoformat()}
                for identity, rule in PUBLISHED_CLOSES.items()
            ]
            response = self.client.post(
                endpoint, {"lots": observations}, content_type="application/json", HTTP_X_API_KEY="timed-lot-test",
            )
            self.assertEqual(response.status_code, 200, response.content)
            for identity, rule in PUBLISHED_CLOSES.items():
                with self.subTest(identity=identity, observed=observed):
                    lot = AuctionWatchLot.objects.get(source_lot_id=identity)
                    self.assertEqual(lot.event_at, getattr(rule, expected))
                    self.assertEqual(lot.source_last_seen_at, observed)

    def test_unrelated_identity_catalog_or_revised_time_is_preserved(self):
        identity = "207575415"
        rule = PUBLISHED_CLOSES[identity]
        fields = lot_fields(identity)
        for change in (
            {"source": "Drouot"}, {"auction_house": "Another house"}, {"lot_number": "71"},
            {"source_lot_id": "207575416"}, {"lot_url": rule.lot_url + "-other"},
            {"image_url": rule.image_url.replace("822652", "822653")}, {"image_url": ""},
            {"sale_url": rule.catalog_url + "x"}, {"is_all_day": True},
            {"observed_at": VERIFIED_AT},
        ):
            with self.subTest(change=change):
                self.assertEqual(calendar_event_at(rule.previous, **{**fields, **change}), rule.previous)
        revised = rule.published + timedelta(seconds=15)
        self.assertEqual(calendar_event_at(revised, **fields), revised)
        self.assertEqual(calendar_event_at(rule.previous, **{**fields, "sale_url": rule.catalog_url}), rule.published)

    def test_migration_preserves_other_columns_newer_refreshes_and_idempotence(self):
        fixes = import_module("secondstateapp.migrations.0057_correct_timed_lot_closes")
        older = AuctionWatchLot.objects.create(
            **lot_fields("207710805"), event_at=PUBLISHED_CLOSES["207710805"].previous,
            active=False, source_last_seen_at=VERIFIED_AT - timedelta(days=1),
            artprice_url="https://www.artprice.com/artist/1",
        )
        fresh = AuctionWatchLot.objects.create(
            **lot_fields("207575415"), event_at=PUBLISHED_CLOSES["207575415"].previous,
            source_last_seen_at=VERIFIED_AT + timedelta(minutes=1),
        )
        before = AuctionWatchLot.objects.values().get(pk=older.pk)
        expected_fresh = AuctionWatchLot.objects.values().get(pk=fresh.pk)
        editor = SimpleNamespace(connection=connection)
        fixes.correct_timed_lot_closes(apps, editor)
        fixes.correct_timed_lot_closes(apps, editor)
        self.assertEqual(
            AuctionWatchLot.objects.values().get(pk=older.pk),
            {**before, "event_at": PUBLISHED_CLOSES["207710805"].published},
        )
        self.assertEqual(AuctionWatchLot.objects.values().get(pk=fresh.pk), expected_fresh)
