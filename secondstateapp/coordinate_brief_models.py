"""Immutable source-supported briefings; suggestions never change the saved plan."""

from django.db import models


class CoordinateBrief(models.Model):
    case = models.ForeignKey("CoordinateCase", on_delete=models.PROTECT, related_name="briefs")
    job = models.OneToOneField("CoordinateJob", on_delete=models.PROTECT, related_name="brief")
    payload = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
