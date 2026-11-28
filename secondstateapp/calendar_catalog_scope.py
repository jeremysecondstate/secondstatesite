"""The default Calendar Catalog's attribution and survivor rules."""

from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.db.models import Q

from catalogapp.tracked_artists import allows_watchlist_credit, is_tracked_credit, tracked_artist_keys
from .models import AuctionWatchLot


def calendar_tracked_credit():
    roster = tracked_artist_keys(Path(settings.BASE_DIR) / "docs" / "artist-links.html")

    @lru_cache(maxsize=None)
    def tracked(label):
        return is_tracked_credit(label, roster)

    return tracked


def regular_catalog_credit(credit, watch, tracked):
    return tracked(credit) or (tracked(watch) and allows_watchlist_credit(credit))


def is_regular_catalog_lot(lot, tracked):
    return bool(lot.superseded_by_id is None and lot.event_at
                and regular_catalog_credit(lot.artist, lot.artist_watchlist_name, tracked))


def regular_catalog_artist_filter(request):
    if not hasattr(request, "_calendar_artist_filter"):
        # Use stored credits on survivors, including historical lots with no watchlist FK.
        lots = AuctionWatchLot.objects.filter(superseded_by__isnull=True)
        pairs = list(lots.order_by().values_list("artist", "artist_watchlist_name").distinct())
        tracked = calendar_tracked_credit()
        names = {label for pair in pairs for label in pair if tracked(label)}
        qualified = {credit for credit, watch in pairs
                     if credit not in names and regular_catalog_credit(credit, watch, tracked)}
        request._calendar_artist_filter = Q(artist__in=names) | Q(artist_watchlist_name__in=names, artist__in=qualified)
    return request._calendar_artist_filter


def clear_regular_random_flags(regular_ids):
    """Retire saved membership on these physical lots, including merged source copies."""
    affected = set(regular_ids)
    pending = affected
    while pending:
        children = AuctionWatchLot.objects.filter(superseded_by_id__in=pending).order_by().values_list("pk", flat=True)
        pending = set(children) - affected
        affected.update(pending)
    if affected:
        AuctionWatchLot.objects.filter(pk__in=affected, random_lot=True).update(random_lot=False)
