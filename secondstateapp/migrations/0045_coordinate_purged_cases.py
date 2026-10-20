from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("secondstateapp", "0044_quote_outreach_permission")]

    operations = [
        migrations.AddField(
            model_name="coordinatecase", name="purged_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddConstraint(
            model_name="coordinatecase",
            constraint=models.CheckConstraint(
                condition=models.Q(purged_at__isnull=True) | models.Q(deleted_at__isnull=False),
                name="coordinate_purged_requires_trash",
            ),
        ),
    ]
