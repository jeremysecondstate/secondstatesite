"""Display-only Calendar labels; source credits and saved data stay untouched."""

from django import template

from secondstateapp.lot_presentation import artist_display_name


register = template.Library()
register.filter("artist_display_name", artist_display_name)
