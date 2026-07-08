import os
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .models import Artwork, ArtworkImage


def _authorized(request):
    expected = os.environ.get("CATALOG_API_KEY")
    return bool(expected and request.headers.get("X-API-KEY") == expected)


def _parse_price(value):
    text = str(value or "0").replace("$", "").replace(",", "").strip()
    try:
        return Decimal(text or "0")
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Price must be numeric.") from exc


@csrf_exempt
def upload_artwork(request):
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method"}, status=405)
    if not _authorized(request):
        return JsonResponse({"error": "Unauthorized"}, status=401)

    data = request.POST
    try:
        with transaction.atomic():
            artwork = Artwork.objects.create(
                title=data.get("title") or "Untitled",
                artist=data.get("artist") or "Unknown Artist",
                year=data.get("year", ""),
                medium=data.get("medium", ""),
                paper_type=data.get("paper_type", ""),
                edition_size=data.get("edition_size", ""),
                printer=data.get("printer", ""),
                publisher=data.get("publisher", ""),
                dimensions_text=data.get("dimensions_text", ""),
                sheet_size=data.get("sheet_size", ""),
                catalog_number=data.get("catalog_number", ""),
                description=data.get("description", ""),
                catalog_description=data.get("catalog_description", ""),
                price=_parse_price(data.get("price", 0)),
                is_available=True,
                display_order=Artwork.next_display_order(),
            )
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    warnings = []
    for key, file_obj in request.FILES.items():
        try:
            ArtworkImage.objects.create(artwork=artwork, image=file_obj)
        except Exception as exc:
            warnings.append(f"{key}: {exc}")

    payload = {"message": "Artwork uploaded successfully!", "id": artwork.id}
    if warnings:
        payload["warnings"] = warnings
    return JsonResponse(payload, status=201)
