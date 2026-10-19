import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("secondstateapp", "0037_coordinate_research_provenance")]

    operations = [
        migrations.CreateModel(
            name="CoordinateBrief",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("payload", models.JSONField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("case", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="briefs", to="secondstateapp.coordinatecase")),
                ("job", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="brief", to="secondstateapp.coordinatejob")),
            ],
            options={"ordering": ["-created_at", "-id"]},
        ),
    ]
