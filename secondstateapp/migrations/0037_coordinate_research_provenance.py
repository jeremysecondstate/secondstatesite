from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("secondstateapp", "0036_coordinate_shipping_workspace")]

    operations = [
        migrations.AddField(
            model_name="coordinateresearch",
            name="source_kind",
            field=models.CharField(
                choices=[("public", "Public source"), ("browser", "Browser source")],
                default="public",
                max_length=12,
            ),
        ),
        migrations.AddField(
            model_name="coordinateresearch",
            name="public_error",
            field=models.CharField(blank=True, max_length=200),
        ),
    ]
