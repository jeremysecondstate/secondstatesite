"""Durable inventory conversations and the local workbook worker queue."""
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class InventoryCase(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=160)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(default=timezone.now)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    deleted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    purged_at = models.DateTimeField(null=True, blank=True, db_index=True)
    purged_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-updated_at", "id"]
        constraints = [models.CheckConstraint(condition=models.Q(purged_at__isnull=True) | models.Q(deleted_at__isnull=False), name="inventory_case_purged_in_trash")]


class InventoryMessage(models.Model):
    case = models.ForeignKey(InventoryCase, on_delete=models.PROTECT, related_name="messages")
    role = models.CharField(max_length=12, choices=[("staff", "Staff"), ("assistant", "Codex")])
    body = models.TextField()
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    client_message_id = models.UUIDField(null=True, blank=True, unique=True)
    in_reply_to = models.OneToOneField("self", null=True, blank=True, on_delete=models.PROTECT, related_name="worker_reply")
    created_at = models.DateTimeField(auto_now_add=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    deleted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    purged_at = models.DateTimeField(null=True, blank=True, db_index=True)
    purged_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["id"]
        constraints = [models.CheckConstraint(condition=models.Q(purged_at__isnull=True) | models.Q(deleted_at__isnull=False), name="inventory_message_purged_in_trash")]


class InventoryJob(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message = models.OneToOneField(InventoryMessage, on_delete=models.PROTECT, related_name="job")
    status = models.CharField(max_length=12, default="queued", choices=[
        ("queued", "Waiting"), ("processing", "Working"), ("completed", "Complete"),
        ("retry", "Retrying"), ("failed", "Needs attention"), ("cancelled", "Cancelled"),
    ])
    attempts = models.PositiveIntegerField(default=0)
    claim_token = models.UUIDField(null=True, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    available_at = models.DateTimeField(default=timezone.now)
    worker_id = models.CharField(max_length=80, blank=True)
    last_error = models.CharField(max_length=500, blank=True)
    result = models.JSONField(default=dict)
    purchase_lot_ids = models.JSONField(default=list)
    completion_digest = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["status", "available_at"], name="inventory_pending_idx")]


class InventoryWorkerState(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    last_successful_check = models.DateTimeField(null=True, blank=True)


class InventoryClaimRequest(models.Model):
    """A poll receipt survives a lost HTTP response, including idle polls."""
    id = models.UUIDField(primary_key=True, editable=False)
    response = models.JSONField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
