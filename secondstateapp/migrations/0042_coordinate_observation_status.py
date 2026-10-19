"""Keep listing and contextual observations separate even at the same page URL."""
import hashlib
import json

from django.db import migrations


def observation_keys(apps, schema_editor):
    Research = apps.get_model("secondstateapp", "CoordinateResearch")
    alias = schema_editor.connection.alias
    for record in Research.objects.using(alias).all().iterator():
        identity = record.identity_match if isinstance(record.identity_match, dict) else {}
        key = hashlib.sha256(json.dumps(
            [record.source_url, record.final_url, record.source_kind, identity.get("status", "unverified")],
            ensure_ascii=True,
        ).encode()).hexdigest()
        Research.objects.using(alias).filter(pk=record.pk).update(observation_key=key)


class Migration(migrations.Migration):
    dependencies = [("secondstateapp", "0041_coordinate_mail")]

    # Reversing the key would collapse legitimate exact/context pairs. Keep the
    # original observations intact rather than pretending that downgrade is safe.
    operations = [migrations.RunPython(observation_keys)]
