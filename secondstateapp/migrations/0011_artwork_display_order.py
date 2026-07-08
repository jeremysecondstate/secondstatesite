# Generated manually for deterministic artwork gallery ordering

from django.db import migrations, models


def populate_display_order(apps, schema_editor):
    Artwork = apps.get_model("secondstateapp", "Artwork")
    for index, artwork_id in enumerate(Artwork.objects.order_by("id").values_list("id", flat=True)):
        Artwork.objects.filter(pk=artwork_id).update(display_order=index)


class Migration(migrations.Migration):

    dependencies = [
        ("secondstateapp", "0010_artwork_catalog_description"),
    ]

    operations = [
        migrations.AddField(
            model_name="artwork",
            name="display_order",
            field=models.PositiveIntegerField(db_index=True, default=0),
        ),
        migrations.RunPython(populate_display_order, migrations.RunPython.noop),
        migrations.AlterModelOptions(
            name="artwork",
            options={"ordering": ["display_order", "id"]},
        ),
    ]
