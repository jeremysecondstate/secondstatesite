"""Staff-reviewed shipping records; no external sending or payment capability."""
import hashlib
import json
import uuid

from django.conf import settings
from django.db import models


class CoordinatePlan(models.Model):
    case = models.OneToOneField("CoordinateCase", primary_key=True, on_delete=models.PROTECT, related_name="shipping_plan")
    stage = models.CharField(max_length=20, default="gathering", choices=[
        ("gathering", "Gathering details"), ("quotes", "Comparing quotes"), ("ready", "Ready for pickup"),
        ("pickup", "Pickup arranged"), ("transit", "In transit"), ("received", "Received"), ("on_hold", "On hold"),
    ])
    destination = models.CharField(max_length=20, default="undecided", choices=[
        ("undecided", "Choose a destination"), ("duarte", "Duarte"),
        ("mar_vista", "Mar Vista"), ("midtown_east", "Midtown East"),
    ])
    handling = models.CharField(max_length=2000, blank=True)
    pickup_deadline = models.DateTimeField(null=True, blank=True)
    deadline_reminded_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    tracking_number = models.CharField(max_length=200, blank=True)
    tracking_url = models.URLField(max_length=2048, blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class CoordinateQuote(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey("CoordinateCase", on_delete=models.PROTECT, related_name="shipping_quotes")
    provider_name = models.CharField(max_length=200)
    provider_email = models.EmailField()
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default="USD")
    latest_amount = models.DecimalField(max_digits=10, decimal_places=2)
    accepted = models.BooleanField(default=False)
    accepted_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    accepted_destination = models.CharField(max_length=20, blank=True)
    accepted_handling = models.CharField(max_length=2000, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    increase_reviewed_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    increase_review_note = models.CharField(max_length=2000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.UniqueConstraint(fields=["case"], condition=models.Q(accepted=True), name="coordinate_one_provider"),
            models.CheckConstraint(condition=models.Q(amount__gte=0, latest_amount__gte=0), name="coordinate_quote_positive"),
        ]


class CoordinateDraft(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey("CoordinateCase", on_delete=models.PROTECT, related_name="email_drafts")
    job = models.ForeignKey("CoordinateJob", null=True, blank=True, on_delete=models.PROTECT, related_name="email_drafts")
    quote = models.ForeignKey(CoordinateQuote, null=True, blank=True, on_delete=models.PROTECT, related_name="email_drafts")
    recipient = models.EmailField()
    subject = models.CharField(max_length=200)
    body = models.TextField()
    purpose = models.CharField(max_length=300, blank=True)
    status = models.CharField(max_length=12, default="draft", choices=[("draft", "Needs review"), ("reviewed", "Reviewed")])
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at", "id"]


class CoordinateResearch(models.Model):
    case = models.ForeignKey("CoordinateCase", on_delete=models.PROTECT, related_name="research")
    job = models.ForeignKey("CoordinateJob", on_delete=models.PROTECT, related_name="research")
    source_url = models.URLField(max_length=2048)
    source_kind = models.CharField(max_length=24, default="public", choices=[
        ("public", "Public source"), ("browser", "Browser source"),
        ("public_fetch", "Public fetch"), ("public_browser", "Public browser"),
        ("authenticated_browser", "Authenticated browser"), ("search_only", "Search lead (unverified)"),
    ])
    public_error = models.CharField(max_length=200, blank=True)
    final_url = models.URLField(max_length=2048, blank=True)
    title = models.CharField(max_length=300, blank=True)
    text = models.TextField(blank=True)
    fetched_at = models.DateTimeField()
    error = models.CharField(max_length=200, blank=True)
    discovery_method = models.CharField(max_length=12, blank=True)
    discovery_query = models.CharField(max_length=500, blank=True)
    discovery_url = models.URLField(max_length=2048, blank=True)
    match_reason = models.CharField(max_length=1200, blank=True)
    identity_match = models.JSONField(default=dict, blank=True)
    attempts = models.JSONField(default=list, blank=True)
    observation_key = models.CharField(max_length=64, editable=False)

    def save(self, *args, **kwargs):
        # A fixed-size key avoids a PostgreSQL btree index over two 2,048-char URLs.
        self.observation_key = hashlib.sha256(json.dumps(
            [self.source_url, self.final_url, self.source_kind], ensure_ascii=True,
        ).encode()).hexdigest()
        if kwargs.get("update_fields") is not None:
            kwargs["update_fields"] = {*kwargs["update_fields"], "observation_key"}
        return super().save(*args, **kwargs)

    class Meta:
        ordering = ["-fetched_at", "id"]
        constraints = [models.UniqueConstraint(fields=["job", "observation_key"], name="coordinate_observation_per_job")]
