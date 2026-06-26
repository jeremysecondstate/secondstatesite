# Generated manually for SecondState catalog descriptions

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("secondstateapp", "0009_userprofile"),
    ]

    operations = [
        migrations.AddField(
            model_name="artwork",
            name="catalog_description",
            field=models.TextField(
                blank=True,
                default="",
                help_text="Public-facing description displayed under Literature on the artwork page.",
            ),
        ),
    ]
