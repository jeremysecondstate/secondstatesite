import json
import os
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from .models import Artwork


@patch.dict(os.environ, {"CATALOG_API_KEY": "test-key"}, clear=False)
class ArtworkOrderingTests(TestCase):
    def create_artwork(self, title, display_order):
        return Artwork.objects.create(
            title=title,
            artist="Test Artist",
            price=Decimal("100.00"),
            display_order=display_order,
        )

    def test_default_queryset_orders_by_display_order_then_id(self):
        third = self.create_artwork("Third", 2)
        first = self.create_artwork("First", 0)
        second = self.create_artwork("Second", 1)

        self.assertEqual(list(Artwork.objects.values_list("id", flat=True)), [first.id, second.id, third.id])

    def test_manage_json_includes_display_order_and_reorder_updates_order(self):
        first = self.create_artwork("First", 0)
        second = self.create_artwork("Second", 1)
        third = self.create_artwork("Third", 2)

        response = self.client.get(reverse("artwork_manage_list"), HTTP_X_API_KEY="test-key")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.json()["artworks"]], [first.id, second.id, third.id])
        self.assertEqual([item["display_order"] for item in response.json()["artworks"]], [0, 1, 2])

        response = self.client.get(reverse("artwork_list"), {"format": "json"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.json()["artworks"]], [first.id, second.id, third.id])
        self.assertEqual([item["display_order"] for item in response.json()["artworks"]], [0, 1, 2])

        response = self.client.post(
            reverse("reorder_artworks"),
            data=json.dumps({"order": [third.id, first.id, second.id]}),
            content_type="application/json",
            HTTP_X_API_KEY="test-key",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual([item["id"] for item in payload["artworks"]], [third.id, first.id, second.id])
        self.assertEqual([item["display_order"] for item in payload["artworks"]], [0, 1, 2])
        self.assertEqual(list(Artwork.objects.values_list("id", flat=True)), [third.id, first.id, second.id])

    def test_reorder_rejects_missing_and_unknown_ids(self):
        first = self.create_artwork("First", 0)
        self.create_artwork("Second", 1)

        response = self.client.post(
            reverse("reorder_artworks"),
            data=json.dumps({"order": [first.id, 999999]}),
            content_type="application/json",
            HTTP_X_API_KEY="test-key",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("unknown ids", response.json()["error"])
        self.assertIn("missing ids", response.json()["error"])

    def test_upload_appends_artwork_to_end(self):
        first = self.create_artwork("First", 0)
        second = self.create_artwork("Second", 1)

        response = self.client.post(
            reverse("upload_artwork"),
            data={
                "title": "Uploaded",
                "artist": "Upload Artist",
                "price": "250",
            },
            HTTP_X_API_KEY="test-key",
        )

        self.assertEqual(response.status_code, 201)
        uploaded = Artwork.objects.get(id=response.json()["id"])
        self.assertEqual(uploaded.display_order, 2)
        self.assertEqual(list(Artwork.objects.values_list("id", flat=True)), [first.id, second.id, uploaded.id])
