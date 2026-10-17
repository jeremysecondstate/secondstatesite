from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("secondstateapp", "0031_auctionwatchlot_superseded_by")]

    operations = [
        migrations.CreateModel(
            name="SharedArtistWatchlist",
            fields=[
                ("id", models.PositiveSmallIntegerField(default=1, editable=False, primary_key=True, serialize=False)),
                ("entries", models.JSONField(default=list)),
                ("artist_artprice_links", models.JSONField(default=dict)),
                ("coverage", models.JSONField(default=list)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
    ]
