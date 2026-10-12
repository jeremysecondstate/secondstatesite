"""Unit tests for matching and scenario math without LiveArt network access."""

from datetime import datetime, timezone
from types import SimpleNamespace

from django.test import SimpleTestCase, override_settings

from secondstateapp.liveart_resale import build_scenarios, normalize_candidate, subject_matches


def lot(
    lot_id,
    *,
    status="sold",
    hammer=1000,
    premium=1250,
    artist="Pablo Picasso",
    title="Test Print",
    materials="screenprint on paper",
    markings="Signed and numbered 13/50",
    notes="Condition: excellent",
    sale_date="2026-10-12T18:00:00-04:00",
    house="Sotheby's",
    lot_num="024A",
    artwork_id=100,
):
    return {
        "id": lot_id,
        "lot_num": lot_num,
        "status": status,
        "auction_house_name": house,
        "sale_id": 88,
        "artwork_id": artwork_id,
        "lot_url": f"https://auction.example/lots/{lot_id}",
        "catalog_notes": notes,
        "price": {"currency": "GBP", "hammer": 800, "hammer_usd": hammer, "premium_usd": premium},
        "sale": {"id": 88, "start_datetime": sale_date},
        "artwork": {
            "id": artwork_id,
            "name": title,
            "artist_id": 7,
            "artist": {"id": 7, "name": artist},
            "materials": materials,
            "markings": markings,
            "measurements_height_cm": 30,
            "measurements_width_cm": 40,
        },
    }


def artwork(artwork_id, *, artist="Pablo Picasso", title="Test Print", materials="screenprint on paper"):
    return {
        "id": artwork_id,
        "artist_id": 7,
        "artist": {"id": 7, "name": artist},
        "description": {
            "name": title,
            "artist_id": 7,
            "artist": {"id": 7, "name": artist},
            "materials": materials,
            "markings": "Signed and numbered 12/50",
            "measurements_height_cm": 30,
            "measurements_width_cm": 40,
        },
    }


@override_settings(CALENDAR_TIME_ZONE="America/New_York")
class LiveArtResaleTests(SimpleTestCase):
    def setUp(self):
        self.calendar_lot = SimpleNamespace(
            auction_house="Sotheby's",
            event_at=datetime(2026, 10, 12, 22, 0, tzinfo=timezone.utc),
            lot_number="24A",
            artist="Picasso, Pablo",
            title="Test Print",
            medium="screenprint, signed and numbered 12/50; 30 x 40 cm",
        )
        self.subject = lot(10, status="upcoming", hammer=None, markings="Signed and numbered 12/50")

    def test_subject_matches_artwork_across_houses_dates_and_lot_numbers(self):
        options = subject_matches(
            self.calendar_lot,
            [
                artwork(100),
                artwork(101, artist="Henri Matisse"),
                artwork(102, title="Another Print"),
            ],
        )
        self.assertEqual(options[0]["id"], "100")
        self.assertTrue(options[0]["verified"])
        self.assertTrue(options[0]["matches"]["artist"])
        self.assertTrue(options[0]["matches"]["title"])
        self.assertFalse(options[1]["verified"])
        self.assertFalse(options[2]["verified"])

    def test_subject_does_not_require_calendar_auction_metadata(self):
        target = SimpleNamespace(
            **{
                **self.calendar_lot.__dict__,
                "auction_house": "",
                "event_at": None,
                "lot_number": "",
            }
        )
        option = subject_matches(target, [artwork(100)])[0]
        self.assertTrue(option["verified"])
        self.assertEqual(option["artist"], "Pablo Picasso")
        self.assertEqual(option["title"], "Test Print")

    def test_print_attributes_and_verified_hammer_are_visible(self):
        candidate = normalize_candidate(lot(21), self.subject, self.calendar_lot)
        self.assertTrue(candidate["credible"])
        self.assertTrue(candidate["selected"])
        self.assertEqual(candidate["hammer_usd"], "1000.00")
        self.assertEqual(candidate["original_hammer"], "800")
        self.assertEqual(candidate["original_currency"], "GBP")
        self.assertEqual(candidate["differences"]["edition"]["status"], "different")
        self.assertEqual(candidate["differences"]["edition"]["subject"], "12/50")
        self.assertEqual(candidate["differences"]["size"]["status"], "same")
        self.assertEqual(candidate["provider_url"], "https://api.liveart.ai/v1/lots?id=21&limit=1")
        self.assertEqual(candidate["provider_id"], "21")

    def test_mismatched_medium_is_reviewable_but_unselected(self):
        candidate = normalize_candidate(lot(22, materials="oil on canvas"), self.subject, self.calendar_lot)
        self.assertTrue(candidate["credible"])
        self.assertFalse(candidate["selected"])
        self.assertEqual(candidate["differences"]["medium"]["status"], "different")
        _, scenarios = build_scenarios([candidate], [candidate["id"]], {})
        self.assertEqual(scenarios[1]["resale_hammer"], "1000.00")

    def test_related_work_with_different_title_is_reviewable_not_auto_selected(self):
        candidate = normalize_candidate(lot(28, title="Test Portrait", artwork_id=101), self.subject, self.calendar_lot)
        self.assertTrue(candidate["credible"])
        self.assertEqual(candidate["match_type"], "related_work")
        self.assertFalse(candidate["selected"])
        self.assertIn("Title differs", candidate["exclusion_reasons"])

    def test_same_artwork_id_does_not_hide_print_differences(self):
        raw = lot(
            40,
            artwork_id=100,
            materials="oil on canvas",
            markings="Signed and numbered 4/500",
        )
        raw["artwork"]["measurements_height_cm"] = 80
        raw["artwork"]["measurements_width_cm"] = 100
        candidate = normalize_candidate(raw, self.subject, self.calendar_lot)
        self.assertEqual(candidate["match_type"], "exact_work")
        self.assertFalse(candidate["selected"])
        self.assertEqual(candidate["differences"]["medium"]["status"], "different")
        self.assertEqual(candidate["differences"]["edition"]["status"], "different")
        self.assertEqual(candidate["differences"]["size"]["status"], "different")

    def test_related_same_category_with_other_medium_needs_manual_review(self):
        subject = lot(41, status="upcoming", hammer=None)
        subject["artwork"]["category_id"] = 2
        raw = lot(42, artwork_id=101, title="Another Print", materials="etching")
        raw["artwork"]["category_id"] = 2
        candidate = normalize_candidate(raw, subject, self.calendar_lot)
        self.assertEqual(candidate["match_type"], "related_work")
        self.assertTrue(candidate["credible"])
        self.assertFalse(candidate["selected"])
        self.assertEqual(candidate["differences"]["medium"]["status"], "different")

    def test_generic_medium_does_not_auto_select_even_exact_artwork(self):
        subject = lot(43, status="upcoming", hammer=None, materials="prints")
        candidate = normalize_candidate(
            lot(44, artwork_id=100, materials="prints"), subject, self.calendar_lot
        )
        self.assertEqual(candidate["match_type"], "exact_work")
        self.assertTrue(candidate["credible"])
        self.assertFalse(candidate["selected"])
        self.assertIn("Specific medium differs or is not reported; review before using", candidate["exclusion_reasons"])

    def test_pencil_and_plate_signatures_are_distinct(self):
        subject = lot(30, status="upcoming", hammer=None, markings="Pencil signed and numbered 12/50")
        candidate = normalize_candidate(
            lot(31, markings="Signed in the plate; numbered 13/50"), subject, self.calendar_lot
        )
        self.assertEqual(candidate["differences"]["signature"]["subject"], "pencil signed")
        self.assertEqual(candidate["signature"], "plate signed")
        self.assertEqual(candidate["differences"]["signature"]["status"], "different")
        self.assertTrue(candidate["credible"])
        self.assertFalse(candidate["selected"])
        self.assertIn("Signature type differs", candidate["exclusion_reasons"])

    def test_explicit_signed_and_vague_signature_mentions_are_distinct(self):
        signed = normalize_candidate(lot(34, markings="Signed and numbered 13/50"), self.subject, self.calendar_lot)
        vague = normalize_candidate(lot(35, markings="Signature noted in catalogue"), self.subject, self.calendar_lot)
        self.assertEqual(signed["signature"], "signed (method unspecified)")
        self.assertEqual(vague["signature"], "signature mentioned; verify")

    def test_missing_or_future_date_is_not_default_selected(self):
        missing = normalize_candidate(lot(32, sale_date=""), self.subject, self.calendar_lot)
        future = normalize_candidate(lot(33, sale_date="2099-01-01T10:00:00Z"), self.subject, self.calendar_lot)
        self.assertTrue(missing["credible"])
        self.assertFalse(missing["selected"])
        self.assertIn("sale_date", missing["missing_data"])
        self.assertFalse(future["credible"])
        self.assertFalse(future["selected"])
        self.assertIn("Sale date is invalid or in the future", future["exclusion_reasons"])

    def test_null_hammer_and_premium_never_become_comp(self):
        candidate = normalize_candidate(lot(23, hammer=None, premium=3000), self.subject, self.calendar_lot)
        self.assertIsNone(candidate["hammer_usd"])
        self.assertFalse(candidate["credible"])
        _, scenarios = build_scenarios([candidate], [candidate["id"]], {})
        self.assertEqual(scenarios, [])

    def test_external_lot_url_is_restricted_to_http(self):
        raw = lot(29)
        raw["lot_url"] = "javascript:alert(1)"
        candidate = normalize_candidate(raw, self.subject, self.calendar_lot)
        self.assertIsNone(candidate["lot_url"])

    def test_wrong_artist_stays_out_even_when_selected(self):
        candidate = normalize_candidate(lot(24, artist="Henri Matisse"), self.subject, self.calendar_lot)
        self.assertFalse(candidate["credible"])
        _, scenarios = build_scenarios([candidate], [candidate["id"]], {})
        self.assertEqual(scenarios, [])

    def test_scenarios_use_selected_hammers_and_all_buying_costs(self):
        low = normalize_candidate(lot(25, hammer=1000), self.subject, self.calendar_lot)
        high = normalize_candidate(lot(26, hammer=2000), self.subject, self.calendar_lot)
        assumptions, scenarios = build_scenarios(
            [low, high],
            [low["id"], high["id"]],
            {
                "premium_min": 25,
                "premium_max": 25,
                "inbound_shipping": "100",
                "other_buying_costs": "50",
                "target_profit": "100",
            },
        )
        self.assertEqual(assumptions["other_buying_costs"], "50.00")
        self.assertEqual([scenario["resale_hammer"] for scenario in scenarios], ["800.00", "1500.00", "2200.00"])
        downside_row = scenarios[0]["bid_rows"][0]
        self.assertEqual(downside_row["break_even_max_bid"], "520.00")
        self.assertEqual(downside_row["target_profit_max_bid"], "440.00")
        self.assertIn("not guaranteed", scenarios[0]["estimate_notice"])

    def test_no_positive_bid_is_explicit(self):
        candidate = normalize_candidate(lot(27, hammer=100), self.subject, self.calendar_lot)
        _, scenarios = build_scenarios([candidate], [candidate["id"]], {})
        self.assertEqual(scenarios[0]["bid_rows"][0]["break_even_max_bid"], None)
        self.assertEqual(scenarios[0]["bid_rows"][0]["target_profit_max_bid"], None)
