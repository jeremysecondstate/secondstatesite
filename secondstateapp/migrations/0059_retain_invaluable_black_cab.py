"""Retain Invaluable for Tate Ward's December 9 Urban & Contemporary Art lot 205a.

The house identifies its unique signed Black Cab silkscreen on paper, 60.9 × 91.4 cm.
https://www.tateward.com/auction/lot/lot-205a---mr-brainwash-french-1966--black-cab-2022?au=139&lot=30598
"""

from datetime import datetime, timezone

from django.db import migrations
from django.db.models import Q


OPERATION = "tate-ward-black-cab-2026-12-09"


def retain_invaluable(apps, schema_editor):
    alias = schema_editor.connection.alias
    lots = apps.get_model("secondstateapp", "AuctionWatchLot").objects.using(alias)
    receipts = apps.get_model("secondstateapp", "AuctionLotSupersessionReceipt").objects.using(alias)
    house_lot = Q(
        source="Tate Ward", source_lot_id="30598", artist="Mr. Brainwash", title="Black Cab, 2022",
        medium="unique silkscreen on paper, signed, sheet; 60.9 x 91.4 cm (framed)",
        sale_url="https://www.tateward.com/auction/details/102-urban--contemporary-art?au=139",
    )
    invaluable_lot = Q(
        source="Invaluable", source_lot_id="207854345", artist="Mr Brainwash", title="Black Cab",
        medium="Silkscreen on paper",
        lot_url="https://www.invaluable.com/auction-lot/mr-brainwash-french-1966-black-cab-2022-205a-c-7f97c36155",
    )
    reviewed = lots.select_for_update().filter(
        house_lot | invaluable_lot,
        auction_house="Tate Ward Auctions", event_at=datetime(2026, 12, 9, 18, tzinfo=timezone.utc),
        lot_number__iexact="205a", currency="GBP", estimate_low=3000, estimate_high=5000,
        superseded_by__isnull=True,
    ).order_by("pk")
    rows = {lot.source: lot for lot in reviewed}
    if len(rows) != 2:
        return
    old, keep = rows["Tate Ward"], rows["Invaluable"]
    if lots.filter(superseded_by_id=old.pk).exists():
        return
    receipts.create(operation=OPERATION, lot_id=old.pk, replacement_id=keep.pk, active_before=old.active)
    lots.filter(pk=old.pk).update(superseded_by_id=keep.pk, active=False)


def restore_tate_ward(apps, schema_editor):
    alias = schema_editor.connection.alias
    lots = apps.get_model("secondstateapp", "AuctionWatchLot").objects.using(alias)
    receipts = apps.get_model("secondstateapp", "AuctionLotSupersessionReceipt").objects.using(alias)
    receipt = receipts.select_for_update().filter(operation=OPERATION).first()
    if receipt is None:
        return
    old = lots.select_for_update().get(pk=receipt.lot_id)
    if old.superseded_by_id != receipt.replacement_id or old.active:
        raise ValueError("The Tate Ward supersession changed and needs review before reversal.")
    active = receipt.active_before and old.sold_price is None and old.source_status != "ended"
    lots.filter(pk=old.pk).update(superseded_by_id=None, active=active)
    receipt.delete(using=alias)


class Migration(migrations.Migration):
    dependencies = [("secondstateapp", "0058_random_lot_membership")]
    operations = [migrations.RunPython(retain_invaluable, restore_tate_ward, atomic=True)]
