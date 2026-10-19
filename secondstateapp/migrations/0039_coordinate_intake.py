import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("secondstateapp", "0038_coordinate_brief")]

    operations = [
        migrations.CreateModel(
            name="CoordinateDocument",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("title", models.CharField(max_length=200)),
                ("kind", models.CharField(choices=[("text", "Pasted text"), ("pdf", "PDF")], max_length=8)),
                ("text", models.TextField(blank=True)),
                ("original_pdf", models.BinaryField(blank=True, default=bytes)),
                ("filename", models.CharField(blank=True, max_length=200)),
                ("byte_size", models.PositiveIntegerField()),
                ("content_digest", models.CharField(max_length=64)),
                ("extraction_status", models.CharField(choices=[("ready", "Text available"), ("truncated", "Partial text available"), ("no_text", "No readable text")], max_length=12)),
                ("extraction_error", models.CharField(blank=True, max_length=300)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("case", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="intake_documents", to="secondstateapp.coordinatecase")),
                ("message", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="intake_document", to="secondstateapp.coordinatemessage")),
            ],
            options={"ordering": ["-message_id"]},
        ),
    ]
