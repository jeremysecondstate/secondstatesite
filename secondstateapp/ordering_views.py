"""Session-authenticated, CSRF-protected ordering controls for gallery staff."""

import json

from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

from .models import Artwork, ArtworkImage


def _staff_error(request):
    user = request.user
    if not (user.is_authenticated and user.is_active and user.is_staff):
        return JsonResponse({"error": "Sign in with a staff account to rearrange artworks or photos."}, status=403)
    return None


def _read_orders(request):
    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError("Send a valid JSON object.") from None
    if not isinstance(payload, dict):
        raise ValueError("Send a valid JSON object.")

    orders = []
    for key in ("order", "original_order"):
        value = payload.get(key)
        if not isinstance(value, list) or any(type(item) is not int for item in value):
            raise ValueError(f"{key} must be a list of integer IDs.")
        if len(value) != len(set(value)):
            raise ValueError(f"{key} must not contain duplicate IDs.")
        orders.append(value)
    return orders


def _save_order(model, items, order, original_order):
    current_order = [item.pk for item in sorted(items, key=lambda item: (item.display_order, item.pk))]
    if original_order != current_order:
        return JsonResponse(
            {"error": "This collection changed while you were rearranging it. Reload the page and try again."},
            status=409,
        )
    if set(order) != set(current_order):
        return JsonResponse({"error": "Include every item in this collection exactly once."}, status=400)

    items_by_id = {item.pk: item for item in items}
    changed = []
    for position, item_id in enumerate(order):
        item = items_by_id[item_id]
        if item.display_order != position:
            item.display_order = position
            changed.append(item)
    if changed:
        # Never invoke ArtworkImage.save(): reordering must not reprocess files.
        model.objects.bulk_update(changed, ["display_order"])
    return JsonResponse({"order": order})


@require_POST
@csrf_protect
def gallery_reorder(request):
    error = _staff_error(request)
    if error is not None:
        return error
    try:
        order, original_order = _read_orders(request)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    with transaction.atomic():
        # Lock in immutable ID order, then read the saved display order in memory.
        artworks = list(Artwork.objects.select_for_update().order_by("pk"))
        return _save_order(Artwork, artworks, order, original_order)


@require_POST
@csrf_protect
def artwork_image_reorder(request, pk):
    error = _staff_error(request)
    if error is not None:
        return error
    try:
        order, original_order = _read_orders(request)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    with transaction.atomic():
        try:
            Artwork.objects.select_for_update().only("pk").get(pk=pk)
        except Artwork.DoesNotExist:
            return JsonResponse({"error": "Artwork not found."}, status=404)
        images = list(ArtworkImage.objects.select_for_update().filter(artwork_id=pk).order_by("pk"))
        return _save_order(ArtworkImage, images, order, original_order)
