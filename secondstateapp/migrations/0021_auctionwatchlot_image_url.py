from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("secondstateapp", "0020_auctionwatchartist"),
    ]

    operations = [
        migrations.AddField(
            model_name="auctionwatchlot",
            name="image_url",
            field=models.URLField(blank=True, max_length=2000),
        ),
    ]
