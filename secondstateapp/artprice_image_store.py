"""Persistent artwork from staff-uploaded Artprice sales."""

from hashlib import sha256
from pathlib import Path

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.http import FileResponse, Http404
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

from .calendar_images import store_normalized_jpeg


def _private_directory() -> Path:
    media_root = Path(settings.MEDIA_ROOT).resolve()
    # Use the same persistent disk, outside the publicly served media tree.
    return media_root.with_name(f"{media_root.name}-private-artprice")


def store_saved_artprice_image(content: bytes) -> str:
    digest = store_normalized_jpeg(content, _private_directory())
    return reverse("saved_artprice_image", args=[digest])


def saved_artprice_image_url(content: bytes) -> str:
    """Compute the future URL while a multipart import is still being validated."""
    return reverse("saved_artprice_image", args=[sha256(content).hexdigest()])


@never_cache
@staff_member_required
@require_safe
def saved_artprice_image(request, digest):
    # The URL pattern admits only a 64-character lowercase hex digest.
    try:
        image = (_private_directory() / f"{digest}.jpg").open("rb")
    except FileNotFoundError:
        raise Http404("Saved Artprice image unavailable.") from None
    return FileResponse(image, content_type="image/jpeg")
