import json
import os
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from . import catalog_api_views, views
from .models import Artwork


@patch.dict(os.environ, {"CATALOG_API_KEY": "test-key"}, clear=False)
class ArtworkOrderingTests(TestCase):
    def create_artwork(self, title, display_order, is_available=True):
        return Artwork.objects.create(
            title=title,
            artist="Test Artist",
            medium="Screenprint",
            price=Decimal("100.00"),
            display_order=display_order,
            is_available=is_available,
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

    def test_gallery_template_keeps_saved_order_with_mosaic_classes(self):
        third = self.create_artwork("Third", 2)
        first = self.create_artwork("First", 0)
        second = self.create_artwork("Second", 1)
        fifth = self.create_artwork("Fifth", 4, is_available=False)
        fourth = self.create_artwork("Fourth", 3)

        response = self.client.get(reverse("gallery"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "auction-mosaic-grid")
        self.assertContains(response, "auction-card--feature")
        self.assertContains(response, "auction-card--wide")
        self.assertContains(response, "4 available works")
        html = response.content.decode()
        rendered_positions = [
            html.index(f'data-artwork-id="{artwork.id}"')
            for artwork in [first, second, third, fourth, fifth]
        ]
        self.assertEqual(rendered_positions, sorted(rendered_positions))

    def test_gallery_uses_default_artwork_image_when_image_is_missing(self):
        self.create_artwork("Missing Image", 0)

        response = self.client.get(reverse("gallery"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "/static/secondstateapp/etching_press.jpg")

    def test_gallery_edit_link_remains_staff_only(self):
        artwork = self.create_artwork("Staff Editable", 0)
        edit_url = reverse("artwork_edit", args=[artwork.id])

        response = self.client.get(reverse("gallery"))
        self.assertNotContains(response, edit_url)

        staff_user = User.objects.create_user(username="staff", password="password", is_staff=True)
        self.client.force_login(staff_user)
        response = self.client.get(reverse("gallery"))

        self.assertContains(response, edit_url)


@patch.dict(os.environ, {"OPENAI_API_KEY": "not-used-in-tests"}, clear=False)
class DescriptionRequestCompatibilityTests(TestCase):
    def response(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = json.dumps({"output_text": "Description."}).encode("utf-8")
        return response

    def artwork(self):
        return Artwork(
            artist="Test Artist",
            title="Test Print",
            medium="Screenprint",
            price=Decimal("100.00"),
        )

    @patch.dict(os.environ, {"OPENAI_DESCRIPTION_MODEL": "gpt-5.6"}, clear=False)
    def test_description_requests_use_gpt_5_6_compatible_parameters(self):
        with patch("secondstateapp.catalog_api_views.urllib.request.urlopen", return_value=self.response()) as mock_api:
            catalog_api_views._generate_description(self.artwork(), use_web=False)
        api_body = json.loads(mock_api.call_args.args[0].data.decode("utf-8"))

        with patch("secondstateapp.views.urllib.request.urlopen", return_value=self.response()) as mock_view:
            views._generate_catalog_description(self.artwork(), use_web=False)
        view_body = json.loads(mock_view.call_args.args[0].data.decode("utf-8"))

        self.assertEqual(api_body["max_output_tokens"], 450)
        self.assertEqual(view_body["max_output_tokens"], 450)
        self.assertEqual(api_body["model"], "gpt-5.6")
        self.assertEqual(view_body["model"], "gpt-5.6")
        self.assertEqual(api_body["reasoning"], {"effort": "none"})
        self.assertEqual(view_body["reasoning"], {"effort": "none"})
        self.assertNotIn("temperature", api_body)
        self.assertNotIn("temperature", view_body)

    @patch.dict(os.environ, {"OPENAI_DESCRIPTION_MODEL": "gpt-4.1"}, clear=False)
    def test_description_requests_keep_older_model_override_compatible(self):
        with patch("secondstateapp.catalog_api_views.urllib.request.urlopen", return_value=self.response()) as mock_api:
            catalog_api_views._generate_description(self.artwork(), use_web=False)
        api_body = json.loads(mock_api.call_args.args[0].data.decode("utf-8"))

        with patch("secondstateapp.views.urllib.request.urlopen", return_value=self.response()) as mock_view:
            views._generate_catalog_description(self.artwork(), use_web=False)
        view_body = json.loads(mock_view.call_args.args[0].data.decode("utf-8"))

        self.assertEqual(api_body["model"], "gpt-4.1")
        self.assertEqual(view_body["model"], "gpt-4.1")
        self.assertNotIn("reasoning", api_body)
        self.assertNotIn("reasoning", view_body)
        self.assertNotIn("temperature", api_body)
        self.assertNotIn("temperature", view_body)
