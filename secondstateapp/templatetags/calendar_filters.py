"""Display-only Calendar labels; source credits and saved data stay untouched."""

from django import template

from secondstateapp.bid_board_snapshot import uses_max_bid_label
from secondstateapp.lot_presentation import artist_display_name


register = template.Library()
register.filter("artist_display_name", artist_display_name)
register.filter("uses_max_bid_label", uses_max_bid_label)
