from django.contrib.auth.models import User
from django.db import models
from django.db.models import Max
from PIL import Image
from io import BytesIO
from django.core.files.base import ContentFile
import os
import uuid


class SoldPiece(models.Model):
    # Keep it simple + match the spreadsheet
    date = models.DateField(blank=True, null=True)
    artist = models.CharField(max_length=255, blank=True, null=True)
    title = models.CharField(max_length=255, blank=True, null=True)  # from "Name"
    sale_location = models.CharField(max_length=255, blank=True, null=True)
    sold_hammer_price = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    link_to_sale = models.URLField(max_length=1000, blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.artist} — {self.title}"


class Artwork(models.Model):
    title = models.CharField(max_length=255)
    artist = models.CharField(max_length=255)
    year = models.CharField(max_length=10, blank=True, null=True)
    medium = models.CharField(max_length=255, blank=True, null=True)
    paper_type = models.CharField(max_length=255, blank=True, null=True)
    printer = models.CharField(max_length=255, blank=True, null=True)
    publisher = models.CharField(max_length=255, blank=True, null=True)
    edition_size = models.CharField(max_length=50, blank=True, null=True)
    dimensions_text = models.CharField(max_length=255, blank=True, null=True)
    sheet_size = models.CharField(max_length=255, blank=True, null=True)
    catalog_number = models.CharField(max_length=255, blank=True, null=True)
    description = models.TextField(blank=True)
    catalog_description = models.TextField(
        blank=True,
        default="",
        help_text="Public-facing description displayed under Literature on the artwork page.",
    )
    price = models.DecimalField(max_digits=10, decimal_places=2)
    is_available = models.BooleanField(default=True)
    display_order = models.PositiveIntegerField(default=0, db_index=True)

    class Meta:
        ordering = ["display_order", "id"]

    def __init__(self, *args, **kwargs):
        self._display_order_was_set = "display_order" in kwargs
        super().__init__(*args, **kwargs)

    @classmethod
    def next_display_order(cls):
        max_order = cls.objects.aggregate(max_order=Max("display_order"))["max_order"]
        return 0 if max_order is None else max_order + 1

    def save(self, *args, **kwargs):
        if (
            self._state.adding
            and not self._display_order_was_set
            and self.display_order == 0
            and type(self).objects.exists()
        ):
            self.display_order = type(self).next_display_order()
        super().save(*args, **kwargs)

    @property
    def formatted_price(self):
        if self.price is None:
            return ""
        return f"$ {int(self.price):,}"

    def __str__(self):
        return f"{self.artist} - {self.title}"


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


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    display_name = models.CharField(max_length=120, blank=True)
    bio = models.TextField(blank=True)
    favorite_artists = models.TextField(blank=True)
    avatar = models.ImageField(upload_to="profiles/", blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["user__username"]

    def __str__(self):
        return self.display_name or self.user.username

    @property
    def public_name(self):
        return self.display_name or self.user.username

    @property
    def favorite_artists_list(self):
        raw_value = (self.favorite_artists or "").replace("\n", ",")
        return [item.strip() for item in raw_value.split(",") if item.strip()]


class AuctionSearchJob(models.Model):
    class State(models.TextChoices):
        PENDING = "pending", "Pending"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        TIMED_OUT = "timed_out", "Timed out"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    correlation_id = models.UUIDField(default=uuid.uuid4, editable=False, db_index=True)
    requester_fingerprint = models.CharField(max_length=80, db_index=True)
    state = models.CharField(max_length=20, choices=State.choices, default=State.PENDING, db_index=True)
    openai_response_id = models.CharField(max_length=255)
    openai_status = models.CharField(max_length=32, blank=True)
    config = models.JSONField()
    openai_settings = models.JSONField()
    attempt_count = models.PositiveSmallIntegerField(default=1)
    retry_warning = models.TextField(blank=True)
    timeout_seconds = models.PositiveIntegerField()
    attempt_deadline_at = models.DateTimeField(db_index=True)
    last_polled_at = models.DateTimeField(blank=True, null=True)
    result = models.JSONField(blank=True, null=True)
    error = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Auction search {self.id} ({self.state})"
