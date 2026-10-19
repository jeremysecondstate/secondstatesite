"""Explicit case authorization and once-per-provider initial quote inquiries."""
from django.conf import settings
from django.db import models


class CoordinateOutreachPolicy(models.Model):
    case = models.OneToOneField("CoordinateCase", on_delete=models.PROTECT, related_name="outreach_policy")
    mode = models.CharField(max_length=12, default="off", choices=[("off", "Reviewed drafts only"), ("test", "Quote test to Jeremy"), ("live", "Initial provider inquiries")])
    destination = models.CharField(max_length=20)
    destination_address = models.TextField(max_length=600)
    authorized_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    originating_message = models.ForeignKey("CoordinateMessage", on_delete=models.PROTECT)
    authorized_at = models.DateTimeField(auto_now=True)


class CoordinateQuoteInquiry(models.Model):
    case = models.ForeignKey("CoordinateCase", on_delete=models.PROTECT, related_name="quote_inquiries")
    mode = models.CharField(max_length=12)
    provider_email = models.EmailField()
    provider_name = models.CharField(max_length=200)
    draft = models.OneToOneField("CoordinateDraft", on_delete=models.PROTECT, related_name="quote_inquiry")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["case", "mode", "provider_email"], name="coordinate_initial_provider_once")]
