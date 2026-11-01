"""Staff selections and immutable, manually started LiveArt research passes."""
import uuid

from django.db import models
from django.utils import timezone


class ResearchQueueState(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    revision = models.PositiveIntegerField(default=0)


class ResearchQueueItem(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RESEARCHING = "researching", "Researching"
        DONE = "done", "Done"
        NEEDS_ATTENTION = "needs_attention", "Needs attention"

    lot = models.OneToOneField("AuctionWatchLot", on_delete=models.PROTECT, related_name="research_queue_item")
    selected = models.BooleanField(default=True, db_index=True)
    position = models.PositiveIntegerField(default=0)
    note = models.TextField(blank=True, default="")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)
    disposition = models.CharField(max_length=32, blank=True, default="")
    generation = models.PositiveIntegerField(default=1)
    latest_result = models.JSONField(default=dict)
    requeue_history = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["position", "pk"]

    @property
    def outcome_label(self):
        return {"researched": "Research saved", "triaged": "Triaged", "skipped": "Skipped", "valuation_unavailable": "Valuation unavailable"}.get(self.disposition, "Needs attention" if self.status == "needs_attention" else "")

    @property
    def outcome_summary(self):
        return self.latest_result.get("reason", "")


class ResearchQueueRun(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request_id = models.UUIDField(unique=True)
    owner_token = models.UUIDField()
    thread_id = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=16, default="running", choices=[("running", "Running"), ("completed", "Completed"), ("blocked", "Blocked")])
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    recovery_log = models.JSONField(default=list)
    completion_audit = models.JSONField(default=dict)
    block_reason = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["status"], condition=models.Q(status="running"), name="research_one_running_pass")]


class ResearchQueueRunItem(models.Model):
    run = models.ForeignKey(ResearchQueueRun, on_delete=models.PROTECT, related_name="items")
    queue_item = models.ForeignKey(ResearchQueueItem, on_delete=models.PROTECT, related_name="run_items")
    lot = models.ForeignKey("AuctionWatchLot", on_delete=models.PROTECT, related_name="research_run_items")
    queue_generation = models.PositiveIntegerField()
    position = models.PositiveIntegerField()
    lot_snapshot = models.JSONField(default=dict)
    note_snapshot = models.TextField(blank=True)
    status = models.CharField(max_length=20, default="queued")
    disposition = models.CharField(max_length=32, blank=True)
    reason = models.TextField(blank=True)
    claimed_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    outcome = models.JSONField(default=dict)
    saved_revisions = models.JSONField(default=dict)

    class Meta:
        ordering = ["position", "pk"]
        constraints = [models.UniqueConstraint(fields=["run", "lot"], name="research_run_lot_unique")]


class ResearchQueueOperation(models.Model):
    """An intent remains unresolved until its exact receipt is reconciled."""
    id = models.UUIDField(primary_key=True, editable=False)
    item = models.ForeignKey(ResearchQueueRunItem, on_delete=models.PROTECT, related_name="operations")
    kind = models.CharField(max_length=40)
    details = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    settled_at = models.DateTimeField(null=True, blank=True)
    receipt = models.JSONField(default=dict)
    units_spent = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
