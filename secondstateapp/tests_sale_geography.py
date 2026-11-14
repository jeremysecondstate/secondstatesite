from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

from django.test import SimpleTestCase

from .sale_geography import sale_geography


class SaleGeographyTests(SimpleTestCase):
    def lot(self, **fields):
        return SimpleNamespace(
            **{"auction_house": "Unlisted house", "location": "", "currency": "USD",
               "source": "Drouot", "title": "American landscape", **fields}
        )

    def assert_country(self, expected, **fields):
        result = sale_geography(self.lot(**fields))
        self.assertEqual(result["country_code"], expected)
        self.assertEqual(result["region"], "us" if expected == "US" else "outside_us" if expected else "unknown")

    def test_explicit_country_locations_include_provider_address_formats(self):
        cases = {
            "Detroit, MI, US": "US", "New York, NY, USA": "US",
            "United States of America": "US", "U.S.A.": "US",
            "London, LDN, UK": "GB", "Paris, France": "FR",
            "Sydney, NSW, AU": "AU", "Hong Kong, HK": "HK",
            "online, IT": "IT", "Berlin, DE": "DE",
            "Toronto, ON, CA": "CA", "New York": "US",
            "Stockholm": "SE", "Cologne": "DE",
        }
        for location, country in cases.items():
            with self.subTest(location=location):
                self.assert_country(country, location=location)

    def test_sale_location_overrides_the_houses_usual_country(self):
        self.assert_country("GB", auction_house="DuMouchelles", location="London, UK")
        self.assert_country("US", auction_house="Aalders Auctions", location="New York, NY, US")
        self.assert_country("", auction_house="DuMouchelles", location="Unconfirmed venue")

    def test_address_state_abbreviations_are_not_mistaken_for_countries(self):
        for location in ("CA", "Los Angeles, CA", "Wilmington, DE",
                         "Chicago, IL", "Indianapolis, IN",
                         "123 Main Street, Los Angeles, CA"):
            with self.subTest(location=location):
                self.assert_country("", location=location)

    def test_ambiguous_or_unrecognized_location_is_not_foreign_by_default(self):
        for location in ("", "Online", "London", "Paris", "US Embassy London", "London, UK; New York, USA",
                         "New York, US; London, GB", "United States; London, GB",
                         "New York, US; Toronto, CA", "Toronto, CA; New York, US",
                         "New York, United States; Berlin, DE", "Berlin, DE; New York, US"):
            with self.subTest(location=location):
                self.assert_country("", location=location)

    def test_multinational_house_requires_sale_location(self):
        for house in ("Sotheby's", "Christie's", "Bonhams", "Phillips", "Heritage Auctions", "Artvisory"):
            with self.subTest(house=house):
                self.assert_country("", auction_house=house)
                self.assert_country("US", auction_house=house, location="New York")
                self.assert_country("GB", auction_house=house, location="London, UK")

    def test_verified_house_aliases_match_complete_names_only(self):
        for house in ("Templum Fine Art Auctions", "Templum Fine art Auction"):
            self.assert_country("ES", auction_house=house)
        self.assert_country("FR", auction_house="  CRAIT + MÜLLER  ")
        self.assert_country("FR", auction_house="Crait & Muller")
        self.assert_country("DE", auction_house="Nosbusch & Stucke GmbH")
        self.assert_country("US", auction_house="Rago Arts and Auction Center")
        for house in ("New Copake Auction Inc.", "DuMouchelles affiliate",
                      "Wright & Sons", "Doyle London", "Crait"):
            with self.subTest(house=house):
                self.assert_country("", auction_house=house)

    def test_online_only_location_can_use_verified_house(self):
        self.assert_country("US", auction_house="Dennis Auction Service", location="Online only")
        self.assert_country("GB", auction_house="Britannica Auctions", location="online")

    def test_provider_title_and_links_do_not_establish_country(self):
        lot = self.lot(currency="USD", source="Invaluable", title="New York / American artist",
                       lot_url="https://www.example.us/item", sale_url="https://drouot.com/en/v/123")
        self.assertEqual(sale_geography(lot), {"region": "unknown", "country_code": ""})
        lot.currency = "EUR"
        lot.source = "Drouot"
        self.assertEqual(sale_geography(lot), {"region": "outside_us", "country_code": ""})

    def test_native_non_usd_currency_classifies_the_sale_without_inventing_a_country(self):
        for currency in ("EUR", "GBP", "CAD", "AUD", "CHF", "JPY", "HKD", "SEK", " eur "):
            with self.subTest(currency=currency):
                lot = self.lot(currency=currency, location="Unconfirmed venue")
                self.assertEqual(sale_geography(lot), {"region": "outside_us", "country_code": ""})

    def test_non_usd_category_rule_preserves_verified_country_metadata(self):
        self.assertEqual(sale_geography(self.lot(currency="EUR", location="Paris, France")),
                         {"region": "outside_us", "country_code": "FR"})
        self.assertEqual(sale_geography(self.lot(currency="CAD", location="New York, US")),
                         {"region": "outside_us", "country_code": "US"})
        self.assertEqual(sale_geography(self.lot(currency="USD", location="London, UK")),
                         {"region": "outside_us", "country_code": "GB"})

    def test_missing_currency_and_display_or_research_currency_do_not_classify_sale(self):
        for currency in ("", None, "unknown", "XXX", "€", "USD"):
            with self.subTest(currency=currency):
                lot = self.lot(currency=currency, sold_currency="EUR", usd_currency="USD",
                               original_currency="GBP", usd_prices={"source_currency": "EUR"})
                self.assertEqual(sale_geography(lot), {"region": "unknown", "country_code": ""})

    def test_presentation_helper_does_not_modify_source_or_saved_fields(self):
        lot = self.lot(auction_house="DuMouchelles", source_lot_id="source-1", won_by_us=True,
                       superseded_by_id=25, artprice_url="https://www.artprice.com/artist/1")
        before = deepcopy(vars(lot))
        self.assert_country("US", auction_house=lot.auction_house)
        sale_geography(lot)
        self.assertEqual(vars(lot), before)

    def test_current_november13_house_labels_have_verified_countries(self):
        countries = {
            "Copake Auction Inc.": "US", "Cross Gate Gallery": "US",
            "Dennis Auction Service": "US", "DuMouchelles": "US",
            "Thomaston Place Auction Galleries": "US", "Aalders Auctions": "AU",
            "Britannica Auctions": "GB", "Crait + Müller": "FR", "Ferri & Associés": "FR",
            "Gregory's Casa d'Aste": "IT", "Mytika": "FR",
            "Nosbüsch & Stucke GmbH": "DE", "Rossini": "FR",
            "Templum Fine art Auction": "ES", "Templum Fine Art Auctions": "ES",
        }
        for house, country in countries.items():
            with self.subTest(house=house):
                self.assert_country(country, auction_house=house)

    def test_blank_locations_on_following_days_use_verified_house_aliases(self):
        # These observed import labels previously left most November 14/15 lots
        # unclassified. Include cross-provider spellings and both US/foreign
        # houses; the absence of imported location must not discard them.
        countries = {
            "Auktionshaus Angerland": "DE", "Auktionshaus Angerland GmbH": "DE",
            "DEWIT Auctions": "BE", "Dewit Auctions": "BE",
            "Kunst & Design Auktionshaus Schops Turowski": "DE",
            "Kunst und Design Auktionshaus Schops Turowski": "DE",
            "Richard Bedot Auction": "FR", "Pastor Maison de Ventes": "FR",
            "FauveParis": "FR", "ArteIn Gallery": "IT",
            "Phillip Caldwell Auctioneers": "AU", "Domusarte": "PT",
            "Neely Auction": "US", "Sarasota Estate Auction": "US",
            "Grogan & Company": "US", "Roland Auctions NY": "US",
            "Burchard Galleries Inc": "US", "Fine Estate Inc.": "US",
            "Trillium Antique Prints & Rare Books": "US",
        }
        for house, country in countries.items():
            with self.subTest(house=house):
                self.assert_country(country, auction_house=house)
                self.assert_country("", auction_house=house, location="Unconfirmed venue")
                self.assert_country("", auction_house=house + " affiliate")
                other_country, location = ("FR", "Paris, France") if country == "US" else ("US", "New York, US")
                self.assert_country(other_country, auction_house=house, location=location)

    def test_usd_sales_outside_us_keep_verified_foreign_country(self):
        for house, country in (("Alyes Auctions", "HK"), ("Hammersite", "IL"), ("Zorrilla Subastas", "UY")):
            with self.subTest(house=house):
                self.assert_country(country, auction_house=house, currency="USD")
        self.assert_country("IL", auction_house="Pasarel", location="Netanya, IL", currency="USD")

    def test_verified_heritage_sale_requires_exact_source_house_date_and_url(self):
        fields = dict(auction_house="Heritage Auctions", source="Heritage", currency="USD",
                      event_at=datetime(2026, 11, 18, 7, tzinfo=timezone.utc),
                      sale_url="https://fineart.ha.com/c/search.zx?saleNo=18242")
        self.assert_country("US", **fields)
        for changed in (
            {"source": "Other provider"}, {"auction_house": "Unverified house"},
            {"event_at": datetime(2026, 11, 19, 7, tzinfo=timezone.utc)},
            {"sale_url": "https://fineart.ha.com/c/search.zx?saleNo=182420"},
            {"sale_url": "https://other.example/c/search.zx?saleNo=18242"},
        ):
            with self.subTest(changed=changed):
                self.assert_country("", **{**fields, **changed})
        self.assert_country("GB", **fields, location="London, UK")

    def test_verified_bonhams_source_lot_fallback_does_not_cover_other_sales(self):
        fields = dict(auction_house="Bonhams", source="Invaluable", currency="USD",
                      source_lot_id="207195647", lot_number="29",
                      event_at=datetime(2026, 10, 28, 16, tzinfo=timezone.utc),
                      lot_url="https://www.invaluable.com/auction-lot/albrecht-durer-1471-1528-the-large-horse-29-c-2f5e2703c1")
        self.assert_country("US", **fields)
        for changed in (
            {"source_lot_id": "another-id"}, {"lot_number": "30"},
            {"lot_url": "https://www.invaluable.com/auction-lot/different-lot"},
            {"sale_url": "https://www.invaluable.com/catalog/another-sale"},
            {"event_at": datetime(2026, 10, 29, 16, tzinfo=timezone.utc)},
        ):
            with self.subTest(changed=changed):
                self.assert_country("", **{**fields, **changed})

