"""Catalog-only medium extraction retains source wording and search scope."""

import json
from pathlib import Path
from unittest import TestCase

from catalogapp.watchlist_adapters import InvaluableAdapter
from catalogapp.watchlist_invaluable_pages import _hit_matches_category


FIXTURE = Path(__file__).parent / "test_fixtures" / "watchlist" / "invaluable_catalog_medium.json"
SEARCH = "https://www.invaluable.com/search?artistName=Wolf+Kahn&Fine+Art=Drawings&Fine+Art=Prints"


class InvaluableCatalogMediumTests(TestCase):
    def setUp(self):
        self.adapter = InvaluableAdapter()

    def medium(self, title="Artwork", description="", **overrides):
        hit = {"objectID": "1", "lotRef": "ref1", "lotTitle": title,
               "lotDescription": description, "artistName": "Example Artist"}
        hit.update(overrides)
        return self.adapter._raw_from_catalog_hit(hit, SEARCH, "Example Artist")["medium"]

    def test_actual_public_catalog_hits_extract_the_explicit_medium_and_retain_every_lot(self):
        hits = json.loads(FIXTURE.read_text(encoding="utf-8"))
        lots = self.adapter.parse_search_page(json.dumps({"results": [{"hits": hits}]}), SEARCH, "")
        by_id = {lot.source_lot_id: lot for lot in lots}
        self.assertEqual(set(by_id), {str(hit["objectID"]) for hit in hits})
        self.assertEqual(len(lots), 8)
        for hit in hits:
            with self.subTest(source_lot_id=hit["objectID"]):
                lot = by_id[str(hit["objectID"])]
                expected = {
                    "207185223": "Etching",
                    "207196967": "Graphite, pastel, and watercolor",
                    "207196969": "Etching",
                }.get(hit["objectID"], "Pastel")
                self.assertEqual(lot.medium, expected)
                self.assertEqual(lot.title, hit["lotTitle"])
                self.assertEqual(lot.lot_number, hit["lotNumber"])
                self.assertEqual(lot.artist, hit["artistName"])
                is_drawing = hit["categoryName"] == "Drawings"
                self.assertEqual("print_classification" in lot.ambiguities, is_drawing)
                self.assertTrue(_hit_matches_category(hit, SEARCH))
                if is_drawing:
                    self.assertFalse(_hit_matches_category(hit, SEARCH.replace("&Fine+Art=Drawings", "")))

    def test_opening_mixed_drawing_medium_is_not_replaced_by_a_separate_print_reference(self):
        for description, expected in (
            ('(France, 1888-1950) Original graphite, pastel, and watercolor on paper study. '
             'The original etching is also being sold in this auction.', 'Graphite, pastel, and watercolor'),
            ('Charcoal and gouache on board. A lithograph is being sold separately.', 'Charcoal and gouache'),
        ):
            with self.subTest(description=description):
                self.assertEqual(self.medium(description=description), expected)

    def test_mixed_drawing_rule_preserves_actual_prints_and_excludes_biographical_materials(self):
        for title, description, expected in (
            ('Color lithograph', 'Original graphite, pastel, and watercolor on paper study.', 'Lithograph'),
            ('Pair of etchings', 'Original graphite, pastel, and watercolor on paper study.', 'Etching'),
            ('Artwork', 'Original hand colored etching. Graphite and watercolor on paper study sold separately.', 'Etching'),
            ('Artwork', 'Original etching heightened with graphite and watercolor on paper.', 'Etching'),
            ('Artwork', 'Biography: Original graphite, pastel, and watercolor on paper study.', 'Print'),
            ('Artwork', 'The artist worked in graphite and watercolor on paper.', 'Print'),
            ('Artwork', 'Graphiteand watercolor on paper.', 'Print'),
            ('Artwork', 'Original graphite, pastel, and watercolor on paperwork. A separate etching is offered.', 'Etching'),
            ('Artwork', 'Original graphite, pastel, and watercolor study. An etching is also offered.', 'Etching'),
        ):
            with self.subTest(title=title, description=description):
                self.assertEqual(self.medium(title, description), expected)

    def test_plural_processes_in_titles_or_explicit_medium_declarations_use_singular_labels(self):
        names = ("Etching", "Engraving", "Lithograph", "Linocut", "Screenprint", "Serigraph",
                 "Woodcut", "Woodblock", "Aquatint", "Mezzotint", "Monotype", "Giclee", "Giclée")
        for name in names:
            for title, description in ((f"Pair of {name}s", ""), ("Two works", f"Medium: {name}s. Signed.")):
                with self.subTest(title=title, description=description):
                    self.assertEqual(self.medium(title, description), name)

    def test_plural_words_in_biographies_and_edition_references_do_not_supply_a_medium(self):
        for description in ("The artist is known for etchings and lithographs.",
                            "Biography: the artist produced etchings.",
                            "Published in Editions and Multiples.",
                            "Charcoal on paper. Medium: charcoal. Biography: etchings.",
                            "Condition: Medium: Etchings."):
            with self.subTest(description=description):
                self.assertEqual(self.medium(description=description), "Print")

    def test_plural_terms_require_whole_words(self):
        for title in ("Reetchings", "Etchingsque", "Lithographss", "Screenprintsman"):
            with self.subTest(title=title):
                self.assertEqual(self.medium(title), "Print")

    def test_pastel_requires_an_explicit_medium_on_support_in_primary_lot_text(self):
        for support in ("paper", "board", "cardboard", "canvas", "vellum"):
            with self.subTest(support=support):
                self.assertEqual(self.medium(description=f"Untitled, pastel on {support}, signed."), "Pastel")
        self.assertEqual(self.medium("Pastel on paper, Landscape"), "Pastel")
        for description in ("A landscape in pastel colors on paper.", "Pastel palette, signed.",
                            "Keywords: pastel on paper", "Biography: worked in pastel on paper.",
                            "About the artist: known for pastel on paper.", "Condition: pastel on paper.",
                            "Provenance: a collection of pastel on paper works.", "Pastel on paperboard"):
            with self.subTest(description=description):
                self.assertEqual(self.medium(description=description), "Print")

    def test_existing_singular_matching_and_fallback_keep_their_precedence(self):
        for title, description, expected in (
            ("Color lithograph", "pastel on paper", "Lithograph"),
            ("Print", "Medium: Etchings.", "Print"),
            ("Pair of etchings", "A lithograph is also included.", "Lithograph"),
            ("Artwork", "Mixografia in colors on wove paper", "Mixografia"),
            ("Artwork", "Oil on canvas", "Print"),
            ("Artwork", "", "Print"),
        ):
            with self.subTest(title=title, description=description):
                self.assertEqual(self.medium(title, description), expected)
        # Extraction's extra vocabulary must not expand the print scope check.
        for text in ("pastel on paper", "etchings", "lithographs"):
            self.assertIsNone(self.adapter._print_terms.search(text))
