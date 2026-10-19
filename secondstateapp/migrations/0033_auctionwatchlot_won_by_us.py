"""Retain the six purchases confirmed by SECONDSTATE on October 18, 2026."""

from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from django.db import migrations, models


# Verified source identities from the saved watchlist and the supplied lot links.
# Match identity, sale date, house, and lot number; never infer a purchase merely
# because an auction reports a sold price.
PURCHASES = (
    ("206556897", "372321acfe", "2026-10-16", "DuMouchelles", "1096"),
    ("206112684", "90220ae2a1", "2026-10-17", "Larsen Art Auction", "177"),
    ("206112873", "15018a0cfe", "2026-10-17", "Larsen Art Auction", "366"),
    ("206672383", "abdb62df6c", "2026-10-18", "Burchard Galleries Inc", "1296"),
    ("205978969", "fd8f723547", "2026-10-18", "Santa Monica Auctions", "50"),
    ("206650433", "92cdc9e41f", "2026-10-18", "Santa Monica Auctions", "92"),
)


def matching_purchases(apps, schema_editor):
    Lot = apps.get_model("secondstateapp", "AuctionWatchLot")
    lots = Lot.objects.using(schema_editor.connection.alias)
    for source_id, reference, day, house, number in PURCHASES:
        start = datetime.fromisoformat(day).replace(tzinfo=timezone.utc)
        for lot in lots.filter(
            source="Invaluable", source_lot_id=source_id,
            auction_house=house, lot_number=number,
            event_at__gte=start, event_at__lt=start + timedelta(days=1),
            superseded_by__isnull=True,
        ):
            url = urlsplit(lot.lot_url)
            if url.hostname in {"www.invaluable.com", "invaluable.com"} and url.path.lower().rstrip("/").endswith(f"-c-{reference}"):
                yield lot.pk


def mark_purchases(apps, schema_editor):
    Lot = apps.get_model("secondstateapp", "AuctionWatchLot")
    Lot.objects.using(schema_editor.connection.alias).filter(
        pk__in=list(matching_purchases(apps, schema_editor)),
    ).update(won_by_us=True)


def unmark_purchases(apps, schema_editor):
    Lot = apps.get_model("secondstateapp", "AuctionWatchLot")
    Lot.objects.using(schema_editor.connection.alias).filter(
        pk__in=list(matching_purchases(apps, schema_editor)),
    ).update(won_by_us=False)


class Migration(migrations.Migration):
    dependencies = [("secondstateapp", "0032_sharedartistwatchlist")]

    operations = [
        migrations.AddField(
            model_name="auctionwatchlot", name="won_by_us",
            field=models.BooleanField(
                default=False, verbose_name="Won by SECONDSTATE",
                help_text="Confirmed purchase by SECONDSTATE; preserved across auction refreshes.",
            ),
        ),
        migrations.RunPython(mark_purchases, unmark_purchases),
    ]
