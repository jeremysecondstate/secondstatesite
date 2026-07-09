# secondstateapp/views.py
import json
import os
import urllib.error
import urllib.request

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User
from django.db import transaction
from django.core.files.storage import default_storage
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .forms import ArtworkForm, RegisterForm, UserProfileForm
from .models import Artwork, ArtworkImage, UserProfile


DESCRIPTION_MODEL_ENV = "OPENAI_DESCRIPTION_MODEL"
DEFAULT_DESCRIPTION_MODEL = "gpt-4.1"


def schwab_callback(request):
    """Display Schwab OAuth callback values for the desktop cockpit setup.

    This endpoint intentionally does not exchange the OAuth code for tokens or
    store any brokerage credentials. It exists so Schwab can redirect back to an
    HTTPS URL during the first manual desktop-app authorization flow.
    """
    return render(
        request,
        "schwab/callback.html",
        {
            "code": request.GET.get("code", ""),
            "state": request.GET.get("state", ""),
            "error": request.GET.get("error", ""),
            "error_description": request.GET.get("error_description", ""),
        },
    )


def healthz(request):
    return JsonResponse({"ok": True})


def home(request):
    return render(request, "home.html")


def about(request):
    return render(request, "about.html")


def contact(request):
    return render(request, "contact.html")


def _ordered_gallery_artworks():
    return Artwork.objects.prefetch_related("images").order_by("display_order", "id")


def _gallery_template_context(artworks):
    return {
        "artworks": artworks,
        "available_count": Artwork.objects.filter(is_available=True).count(),
    }


def gallery(request):
    # Show the same content as /artworks/
    artworks = _ordered_gallery_artworks()
    # artworks = Artwork.objects.order_by("-id")
    return render(request, "artworks/artwork_list.html", _gallery_template_context(artworks))


def register(request):
    if request.user.is_authenticated:
        return redirect("account_profile")

    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            raw_password = form.cleaned_data.get("password1")
            authenticated_user = authenticate(request, username=user.username, password=raw_password)
            if authenticated_user is not None:
                login(request, authenticated_user)
            messages.success(request, "Welcome to SecondState. Your account is ready.")
            return redirect("account_profile")
    else:
        form = RegisterForm()

    return render(request, "accounts/register.html", {"form": form})


def login_view(request):
    if request.user.is_authenticated:
        return redirect("account_profile")

    if request.method == "POST":
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            messages.success(request, f"Welcome back, {user.username}.")
            next_url = request.GET.get("next")
            return redirect(next_url or "account_profile")
    else:
        form = AuthenticationForm(request)

    return render(request, "accounts/login.html", {"form": form})


def logout_view(request):
    logout(request)
    messages.info(request, "You have been logged out.")
    return redirect("home")


@login_required
def account_profile(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)

    if request.method == "POST":
        form = UserProfileForm(request.POST, request.FILES, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, "Your profile was updated.")
            return redirect("account_profile")
    else:
        form = UserProfileForm(instance=profile)

    return render(
        request,
        "accounts/account_profile.html",
        {
            "form": form,
            "profile": profile,
        },
    )


def public_profile(request, username):
    site_user = get_object_or_404(User, username=username)
    profile_user, _ = UserProfile.objects.get_or_create(user=site_user)
    return render(
        request,
        "accounts/public_profile.html",
        {
            "profile_user": profile_user,
        },
    )


def _authorized(request):
    expected = os.environ.get("CATALOG_API_KEY")
    if not expected:
        return False
    return request.headers.get("X-API-KEY") == expected


def _user_can_manage_catalog(request):
    user = getattr(request, "user", None)
    return bool(user and user.is_authenticated and user.is_staff) or _authorized(request)


def _delete_artwork_image_file(artwork_image):
    if artwork_image.image and default_storage.exists(artwork_image.image.name):
        default_storage.delete(artwork_image.image.name)
    artwork_image.delete()


def _artwork_prompt_fields(artwork):
    return {
        "Artist": artwork.artist,
        "Title": artwork.title,
        "Year": artwork.year,
        "Medium": artwork.medium,
        "Paper type": artwork.paper_type,
        "Printer": artwork.printer,
        "Publisher": artwork.publisher,
        "Edition size": artwork.edition_size,
        "Image size": artwork.dimensions_text,
        "Sheet size": artwork.sheet_size,
        "Literature": artwork.catalog_number,
        "Notes / signature text": artwork.description,
        "Current description": artwork.catalog_description,
    }


def _extract_response_text(payload):
    output_text = payload.get("output_text")
    if output_text:
        return output_text.strip()

    text_parts = []
    for item in payload.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                text_parts.append(content["text"])
    return "\n".join(text_parts).strip()


def _generate_catalog_description(artwork, use_web=True):
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured on the server.")

    facts = "\n".join(
        f"{label}: {value}"
        for label, value in _artwork_prompt_fields(artwork).items()
        if value
    )
    prompt = f"""
Write a polished SecondState artwork catalog description for the print below.

Style requirements:
- 85 to 140 words.
- Write in a confident fine-art gallery voice, not hype or sales copy.
- Mention the artist, title, year, medium, and visual/cultural context when known.
- If web search finds reliable context, use it quietly to improve accuracy.
- Do not invent edition details, catalogue raisonné numbers, signatures, provenance, or condition.
- Return only the description paragraph. Do not include bullets, headings, citations, or price.

Artwork facts:
{facts}
""".strip()

    body = {
        "model": os.environ.get(DESCRIPTION_MODEL_ENV, DEFAULT_DESCRIPTION_MODEL),
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
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            error_payload = json.loads(exc.read().decode("utf-8"))
            message = error_payload.get("error", {}).get("message") or str(error_payload)
        except Exception:
            message = str(exc)
        raise RuntimeError(f"OpenAI request failed: {message}") from exc

    text = _extract_response_text(payload)
    if not text:
        raise RuntimeError("OpenAI returned an empty description.")
    return text


def artwork_list(request):
    """Render artwork_list.html for normal browser requests; return JSON only when explicitly requested."""
    artworks = _ordered_gallery_artworks()
    # Check if the request explicitly asks for JSON
    if "format" in request.GET and request.GET["format"] == "json":
        artwork_data = list(
            artworks.values(
                "id",
                "title",
                "artist",
                "year",
                "medium",
                "description",
                "catalog_description",
                "dimensions_text",
                "sheet_size",
                "catalog_number",
                "price",
                "is_available",
                "display_order",
            )
        )
        return JsonResponse({"artworks": artwork_data})
    # Otherwise, render the template
    return render(request, "artworks/artwork_list.html", _gallery_template_context(artworks))


def artwork_detail(request, pk):
    """Renders the detail page of an artwork from the database."""
    try:
        artwork = Artwork.objects.get(id=pk)  # Fetch from database
    except Artwork.DoesNotExist:
        return render(request, "404.html")  # Ensure you have a 404.html template
    return render(request, "artworks/artwork_detail.html", {"artwork": artwork})


@staff_member_required
def artwork_edit(request, pk):
    artwork = get_object_or_404(Artwork, id=pk)

    if request.method == "POST":
        form = ArtworkForm(request.POST, instance=artwork)
        if form.is_valid():
            artwork = form.save()

            for image_id in request.POST.getlist("delete_images"):
                image = artwork.images.filter(id=image_id).first()
                if image:
                    _delete_artwork_image_file(image)

            for uploaded_image in request.FILES.getlist("images"):
                ArtworkImage.objects.create(artwork=artwork, image=uploaded_image)

            messages.success(request, "Artwork updated.")
            if "_continue" in request.POST:
                return redirect("artwork_edit", pk=artwork.id)
            return redirect("artwork_detail", pk=artwork.id)
    else:
        form = ArtworkForm(instance=artwork)

    return render(
        request,
        "artworks/artwork_edit.html",
        {
            "artwork": artwork,
            "form": form,
        },
    )


@csrf_exempt
@require_POST
def generate_artwork_description(request, pk):
    if not _user_can_manage_catalog(request):
        return JsonResponse({"error": "Unauthorized"}, status=401)

    artwork = get_object_or_404(Artwork, id=pk)
    payload = {}
    if request.body:
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON body"}, status=400)

    # Let the edit page send unsaved form values so the generation reflects the latest edits.
    for attr in [
        "artist",
        "title",
        "year",
        "medium",
        "paper_type",
        "printer",
        "publisher",
        "edition_size",
        "dimensions_text",
        "sheet_size",
        "catalog_number",
        "description",
        "catalog_description",
    ]:
        if attr in payload:
            setattr(artwork, attr, payload.get(attr) or "")

    try:
        description = _generate_catalog_description(artwork, use_web=payload.get("use_web", True))
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    return JsonResponse({"description": description})


@csrf_exempt
def delete_artwork(request):
    """Deletes an artwork and all its associated images from the database and storage."""
    if request.method == "POST":
        try:
            if not _authorized(request):
                return JsonResponse({"error": "Unauthorized"}, status=401)
            data = json.loads(request.body)
            title = data.get("title")
            # Find the artwork
            artwork = Artwork.objects.filter(title=title).first()
            if not artwork:
                return JsonResponse({"error": "Artwork not found"}, status=404)
            # Delete all associated images from storage
            for image in artwork.images.all():
                if image.image and default_storage.exists(image.image.name):
                    default_storage.delete(image.image.name)
            # Delete the artwork and its associated images from the database
            artwork.images.all().delete()  # Delete image entries
            artwork.delete()  # Delete artwork entry
            return JsonResponse({"message": f"'{title}' and all associated images deleted successfully!"}, status=200)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)
    return JsonResponse({"error": "Invalid request method"}, status=405)


@csrf_exempt
def upload_artwork(request):
    if request.method == "POST":
        try:
            if not _authorized(request):
                return JsonResponse({"error": "Unauthorized"}, status=401)
            data = request.POST
            # Save artwork to the database using raw fields from Excel
            with transaction.atomic():
                artwork = Artwork.objects.create(
                    title=data.get("title"),
                    artist=data.get("artist"),
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
                    price=float(data.get("price", 0)),
                    is_available=True,
                    display_order=Artwork.next_display_order(),
                )
            # Save uploaded images
            for _key, file in request.FILES.items():
                ArtworkImage.objects.create(artwork=artwork, image=file)
            return JsonResponse({"message": "Artwork uploaded successfully!", "id": artwork.id}, status=201)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)
    return JsonResponse({"error": "Invalid request method"}, status=405)
