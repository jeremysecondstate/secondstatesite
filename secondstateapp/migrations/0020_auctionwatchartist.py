from html import unescape
import re
import unicodedata

import django.db.models.deletion
from django.db import migrations, models


YEAR_PARENTHETICAL = re.compile(
    r"\(\s*(?:c\.?\s*)?\d{4}(?:\s*[-\u2013\u2014]\s*(?:\d{0,4})?)?\s*\)",
    re.IGNORECASE,
)


def artist_identity_key(value):
    label = unicodedata.normalize("NFKC", unescape(str(value or "")))
    label = YEAR_PARENTHETICAL.sub(" ", label)
    label = unicodedata.normalize("NFKD", label)
    label = "".join(character for character in label if not unicodedata.combining(character))
    label = label.casefold().replace("&", " and ")
    label = re.sub(r"[^\w]+", " ", label, flags=re.UNICODE)
    return " ".join(sorted(label.split()))[:255]


def associate_existing_lots(apps, schema_editor):
    AuctionWatchArtist = apps.get_model("secondstateapp", "AuctionWatchArtist")
    AuctionWatchLot = apps.get_model("secondstateapp", "AuctionWatchLot")
    artists = {}
    pending = []
    for lot in AuctionWatchLot.objects.all().iterator():
        name = (lot.artist_watchlist_name or lot.artist or "").strip()
        normalized_name = artist_identity_key(name)
        if not normalized_name:
            continue
        artist = artists.get(normalized_name)
        if artist is None:
            artist, _created = AuctionWatchArtist.objects.get_or_create(
                normalized_name=normalized_name,
                defaults={"name": name[:255]},
            )
            artists[normalized_name] = artist
        lot.watchlist_artist_id = artist.pk
        pending.append(lot)
    if pending:
        AuctionWatchLot.objects.bulk_update(pending, ("watchlist_artist",))


def remove_existing_associations(apps, schema_editor):
    AuctionWatchLot = apps.get_model("secondstateapp", "AuctionWatchLot")
    AuctionWatchArtist = apps.get_model("secondstateapp", "AuctionWatchArtist")
    AuctionWatchLot.objects.update(watchlist_artist=None)
    AuctionWatchArtist.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("secondstateapp", "0019_auctionwatchlot_bid_count"),
    ]

    operations = [
        migrations.CreateModel(
            name="AuctionWatchArtist",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=255)),
                ("normalized_name", models.CharField(max_length=255, unique=True)),
                ("artprice_url", models.URLField(blank=True, max_length=2000)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["name", "id"]},
        ),
        migrations.AddField(
            model_name="auctionwatchlot",
            name="watchlist_artist",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="lots",
                to="secondstateapp.auctionwatchartist",
            ),
        ),
        migrations.RunPython(associate_existing_lots, remove_existing_associations),
    ]
