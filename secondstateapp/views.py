import json
import os
# from django.conf import settings
from django.core.files.storage import default_storage
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from .models import Artwork, ArtworkImage  # Import ArtworkImage model


def healthz(request):
    return JsonResponse({"ok": True})


def home(request):
    return render(request, "home.html")

def about(request):
    return render(request, "about.html")

def contact(request):
    return render(request, "contact.html")

def gallery(request):
    # Show the same content as /artworks/
    artworks = Artwork.objects.all()
    # artworks = Artwork.objects.order_by("-id")
    return render(request, "artworks/artwork_list.html", {"artworks": artworks})


def pieces_sold(request):
    # leave blank for now (later: pull from DB)
    return render(request, "pieces_sold.html")

def _authorized(request):
    expected = os.environ.get("CATALOG_API_KEY")
    if not expected:
        return False
    return request.headers.get("X-API-KEY") == expected

def artwork_list(request):
    """Render artwork_list.html for normal browser requests; return JSON only when explicitly requested."""
    artworks = Artwork.objects.all()

    # Check if the request explicitly asks for JSON
    if 'format' in request.GET and request.GET['format'] == 'json':
        artwork_data = list(artworks.values('id', 'title', 'artist', 'description', 'price'))
        return JsonResponse({'artworks': artwork_data})

    # Otherwise, render the template
    return render(request, 'artworks/artwork_list.html', {'artworks': artworks})


def artwork_detail(request, pk):
    """Renders the detail page of an artwork from the database."""
    try:
        artwork = Artwork.objects.get(id=pk)  # Fetch from database
    except Artwork.DoesNotExist:
        return render(request, '404.html')  # Ensure you have a 404.html template

    return render(request, 'artworks/artwork_detail.html', {'artwork': artwork})


@csrf_exempt
def delete_artwork(request):
    """Deletes an artwork and all its associated images from the database and storage."""
    if request.method == 'POST':
        try:
            if not _authorized(request):
                return JsonResponse({"error": "Unauthorized"}, status=401)

            data = json.loads(request.body)
            title = data.get('title')

            # Find the artwork
            artwork = Artwork.objects.filter(title=title).first()
            if not artwork:
                return JsonResponse({'error': 'Artwork not found'}, status=404)

            # Delete all associated images from storage
            for image in artwork.images.all():
                # image_path = os.path.join(settings.MEDIA_ROOT, str(image.image))
                # if default_storage.exists(image_path):
                #     default_storage.delete(image_path)
                if image.image and default_storage.exists(image.image.name):
                    default_storage.delete(image.image.name)

            # Delete the artwork and its associated images from the database
            artwork.images.all().delete()  # Delete image entries
            artwork.delete()  # Delete artwork entry

            return JsonResponse({'message': f"'{title}' and all associated images deleted successfully!"}, status=200)

        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)

    return JsonResponse({'error': 'Invalid request method'}, status=405)


@csrf_exempt
def upload_artwork(request):
    if request.method == 'POST':
        try:
            if not _authorized(request):
                return JsonResponse({"error": "Unauthorized"}, status=401)

            data = request.POST

            # Save artwork to the database using raw fields from Excel
            artwork = Artwork.objects.create(
                title=data.get('title'),
                artist=data.get('artist'),
                year=data.get('year', ''),
                medium=data.get('medium', ''),
                paper_type=data.get('paper_type', ''),
                edition_size=data.get('edition_size', ''),
                printer=data.get('printer', ''),
                publisher=data.get('publisher', ''),
                dimensions_text=data.get('dimensions_text', ''),
                sheet_size=data.get('sheet_size', ''),
                catalog_number=data.get('catalog_number', ''),
                description=data.get('description', ''),  # ✅ This is now the 'Description/Notes' field
                price=float(data.get('price', 0)),
                is_available=True
            )

            # Save uploaded images
            for key, file in request.FILES.items():
                ArtworkImage.objects.create(artwork=artwork, image=file)

            return JsonResponse({'message': 'Artwork uploaded successfully!', 'id': artwork.id}, status=201)

        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)

    return JsonResponse({'error': 'Invalid request method'}, status=405)
