from django.db import migrations, models


def preserve_saved_sources(apps, schema_editor):
    Analysis = apps.get_model("secondstateapp", "AuctionMaxBidAnalysis")
    for analysis in Analysis.objects.using(schema_editor.connection.alias).all().iterator():
        analysis.sources = [{
            "id": f"legacy-{analysis.pk}",
            "filename": analysis.source_filename,
            "currency": analysis.currency,
            "comparables": analysis.comparables,
            "uploaded_at": analysis.updated_at.isoformat(),
        }]
        analysis.save(update_fields=["sources"])


class Migration(migrations.Migration):
    dependencies = [("secondstateapp", "0025_liveartresaleanalysis_source_summary")]

    operations = [
        migrations.AddField(
            model_name="auctionmaxbidanalysis",
            name="sources",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.RunPython(preserve_saved_sources, migrations.RunPython.noop),
    ]
