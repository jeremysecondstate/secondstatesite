from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("secondstateapp", "0048_research_queue"),
    ]

    operations = [
        # Retire the workspaces from Django without erasing historical staff
        # conversations, receipts, or workbook-operation records. Historical
        # migrations remain necessary for existing and fresh installations.
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.DeleteModel(name="CoordinateActivity"),
                migrations.DeleteModel(name="CoordinateBrief"),
                migrations.DeleteModel(name="CoordinateDocument"),
                migrations.DeleteModel(name="CoordinateMailDelivery"),
                migrations.DeleteModel(name="CoordinateMailMessage"),
                migrations.DeleteModel(name="CoordinateDraft"),
                migrations.DeleteModel(name="CoordinateMailThread"),
                migrations.DeleteModel(name="CoordinateOutreachPolicy"),
                migrations.DeleteModel(name="CoordinateQuoteInquiry"),
                migrations.DeleteModel(name="CoordinateResearch"),
                migrations.DeleteModel(name="CoordinateQuote"),
                migrations.DeleteModel(name="CoordinatePlan"),
                migrations.DeleteModel(name="CoordinateJob"),
                migrations.DeleteModel(name="CoordinateMessage"),
                migrations.DeleteModel(name="CoordinateCase"),
                migrations.DeleteModel(name="CoordinateWorkerState"),
                migrations.DeleteModel(name="InventoryClaimRequest"),
                migrations.DeleteModel(name="InventoryJob"),
                migrations.DeleteModel(name="InventoryMessage"),
                migrations.DeleteModel(name="InventoryCase"),
                migrations.DeleteModel(name="InventoryWorkerState"),
            ],
        ),
    ]
