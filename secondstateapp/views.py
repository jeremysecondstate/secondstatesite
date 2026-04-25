# secondstateapp/views.py
import json
import os

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User
from django.core.files.storage import default_storage
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.core.mail import send_mail
from .forms import ContactForm


from .forms import RegisterForm, UserProfileForm
from .models import Artwork, ArtworkImage, SoldPiece, UserProfile


@csrf_exempt
def delete_sold_piece(request):
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method"}, status=405)

    if not _authorized(request):
        return JsonResponse({"error": "Unauthorized"}, status=401)

    try:
        payload = json.loads(request.body or "{}")
        sold_id = payload.get("id")

        if not sold_id:
            return JsonResponse({"error": "Missing id"}, status=400)

        sp = SoldPiece.objects.filter(id=sold_id).first()
        if not sp:
            return JsonResponse({"error": "Not found"}, status=404)

        sp.delete()
        return JsonResponse({"message": "Deleted"}, status=200)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


def sold_piece_detail(request, pk):
    try:
        sold = SoldPiece.objects.get(id=pk)
    except SoldPiece.DoesNotExist:
        return render(request, "404.html")
    return render(request, "sold_piece_detail.html", {"sold": sold})


def healthz(request):
    return JsonResponse({"ok": True})


def home(request):
    return render(request, "home.html")


def about(request):
    return render(request, "about.html")


def contact(request):
    success = False

    if request.method == "POST":
        form = ContactForm(request.POST)

        if form.is_valid():
            name = form.cleaned_data["name"]
            email = form.cleaned_data["email"]
            message = form.cleaned_data["message"]

            send_mail(
                subject=f"Second State Contact Form - {name}",
                message=f"""
New contact form submission:

Name: {name}
Email: {email}

Message:
{message}
""",
                from_email="hello@secondstate.art",
                recipient_list=[
                    "oliver@secondstate.art",
                    "hello@secondstate.art",
                ],
                fail_silently=False,
            )

            success = True
            form = ContactForm()
    else:
        form = ContactForm()

    return render(request, "contact.html", {
        "form": form,
        "success": success,
    })


def gallery(request):
    # Show the same content as /artworks/
    artworks = Artwork.objects.all()
    # artworks = Artwork.objects.order_by("-id")
    return render(request, "artworks/artwork_list.html", {"artworks": artworks})


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


def artwork_list(request):
    """Render artwork_list.html for normal browser requests; return JSON only when explicitly requested."""
    artworks = Artwork.objects.all()
    # Check if the request explicitly asks for JSON
    if "format" in request.GET and request.GET["format"] == "json":
        artwork_data = list(artworks.values("id", "title", "artist", "description", "price"))
        return JsonResponse({"artworks": artwork_data})
    # Otherwise, render the template
    return render(request, "artworks/artwork_list.html", {"artworks": artworks})


def artwork_detail(request, pk):
    """Renders the detail page of an artwork from the database."""
    try:
        artwork = Artwork.objects.get(id=pk)  # Fetch from database
    except Artwork.DoesNotExist:
        return render(request, "404.html")  # Ensure you have a 404.html template
    return render(request, "artworks/artwork_detail.html", {"artwork": artwork})


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
                description=data.get("description", ""),  # This is now the 'Description/Notes' field
                price=float(data.get("price", 0)),
                is_available=True,
            )
            # Save uploaded images
            for _key, file in request.FILES.items():
                ArtworkImage.objects.create(artwork=artwork, image=file)
            return JsonResponse({"message": "Artwork uploaded successfully!", "id": artwork.id}, status=201)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)
    return JsonResponse({"error": "Invalid request method"}, status=405)
