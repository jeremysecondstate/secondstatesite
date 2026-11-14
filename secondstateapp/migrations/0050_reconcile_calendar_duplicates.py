"""Hide reviewed repeated listings without deleting source history or saved work.

The manifest records the complete November 13 Calendar audit. Each source
identity and its corroborating fields must still match before a pair changes.
Invaluable is the retained provider wherever it is available. The existing
retained-work links continue to expose research and selections on older rows.
"""

from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path

import django.db.models.deletion
from django.db import migrations, models


OPERATION = "calendar-duplicates-2026-11-13"


MATCH_FIELDS = (
    "source", "source_lot_id", "artist", "artist_watchlist_name", "title",
    "auction_house", "lot_number", "event_at", "currency", "estimate_low",
    "estimate_high", "lot_url", "sale_url",
)


def load_manifest():
    return json.loads(Path(__file__).with_name("0050_calendar_duplicate_manifest.json").read_text(encoding="utf-8"))["pairs"]


def matches(lot, expected):
    for field in MATCH_FIELDS:
        value = expected[field]
        if value is not None and field == "event_at":
            value = datetime.fromisoformat(value)
        if value is not None and field in ("estimate_low", "estimate_high"):
            value = Decimal(value)
        if getattr(lot, field) != value:
            return False
    return True


def supersede_reviewed_lots(apps, schema_editor):
    Lot = apps.get_model("secondstateapp", "AuctionWatchLot")
    Receipt = apps.get_model("secondstateapp", "AuctionLotSupersessionReceipt")
    alias = schema_editor.connection.alias
    lots = Lot.objects.using(alias)
    for pair in load_manifest():
        old_expected, kept_expected = pair["remove"], pair["keep"]
        old = lots.select_for_update().filter(source=old_expected["source"], source_lot_id=old_expected["source_lot_id"]).first()
        kept = lots.select_for_update().filter(source=kept_expected["source"], source_lot_id=kept_expected["source_lot_id"]).first()
        if old is None or kept is None or old.pk == kept.pk:
            continue
        if old.superseded_by_id is not None or kept.superseded_by_id is not None:
            continue
        if not matches(old, old_expected) or not matches(kept, kept_expected):
            continue
        if lots.filter(superseded_by_id=old.pk).exists():
            continue
        Receipt.objects.using(alias).create(
            operation=OPERATION, lot_id=old.pk, replacement_id=kept.pk, active_before=old.active,
        )
        lots.filter(pk=old.pk).update(superseded_by_id=kept.pk, active=False)


def restore_reviewed_lots(apps, schema_editor):
    Lot = apps.get_model("secondstateapp", "AuctionWatchLot")
    Receipt = apps.get_model("secondstateapp", "AuctionLotSupersessionReceipt")
    alias = schema_editor.connection.alias
    lots = Lot.objects.using(alias)
    # A preexisting link skipped by forward has no receipt and is never undone.
    for receipt in Receipt.objects.using(alias).filter(operation=OPERATION):
        old = lots.select_for_update().filter(
            pk=receipt.lot_id, superseded_by_id=receipt.replacement_id,
        ).first()
        if old is None:
            continue
        # Source refreshes and sold results since the cleanup remain authoritative.
        active = receipt.active_before and old.sold_price is None and old.source_status != "ended"
        lots.filter(pk=old.pk).update(superseded_by=None, active=active)
        receipt.delete(using=alias)


class Migration(migrations.Migration):
    dependencies = [("secondstateapp", "0049_retire_staff_workspaces")]
    operations = [
        migrations.CreateModel(
            name="AuctionLotSupersessionReceipt",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("operation", models.CharField(max_length=80)),
                ("active_before", models.BooleanField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("lot", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="supersession_receipts", to="secondstateapp.auctionwatchlot")),
                ("replacement", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to="secondstateapp.auctionwatchlot")),
            ],
            options={"constraints": [models.UniqueConstraint(fields=("operation", "lot"), name="unique_calendar_supersession_receipt")]},
        ),
        migrations.RunPython(supersede_reviewed_lots, restore_reviewed_lots),
    ]
