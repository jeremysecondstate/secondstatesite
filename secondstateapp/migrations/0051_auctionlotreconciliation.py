from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("secondstateapp", "0050_reconcile_calendar_duplicates")]
    operations = [
        migrations.CreateModel(
            name="AuctionLotReconciliation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("operation", models.CharField(max_length=76, unique=True)),
                ("request_hash", models.CharField(max_length=64)),
                ("receipt", models.JSONField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
    ]
