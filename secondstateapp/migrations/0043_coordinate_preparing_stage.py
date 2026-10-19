"""Treat lot research and quote collection as one shipment preparation stage."""
from django.db import migrations, models


def consolidate_preparation(apps, schema_editor):
    Plan = apps.get_model("secondstateapp", "CoordinatePlan")
    Activity = apps.get_model("secondstateapp", "CoordinateActivity")
    alias = schema_editor.connection.alias
    for plan in Plan.objects.using(alias).filter(stage__in=["gathering", "quotes"]).iterator():
        Activity.objects.using(alias).create(case_id=plan.case_id, event="shipping_stage_consolidated",
            details={"previous_stage": plan.stage, "stage": "preparing"})
        Plan.objects.using(alias).filter(pk=plan.pk).update(stage="preparing")


class Migration(migrations.Migration):
    dependencies = [("secondstateapp", "0042_coordinate_observation_status")]
    operations = [
        migrations.RunPython(consolidate_preparation),
        migrations.AlterField(model_name="coordinateplan", name="stage",
            field=models.CharField(max_length=20, default="preparing", choices=[
                ("preparing", "Preparing shipment"), ("ready", "Ready for pickup"),
                ("pickup", "Pickup arranged"), ("transit", "In transit"),
                ("received", "Received"), ("on_hold", "On hold")]))
    ]
