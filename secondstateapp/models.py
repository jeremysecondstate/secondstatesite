from django.db import models
from PIL import Image
from io import BytesIO
from django.core.files.base import ContentFile
import os


class SoldPiece(models.Model):
    # Keep it simple + match the spreadsheet
    date = models.DateField(blank=True, null=True)
    artist = models.CharField(max_length=255, blank=True, null=True)
    title = models.CharField(max_length=255, blank=True, null=True)  # from "Name"
    sale_location = models.CharField(max_length=255, blank=True, null=True)
    sold_hammer_price = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    link_to_sale = models.URLField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.artist} — {self.title}"

class SoldPieceImage(models.Model):
    sold_piece = models.ForeignKey(
        SoldPiece,
        related_name="images",
        on_delete=models.CASCADE
    )
    image = models.ImageField(upload_to="sold_pieces/")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"SoldPieceImage({self.sold_piece_id})"

class Artwork(models.Model):
    title = models.CharField(max_length=255)
    artist = models.CharField(max_length=255)
    year = models.CharField(max_length=10, blank=True, null=True)  # New field
    medium = models.CharField(max_length=255, blank=True, null=True)
    paper_type = models.CharField(max_length=255, blank=True, null=True)  # New field
    printer = models.CharField(max_length=255, blank=True, null=True)  # New field
    publisher = models.CharField(max_length=255, blank=True, null=True)  # New field
    edition_size = models.CharField(max_length=50, blank=True, null=True)  # New field
    dimensions_text = models.CharField(max_length=255, blank=True, null=True)
    sheet_size = models.CharField(max_length=255, blank=True, null=True)  # New field
    catalog_number = models.CharField(max_length=255, blank=True, null=True)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    is_available = models.BooleanField(default=True)

class ArtworkImage(models.Model):
    artwork = models.ForeignKey("Artwork", related_name="images", on_delete=models.CASCADE)
    image = models.ImageField(upload_to="artworks/")
    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)  # save original first so self.image.path exists
        if not self.image:
            return
        img = Image.open(self.image.path)
        # Fix orientation from phones (optional but useful)
        try:
            from PIL import ImageOps
            img = ImageOps.exif_transpose(img)
        except Exception:
            pass
        # Convert to RGB for JPEG
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        # Resize: cap the long edge (pick your number)
        MAX_EDGE = 2000
        img.thumbnail((MAX_EDGE, MAX_EDGE), Image.Resampling.LANCZOS)
        # Re-encode as JPEG with quality
        buffer = BytesIO()
        img.save(buffer, format="JPEG", quality=82, optimize=True, progressive=True)
        base, _ext = os.path.splitext(os.path.basename(self.image.name))
        new_name = f"artworks/{base}.jpg"
        self.image.save(new_name, ContentFile(buffer.getvalue()), save=False)
        super().save(update_fields=["image"])