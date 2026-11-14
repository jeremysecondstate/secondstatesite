"""Conservative duplicate review cannot discard source facts or saved work."""

from datetime import datetime, timedelta
from importlib import import_module
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from django.apps import apps
from django.core.management import call_command
from django.test import TestCase

from .calendar_duplicates import apply_pairs, audit_lots, fingerprint, rollback_receipt, snapshot
from .models import AuctionEmailBatch, AuctionEmailBatchItem, AuctionWatchLot, AuctionLotSupersessionReceipt
from .tests_calendar import watch_lot, stored_analysis


class CalendarDuplicateTests(TestCase):
    def pair(self, **overrides):
        keep = watch_lot(source_lot_id="preferred", lot_url="https://www.invaluable.com/auction-lot/test-1-c-abc123")
        old = watch_lot(source="Drouot", source_lot_id="duplicate", lot_url="https://drouot.com/en/l/123-test", **overrides)
        return keep, old

    def reviewed(self, keep, old):
        return {"keep_id": keep.pk, "remove_id": old.pk, "reason": "Reviewed matching source sale and lot",
                "keep_fingerprint": fingerprint(keep), "remove_fingerprint": fingerprint(old)}

    def test_cross_source_preference_and_all_dates_are_audited(self):
        keep, old = self.pair()
        watch_lot(source_lot_id="historical", event_at=keep.event_at - timedelta(days=90), active=False,
                  lot_url="https://www.invaluable.com/auction-lot/historical-2-c-def456")
        audit = audit_lots(AuctionWatchLot.objects.all())
        self.assertEqual(audit["visible_records"], 3)
        self.assertEqual(audit["dated_days"], 2)
        self.assertEqual(len(audit["pairs"]), 1)
        self.assertEqual(audit["pairs"][0]["keep_id"], keep.pk)
        self.assertEqual(audit["pairs"][0]["confidence"], "strong")
        old.refresh_from_db()
        self.assertIsNone(old.superseded_by_id)

    def test_native_provider_and_same_provider_are_not_omitted(self):
        keep, old = self.pair()
        old.source = "Forum"
        old.save(update_fields=["source"])
        audit = audit_lots(AuctionWatchLot.objects.all())
        self.assertEqual(audit["pairs"][0]["keep_id"], keep.pk)
        old.source = "Invaluable"
        old.save(update_fields=["source"])
        audit = audit_lots(AuctionWatchLot.objects.all())
        self.assertEqual(audit["pairs"][0]["confidence"], "review")

    def test_distinct_lot_numbers_and_artists_do_not_match(self):
        self.pair(lot_number="26")
        self.assertEqual(audit_lots(AuctionWatchLot.objects.all())["pairs"], [])
        AuctionWatchLot.objects.filter(source="Drouot").update(lot_number="25", artist_watchlist_name="Max Ernst")
        self.assertEqual(audit_lots(AuctionWatchLot.objects.all())["pairs"], [])

    def test_another_house_cannot_be_a_strong_candidate(self):
        self.pair(auction_house="Unrelated Auction House")
        pair, = audit_lots(AuctionWatchLot.objects.all())["pairs"]
        self.assertEqual(pair["confidence"], "review")

    def test_source_url_slug_alias_identifies_same_provider_lot(self):
        keep, old = self.pair()
        old.source = "Invaluable"
        old.lot_url = "https://www.invaluable.com/auction-lot/renamed-1-c-abc123"
        old.save(update_fields=["source", "lot_url"])
        pair, = audit_lots(AuctionWatchLot.objects.all())["pairs"]
        self.assertEqual(pair["reason"], "same_source_lot_url")

    def test_apply_retains_research_and_tray_then_rollback_restores_visibility(self):
        keep, old = self.pair()
        analysis = stored_analysis(old)
        tray = AuctionEmailBatchItem.objects.create(batch=AuctionEmailBatch.objects.create(), lot=old)
        receipt = apply_pairs([self.reviewed(keep, old)])
        old.refresh_from_db()
        self.assertEqual(old.superseded_by_id, keep.pk)
        self.assertFalse(old.active)
        self.assertEqual(AuctionWatchLot.objects.count(), 2)
        analysis.refresh_from_db(); tray.refresh_from_db()
        self.assertEqual((analysis.lot_id, tray.lot_id), (old.pk, old.pk))
        self.assertEqual(rollback_receipt(receipt), 1)
        old.refresh_from_db()
        self.assertIsNone(old.superseded_by_id)
        self.assertTrue(old.active)

    def test_stale_review_is_rejected_without_partial_changes(self):
        keep, old = self.pair()
        plan = self.reviewed(keep, old)
        AuctionWatchLot.objects.filter(pk=old.pk).update(title="A different work")
        with self.assertRaisesRegex(ValueError, "changed since review"):
            apply_pairs([plan])
        old.refresh_from_db()
        self.assertIsNone(old.superseded_by_id)

    def test_invaluable_cannot_be_discarded_for_drouot(self):
        keep, old = self.pair()
        with self.assertRaisesRegex(ValueError, "Invaluable listing must be kept"):
            apply_pairs([self.reviewed(old, keep)])

    def test_chain_plan_is_rejected(self):
        keep, old = self.pair()
        third = watch_lot(source_lot_id="third")
        with self.assertRaisesRegex(ValueError, "may not also be a survivor"):
            apply_pairs([self.reviewed(keep, old), self.reviewed(third, keep)])

    def test_rollback_never_reactivates_a_newly_sold_lot(self):
        keep, old = self.pair()
        receipt = apply_pairs([self.reviewed(keep, old)])
        AuctionWatchLot.objects.filter(pk=old.pk).update(sold_price=123)
        rollback_receipt(receipt)
        old.refresh_from_db()
        self.assertFalse(old.active)

    def test_management_command_is_read_only_by_default(self):
        keep, old = self.pair()
        with TemporaryDirectory() as directory:
            path = Path(directory) / "audit.json"
            call_command("reconcile_calendar_duplicates", report=path, stdout=StringIO())
            report = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(report["visible_records"], 2)
        old.refresh_from_db()
        self.assertIsNone(old.superseded_by_id)

    def migration(self):
        return import_module("secondstateapp.migrations.0050_reconcile_calendar_duplicates")

    def test_reviewed_migration_preserves_saved_work_and_is_reversible(self):
        keep, old = self.pair()
        artprice = stored_analysis(old)
        pair = {"keep": snapshot(keep), "remove": snapshot(old)}
        migration = self.migration()
        editor = SimpleNamespace(connection=SimpleNamespace(alias="default"))
        with patch.object(migration, "load_manifest", return_value=[pair]):
            migration.supersede_reviewed_lots(apps, editor)
            migration.supersede_reviewed_lots(apps, editor)
            old.refresh_from_db(); artprice.refresh_from_db()
            self.assertEqual(old.superseded_by_id, keep.pk)
            self.assertEqual(artprice.lot_id, old.pk)
            self.assertEqual(AuctionWatchLot.objects.count(), 2)
            migration.restore_reviewed_lots(apps, editor)
        old.refresh_from_db()
        self.assertIsNone(old.superseded_by_id)
        self.assertTrue(old.active)

    def test_reviewed_migration_skips_changed_work_identity(self):
        keep, old = self.pair()
        pair = {"keep": snapshot(keep), "remove": snapshot(old)}
        AuctionWatchLot.objects.filter(pk=old.pk).update(title="Another edition")
        migration = self.migration()
        with patch.object(migration, "load_manifest", return_value=[pair]):
            migration.supersede_reviewed_lots(apps, SimpleNamespace(connection=SimpleNamespace(alias="default")))
        old.refresh_from_db()
        self.assertIsNone(old.superseded_by_id)

    def test_migration_reverse_does_not_undo_a_preexisting_link(self):
        keep, old = self.pair()
        pair = {"keep": snapshot(keep), "remove": snapshot(old)}
        AuctionWatchLot.objects.filter(pk=old.pk).update(superseded_by=keep, active=False)
        migration = self.migration()
        editor = SimpleNamespace(connection=SimpleNamespace(alias="default"))
        with patch.object(migration, "load_manifest", return_value=[pair]):
            migration.supersede_reviewed_lots(apps, editor)
            self.assertEqual(AuctionLotSupersessionReceipt.objects.count(), 0)
            migration.restore_reviewed_lots(apps, editor)
        old.refresh_from_db()
        self.assertEqual(old.superseded_by_id, keep.pk)
        self.assertFalse(old.active)

    def test_migration_reverse_restores_actual_active_state_not_manifest_snapshot(self):
        keep, old = self.pair()
        pair = {"keep": snapshot(keep), "remove": snapshot(old)}
        AuctionWatchLot.objects.filter(pk=old.pk).update(active=False)
        migration = self.migration()
        editor = SimpleNamespace(connection=SimpleNamespace(alias="default"))
        with patch.object(migration, "load_manifest", return_value=[pair]):
            migration.supersede_reviewed_lots(apps, editor)
            self.assertFalse(AuctionLotSupersessionReceipt.objects.get(lot=old).active_before)
            migration.restore_reviewed_lots(apps, editor)
        old.refresh_from_db()
        self.assertIsNone(old.superseded_by_id)
        self.assertFalse(old.active)

    def test_manifest_has_no_chains_repeated_removals_or_reversed_provider_preference(self):
        pairs = self.migration().load_manifest()
        removed = [(pair["remove"]["source"], pair["remove"]["source_lot_id"]) for pair in pairs]
        kept = {(pair["keep"]["source"], pair["keep"]["source_lot_id"]) for pair in pairs}
        self.assertEqual(len(set(removed)), len(removed))
        self.assertFalse(set(removed) & kept)
        for pair in pairs:
            if pair["remove"]["source"] == "Invaluable":
                self.assertEqual(pair["keep"]["source"], "Invaluable")
