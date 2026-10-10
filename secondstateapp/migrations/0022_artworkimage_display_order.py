from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("secondstateapp", "0021_auctionwatchlot_image_url"),
    ]

    operations = [
        migrations.AddField(
            model_name="artworkimage",
            name="display_order",
            field=models.PositiveIntegerField(default=0, db_index=True),
        ),
        migrations.AlterModelOptions(
            name="artworkimage",
            options={"ordering": ["display_order", "id"]},
        ),
    ]
