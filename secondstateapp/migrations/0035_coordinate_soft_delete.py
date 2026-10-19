from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("secondstateapp", "0034_coordinate"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="coordinatecase", name="deleted_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="coordinatecase", name="deleted_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name="+", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="coordinatemessage", name="deleted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="coordinatemessage", name="deleted_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name="+", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name="coordinatejob", name="status",
            field=models.CharField(choices=[("queued", "Queued"), ("processing", "Processing"),
                                            ("completed", "Completed"), ("retry", "Retry"),
                                            ("cancelled", "Cancelled")], default="queued", max_length=12),
        ),
        migrations.AlterField(
            model_name="coordinatemessage", name="role",
            field=models.CharField(choices=[("staff", "Staff"), ("assistant", "Codex"), ("system", "System")], max_length=12),
        ),
    ]
