from copy import deepcopy
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
        for house in ("Sotheby's", "Christie's", "Bonhams", "Phillips", "Heritage Auctions"):
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

    def test_currency_provider_title_and_links_do_not_establish_country(self):
        lot = self.lot(currency="USD", source="Invaluable", title="New York / American artist",
                       lot_url="https://www.example.us/item", sale_url="https://drouot.com/en/v/123")
        self.assertEqual(sale_geography(lot), {"region": "unknown", "country_code": ""})
        lot.currency = "EUR"
        lot.source = "Drouot"
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

