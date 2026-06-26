import json
import os
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation

from django.core.files.storage import default_storage
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .models import Artwork, ArtworkImage


TEXT_FIELDS = [
    "title", "artist", "year", "medium", "paper_type", "printer", "publisher",
    "edition_size", "dimensions_text", "sheet_size", "catalog_number",
    "description", "catalog_description",
]


def _authorized(request):
    expected = os.environ.get("CATALOG_API_KEY")
    return bool(expected and request.headers.get("X-API-KEY") == expected)


def _can_manage(request):
    user = getattr(request, "user", None)
    return bool(user and user.is_authenticated and user.is_staff) or _authorized(request)


def _bool(value):
    return str(value).lower() in {"1", "true", "yes", "on"}


def _price(value):
    cleaned = str(value or "0").replace("$", "").replace(",", "").strip()
    try:
        return Decimal(cleaned or "0")
    except (InvalidOperation, ValueError):
        raise ValueError("Price must be a number.")


def _apply(artwork, data):
    for field in TEXT_FIELDS:
        if field in data:
            setattr(artwork, field, data.get(field) or "")
    if "price" in data:
        artwork.price = _price(data.get("price"))
    if "is_available" in data:
        artwork.is_available = _bool(data.get("is_available"))


def _image_url(request, image):
    if not image.image:
        return ""
    try:
        url = image.image.url
    except ValueError:
        return ""
    return request.build_absolute_uri(url) if request else url


def _serialize(request, artwork):
    return {
        "id": artwork.id,
        "artist": artwork.artist,
        "title": artwork.title,
        "year": artwork.year or "",
        "medium": artwork.medium or "",
        "paper_type": artwork.paper_type or "",
        "printer": artwork.printer or "",
        "publisher": artwork.publisher or "",
        "edition_size": artwork.edition_size or "",
        "dimensions_text": artwork.dimensions_text or "",
        "sheet_size": artwork.sheet_size or "",
        "catalog_number": artwork.catalog_number or "",
        "description": artwork.description or "",
        "catalog_description": artwork.catalog_description or "",
        "price": str(artwork.price) if artwork.price is not None else "",
        "formatted_price": artwork.formatted_price,
        "is_available": artwork.is_available,
        "images": [{"id": image.id, "url": _image_url(request, image)} for image in artwork.images.all()],
    }


def _prompt_fields(artwork):
    return {
        "Artist": artwork.artist,
        "Title": artwork.title,
        "Year": artwork.year,
        "Medium": artwork.medium,
        "Image size": artwork.dimensions_text,
        "Sheet size": artwork.sheet_size,
        "Literature": artwork.catalog_number,
        "Notes / signature text": artwork.description,
        "Current description": artwork.catalog_description,
    }


def _extract_text(payload):
    if payload.get("output_text"):
        return payload["output_text"].strip()
    pieces = []
    for item in payload.get("output", []):
        for content in item.get("content", []):
            if content.get("text"):
                pieces.append(content["text"])
    return "\n".join(pieces).strip()


def _generate_description(artwork, use_web=True):
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured on the server.")
    facts = "\n".join(f"{k}: {v}" for k, v in _prompt_fields(artwork).items() if v)
    prompt = f"""
Write a polished SecondState artwork catalog description for the print below.
Use 85 to 140 words. Write in a confident fine-art gallery voice.
Do not invent edition details, provenance, signatures, condition, or price.
Return only the description paragraph.

Artwork facts:
{facts}
""".strip()
    body = {
        "model": os.environ.get("OPENAI_DESCRIPTION_MODEL", "gpt-4.1"),
        "input": prompt,
        "max_output_tokens": 450,
        "temperature": 0.4,
    }
    if use_web:
        body["tools"] = [{"type": "web_search", "search_context_size": "low"}]
        body["tool_choice"] = "auto"
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            message = json.loads(exc.read().decode("utf-8")).get("error", {}).get("message")
        except Exception:
            message = str(exc)
        raise RuntimeError(f"OpenAI request failed: {message}") from exc
    text = _extract_text(payload)
    if not text:
        raise RuntimeError("OpenAI returned an empty description.")
    return text


@require_GET
def artwork_manage_list(request):
    if not _can_manage(request):
        return JsonResponse({"error": "Unauthorized"}, status=401)
    artworks = Artwork.objects.prefetch_related("images").all()
    return JsonResponse({"artworks": [_serialize(request, artwork) for artwork in artworks]})


@csrf_exempt
@require_POST
def generate_catalog_description_from_payload(request):
    if not _can_manage(request):
        return JsonResponse({"error": "Unauthorized"}, status=401)
    try:
        data = json.loads(request.body.decode("utf-8")) if request.body else {}
        artwork = Artwork(price=Decimal("0"), is_available=True)
        _apply(artwork, data)
        return JsonResponse({"description": _generate_description(artwork, data.get("use_web", True))})
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=400)


@csrf_exempt
def update_artwork(request, pk):
    if request.method not in {"POST", "PATCH"}:
        return JsonResponse({"error": "Invalid request method"}, status=405)
    if not _authorized(request):
        return JsonResponse({"error": "Unauthorized"}, status=401)
    artwork = get_object_or_404(Artwork, id=pk)
    try:
        data = request.POST.copy()
        _apply(artwork, data)
        artwork.save()
        for image_id in request.POST.getlist("delete_image_ids"):
            image = artwork.images.filter(id=image_id).first()
            if image:
                if image.image and default_storage.exists(image.image.name):
                    default_storage.delete(image.image.name)
                image.delete()
        for _key, uploaded in request.FILES.items():
            ArtworkImage.objects.create(artwork=artwork, image=uploaded)
        artwork.refresh_from_db()
        return JsonResponse({"message": "Artwork updated successfully!", "artwork": _serialize(request, artwork)})
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=400)
