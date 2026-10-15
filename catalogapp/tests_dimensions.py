import unittest
from decimal import Decimal

from secondstate.artwork_dimensions import format_catalog_dimensions, normalize_dimensions


class CatalogDimensionTests(unittest.TestCase):
    def test_preserves_benton_decimals_and_removes_redundant_zeroes(self):
        self.assertEqual(format_catalog_dimensions(11.5, 14.75), ('11.5" x 14.75"', ""))
        self.assertEqual(format_catalog_dimensions("12.000", "9.0"), ('12" x 9"', ""))

    def test_rounds_excel_conversion_noise_without_fraction_snapping(self):
        self.assertEqual(
            format_catalog_dimensions(35.8267716535433, 24.015748031496063),
            ('35.83" x 24.02"', ""),
        )
        self.assertEqual(format_catalog_dimensions(Decimal("1.005"), "14.999"), ('1.01" x 15"', ""))

    def test_missing_either_dimension_does_not_publish_nan_or_partial_size(self):
        for missing in (None, float("nan"), Decimal("NaN"), "", "  ", "NaN", "<NA>", "n/a"):
            with self.subTest(missing=repr(missing)):
                self.assertEqual(format_catalog_dimensions(missing, 10), ("", ""))
                self.assertEqual(format_catalog_dimensions(10, missing), ("", ""))
                self.assertEqual(normalize_dimensions(missing), "")

    def test_sheet_prefix_on_either_cell_routes_dimensions(self):
        self.assertEqual(format_catalog_dimensions("S11.5", "S 14.75"), ("", '11.5" x 14.75"'))
        self.assertEqual(format_catalog_dimensions("11.5", "s14.75"), ("", '11.5" x 14.75"'))

    def test_fractions_in_catalog_cells_are_decimal_inches(self):
        self.assertEqual(format_catalog_dimensions("11 1/2", "14-3/4"), ('11.5" x 14.75"', ""))
        self.assertEqual(format_catalog_dimensions("11½", "14¾″"), ('11.5" x 14.75"', ""))

    def test_metric_catalog_cells_convert_and_share_explicit_suffix(self):
        self.assertEqual(format_catalog_dimensions("61", "91 cm"), ('24.02" x 35.83"', ""))
        self.assertEqual(format_catalog_dimensions("S 254mm", "508 millimetres"), ("", '10" x 20"'))

    def test_unrecognized_catalog_cell_text_is_not_rewritten_or_reunitized(self):
        self.assertEqual(format_catalog_dimensions("Sight 11.5", "14.75"), ("Sight 11.5 x 14.75", ""))


class ExistingDimensionTests(unittest.TestCase):
    def test_normalizes_supported_pair_separators_and_inch_marks(self):
        for value in ('11.5" x 14.750"', "11.5 × 14.75 inches", "11.5″ ✕ 14.75″", "11.5 by 14.75 in."):
            with self.subTest(value=value):
                self.assertEqual(normalize_dimensions(value), '11.5" x 14.75"')

    def test_fraction_pairs_round_to_at_most_two_decimals(self):
        self.assertEqual(normalize_dimensions('11 1/2" x 14 3/4"'), '11.5" x 14.75"')
        self.assertEqual(normalize_dimensions("11½ × 14¾"), '11.5" x 14.75"')
        self.assertEqual(normalize_dimensions("1/3 x 2/3"), '0.33" x 0.67"')

    def test_metric_and_mixed_explicit_units(self):
        self.assertEqual(normalize_dimensions("61 x 91 cm"), '24.02" x 35.83"')
        self.assertEqual(normalize_dimensions("254 mm x 20 inches"), '10" x 20"')

    def test_does_not_guess_at_qualifiers_ranges_or_invalid_numbers(self):
        for value in (
            "Image: 11.5 x 14.75 in", '11.5" x 14.75" (sight)', "12 in diameter",
            "11–12 x 14", "11 x 14 x 2", "1/0 x 14", "NaN x 14", "inf x 14",
            "Signed lower right", "", "0.5 cm",
        ):
            with self.subTest(value=value):
                self.assertEqual(normalize_dimensions(value), value)

    def test_is_idempotent_for_clean_dimension_pairs(self):
        for value in ('11.5" x 14.75"', "61 x 91 cm", "1/3 x 2/3", "11½ × 14¾"):
            with self.subTest(value=value):
                once = normalize_dimensions(value)
                self.assertEqual(normalize_dimensions(once), once)


if __name__ == "__main__":
    unittest.main()
