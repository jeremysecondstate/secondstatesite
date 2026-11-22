from datetime import datetime, timedelta
from types import SimpleNamespace

from django.test import SimpleTestCase

from .calendar_sales import verified_timed_catalog


# Published first closings and catalog references for the ten affected sales.
# The photo extension and lot number retain the source feed's original case.
CATALOGS = (
    ("Alyes Auctions", "Alyes/94/822594/H21147", "y4fscaz8rx", "2026-11-22T20:00Z", "997", "jpg"),
    ("Weschler's", "weschlers/51/820351/H0143", "2vsj20nczp", "2026-11-24T15:00Z", "528", "JPG"),
    ("Gibson's", "gibsonsauctions/01/818301/H21402", "knjv6vqz4x", "2026-11-24T23:00Z", "237", "JPG"),
    ("Ozbid Auctions", "ozbid/69/822969/H4502", "tp5ezokvsw", "2026-11-30T09:00Z", "152", "JPG"),
    ("Leonard Joel", "leonardjoel/84/814284/H3018", "zls47cuze8", "2026-11-30T23:00Z", "138", "jpg"),
    ("For-Auction", "ForAuction/65/822565/H22978", "7m3kbjr8mb", "2026-12-01T06:00Z", "93", "JPG"),
    ("Ripley Auctions", "ripleyauctions/52/822652/H0071", "qs77vvq8yd", "2026-12-02T20:00Z", "112A", "JPG"),
    ("De Vuyst", "deVuyst/79/823079/H0426", "fsmjfi2w0i", "2026-12-05T09:00Z", "146", "jpg"),
    ("Bradford's", "bradfordsauction/48/815448/H22021", "681t8hybuo", "2026-12-06T16:00Z", "8083", "jpg"),
    ("Neal Auction Company", "nealauction/60/822560/H0120", "tztpio7ij0", "2026-12-08T17:00Z", "9151", "JPG"),
)


def catalog_lot(example):
    house, photo, _, first_closing, number, extension = example
    return SimpleNamespace(
        source="Invaluable", auction_house=house, is_all_day=False,
        event_at=datetime.fromisoformat(first_closing) + timedelta(minutes=10),
        sale_url="", lot_number=number,
        lot_url=f"https://www.invaluable.com/auction-lot/work-{number.lower()}-c-3d6abd50f8",
        image_url=f"https://image.invaluable.com/housePhotos/{photo}-CatalogPhoto.{extension}",
    )


class VerifiedTimedCatalogTests(SimpleTestCase):
    def test_missing_and_explicit_catalog_urls_resolve_to_the_same_published_start(self):
        for example in CATALOGS:
            house, _, ref, first_closing, _, _ = example
            canonical = f"https://www.invaluable.com/catalog/{ref}"
            lot = catalog_lot(example)
            for url in ("", canonical, f"https://invaluable.com/auction-catalog/sale_{ref.upper()}/"):
                with self.subTest(house=house, sale_url=url):
                    lot.sale_url = url
                    if url:
                        lot.image_url = ""
                    result = verified_timed_catalog(lot)
                    self.assertIsNotNone(result)
                    self.assertEqual(result["identity"], "sale:" + canonical)
                    self.assertEqual(result["starts_at"], datetime.fromisoformat(first_closing))

    def test_an_explicit_different_or_invalid_sale_url_overrides_a_matching_photo(self):
        lot = catalog_lot(CATALOGS[0])
        for url in (
            "https://www.invaluable.com/catalog/2vsj20nczp",
            "https://www.invaluable.com/catalog/y4fscaz8rx/another",
            "https://www.invaluable.com/auction-lot/work-997-c-3d6abd50f8",
            "https://www.invaluable.com.example.org/catalog/y4fscaz8rx",
            "https://invaluable.com@other.example/catalog/y4fscaz8rx",
            "http://www.invaluable.com/catalog/y4fscaz8rx",
        ):
            with self.subTest(sale_url=url):
                lot.sale_url = url
                self.assertIsNone(verified_timed_catalog(lot))

    def test_source_house_day_and_matching_lot_number_are_required_for_both_paths(self):
        lot = catalog_lot(CATALOGS[6])
        changes = (
            {"source": "Drouot"}, {"auction_house": "Ripley Auctions Partners"},
            {"event_at": lot.event_at + timedelta(days=1)}, {"event_at": None},
            {"event_at": lot.event_at.replace(tzinfo=None)}, {"is_all_day": True},
            {"lot_number": ""}, {"lot_number": "112"}, {"lot_number": "112B"},
            {"lot_number": "112-1"}, {"lot_url": ""},
            {"lot_url": lot.lot_url.replace("-c-", "-other-")},
            {"lot_url": lot.lot_url.replace("www.invaluable.com", "invaluable.com.example.org")},
            {"lot_url": "https://[invalid"},
        )
        for sale_url in ("", "https://www.invaluable.com/catalog/qs77vvq8yd"):
            for change in changes:
                with self.subTest(sale_url=sale_url, change=change):
                    candidate = SimpleNamespace(**{**vars(lot), "sale_url": sale_url, **change})
                    self.assertIsNone(verified_timed_catalog(candidate))

    def test_missing_sale_link_requires_the_exact_catalog_photo(self):
        lot = catalog_lot(CATALOGS[0])
        self.assertIsNone(verified_timed_catalog(SimpleNamespace(**{**vars(lot), "image_url": ""})))
        for old, new in (
            ("/Alyes/", "/OtherHouse/"), ("/94/", "/93/"), ("/822594/", "/821739/"),
            ("H21147-", "H21148-"), ("image.invaluable.com", "image.invaluable.com.example.org"),
            (".jpg", ".jpg/unrelated.jpg"), ("https://", "http://"),
        ):
            with self.subTest(old=old, new=new):
                candidate = SimpleNamespace(**{**vars(lot), "image_url": lot.image_url.replace(old, new)})
                self.assertIsNone(verified_timed_catalog(candidate))

    def test_pacific_sale_day_accepts_a_lot_closing_after_utc_midnight(self):
        lot = catalog_lot(CATALOGS[0])
        lot.event_at = datetime.fromisoformat("2026-11-23T04:10Z")
        self.assertEqual(verified_timed_catalog(lot)["catalog_url"], "https://www.invaluable.com/catalog/y4fscaz8rx")
        lot.event_at = datetime.fromisoformat("2026-11-23T08:00Z")
        self.assertIsNone(verified_timed_catalog(lot))
