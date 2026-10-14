from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("secondstateapp", "0028_auction_bid_board_analysis"),
    ]

    operations = [
        migrations.AddField(
            model_name="auctionwatchlot",
            name="sold_price",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=15, null=True),
        ),
        migrations.AddField(
            model_name="auctionwatchlot",
            name="sold_currency",
            field=models.CharField(blank=True, max_length=8),
        ),
    ]
