"""Apply the auctioneers' verified session times to existing Calendar records."""

from django.db import migrations, transaction
from django.db.models import Q

from secondstateapp.calendar_sessions_2026 import SESSION_TIMES, corrected_session_time


def correct_auction_session_times(apps, schema_editor):
    lot_model = apps.get_model("secondstateapp", "AuctionWatchLot")
    alias = schema_editor.connection.alias
    lots = lot_model.objects.using(alias)
    candidates = Q(pk__in=[])
    for rule in SESSION_TIMES:
        candidates |= Q(auction_house=rule.house, event_at=rule.reported)

    with transaction.atomic(using=alias):
        locked = (
            lots.select_for_update()
            .filter(candidates, is_all_day=False)
            .only("pk", "source", "auction_house", "event_at", "sale_url", "lot_number",
                  "source_lot_id", "lot_url", "image_url", "is_all_day")
            .order_by("pk")
        )
        changed = []
        for lot in locked:
            corrected = corrected_session_time(
                lot.event_at,
                source=lot.source,
                auction_house=lot.auction_house,
                sale_url=lot.sale_url,
                lot_number=lot.lot_number,
                source_lot_id=lot.source_lot_id,
                lot_url=lot.lot_url,
                image_url=lot.image_url,
                is_all_day=lot.is_all_day,
            )
            if corrected is not None and corrected != lot.event_at:
                lot.event_at = corrected
                changed.append(lot)
        if changed:
            lots.bulk_update(changed, ["event_at"])


class Migration(migrations.Migration):
    dependencies = [("secondstateapp", "0055_correct_templum_december_sale_time")]
    operations = [migrations.RunPython(correct_auction_session_times, migrations.RunPython.noop)]
