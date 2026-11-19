from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.test import TestCase
from PIL import Image

from .artprice_image_store import saved_artprice_image_url, store_saved_artprice_image
from .artprice_max_bid import is_saved_artprice_image_url


class PrivateArtpriceImageTests(TestCase):
    def test_repeated_uploads_share_a_file_served_only_to_staff(self):
        jpeg = BytesIO()
        Image.new("RGB", (24, 24), "blue").save(jpeg, "JPEG")
        content = jpeg.getvalue()
        with TemporaryDirectory() as root, self.settings(MEDIA_ROOT=Path(root) / "media"):
            url = saved_artprice_image_url(content)
            self.assertTrue(is_saved_artprice_image_url(url))
            self.assertEqual(list(Path(root).iterdir()), [])
            self.assertEqual(store_saved_artprice_image(content), url)
            self.assertEqual(store_saved_artprice_image(content), url)
            stored, = Path(root).rglob("*.jpg")
            self.assertFalse(stored.is_relative_to(Path(root) / "media"))
            self.assertEqual(stored.read_bytes(), content)
            self.assertEqual(self.client.get(url).status_code, 302)
            ordinary = get_user_model().objects.create_user("reader")
            self.client.force_login(ordinary)
            self.assertEqual(self.client.get(url).status_code, 302)
            staff = get_user_model().objects.create_user("staff", is_staff=True)
            self.client.force_login(staff)
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Content-Type"], "image/jpeg")
            self.assertIn("private", response["Cache-Control"])
            self.assertEqual(b"".join(response.streaming_content), content)
            response.close()
            head = self.client.head(url)
            self.assertEqual(head.status_code, 200)
            head.close()
            self.assertEqual(self.client.post(url).status_code, 405)
            self.assertEqual(self.client.get(saved_artprice_image_url(b"missing")).status_code, 404)
            self.assertEqual(self.client.get(url.replace(stored.stem, "not-a-digest")).status_code, 404)
