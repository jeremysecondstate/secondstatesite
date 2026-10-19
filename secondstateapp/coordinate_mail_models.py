"""Explicitly approved email delivery and case-scoped correspondence records."""
import uuid

from django.conf import settings
from django.db import models


class CoordinateMailThread(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey("CoordinateCase", on_delete=models.PROTECT, related_name="mail_threads")
    originating_message = models.ForeignKey("CoordinateMessage", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    provider_email = models.EmailField()
    sender_email = models.EmailField(default="jeremy@secondstate.art")
    subject = models.CharField(max_length=200)
    gmail_thread_id = models.CharField(max_length=255, unique=True, null=True, blank=True)
    sync_checked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "id"]


class CoordinateMailDelivery(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    draft = models.OneToOneField("CoordinateDraft", on_delete=models.PROTECT, related_name="mail_delivery")
    thread = models.ForeignKey(CoordinateMailThread, null=True, blank=True, on_delete=models.PROTECT, related_name="deliveries")
    request_id = models.UUIDField(unique=True)
    status = models.CharField(max_length=12, choices=[("sending", "Sending"), ("sent", "Sent"), ("unknown", "Outcome unknown")])
    sender_email = models.EmailField()
    recipient = models.EmailField()
    subject = models.CharField(max_length=200)
    body = models.TextField()
    reviewed_digest = models.CharField(max_length=64)
    approval_snapshot = models.JSONField(default=dict)
    rfc_message_id = models.CharField(max_length=255, unique=True)
    in_reply_to = models.CharField(max_length=998, blank=True)
    references = models.TextField(blank=True)
    gmail_message_id = models.CharField(max_length=255, blank=True)
    gmail_thread_id = models.CharField(max_length=255, blank=True)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    requested_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    error_code = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["-requested_at", "id"]


class CoordinateMailMessage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    thread = models.ForeignKey(CoordinateMailThread, on_delete=models.PROTECT, related_name="mail_messages")
    message = models.OneToOneField("CoordinateMessage", on_delete=models.PROTECT, related_name="mail_message")
    direction = models.CharField(max_length=8, choices=[("inbound", "Received"), ("outbound", "Sent")])
    gmail_message_id = models.CharField(max_length=255, unique=True)
    rfc_message_id = models.CharField(max_length=998, blank=True)
    in_reply_to = models.CharField(max_length=998, blank=True)
    references = models.TextField(blank=True)
    from_email = models.EmailField()
    to_emails = models.JSONField(default=list)
    cc_emails = models.JSONField(default=list, blank=True)
    subject = models.CharField(max_length=200)
    body_text = models.TextField()
    body_truncated = models.BooleanField(default=False)
    attachments = models.JSONField(default=list, blank=True)
    received_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["received_at", "id"]
