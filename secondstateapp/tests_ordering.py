import json
import os
import tempfile
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .models import Artwork, ArtworkImage


class BrowserOrderingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = User.objects.create_user(username="order-staff", is_staff=True)
        cls.member = User.objects.create_user(username="order-member")
        cls.inactive = User.objects.create_user(username="order-inactive", is_staff=True, is_active=False)
        cls.artworks = [
            Artwork.objects.create(title=f"Work {index}", artist="Artist", price=100, display_order=index)
            for index in range(3)
        ]
        cls.images = ArtworkImage.objects.bulk_create([
            ArtworkImage(artwork=cls.artworks[0], image=f"artworks/photo-{index}.jpg")
            for index in range(3)
        ])
        cls.foreign_image = ArtworkImage.objects.bulk_create([
            ArtworkImage(artwork=cls.artworks[1], image="artworks/other-work.jpg", display_order=7),
        ])[0]

    def setUp(self):
        self.client.force_login(self.staff)
        self.artwork_ids = [artwork.pk for artwork in self.artworks]
        self.image_ids = [image.pk for image in self.images]
        self.gallery_url = reverse("gallery_reorder")
        self.photos_url = reverse("artwork_image_reorder", args=[self.artworks[0].pk])

    def post_order(self, url, order, original, client=None, **headers):
        return (client or self.client).post(
            url,
            json.dumps({"order": order, "original_order": original}),
            content_type="application/json",
            **headers,
        )

    def snapshot(self):
        return (
            list(Artwork.objects.order_by("pk").values_list("pk", "display_order")),
            list(ArtworkImage.objects.order_by("pk").values_list("pk", "display_order", "image")),
        )

    def test_gallery_reorder_persists_for_public_gallery_and_json(self):
        order = list(reversed(self.artwork_ids))
        response = self.post_order(self.gallery_url, order, self.artwork_ids)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"order": order})
        self.assertEqual(list(Artwork.objects.values_list("pk", flat=True)), order)
        self.client.logout()
        for route in ("gallery", "artwork_list"):
            response = self.client.get(reverse(route))
            self.assertEqual([artwork.pk for artwork in response.context["artworks"]], order)
        response = self.client.get(reverse("artwork_list"), {"format": "json"})
        self.assertEqual([artwork["id"] for artwork in response.json()["artworks"]], order)

    def test_photo_reorder_changes_primary_and_all_consumers_without_reprocessing_files(self):
        order = [self.image_ids[2], self.image_ids[0], self.image_ids[1]]
        before_names = dict(ArtworkImage.objects.values_list("pk", "image"))
        with patch.object(ArtworkImage, "save", side_effect=AssertionError("Must not process images")):
            response = self.post_order(self.photos_url, order, self.image_ids)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"order": order})
        self.assertEqual(list(self.artworks[0].images.values_list("pk", flat=True)), order)
        self.assertEqual(dict(ArtworkImage.objects.values_list("pk", "image")), before_names)
        self.foreign_image.refresh_from_db()
        self.assertEqual(self.foreign_image.display_order, 7)

        self.client.logout()
        for route in ("gallery", "artwork_list"):
            response = self.client.get(reverse(route))
            artwork = response.context["artworks"][0]
            self.assertEqual([image.pk for image in artwork.images.all()], order)
            self.assertEqual(artwork.images.first().pk, order[0])
        response = self.client.get(reverse("artwork_detail", args=[self.artworks[0].pk]))
        self.assertEqual(list(response.context["artwork"].images.values_list("pk", flat=True)), order)
        self.assertContains(response, f'id="mainImage" src="{self.images[2].image.url}"')

        with patch.dict(os.environ, {"CATALOG_API_KEY": "test-ordering-key"}):
            response = self.client.get(reverse("artwork_manage_list"), HTTP_X_API_KEY="test-ordering-key")
        self.assertEqual([image["id"] for image in response.json()["artworks"][0]["images"]], order)
        self.assertEqual(set(response.json()["artworks"][0]["images"][0]), {"id", "url"})

    def test_legacy_photo_order_uses_id_as_tie_breaker(self):
        self.assertEqual(list(self.artworks[0].images.values_list("pk", flat=True)), self.image_ids)

    def test_anonymous_nonstaff_and_inactive_staff_cannot_reorder(self):
        before = self.snapshot()
        for user in (None, self.member, self.inactive):
            client = Client()
            if user is not None:
                client.force_login(user)
            for url, ids in ((self.gallery_url, self.artwork_ids), (self.photos_url, self.image_ids)):
                with self.subTest(user=user, url=url):
                    response = self.post_order(url, list(reversed(ids)), ids, client=client)
                    self.assertEqual(response.status_code, 403)
                    self.assertIn("error", response.json())
        self.assertEqual(self.snapshot(), before)

    def test_api_key_does_not_authorize_browser_ordering(self):
        self.client.logout()
        with patch.dict(os.environ, {"CATALOG_API_KEY": "test-ordering-key"}):
            for url, ids in ((self.gallery_url, self.artwork_ids), (self.photos_url, self.image_ids)):
                response = self.post_order(url, ids, ids, HTTP_X_API_KEY="test-ordering-key")
                self.assertEqual(response.status_code, 403)

    def test_only_post_is_allowed(self):
        before = self.snapshot()
        for url in (self.gallery_url, self.photos_url):
            for method in ("get", "put", "delete"):
                response = getattr(self.client, method)(url)
                self.assertEqual(response.status_code, 405)
        self.assertEqual(self.snapshot(), before)

    def test_staff_session_requires_csrf_and_accepts_valid_token(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.staff)
        before = self.snapshot()
        for url, ids in ((self.gallery_url, self.artwork_ids), (self.photos_url, self.image_ids)):
            response = self.post_order(url, list(reversed(ids)), ids, client=client)
            self.assertEqual(response.status_code, 403)
        self.assertEqual(self.snapshot(), before)
        # The login form issues a real CSRF token without depending on editor markup.
        client.logout()
        client.get(reverse("login"))
        client.force_login(self.staff)
        token = client.cookies["csrftoken"].value
        for url, ids in ((self.gallery_url, self.artwork_ids), (self.photos_url, self.image_ids)):
            response = self.post_order(url, list(reversed(ids)), ids, client=client, HTTP_X_CSRFTOKEN=token)
            self.assertEqual(response.status_code, 200)

    def test_invalid_payloads_are_rejected_without_changes(self):
        before = self.snapshot()
        for url, ids in ((self.gallery_url, self.artwork_ids), (self.photos_url, self.image_ids)):
            payloads = [None, [], True, {}, {"order": ids}, {"original_order": ids}]
            for field in ("order", "original_order"):
                for bad_order in (None, "1,2,3", {}, [True, *ids[1:]], [1.5, *ids[1:]], [str(ids[0]), *ids[1:]], [ids[0], ids[0], ids[2]]):
                    payload = {"order": ids, "original_order": ids}
                    payload[field] = bad_order
                    payloads.append(payload)
            for payload in payloads:
                with self.subTest(url=url, payload=payload):
                    response = self.client.post(url, json.dumps(payload), content_type="application/json")
                    self.assertEqual(response.status_code, 400)
                    self.assertIn("error", response.json())
            for body in (b"{broken", b"\xff", b""):
                response = self.client.post(url, body, content_type="application/json")
                self.assertEqual(response.status_code, 400)
        self.assertEqual(self.snapshot(), before)

    def test_missing_unknown_and_foreign_ids_are_rejected(self):
        before = self.snapshot()
        for url, ids in ((self.gallery_url, self.artwork_ids), (self.photos_url, self.image_ids)):
            for order in (ids[:-1], ids + [999999], [999999, *ids[1:]], []):
                with self.subTest(url=url, order=order):
                    response = self.post_order(url, order, ids)
                    self.assertEqual(response.status_code, 400)
        response = self.post_order(self.photos_url, [self.foreign_image.pk, *self.image_ids[1:]], self.image_ids)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.snapshot(), before)

    def test_stale_original_order_cannot_overwrite_newer_save(self):
        for url, ids in ((self.gallery_url, self.artwork_ids), (self.photos_url, self.image_ids)):
            order = list(reversed(ids))
            response = self.post_order(url, order, ids)
            self.assertEqual(response.status_code, 200)
            before = self.snapshot()
            response = self.post_order(url, [ids[1], ids[0], ids[2]], ids)
            self.assertEqual(response.status_code, 409)
            self.assertIn("Reload", response.json()["error"])
            self.assertEqual(self.snapshot(), before)

    def test_collection_membership_changes_also_report_stale_edit(self):
        Artwork.objects.create(title="New work", artist="Artist", price=100)
        ArtworkImage.objects.bulk_create([ArtworkImage(artwork=self.artworks[0], image="artworks/new.jpg")])
        before = self.snapshot()
        for url, ids in ((self.gallery_url, self.artwork_ids), (self.photos_url, self.image_ids)):
            response = self.post_order(url, list(reversed(ids)), ids)
            self.assertEqual(response.status_code, 409)
        self.assertEqual(self.snapshot(), before)

    def test_missing_artwork_returns_json_not_found(self):
        response = self.post_order(reverse("artwork_image_reorder", args=[999999]), [], [])
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"error": "Artwork not found."})

    def test_empty_photo_collection_is_valid(self):
        response = self.post_order(reverse("artwork_image_reorder", args=[self.artworks[2].pk]), [], [])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"order": []})

    def test_new_uploads_append_without_rewriting_existing_images(self):
        order = list(reversed(self.image_ids))
        self.assertEqual(self.post_order(self.photos_url, order, self.image_ids).status_code, 200)
        # Leave a deliberate gap: appending respects the maximum, not the count.
        ArtworkImage.objects.filter(pk=order[-1]).update(display_order=10)
        before_images = list(self.artworks[0].images.values_list("pk", "display_order", "image"))
        buffer = BytesIO()
        Image.new("RGB", (4, 4), "white").save(buffer, format="PNG")
        uploads = [SimpleUploadedFile(f"upload-{i}.png", buffer.getvalue(), content_type="image/png") for i in range(2)]
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            response = self.client.post(
                reverse("artwork_edit", args=[self.artworks[0].pk]),
                {"title": "Work 0", "artist": "Artist", "price": "100", "is_available": "on", "images": uploads},
            )
            self.assertEqual(response.status_code, 302)
            images = list(self.artworks[0].images.all())
            self.assertEqual([image.pk for image in images[:3]], order)
            self.assertEqual([image.display_order for image in images[3:]], [11, 12])
            self.assertTrue(all(image.image.storage.exists(image.image.name) for image in images[3:]))
        self.assertEqual(list(self.artworks[0].images.filter(pk__in=order).values_list("pk", "display_order", "image")), before_images)
