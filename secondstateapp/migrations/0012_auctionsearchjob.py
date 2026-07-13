import uuid

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("secondstateapp", "0011_artwork_display_order"),
    ]

    operations = [
        migrations.CreateModel(
            name="AuctionSearchJob",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("correlation_id", models.UUIDField(db_index=True, default=uuid.uuid4, editable=False)),
                ("requester_fingerprint", models.CharField(db_index=True, max_length=80)),
                (
                    "state",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("completed", "Completed"),
                            ("failed", "Failed"),
                            ("timed_out", "Timed out"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("openai_response_id", models.CharField(max_length=255)),
                ("openai_status", models.CharField(blank=True, max_length=32)),
                ("config", models.JSONField()),
                ("openai_settings", models.JSONField()),
                ("attempt_count", models.PositiveSmallIntegerField(default=1)),
                ("retry_warning", models.TextField(blank=True)),
                ("timeout_seconds", models.PositiveIntegerField()),
                ("attempt_deadline_at", models.DateTimeField(db_index=True)),
                ("last_polled_at", models.DateTimeField(blank=True, null=True)),
                ("result", models.JSONField(blank=True, null=True)),
                ("error", models.JSONField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["-created_at"]},
        ),
    ]
