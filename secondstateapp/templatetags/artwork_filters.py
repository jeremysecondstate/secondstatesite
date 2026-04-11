from django import template
from django.utils.safestring import mark_safe
import re

register = template.Library()

KEYWORDS = [
    "lithograph",
    "etching",
    "woodcut",
    "screenprint",
    "drypoint",
    "monotype",
    "aquatint",
    "linocut",
]

pattern = re.compile(r"(" + "|".join(re.escape(k) for k in KEYWORDS) + r")", re.IGNORECASE)

@register.filter
def highlight_medium_terms(value):
    if not value:
        return ""

    def repl(match):
        return f"<strong>{match.group(0)}</strong>"

    return mark_safe(pattern.sub(repl, str(value)))