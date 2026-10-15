"""Withdrawn catalog listings stay hidden without losing their replacement's work."""

import json
import os
from datetime import datetime
from decimal import Decimal
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .bid_board import build_board
from .models import (
    AuctionBidBoardAnalysis, AuctionEmailBatch, AuctionEmailBatchItem, AuctionWatchLot,
    LiveArtResaleAnalysis,
)
from .tests_calendar import CALENDAR_ZONE, stored_analysis, watch_lot


@override_settings(CALENDAR_TIME_ZONE="America/Los_Angeles", AUCTION_EMAIL_SENDING_ENABLED=False)
class CalendarSupersededLotTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user("superseded-calendar-staff", is_staff=True)
        self.client.force_login(self.staff)

    def replacement_pair(self, **overrides):
        replacement = watch_lot(
            source_lot_id="replacement-listing", lot_url="https://www.invaluable.com/auction-lot/replacement",
            sale_url="https://www.invaluable.com/catalog/replacement-sale",
            image_url="https://images.example/replacement.jpg", **overrides,
        )
        old = watch_lot(
            source_lot_id="withdrawn-listing", lot_url="https://www.invaluable.com/auction-lot/withdrawn",
            sale_url="https://www.invaluable.com/catalog/withdrawn-sale",
            superseded_by=replacement, **overrides,
        )
        return old, replacement

    def calendar(self, **params):
        with patch(
            "secondstateapp.calendar_views.timezone.now",
            return_value=datetime(2026, 7, 20, 12, tzinfo=CALENDAR_ZONE),
        ):
            response = self.client.get(reverse("auction_calendar"), {"month": "2026-07", **params})
        self.assertEqual(response.status_code, 200)
        return response

    def sync(self, lot, **overrides):
        record = {
            "source": lot.source, "source_lot_id": lot.source_lot_id,
            "artist": lot.artist, "artist_watchlist_name": lot.artist_watchlist_name,
            "title": lot.title, "medium": lot.medium, "auction_house": lot.auction_house,
            "sale_title": lot.sale_title, "lot_number": lot.lot_number,
            "end_at": lot.event_at.isoformat(), "currency": lot.currency,
            "lot_url": lot.lot_url, "sale_url": lot.sale_url,
            "image_url": lot.image_url, "status": "changed", "active": True,
            **overrides,
        }
        with patch.dict(os.environ, {"CATALOG_API_KEY": "superseded-test-key"}):
            response = self.client.post(
                reverse("auction_calendar_sync"), json.dumps({"lots": [record]}),
                content_type="application/json", HTTP_X_API_KEY="superseded-test-key",
            )
        self.assertEqual(response.status_code, 200, response.content)
        return response

    def save_research_and_email(self, lot):
        artprice = stored_analysis(lot, created_by=self.staff)
        board = build_board({
            "starting_hammer": "1000", "starting_basis": "opening", "buyer_premium_pct": "25",
            "acquisition_costs": "200", "minimum_profit": "500", "minimum_return_pct": "20",
            "resale_overrides": {"conservative": "2400", "working": "3000", "optimistic": "4000"},
        }, selected_bid="1400", selected_case="working")
        saved_board = AuctionBidBoardAnalysis.objects.create(
            lot=lot, assumptions=board["assumptions"], analysis=board, include_in_email=True,
            evidence_snapshot={"selected_records": [{"id": "verified-comparable"}]},
        )
        tray_item = AuctionEmailBatchItem.objects.create(batch=AuctionEmailBatch.objects.create(), lot=lot)
        return artprice, saved_board, tray_item

    def test_month_catalog_and_counts_hide_only_explicitly_superseded_listing(self):
        old, replacement = self.replacement_pair()
        # Matching title, artist, date, house, and lot number alone do not prove duplication.
        distinct = watch_lot(
            source_lot_id="another-genuine-listing", lot_url="https://www.invaluable.com/auction-lot/another",
            sale_url="https://www.invaluable.com/catalog/another-sale",
        )

        response = self.calendar(day="2026-07-25", view="catalog")

        self.assertEqual(
            {lot["id"] for lot in response.context["calendar_data"]["2026-07-25"]},
            {replacement.pk, distinct.pk},
        )
        sales = response.context["calendar_sales_data"]["2026-07-25"]
        self.assertEqual({sale["sale_url"] for sale in sales}, {replacement.sale_url, distinct.sale_url})
        self.assertEqual([sale["lot_count"] for sale in sales], [1, 1])
        day = next(day for week in response.context["weeks"] for day in week if day["iso"] == "2026-07-25")
        self.assertEqual(day["lot_count"], 2)
        self.assertEqual(day["sale_count"], 2)
        self.assertEqual(response.context["synced_lot_count"], 2)
        self.assertTrue(AuctionWatchLot.objects.filter(pk=old.pk, superseded_by=replacement).exists())

    def test_ordinary_ended_lot_remains_in_historical_catalog(self):
        old, replacement = self.replacement_pair()
        old.active = False
        old.save(update_fields=("active",))
        historical = watch_lot(source_lot_id="historical-sale", active=False, source_status="ended")

        response = self.calendar()

        details = {lot["id"]: lot for lot in response.context["calendar_data"]["2026-07-25"]}
        self.assertEqual(set(details), {replacement.pk, historical.pk})
        self.assertTrue(details[historical.pk]["ended"])
        self.assertEqual(response.context["synced_lot_count"], 2)

    def test_outside_month_upcoming_catalog_and_sale_counts_exclude_superseded_listing(self):
        event_at = datetime(2026, 8, 3, 14, tzinfo=CALENDAR_ZONE)
        old, replacement = self.replacement_pair(event_at=event_at)
        historical = watch_lot(
            source_lot_id="august-ended", event_at=event_at, active=False,
            sale_url=replacement.sale_url,
        )

        response = self.calendar(day="2026-08-03", view="catalog")

        self.assertEqual(
            {lot["id"] for lot in response.context["calendar_data"]["2026-08-03"]},
            {replacement.pk, historical.pk},
        )
        sales = response.context["calendar_sales_data"]["2026-08-03"]
        self.assertEqual(len(sales), 1)
        self.assertEqual(sales[0]["lot_count"], 2)
        upcoming = response.context["upcoming_groups"]
        self.assertEqual(len(upcoming), 1)
        self.assertEqual(upcoming[0]["sale_url"], replacement.sale_url)
        self.assertEqual(upcoming[0]["lot_count"], 1)
        self.assertNotEqual(upcoming[0]["sale_url"], old.sale_url)

    def test_resync_cannot_reactivate_old_listing_or_overwrite_replacement_research(self):
        old, replacement = self.replacement_pair()
        artprice, saved_board, tray_item = self.save_research_and_email(replacement)
        replacement_before = AuctionWatchLot.objects.filter(pk=replacement.pk).values().get()
        research_before = saved_board.analysis

        for status in ("new", "changed", "unchanged"):
            with self.subTest(status=status):
                result = self.sync(
                    old, status=status, active=True, current_bid=9999,
                    title="Stale source title", image_url="", superseded_by=None,
                )
                self.assertEqual(result.json()["created"], 0)
                self.assertEqual(result.json()["updated"], 1)
                self.assertEqual(result.json()["ended"], 1)
                old.refresh_from_db()
                self.assertFalse(old.active)
                self.assertEqual(old.superseded_by_id, replacement.pk)

        self.assertEqual(AuctionWatchLot.objects.filter(pk=replacement.pk).values().get(), replacement_before)
        artprice.refresh_from_db()
        saved_board.refresh_from_db()
        tray_item.refresh_from_db()
        self.assertEqual(artprice.lot_id, replacement.pk)
        self.assertEqual(artprice.expected_resale_hammer, Decimal("1205.00"))
        self.assertEqual(saved_board.analysis, research_before)
        self.assertTrue(saved_board.include_in_email)
        self.assertEqual(tray_item.lot_id, replacement.pk)
        response = self.calendar()
        detail, = response.context["calendar_data"]["2026-07-25"]
        self.assertEqual(detail["id"], replacement.pk)
        self.assertTrue(detail["email_tray_selected"])
        self.assertEqual(detail["saved_bid_board"]["selected_bid"], "1400.00")

    def test_replacement_still_updates_in_place_and_keeps_saved_research_and_email(self):
        old, replacement = self.replacement_pair()
        artprice, saved_board, tray_item = self.save_research_and_email(replacement)
        research_before = saved_board.analysis

        result = self.sync(replacement, current_bid=1600, bid_count=3)

        self.assertEqual(result.json()["created"], 0)
        self.assertEqual(result.json()["updated"], 1)
        self.assertEqual(result.json()["ended"], 0)
        replacement.refresh_from_db()
        old.refresh_from_db()
        saved_board.refresh_from_db()
        self.assertTrue(replacement.active)
        self.assertIsNone(replacement.superseded_by_id)
        self.assertEqual(replacement.current_bid, Decimal("1600.00"))
        self.assertEqual(old.superseded_by_id, replacement.pk)
        self.assertEqual(AuctionWatchLot.objects.count(), 2)
        self.assertEqual(saved_board.analysis, research_before)
        self.assertTrue(saved_board.include_in_email)
        self.assertEqual(replacement.max_bid_analysis.pk, artprice.pk)
        self.assertTrue(AuctionEmailBatchItem.objects.filter(pk=tray_item.pk, lot=replacement).exists())
        detail, = self.calendar().context["calendar_data"]["2026-07-25"]
        self.assertEqual(detail["id"], replacement.pk)
        self.assertTrue(detail["email_tray_selected"])
        self.assertEqual(detail["current_bid"], "1600.00")

    def test_stale_page_cannot_select_withdrawn_listing_but_can_remove_it(self):
        old, replacement = self.replacement_pair()
        old.artprice_url = "https://www.artprice.com/artist/1/example/lots/pasts"
        old.save(update_fields=("artprice_url",))
        selection_url = reverse("auction_email_lot_selection", args=(old.pk,))

        selected = self.client.post(selection_url, {"selected": "true"})

        self.assertEqual(selected.status_code, 409)
        self.assertFalse(AuctionEmailBatchItem.objects.exists())
        batch = AuctionEmailBatch.objects.create()
        AuctionEmailBatchItem.objects.create(batch=batch, lot=old)
        replacement_item = AuctionEmailBatchItem.objects.create(batch=batch, lot=replacement)

        removed = self.client.post(selection_url, {"selected": "false"})

        self.assertEqual(removed.status_code, 200)
        self.assertEqual(removed.json()["selected_count"], 1)
        self.assertFalse(AuctionEmailBatchItem.objects.filter(lot=old).exists())
        self.assertTrue(AuctionEmailBatchItem.objects.filter(pk=replacement_item.pk).exists())


class ClarsCatalogSupersessionMigrationTests(TestCase):
    def setUp(self):
        self.migration = import_module("secondstateapp.migrations.0031_auctionwatchlot_superseded_by")
        self.schema_editor = SimpleNamespace(connection=SimpleNamespace(alias="default"))

    def pair(self, entry):
        old_id, new_id, number, title = entry
        identity = {
            "source": "Invaluable", "auction_house": "Clars Auctions", "lot_number": number,
            "title": title, "event_at": datetime.fromisoformat("2026-10-16T16:30:00+00:00"),
        }
        old = watch_lot(source_lot_id=old_id, sale_url=self.migration.OLD_CATALOG, **identity)
        replacement = watch_lot(source_lot_id=new_id, sale_url=self.migration.NEW_CATALOG, **identity)
        return old, replacement

    def migrate(self):
        self.migration.supersede_clars_catalog(apps, self.schema_editor)

    def test_only_verified_five_pairs_change_and_replacement_work_survives_idempotent_migration(self):
        pairs = [self.pair(entry) for entry in self.migration.REPLACEMENTS]
        replacement = pairs[0][1]
        artprice = stored_analysis(replacement)
        board = AuctionBidBoardAnalysis.objects.create(
            lot=replacement, analysis={"selected_bid": "2150.00"}, include_in_email=True,
        )
        item = AuctionEmailBatchItem.objects.create(batch=AuctionEmailBatch.objects.create(), lot=replacement)
        unrelated = watch_lot(
            source_lot_id="unverified-source-id", sale_url=self.migration.OLD_CATALOG,
            auction_house="Clars Auctions", lot_number=pairs[0][0].lot_number,
            title=pairs[0][0].title, event_at=pairs[0][0].event_at,
        )
        replacement_before = AuctionWatchLot.objects.filter(pk__in=[new.pk for _, new in pairs]).values()
        replacement_before = list(replacement_before)

        self.migrate()
        self.migrate()

        for old, new in pairs:
            old.refresh_from_db()
            self.assertEqual(old.superseded_by_id, new.pk)
            self.assertFalse(old.active)
        self.assertEqual(AuctionWatchLot.objects.count(), 11)
        self.assertEqual(
            list(AuctionWatchLot.objects.filter(pk__in=[new.pk for _, new in pairs]).values()),
            replacement_before,
        )
        unrelated.refresh_from_db()
        self.assertIsNone(unrelated.superseded_by_id)
        self.assertTrue(unrelated.active)
        self.assertEqual(replacement.max_bid_analysis.pk, artprice.pk)
        board.refresh_from_db()
        self.assertEqual(board.analysis, {"selected_bid": "2150.00"})
        self.assertTrue(board.include_in_email)
        self.assertTrue(AuctionEmailBatchItem.objects.filter(pk=item.pk, lot=replacement).exists())

    def test_migration_requires_exact_identity_on_both_old_and_replacement(self):
        old, replacement = self.pair(self.migration.REPLACEMENTS[0])
        mismatches = {
            "source": "Another source", "source_lot_id": "unverified-id",
            "auction_house": "Another house", "title": "Different artwork", "lot_number": "999",
            "event_at": datetime.fromisoformat("2026-10-17T16:30:00+00:00"),
            "sale_url": "https://www.invaluable.com/catalog/another-sale",
        }
        for lot in (old, replacement):
            for field, value in mismatches.items():
                with self.subTest(listing=lot.source_lot_id, field=field):
                    original = getattr(lot, field)
                    AuctionWatchLot.objects.filter(pk=lot.pk).update(**{field: value})
                    self.migrate()
                    old.refresh_from_db()
                    self.assertIsNone(old.superseded_by_id)
                    self.assertTrue(old.active)
                    AuctionWatchLot.objects.filter(pk=lot.pk).update(**{field: original})
                    lot.refresh_from_db()

    def test_migration_skips_old_listing_with_new_research_email_result_or_manual_changes(self):
        old, _replacement = self.pair(self.migration.REPLACEMENTS[0])
        factories = (
            lambda: stored_analysis(old),
            lambda: LiveArtResaleAnalysis.objects.create(lot=old, retrieved_at=old.event_at),
            lambda: AuctionBidBoardAnalysis.objects.create(lot=old),
            lambda: AuctionEmailBatchItem.objects.create(batch=AuctionEmailBatch.objects.create(), lot=old),
        )
        for factory in factories:
            record = factory()
            with self.subTest(evidence=type(record).__name__):
                self.migrate()
                old.refresh_from_db()
                self.assertIsNone(old.superseded_by_id)
                self.assertTrue(old.active)
                self.assertTrue(type(record).objects.filter(pk=record.pk).exists())
            record.delete()
        for field, value in (
            ("artprice_url", "https://www.artprice.com/artist/1/example/lots/pasts"),
            ("sold_price", Decimal("2400.00")),
            ("active", False),
        ):
            with self.subTest(field=field):
                original = getattr(old, field)
                AuctionWatchLot.objects.filter(pk=old.pk).update(**{field: value})
                self.migrate()
                old.refresh_from_db()
                self.assertIsNone(old.superseded_by_id)
                self.assertEqual(getattr(old, field), value)
                AuctionWatchLot.objects.filter(pk=old.pk).update(**{field: original})
                old.refresh_from_db()
