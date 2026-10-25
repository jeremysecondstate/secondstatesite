from django.test import SimpleTestCase

from .oliver_houses import is_oliver_house, oliver_house_names


class OliverHouseMembershipTests(SimpleTestCase):
    def test_all_workbook_houses_are_included_in_workbook_order(self):
        expected = (
            "Sotheby's", "Christie's", "Bonhams", "Phillips", "Swann Auction Galleries",
            "Doyle", "Rago Auctions", "Wright", "John Moran Auctioneers", "Heritage Auctions",
            "Freeman's", "Artcurial", "Dorotheum", "Bukowskis", "Bradford's Auction Galleries",
            "Los Angeles Modern Auctions (LAMA)", "Clars Auctions",
        )
        self.assertEqual(oliver_house_names(), expected)
        for name in expected:
            with self.subTest(name=name):
                self.assertTrue(is_oliver_house(name))

    def test_observed_calendar_names_match_explicit_aliases(self):
        for name in (
            "Bradford's", "Rago Arts and Auction Center", "Los Angeles Modern Auctions", "Freeman’s",
        ):
            with self.subTest(name=name):
                self.assertTrue(is_oliver_house(name))

    def test_case_unicode_punctuation_and_spacing_do_not_prevent_membership(self):
        for name in (
            "  PHILLIPS\t", "SOTHEBY’S", "Christies", "Freeman\u02bcs",
            "Swann  Auction\nGalleries", "John Moran, Auctioneers", "Ｂｏｎｈａｍｓ",
            "Los Angeles Modern Auctions [LAMA]", "Freeman&rsquo;s", "Freemanâ€™s",
        ):
            with self.subTest(name=name):
                self.assertTrue(is_oliver_house(name))

    def test_similar_names_affiliates_and_unlisted_houses_are_excluded(self):
        for name in (
            "Artcurial Beurret Bailly Widmer", "Bonhams Skinner", "Bonhams Cornette de Saint Cyr",
            "Freeman's | Hindman", "Heritage Auctions Europe", "Phillips Auctioneers Example",
            "Wright & Company", "Clarke Auction Gallery", "Rago Auctions Example",
            "Bradford's Collectibles", "Not Bonhams", "Sotheby's Example",
        ):
            with self.subTest(name=name):
                self.assertFalse(is_oliver_house(name))

    def test_short_names_are_not_inferred_and_missing_names_are_excluded(self):
        for name in ("Heritage", "Swann", "Rago", "Moran", "Clars", "LAMA", "", "   ", None):
            with self.subTest(name=name):
                self.assertFalse(is_oliver_house(name))
