"""Confirmed purchases remain separate from public auction sale results."""

import json
import os
from datetime import datetime, timezone
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import AuctionWatchLot
from .tests_calendar import watch_lot


class CalendarPurchaseTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user("purchase-staff", is_staff=True))

    def test_purchase_flag_is_exposed_and_survives_source_refresh(self):
        won = watch_lot(won_by_us=True, active=False, sold_price=850, sold_currency="USD")
        other_sale = watch_lot(source_lot_id="another-sale", active=False, sold_price=1200)
        record = {
            "source": won.source, "source_lot_id": won.source_lot_id,
            "artist": won.artist, "title": won.title, "lot_url": won.lot_url,
            "auction_house": won.auction_house, "lot_number": won.lot_number,
            "end_at": won.event_at.isoformat(), "status": "ended",
            "won_by_us": False,  # Auction sources cannot overwrite staff ownership.
        }
        with patch.dict(os.environ, {"CATALOG_API_KEY": "purchase-test"}):
            response = self.client.post(
                reverse("auction_calendar_sync"), json.dumps({"lots": [record]}),
                content_type="application/json", HTTP_X_API_KEY="purchase-test",
            )
        self.assertEqual(response.status_code, 200, response.content)
        won.refresh_from_db()
        self.assertTrue(won.won_by_us)
        self.assertEqual(won.sold_price, 850)
        response = self.client.get(reverse("auction_calendar"), {"month": "2026-07", "view": "catalog"})
        lots = {lot["id"]: lot for lot in response.context["calendar_data"]["2026-07-25"]}
        self.assertTrue(lots[won.pk]["won_by_us"])
        self.assertTrue(lots[won.pk]["ended"])
        self.assertFalse(lots[other_sale.pk]["won_by_us"])

    def test_seed_matches_only_six_verified_lot_identities_and_preserves_other_fields(self):
        migration = import_module("secondstateapp.migrations.0033_auctionwatchlot_won_by_us")
        expected = []
        for source_id, reference, day, house, number in migration.PURCHASES:
            lot = watch_lot(
                source_lot_id=source_id, auction_house=house, lot_number=number,
                event_at=datetime.fromisoformat(f"{day}T17:00:00").replace(tzinfo=timezone.utc),
                lot_url=f"https://www.invaluable.com/auction-lot/example-{number}-c-{reference}?tracking=1",
                artprice_url="https://www.artprice.com/artist/123/example",
            )
            expected.append(lot.pk)
        unrelated = watch_lot(source_lot_id="unrelated", won_by_us=True)
        lookalike = watch_lot(source_lot_id="same-title-new-sale", title=lot.title, lot_number=lot.lot_number)
        before = list(AuctionWatchLot.objects.order_by("pk").values())
        editor = SimpleNamespace(connection=SimpleNamespace(alias="default"))
        migration.mark_purchases(apps, editor)
        migration.mark_purchases(apps, editor)
        self.assertEqual(
            set(AuctionWatchLot.objects.filter(won_by_us=True).values_list("pk", flat=True)),
            set(expected + [unrelated.pk]),
        )
        after = list(AuctionWatchLot.objects.order_by("pk").values())
        for old, new in zip(before, after):
            old.pop("won_by_us")
            new.pop("won_by_us")
            self.assertEqual(old, new)
        migration.unmark_purchases(apps, editor)
        self.assertEqual(list(AuctionWatchLot.objects.filter(won_by_us=True).values_list("pk", flat=True)), [unrelated.pk])
        lookalike.refresh_from_db()
        self.assertFalse(lookalike.won_by_us)

    def test_seed_does_not_match_changed_sale_or_wrong_url(self):
        migration = import_module("secondstateapp.migrations.0033_auctionwatchlot_won_by_us")
        source_id, reference, day, house, number = migration.PURCHASES[0]
        lot = watch_lot(
            source_lot_id=source_id, auction_house=house, lot_number=number,
            event_at=datetime(2026, 10, 17, 17, tzinfo=timezone.utc),
            lot_url=f"https://www.invaluable.com/auction-lot/example-c-{reference}",
        )
        editor = SimpleNamespace(connection=SimpleNamespace(alias="default"))
        migration.mark_purchases(apps, editor)
        lot.refresh_from_db()
        self.assertFalse(lot.won_by_us)
        lot.event_at = datetime(2026, 10, 16, 17, tzinfo=timezone.utc)
        lot.lot_url = f"https://example.com/auction-lot/example-c-{reference}"
        lot.save()
        migration.mark_purchases(apps, editor)
        lot.refresh_from_db()
        self.assertFalse(lot.won_by_us)
