"""Clear historical Random Lots placements owned by a dated Catalog survivor."""

from pathlib import Path

from django.conf import settings
from django.db import migrations
from django.db.models import Q

from catalogapp.tracked_artists import allows_watchlist_credit, is_tracked_credit, tracked_artist_keys


def remove_overlaps(apps, schema_editor):
    connection = schema_editor.connection
    model = apps.get_model("secondstateapp", "AuctionWatchLot")
    lots = model.objects.using(connection.alias).order_by()
    if not lots.filter(random_lot=True).exists():
        return

    survivors = lots.filter(event_at__isnull=False, superseded_by__isnull=True)
    roster = tracked_artist_keys(Path(settings.BASE_DIR) / "docs" / "artist-links.html")
    pairs = survivors.values_list("artist", "artist_watchlist_name").distinct()
    names, fallback = set(), set()
    for artist, watch in pairs.iterator():
        if is_tracked_credit(artist, roster):
            names.add(artist)
        if is_tracked_credit(watch, roster):
            names.add(watch)
            if allows_watchlist_credit(artist):
                fallback.add(artist)
    if not names:
        return

    eligible = survivors.filter(Q(artist__in=names) | Q(artist_watchlist_name__in=names, artist__in=fallback))
    seeds, params = eligible.values("pk").query.get_compiler(using=connection.alias).as_sql()
    table = connection.ops.quote_name(model._meta.db_table)
    # Check the live credits and replacement links in the same statement as the
    # update. A saved secondary listing can donate membership across several merges.
    with connection.cursor() as cursor:
        cursor.execute(f"""
            WITH RECURSIVE catalog_ids(id) AS (
                {seeds}
                UNION
                SELECT child.id FROM {table} child
                JOIN catalog_ids parent ON child.superseded_by_id = parent.id
            )
            UPDATE {table} SET random_lot = FALSE
            WHERE random_lot AND id IN (SELECT id FROM catalog_ids)
        """, params)


class Migration(migrations.Migration):
    dependencies = [("secondstateapp", "0059_retain_invaluable_black_cab")]
    operations = [migrations.RunPython(remove_overlaps, migrations.RunPython.noop)]
