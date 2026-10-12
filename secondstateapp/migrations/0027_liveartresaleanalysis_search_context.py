from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("secondstateapp", "0026_auctionmaxbidanalysis_sources")]

    operations = [
        migrations.AddField(
            model_name="liveartresaleanalysis",
            name="search_context",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
