"""Correct the two older lot closes that differ from the published catalog."""

from django.db import migrations, transaction

from secondstateapp.calendar_closing_times_2026 import PUBLISHED_CLOSES, corrected_lot_close


def correct_timed_lot_closes(apps, schema_editor):
    alias = schema_editor.connection.alias
    lots = apps.get_model("secondstateapp", "AuctionWatchLot").objects.using(alias)
    with transaction.atomic(using=alias):
        candidates = lots.select_for_update().filter(
            source="Invaluable", source_lot_id__in=PUBLISHED_CLOSES,
        ).order_by("pk")
        for lot in candidates:
            end = corrected_lot_close(
                lot.event_at, source=lot.source, auction_house=lot.auction_house,
                sale_url=lot.sale_url, is_all_day=lot.is_all_day, source_lot_id=lot.source_lot_id,
                lot_number=lot.lot_number, lot_url=lot.lot_url, image_url=lot.image_url,
                observed_at=lot.source_last_seen_at,
            )
            if end != lot.event_at:
                lot.event_at = end
                lot.save(using=alias, update_fields=["event_at"])


class Migration(migrations.Migration):
    dependencies = [("secondstateapp", "0056_correct_auction_session_times")]
    # Keep later provider observations and already-correct closes on rollback.
    operations = [migrations.RunPython(correct_timed_lot_closes, migrations.RunPython.noop)]
