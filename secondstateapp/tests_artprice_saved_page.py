"""Sale identity and archive boundaries for saved Artprice artwork imports."""

from io import BytesIO
from unittest import TestCase
from unittest.mock import patch
import warnings
from zipfile import ZIP_DEFLATED, ZipFile

from PIL import Image

from .artprice_saved_page import read_artprice_saved_page
from .tests_artprice_react_store import react_store_html


def raster(color):
    payload = BytesIO()
    Image.new("RGB", (24, 16), color).save(payload, format="PNG")
    return payload.getvalue()


def archive(entries):
    upload = BytesIO()
    with ZipFile(upload, mode="w", compression=ZIP_DEFLATED) as saved:
        for name, content in entries:
            saved.writestr(name, content)
    return upload


def sale_page(markup):
    lots = {str(i): {
        "id": i, "title": "Same title", "lotstatus": 1,
        "price": "$100", "saleDtStart": "1 Jan 2026", "number": str(i),
    } for i in (1001, 1002, 1003, 1004)}
    html = react_store_html(lots, active_lot_ids=[1001, 1002, 1003])
    return (html + "\r\n" + markup).encode("utf8")


class SavedPageImageTests(TestCase):
    def test_first_artwork_in_each_active_sale_tile_uses_its_exact_companion_file(self):
        html = sale_page("""
            <div id="lot-1002"><img src="./sale_files/icon.png"><div class="lot-img">
              <img src="./sale_files/img-non-dispo.svg"><img src="./sale_files/xl%281%29">
            </div></div>
            <div id="lot-1001"><div class="lot-img"><img src="./sale_files/xl">
              <img src="./sale_files/second.png"></div></div>
            <div id="lot-1003"><div class="lot-img">
              <img src="./sale_files/../different_files/xl"><img src="https://host/sale_files/xl">
              <img src="./different_files/xl"><img src="./sale_files/img-non-dispo.svg">
            </div></div>
            <div id="lot-1004"><div class="lot-img"><img src="./sale_files/cache.png"></div></div>
        """)
        entries = [("outer/sale.htm", html), ("outer/sale_files/inner.html", b"other page"),
                   ("outer/sale_files/xl", raster("red")), ("outer/sale_files/xl(1)", raster("blue")),
                   ("outer/different_files/xl", b"unrelated"), ("outer/sale_files/icon.png", b"ui icon"),
                   ("outer/sale_files/second.png", b"extra photograph"),
                   ("outer/sale_files/cache.png", b"off-page sale"), ("outer/sale_files/img-non-dispo.svg", b"<svg/>")]
        name, raw, images = read_artprice_saved_page(archive(entries))
        self.assertEqual((name, raw), ("sale.htm", html))
        self.assertEqual(set(images), {"1001", "1002"})
        for provider_id, channel in [("1001", 0), ("1002", 2)]:
            with Image.open(BytesIO(images[provider_id])) as image:
                self.assertEqual(image.format, "JPEG")
                self.assertGreater(image.getpixel((1, 1))[channel], 250)

    def test_rejects_ambiguous_and_traversing_members_and_requires_the_companion(self):
        base = [("sale.html", sale_page("")), ("sale_files/logo.svg", b"<svg/>")]
        for name, entries, message in [
            ("two pages", base + [("second.htm", b"")], "one saved Artprice HTML"),
            ("missing companion", base[:1], "matching _files"),
            ("path traversal", base + [("sale_files/../lot.jpg", b"")], "invalid or duplicate"),
            ("duplicate name", base + [base[1]], "invalid or duplicate"),
        ]:
            with self.subTest(name=name), warnings.catch_warnings():
                warnings.filterwarnings("ignore", "Duplicate name", UserWarning)
                with self.assertRaisesRegex(ValueError, message):
                    read_artprice_saved_page(archive(entries))

    def test_bounds_archive_html_and_images_and_rejects_corrupt_selected_raster(self):
        html = sale_page('<div id="lot-1001"><div class="lot-img"><img src="./sale_files/xl"></div></div>')
        entries = [("sale.html", html), ("sale_files/xl", raster("red"))]
        for limit, message in [
            ("MAX_ARTPRICE_ARCHIVE_BYTES", "25 MB"),
            ("MAX_ARTPRICE_UNPACKED_BYTES", "unpacked size"),
            ("MAX_ARTPRICE_HTML_BYTES", "HTML page exceeds"),
            ("MAX_SAVED_IMAGE_BYTES", "artwork image exceeds"),
        ]:
            with self.subTest(limit=limit), patch(f"secondstateapp.artprice_saved_page.{limit}", 1):
                with self.assertRaisesRegex(ValueError, message):
                    read_artprice_saved_page(archive(entries))
        with self.assertRaisesRegex(ValueError, "sale 1001 is invalid"):
            read_artprice_saved_page(archive([entries[0], ("sale_files/xl", b"broken JPEG")]))
