from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("secondstateapp", "0029_auctionwatchlot_sold_price_sold_currency")]

    operations = [
        migrations.AddField(
            model_name="auctionbidboardanalysis",
            name="include_in_email",
            field=models.BooleanField(default=False),
        ),
    ]
