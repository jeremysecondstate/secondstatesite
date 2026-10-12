from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("secondstateapp", "0023_liveart_resale_analysis"),
    ]

    operations = [
        migrations.AlterField(
            model_name="liveartresaleanalysis",
            name="data_units_spent",
            field=models.DecimalField(blank=True, decimal_places=1, max_digits=8, null=True),
        ),
    ]
