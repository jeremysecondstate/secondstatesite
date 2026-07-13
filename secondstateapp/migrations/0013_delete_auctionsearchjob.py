from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("secondstateapp", "0012_auctionsearchjob"),
    ]

    operations = [
        migrations.DeleteModel(
            name="AuctionSearchJob",
        ),
    ]
