"""Private case documents; originals never enter the site's public media tree."""

import uuid

from django.db import models


class CoordinateDocument(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey("CoordinateCase", on_delete=models.PROTECT, related_name="intake_documents")
    message = models.OneToOneField("CoordinateMessage", on_delete=models.PROTECT, related_name="intake_document")
    title = models.CharField(max_length=200)
    kind = models.CharField(max_length=8, choices=[("text", "Pasted text"), ("pdf", "PDF")])
    text = models.TextField(blank=True)
    original_pdf = models.BinaryField(blank=True, default=bytes)
    filename = models.CharField(max_length=200, blank=True)
    byte_size = models.PositiveIntegerField()
    content_digest = models.CharField(max_length=64)
    extraction_status = models.CharField(max_length=12, choices=[
        ("ready", "Text available"), ("truncated", "Partial text available"),
        ("no_text", "No readable text"),
    ])
    extraction_error = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-message_id"]
