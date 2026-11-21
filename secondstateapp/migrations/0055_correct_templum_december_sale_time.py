from datetime import datetime, timezone

from django.db import migrations, transaction


def correct_templum_sale_time(apps, schema_editor):
    # The house lists December 3 at 15:00 in Barcelona (14:00 UTC).
    # https://templumauctions.com/auction/312-gran-subasta-de-es/
    # https://drouot.com/en/v/188631
    lot_model = apps.get_model("secondstateapp", "AuctionWatchLot")
    alias = schema_editor.connection.alias
    affected = lot_model.objects.using(alias).filter(
        source="Drouot",
        auction_house="Templum Fine art Auction",
        sale_url="https://drouot.com/en/v/188631",
        event_at=datetime(2026, 12, 3, 2, tzinfo=timezone.utc),
        is_all_day=False,
    )
    with transaction.atomic(using=alias):
        lot_ids = list(affected.select_for_update().order_by("pk").values_list("pk", flat=True))
        affected.filter(pk__in=lot_ids).update(event_at=datetime(2026, 12, 3, 14, tzinfo=timezone.utc))


class Migration(migrations.Migration):
    dependencies = [("secondstateapp", "0054_reassess_nov19_market_reviews")]
    operations = [migrations.RunPython(correct_templum_sale_time, migrations.RunPython.noop)]
