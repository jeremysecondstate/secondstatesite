from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("secondstateapp", "0024_liveart_decimal_data_units"),
    ]

    operations = [
        migrations.AddField(
            model_name="liveartresaleanalysis",
            name="source_summary",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
