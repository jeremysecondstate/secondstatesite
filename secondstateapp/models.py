from django.contrib.auth.models import User
from django.db import models
from django.db.models import Max, Q
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


class AuctionWatchArtist(models.Model):
    """A persistent artist identity imported through the Artist Watchlist."""

    name = models.CharField(max_length=255)
    normalized_name = models.CharField(max_length=255, unique=True)
    artprice_url = models.URLField(max_length=2000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "id"]

    def __str__(self):
        return self.name


class AuctionWatchLot(models.Model):
    """A normalized auction lot synced from the desktop Artist Watchlist."""

    source = models.CharField(max_length=80)
    source_lot_id = models.CharField(max_length=255)
    artist = models.CharField(max_length=255, blank=True)
    artist_watchlist_name = models.CharField(max_length=255, blank=True)
    watchlist_artist = models.ForeignKey(
        AuctionWatchArtist,
        related_name="lots",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
    )
    title = models.CharField(max_length=500, blank=True)
    medium = models.CharField(max_length=500, blank=True)
    auction_house = models.CharField(max_length=255, blank=True)
    sale_title = models.CharField(max_length=500, blank=True)
    lot_number = models.CharField(max_length=80, blank=True)
    location = models.CharField(max_length=255, blank=True)
    event_at = models.DateTimeField(blank=True, null=True, db_index=True)
    is_all_day = models.BooleanField(default=False)
    estimate_low = models.DecimalField(max_digits=15, decimal_places=2, blank=True, null=True)
    estimate_high = models.DecimalField(max_digits=15, decimal_places=2, blank=True, null=True)
    currency = models.CharField(max_length=8, blank=True)
    current_bid = models.DecimalField(max_digits=15, decimal_places=2, blank=True, null=True)
    bid_count = models.PositiveIntegerField(blank=True, null=True)
    lot_url = models.URLField(max_length=2000, blank=True)
    sale_url = models.URLField(max_length=2000, blank=True)
    artprice_url = models.URLField(max_length=2000, blank=True)
    source_status = models.CharField(max_length=24, blank=True, default="unchanged")
    active = models.BooleanField(default=True, db_index=True)
    source_first_seen_at = models.DateTimeField(blank=True, null=True)
    source_last_seen_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["event_at", "auction_house", "artist", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=("source", "source_lot_id"),
                name="unique_auction_watch_source_lot",
            )
        ]

    def __str__(self):
        label = self.artist_watchlist_name or self.artist or "Unknown artist"
        return f"{label} - {self.title or self.source_lot_id}"


class AuctionMaxBidAnalysis(models.Model):
    """Normalized Artprice comparables and maximum-bid calculations for one lot."""

    class ResaleMethod(models.TextChoices):
        MEDIAN = "median", "Median"
        MEAN = "mean", "Mean"
        RECENT = "recent", "Recent records"
        MAX = "max", "Maximum"
        MIN = "min", "Minimum"
        MANUAL = "manual", "Manual"

    lot = models.OneToOneField(
        AuctionWatchLot,
        on_delete=models.CASCADE,
        related_name="max_bid_analysis",
    )
    source_filename = models.CharField(max_length=255)
    currency = models.CharField(max_length=8, default="USD")
    resale_method = models.CharField(max_length=12, choices=ResaleMethod.choices)
    manual_resale_value = models.DecimalField(max_digits=15, decimal_places=2, blank=True, null=True)
    recent_count = models.PositiveIntegerField(default=3)
    expected_resale_hammer = models.DecimalField(max_digits=15, decimal_places=2)
    net_resale_proceeds = models.DecimalField(max_digits=15, decimal_places=2)
    inbound_shipping = models.DecimalField(max_digits=15, decimal_places=2)
    target_profit = models.DecimalField(max_digits=15, decimal_places=2)
    seller_commission_pct = models.DecimalField(max_digits=7, decimal_places=2)
    outbound_shipping = models.DecimalField(max_digits=15, decimal_places=2)
    other_resale_costs = models.DecimalField(max_digits=15, decimal_places=2)
    premium_min = models.PositiveSmallIntegerField()
    premium_max = models.PositiveSmallIntegerField()
    sold_records_count = models.PositiveIntegerField()
    comparables = models.JSONField(default=list, blank=True)
    bid_rows = models.JSONField(default=list, blank=True)
    created_by = models.ForeignKey(
        User,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]
        verbose_name = "auction max-bid analysis"
        verbose_name_plural = "auction max-bid analyses"

    def __str__(self):
        return f"{self.lot} ({self.get_resale_method_display()})"


class AuctionReminderDelivery(models.Model):
    """Idempotency and delivery audit record for one daily reminder digest."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    target_date = models.DateField(db_index=True)
    days_before = models.PositiveSmallIntegerField()
    recipient_hash = models.CharField(max_length=64)
    recipient_display = models.CharField(max_length=32, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    twilio_message_sid = models.CharField(max_length=64, blank=True)
    twilio_status = models.CharField(max_length=32, blank=True)
    covered_sale_hashes = models.JSONField(default=list, blank=True)
    error = models.TextField(blank=True)
    attempted_at = models.DateTimeField(blank=True, null=True)
    sent_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-target_date", "days_before", "recipient_display"]
        constraints = [
            models.UniqueConstraint(
                fields=("target_date", "days_before", "recipient_hash"),
                name="unique_auction_reminder_digest",
            )
        ]

    def __str__(self):
        return f"{self.target_date} ({self.days_before}d) to {self.recipient_display or 'recipient'}"


class AuctionReminderControl(models.Model):
    """Singleton operational switch and audit summary for auction reminder delivery."""

    singleton_key = models.PositiveSmallIntegerField(default=1, unique=True, editable=False)
    active = models.BooleanField(default=False)
    started_at = models.DateTimeField(blank=True, null=True)
    paused_at = models.DateTimeField(blank=True, null=True)
    updated_by = models.ForeignKey(
        User,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    last_run_at = models.DateTimeField(blank=True, null=True)
    last_run_source = models.CharField(max_length=24, blank=True)
    last_run_status = models.CharField(max_length=24, blank=True)
    last_run_summary = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "auction reminder control"
        verbose_name_plural = "auction reminder control"

    @classmethod
    def load(cls) -> "AuctionReminderControl":
        control, _created = cls.objects.get_or_create(singleton_key=1)
        return control

    def __str__(self):
        return "Auction reminder texts: active" if self.active else "Auction reminder texts: paused"


class AuctionEmailBatch(models.Model):
    """One shared manual auction-lot email tray and its delivery history."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SENDING = "sending", "Sending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    requested_by = models.ForeignKey(
        User,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    recipient_keys = models.JSONField(default=list, blank=True)
    recipient_snapshot = models.JSONField(default=list, blank=True)
    subject_snapshot = models.TextField(blank=True)
    html_body_snapshot = models.TextField(blank=True)
    text_body_snapshot = models.TextField(blank=True)
    gmail_message_id = models.CharField(max_length=255, blank=True)
    attempt_count = models.PositiveIntegerField(default=0)
    attempted_at = models.DateTimeField(blank=True, null=True)
    sent_at = models.DateTimeField(blank=True, null=True)
    failure_summary = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=("is_active",),
                condition=Q(is_active=True),
                name="unique_active_auction_email_batch",
            ),
            models.CheckConstraint(
                condition=(
                    Q(is_active=True, status__in=("draft", "sending", "failed"))
                    | Q(is_active=False, status="sent")
                ),
                name="auction_email_batch_active_status",
            ),
        ]

    def __str__(self):
        return f"Auction email batch {self.pk or 'new'} ({self.status})"


class AuctionEmailBatchItem(models.Model):
    """A selected lot plus the staff attribution and send-time lot snapshot."""

    batch = models.ForeignKey(AuctionEmailBatch, related_name="items", on_delete=models.CASCADE)
    lot = models.ForeignKey(AuctionWatchLot, related_name="email_batch_items", on_delete=models.PROTECT)
    selected_by = models.ForeignKey(
        User,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    selected_at = models.DateTimeField(auto_now_add=True)
    lot_snapshot = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["selected_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=("batch", "lot"),
                name="unique_auction_email_batch_lot",
            )
        ]

    def __str__(self):
        return f"{self.lot} in batch {self.batch_id}"
