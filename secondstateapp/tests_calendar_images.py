from __future__ import annotations

import base64
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings
from PIL import Image

from .calendar_images import MAX_SAVED_IMAGE_BYTES, prepare_saved_calendar_image
from .calendar_views import _calendar_image_url
from .models import AuctionEmailBatch, AuctionEmailBatchItem, AuctionWatchArtist, AuctionWatchLot


def encoded_image(*, image_format="JPEG", size=(40, 60), color="gold", exif=None):
    output = BytesIO()
    options = {"exif": exif} if exif is not None else {}
    Image.new("RGB", size, color).save(output, format=image_format, **options)
    return base64.b64encode(output.getvalue()).decode("ascii")


class SavedCalendarImageValidationTests(SimpleTestCase):
    def test_accepts_supported_formats_and_removes_metadata_and_resizes(self):
        exif = Image.Exif()
        exif[270] = "Private source metadata"
        for image_format in ("JPEG", "PNG", "WEBP"):
            with self.subTest(image_format=image_format):
                content = prepare_saved_calendar_image(encoded_image(
                    image_format=image_format, size=(1800, 1000), exif=exif,
                ))
                with Image.open(BytesIO(content)) as image:
                    self.assertEqual(image.format, "JPEG")
                    self.assertEqual(image.size, (1600, 889))
                    self.assertFalse(image.getexif())
                    self.assertNotIn("Private source metadata", str(image.info))

    def test_rejects_invalid_formats_bytes_and_dimensions(self):
        invalid_images = (
            None, "", 1, "not base64!", "../../secret.jpg",
            base64.b64encode(b'<svg xmlns="http://www.w3.org/2000/svg"/>').decode("ascii"),
            base64.b64encode(b"not an image").decode("ascii"),
            encoded_image(image_format="GIF"),
            encoded_image(size=(8, 50)),
            encoded_image(size=(2001, 2000)),
            encoded_image()[:80],
        )
        for value in invalid_images:
            with self.subTest(value=str(value)[:40]):
                with self.assertRaises(ValueError):
                    prepare_saved_calendar_image(value)

    def test_rejects_oversized_encoded_and_decoded_data(self):
        for size in (MAX_SAVED_IMAGE_BYTES + 1, MAX_SAVED_IMAGE_BYTES + 10):
            with self.subTest(size=size), self.assertRaisesRegex(ValueError, "512 KiB"):
                prepare_saved_calendar_image(base64.b64encode(b"x" * size).decode("ascii"))

    def test_relative_image_urls_accept_only_the_exact_saved_image_shape(self):
        valid = "/media/calendar-lots/" + "a" * 64 + ".jpg"
        self.assertEqual(_calendar_image_url(valid), valid)
        for url in (
            valid + "?query=1", valid + "/../private.jpg", valid + "\n",
            "/media/calendar-lots/../private.jpg", "/media/calendar-lots/%2e%2e/private.jpg",
            "/media/calendar-lots/" + "a" * 64 + ".svg", "//evil.example/image.jpg",
            "file:///C:/private/image.jpg", "data:image/jpeg;base64,aGVsbG8=",
        ):
            with self.subTest(url=url):
                self.assertEqual(_calendar_image_url(url), "")

    def test_doyle_and_phillips_images_use_only_recognized_hosts(self):
        for url in ("https://dist.phillips.com/auction-assets/NY030726/123.jpg",
                    "https://goauctiondoyle.blob.core.windows.net/stock/123.jpg"):
            self.assertEqual(_calendar_image_url(url), url)
        self.assertEqual(_calendar_image_url("https://other.blob.core.windows.net/123.jpg"), "")
        self.assertEqual(_calendar_image_url("https://dist.phillips.com.evil.test/123.jpg"), "")


@override_settings(CALENDAR_TIME_ZONE="America/New_York")
@patch.dict(os.environ, {"CATALOG_API_KEY": "saved-image-test-key"}, clear=False)
class CalendarSavedImageSyncTests(TestCase):
    endpoint = "/calendar/sync/"

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.media_settings = override_settings(MEDIA_ROOT=self.temporary.name)
        self.media_settings.enable()
        self.addCleanup(self.media_settings.disable)
        self.record = {
            "source": "Heritage", "source_lot_id": "8280-65050", "lot_number": "65050",
            "artist": "Agnes Martin", "artist_watchlist_name": "Agnes Martin",
            "title": "Paintings and Drawings", "auction_house": "Heritage Auctions",
            "end_at": "2026-10-22", "current_bid": 2000, "currency": "USD",
            "lot_url": "https://fineart.ha.com/itm/prints-and-multiples/a/8280-65050.s",
            "image_url": "https://dyn1.heritagestatic.com/ha?p=sample",
            "saved_image_base64": encoded_image(),
        }

    def sync(self, records=None, *, artist_links=None):
        payload = {"lots": records if records is not None else [self.record]}
        if artist_links is not None:
            payload["artist_links"] = artist_links
        return self.client.post(
            self.endpoint, json.dumps(payload), content_type="application/json",
            HTTP_X_API_KEY="saved-image-test-key",
        )

    def image_files(self):
        return list(Path(self.temporary.name).rglob("*.*"))

    def test_sync_saves_valid_image_and_reuses_the_same_file_on_repeated_upload(self):
        first = self.sync()
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["images_received"], 1)
        lot = AuctionWatchLot.objects.get()
        self.assertRegex(lot.image_url, r"^/media/calendar-lots/[0-9a-f]{64}\.jpg$")
        self.assertEqual(len(self.image_files()), 1)
        with Image.open(self.image_files()[0]) as image:
            self.assertEqual(image.format, "JPEG")
            self.assertEqual(image.size, (40, 60))
        second = self.sync()
        lot.refresh_from_db()
        self.assertEqual(second.json()["created"], 0)
        self.assertEqual(second.json()["updated"], 1)
        self.assertEqual(second.json()["images_received"], 1)
        self.assertEqual(len(self.image_files()), 1)
        self.assertEqual(AuctionWatchLot.objects.count(), 1)

    def test_later_url_only_sync_preserves_saved_image_artprice_and_tray(self):
        self.sync()
        lot = AuctionWatchLot.objects.get()
        image_url = lot.image_url
        lot.artprice_url = "https://www.artprice.com/artist/27973/agnes-martin/lots/pasts"
        lot.save(update_fields=("artprice_url",))
        batch = AuctionEmailBatch.objects.create()
        tray_item = AuctionEmailBatchItem.objects.create(batch=batch, lot=lot)
        record = dict(self.record, current_bid=2400, status="changed")
        record.pop("saved_image_base64")
        for replacement in ("", "https://dyn1.heritagestatic.com/ha?p=new"):
            with self.subTest(replacement=replacement):
                record["image_url"] = replacement
                response = self.sync([record])
                self.assertEqual(response.json()["images_received"], 0)
                lot.refresh_from_db()
                self.assertEqual(lot.image_url, image_url)
                self.assertEqual(lot.current_bid, 2400)
                self.assertEqual(lot.source_status, "changed")
                self.assertTrue(lot.artprice_url.endswith("/lots/pasts"))
                self.assertEqual(lot.lot_number, "65050")
                self.assertTrue(lot.is_all_day)
                self.assertTrue(AuctionEmailBatchItem.objects.filter(pk=tray_item.pk, lot=lot).exists())

    def test_new_saved_image_can_replace_an_existing_saved_image(self):
        self.sync()
        old_url = AuctionWatchLot.objects.get().image_url
        response = self.sync([dict(self.record, saved_image_base64=encoded_image(color="red"))])
        self.assertEqual(response.json()["images_received"], 1)
        self.assertNotEqual(AuctionWatchLot.objects.get().image_url, old_url)

    def test_invalid_later_record_prevents_any_file_artist_or_lot_writes(self):
        invalid_records = (
            dict(self.record, source_lot_id="bad-image", saved_image_base64="broken"),
            dict(self.record, source_lot_id="bad-date", end_at="not a date"),
        )
        for record in invalid_records:
            with self.subTest(source_lot_id=record["source_lot_id"]):
                response = self.sync([self.record, record], artist_links=[{
                    "name": "Agnes Martin", "artprice_url": "https://www.artprice.com/artist/1/agnes-martin",
                }])
                self.assertEqual(response.status_code, 400)
                self.assertFalse(AuctionWatchLot.objects.exists())
                self.assertFalse(AuctionWatchArtist.objects.exists())
                self.assertEqual(self.image_files(), [])

    def test_authentication_happens_before_image_processing(self):
        with patch("secondstateapp.calendar_views.prepare_saved_calendar_image") as prepare:
            response = self.client.post(
                self.endpoint, json.dumps({"lots": [self.record]}), content_type="application/json",
            )
        self.assertEqual(response.status_code, 401)
        prepare.assert_not_called()
        self.assertEqual(self.image_files(), [])

    def test_storage_failure_leaves_database_unchanged(self):
        with patch("secondstateapp.calendar_views.store_saved_calendar_image", side_effect=OSError("private path")):
            response = self.sync()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private path", response.content.decode())
        self.assertFalse(AuctionWatchLot.objects.exists())
        self.assertFalse(AuctionWatchArtist.objects.exists())

    def test_default_django_body_limit_returns_a_controlled_error(self):
        with override_settings(DATA_UPLOAD_MAX_MEMORY_SIZE=100):
            response = self.sync()
        self.assertEqual(response.status_code, 413)
        self.assertFalse(AuctionWatchLot.objects.exists())
