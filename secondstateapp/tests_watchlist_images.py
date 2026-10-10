"""Saved artwork images remain bounded and confined to the selected catalog."""

import base64
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from PIL import Image, ImageDraw
from PIL.PngImagePlugin import PngInfo

from catalogapp.bookmark_watchlist import BookmarkEntry
from catalogapp.watchlist_adapters import HeritageAdapter
from catalogapp.watchlist_cache import WatchlistCache
from catalogapp.watchlist_images import (
    MAX_SAVED_IMAGE_BYTES,
    attach_saved_heritage_images,
    heritage_preview_url,
    normalize_saved_thumbnail,
    prefer_cached_saved_image,
)
from catalogapp.watchlist_saved_pages import import_saved_heritage_pages


SALE_URL = "https://fineart.ha.com/c/search/results.zx?auction_name=8280"
PUBLIC_IMAGE = "https://dyn1.heritagestatic.com/ha?p=1-2-3-12345678&it=product"


def image_bytes(*, size=(120, 160), color="red", metadata=False):
    canvas = Image.new("RGB", size, "white")
    ImageDraw.Draw(canvas).rectangle((10, 10, size[0] - 10, size[1] - 10), fill=color)
    output = BytesIO()
    info = PngInfo()
    if metadata:
        info.add_text("Comment", "Private test metadata must not leave this image")
    canvas.save(output, format="PNG", pnginfo=info)
    return output.getvalue()


def card(number="65001", src="./catalog_files/art", sale="8280"):
    return f"""<li class="item-block">
      <a class="photo-holder"><img src="{src}" data-src="{PUBLIC_IMAGE}"></a>
      <a class="item-title" href="https://fineart.ha.com/itm/work/a/{sale}-{number}.s">
        <b>Pablo Picasso (1881-1973)</b><br><i>Portrait</i>, 1962<br>Linocut
      </a><span class="live-auction-date">Oct 22, 2026</span>
    </li>"""


class SavedWatchlistImageTests(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.page_path = self.root / "catalog.html"
        self.assets = self.root / "catalog_files"
        self.assets.mkdir()
        self.art = self.assets / "art"
        self.art.write_bytes(image_bytes(metadata=True))

    @staticmethod
    def lots(html):
        return HeritageAdapter().parse_search_page(html, SALE_URL, "")

    def test_preview_url_only_accepts_recognized_public_product_images(self):
        expected = "https://dyn1.heritagestatic.com/ha?p=1-2-3-12345678&w=612&h=600&it=product"
        self.assertEqual(heritage_preview_url(PUBLIC_IMAGE + "&w=120&h=300&tracking=discard"), expected)
        self.assertEqual(heritage_preview_url(expected), expected)
        self.assertTrue(heritage_preview_url(PUBLIC_IMAGE.replace("dyn1.", "dyn2.")))
        invalid = [
            PUBLIC_IMAGE.replace("https:", "http:"),
            PUBLIC_IMAGE.replace("dyn1.heritagestatic.com", "example.com"),
            PUBLIC_IMAGE.replace("dyn1.heritagestatic.com", "dyn1.heritagestatic.com.example.com"),
            PUBLIC_IMAGE.replace("dyn1.", "www."),
            PUBLIC_IMAGE.replace("https://", "https://name:password@"),
            PUBLIC_IMAGE.replace(".com/", ".com:8443/"),
            PUBLIC_IMAGE.replace("/ha?", "/other?"),
            PUBLIC_IMAGE.replace("1-2-3-12345678", "../private"),
            PUBLIC_IMAGE + "&p=1-2-3-9999", PUBLIC_IMAGE + "#fragment",
            PUBLIC_IMAGE.replace("it=product", "it=account"), PUBLIC_IMAGE + "\x00",
        ]
        for value in invalid:
            with self.subTest(value=value):
                self.assertEqual(heritage_preview_url(value), "")

    def test_companion_origin_stream_recovers_public_url_without_retaining_metadata(self):
        html = card().replace(f' data-src="{PUBLIC_IMAGE}"', "")
        lot = self.lots(html)[0]
        stream_path = Path(f"{self.art}:Zone.Identifier")
        stream_path.write_bytes(
            ("[ZoneTransfer]\nZoneId=3\nReferrerUrl=https://private.example/account\n"
             f"HostUrl={PUBLIC_IMAGE}&w=120&h=300\x00\n").encode("utf-8")
        )
        notices = attach_saved_heritage_images(html, self.page_path, [lot])
        self.assertEqual(notices, [])
        self.assertEqual(lot.image_url, heritage_preview_url(PUBLIC_IMAGE))
        self.assertNotIn("private.example", repr(lot.to_dict()))
        self.assertNotIn("Zone.Identifier", repr(lot.to_dict()))
        self.assertEqual(lot.content_hash, lot.calculate_content_hash())

    def test_origin_stream_is_not_read_outside_companion_folder_or_used_for_unrelated_hosts(self):
        html = card(src="catalog_files/../outside").replace(f' data-src="{PUBLIC_IMAGE}"', "")
        lot = self.lots(html)[0]
        with patch("catalogapp.watchlist_images._asset_heritage_preview_url") as origin:
            attach_saved_heritage_images(html, self.page_path, [lot])
            origin.assert_not_called()
        self.assertEqual(lot.image_url, "")
        html = card().replace(f' data-src="{PUBLIC_IMAGE}"', "")
        lot = self.lots(html)[0]
        Path(f"{self.art}:Zone.Identifier").write_text(
            "[ZoneTransfer]\nHostUrl=https://private.example/image\n", encoding="utf-8"
        )
        attach_saved_heritage_images(html, self.page_path, [lot])
        self.assertEqual(lot.image_url, "")

    def test_actual_image_identity_takes_precedence_over_stale_lazy_source(self):
        changed_image = PUBLIC_IMAGE.replace("12345678", "99999999")
        remote = card(src=changed_image)
        lot = self.lots(remote)[0]
        attach_saved_heritage_images(remote, self.page_path, [lot])
        self.assertEqual(lot.image_url, heritage_preview_url(changed_image))
        Path(f"{self.art}:Zone.Identifier").write_text(
            f"[ZoneTransfer]\nHostUrl={changed_image}\n", encoding="utf-8"
        )
        html = card()
        incoming = self.lots(html)[0]
        cached = self.lots(html)[0]
        cached.saved_image_base64 = normalize_saved_thumbnail(image_bytes(size=(450, 600)))
        attach_saved_heritage_images(html, self.page_path, [incoming])
        expected = incoming.saved_image_base64
        prefer_cached_saved_image(incoming, cached)
        self.assertEqual(incoming.image_url, heritage_preview_url(changed_image))
        self.assertEqual(incoming.saved_image_base64, expected)
        self.assertNotEqual(incoming.saved_image_base64, cached.saved_image_base64)

    def test_larger_cached_preview_survives_smaller_or_missing_saved_thumbnail(self):
        cached = self.lots(card())[0]
        cached.saved_image_base64 = normalize_saved_thumbnail(image_bytes(size=(450, 600)))
        small = self.lots(card())[0]
        small.saved_image_base64 = normalize_saved_thumbnail(image_bytes(size=(120, 160)))
        prefer_cached_saved_image(small, cached)
        self.assertEqual(small.saved_image_base64, cached.saved_image_base64)
        self.assertEqual(small.content_hash, small.calculate_content_hash())
        missing = self.lots(card())[0]
        prefer_cached_saved_image(missing, cached)
        self.assertEqual(missing.saved_image_base64, cached.saved_image_base64)

    def test_new_primary_image_id_or_larger_new_image_takes_precedence(self):
        cached = self.lots(card())[0]
        cached.saved_image_base64 = normalize_saved_thumbnail(image_bytes(size=(450, 600)))
        replacement = self.lots(card())[0]
        replacement.image_url = PUBLIC_IMAGE.replace("12345678", "99999999")
        replacement.saved_image_base64 = normalize_saved_thumbnail(image_bytes(color="blue"))
        expected = replacement.saved_image_base64
        prefer_cached_saved_image(replacement, cached)
        self.assertEqual(replacement.saved_image_base64, expected)
        larger = self.lots(card())[0]
        larger.saved_image_base64 = normalize_saved_thumbnail(image_bytes(size=(600, 800)))
        expected = larger.saved_image_base64
        prefer_cached_saved_image(larger, cached)
        self.assertEqual(larger.saved_image_base64, expected)

    def test_invalid_or_oversized_cached_image_is_not_retained(self):
        new = self.lots(card())[0]
        new.saved_image_base64 = normalize_saved_thumbnail(image_bytes())
        expected = new.saved_image_base64
        for value in ["not valid base64", base64.b64encode(b"x" * (MAX_SAVED_IMAGE_BYTES + 1)).decode()]:
            cached = self.lots(card())[0]
            cached.saved_image_base64 = value
            prefer_cached_saved_image(new, cached)
            self.assertEqual(new.saved_image_base64, expected)

    def test_attaches_correct_primary_image_by_lot_identity(self):
        second = self.assets / "blue"
        second.write_bytes(image_bytes(color="blue"))
        html = card("65002", "catalog_files/blue") + card("65001")
        lots = self.lots(html)
        before = {lot.source_lot_id: lot.content_hash for lot in lots}
        notices = attach_saved_heritage_images(html, self.page_path, lots)
        self.assertEqual(notices, [])
        mapped = {lot.source_lot_id: lot for lot in lots}
        for identity, color in [("8280-65001", "red"), ("8280-65002", "blue")]:
            lot = mapped[identity]
            self.assertNotEqual(lot.content_hash, before[identity])
            self.assertEqual(lot.content_hash, lot.calculate_content_hash())
            with Image.open(BytesIO(base64.b64decode(lot.saved_image_base64))) as saved:
                pixel = saved.getpixel((60, 80))
                self.assertGreater(pixel[0 if color == "red" else 2], 240)
                self.assertNotIn("Comment", saved.info)
            self.assertEqual(lot.image_url, heritage_preview_url(PUBLIC_IMAGE))
            self.assertNotIn(str(self.root), repr(lot.to_dict()))

    def test_external_absolute_traversal_and_other_folder_references_are_not_read(self):
        outside = self.root / "outside"
        outside.write_bytes(image_bytes())
        bad_sources = [
            str(outside), outside.as_uri(), PUBLIC_IMAGE, "//example.com/image.jpg",
            "../outside", "catalog_files/../outside", "catalog_files/%2e%2e/outside",
            "catalog_files/..\\outside", "other_files/art", "catalog_files/art:Zone.Identifier",
        ]
        for src in bad_sources:
            with self.subTest(src=src):
                html = card(src=src)
                lots = self.lots(html)
                with patch("catalogapp.watchlist_images.normalize_saved_thumbnail") as normalize:
                    notices = attach_saved_heritage_images(html, self.page_path, lots)
                    normalize.assert_not_called()
                self.assertEqual(lots[0].saved_image_base64, "")
                self.assertEqual(lots[0].image_url, heritage_preview_url(PUBLIC_IMAGE))
                self.assertIn("Webpage, Complete", notices[0])

    def test_symlink_cannot_escape_companion_directory(self):
        outside = self.root / "outside"
        outside.write_bytes(image_bytes())
        linked = self.assets / "linked"
        try:
            linked.symlink_to(outside)
        except OSError as exc:
            self.skipTest(f"Symlink creation is unavailable: {exc}")
        html = card(src="catalog_files/linked")
        lots = self.lots(html)
        self.assertTrue(attach_saved_heritage_images(html, self.page_path, lots))
        self.assertEqual(lots[0].saved_image_base64, "")

    def test_symlink_companion_directory_is_not_followed(self):
        outside_assets = self.root / "other_assets"
        outside_assets.mkdir()
        (outside_assets / "art").write_bytes(image_bytes())
        linked_assets = self.root / "linked_files"
        try:
            linked_assets.symlink_to(outside_assets, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"Symlink creation is unavailable: {exc}")
        html = card(src="linked_files/art")
        lots = self.lots(html)
        self.assertTrue(attach_saved_heritage_images(html, self.root / "linked.html", lots))
        self.assertEqual(lots[0].saved_image_base64, "")

    def test_jpeg_is_bounded_and_metadata_free(self):
        encoded = normalize_saved_thumbnail(image_bytes(size=(2400, 1900), metadata=True))
        data = base64.b64decode(encoded, validate=True)
        self.assertLessEqual(len(data), MAX_SAVED_IMAGE_BYTES)
        self.assertNotIn(b"Private test metadata", data)
        with Image.open(BytesIO(data)) as saved:
            self.assertEqual(saved.format, "JPEG")
            self.assertLessEqual(max(saved.size), 1600)
            self.assertEqual(saved.getexif(), {})
            self.assertFalse(set(saved.info) & {"exif", "xmp", "icc_profile", "comment", "Comment"})

    def test_corrupt_missing_and_placeholder_images_keep_public_fallback(self):
        (self.assets / "bad").write_bytes(b"not an image")
        for name, mode, color, size in [
            ("single", "RGB", "white", (1, 1)),
            ("blank", "RGB", "white", (100, 100)),
            ("invisible", "RGBA", (0, 0, 0, 0), (100, 100)),
        ]:
            Image.new(mode, size, color).save(self.assets / name, format="PNG")
        for name in ("bad", "absent", "single", "blank", "invisible"):
            with self.subTest(name=name):
                html = card(src=f"catalog_files/{name}")
                lots = self.lots(html)
                notices = attach_saved_heritage_images(html, self.page_path, lots)
                self.assertEqual(len(notices), 1)
                self.assertEqual(lots[0].saved_image_base64, "")
                self.assertEqual(lots[0].image_url, heritage_preview_url(PUBLIC_IMAGE))

    def test_saved_import_persists_images_and_later_missing_asset_keeps_cached_image(self):
        self.page_path.write_text(card(), encoding="utf-8")
        entry = BookmarkEntry(("HERITAGE",), "Print sale", SALE_URL, source="Heritage")
        now = datetime(2026, 10, 10, tzinfo=timezone.utc)
        with WatchlistCache(":memory:") as cache:
            first = import_saved_heritage_pages([self.page_path], entry, cache, now=now, horizon_days=30)
            self.assertTrue(first.lots[0].saved_image_base64)
            repeated = import_saved_heritage_pages([self.page_path], entry, cache, now=now, horizon_days=30)
            self.assertEqual(repeated.metrics.unchanged_lots, 1)
            self.art.unlink()
            fallback = import_saved_heritage_pages([self.page_path], entry, cache, now=now, horizon_days=30)
            self.assertEqual(fallback.lots[0].saved_image_base64, first.lots[0].saved_image_base64)
            self.assertEqual(cache.get(first.lots[0].cache_key).saved_image_base64, first.lots[0].saved_image_base64)
            self.assertTrue(fallback.notices)

    def test_saved_import_does_not_downgrade_cached_preview(self):
        self.page_path.write_text(card(), encoding="utf-8")
        entry = BookmarkEntry(("HERITAGE",), "Print sale", SALE_URL, source="Heritage")
        now = datetime(2026, 10, 10, tzinfo=timezone.utc)
        self.art.write_bytes(image_bytes(size=(450, 600)))
        with WatchlistCache(":memory:") as cache:
            high = import_saved_heritage_pages([self.page_path], entry, cache, now=now, horizon_days=30)
            self.art.write_bytes(image_bytes(size=(120, 160)))
            small = import_saved_heritage_pages([self.page_path], entry, cache, now=now, horizon_days=30)
            self.assertEqual(small.lots[0].saved_image_base64, high.lots[0].saved_image_base64)
            self.assertEqual(small.metrics.unchanged_lots, 1)

    def test_mismatched_second_page_does_not_cache_first_page_images(self):
        self.page_path.write_text(card(), encoding="utf-8")
        wrong = self.root / "wrong.html"
        wrong.write_text(card(sale="9999"), encoding="utf-8")
        entry = BookmarkEntry(("HERITAGE",), "Print sale", SALE_URL, source="Heritage")
        with WatchlistCache(":memory:") as cache:
            with self.assertRaises(ValueError):
                import_saved_heritage_pages([self.page_path, wrong], entry, cache)
            self.assertEqual(cache.active_lots_for_watch_url(SALE_URL), [])
