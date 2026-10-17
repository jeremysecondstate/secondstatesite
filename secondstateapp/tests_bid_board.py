import json
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from .bid_board import BidBoardError, BidLadder, build_board, cash_flow, ceiling, detail_for, normalize_assumptions
from .models import AuctionBidBoardAnalysis, AuctionWatchLot, LiveArtResaleAnalysis


class BidBoardCalculationTests(SimpleTestCase):
    def assumptions(self, **values):
        return normalize_assumptions({"starting_hammer": "1000", "buyer_premium_pct": "0", "acquisition_costs": "0", "minimum_profit": "0", "minimum_return_pct": "0", **values})

    def test_explicit_tax_and_selling_cost_cash_flows(self):
        assumptions = self.assumptions(buyer_premium_pct="25", purchase_tax_pct="8.5", purchase_tax_basis="hammer_premium", acquisition_costs="200", selling_commission_pct="10", selling_costs="50", fixed_increment="50")
        detail = detail_for(Decimal(1000), Decimal(2500), assumptions, BidLadder(assumptions))
        self.assertEqual(detail["buyer_premium"], "250.00")
        self.assertEqual(detail["purchase_tax_basis_amount"], "1250.00")
        self.assertEqual(detail["purchase_tax"], "106.25")
        self.assertEqual(detail["all_in_acquisition"], "1556.25")
        self.assertEqual(detail["net_resale_proceeds"], "2200.00")
        self.assertEqual(detail["net_profit"], "643.75")
        self.assertEqual(detail["return_on_cost_pct"], "41.37")
        self.assertEqual(detail["profit_on_gross_pct"], "25.75")
        self.assertEqual(detail["one_more_bid"]["additional_all_in_cost"], "67.81")
        self.assertEqual(detail["one_more_bid"]["profit_reduction"], "67.81")
        self.assertTrue(detail["profit_500"])
        self.assertFalse(detail["profit_1000"])

    def test_tax_bases_are_distinct(self):
        taxes = []
        for basis in ("hammer", "hammer_premium", "acquisition"):
            assumptions = self.assumptions(buyer_premium_pct="25", acquisition_costs="200", purchase_tax_pct="10", purchase_tax_basis=basis)
            taxes.append(cash_flow(Decimal(1000), Decimal(2000), assumptions)["purchase_tax"])
        self.assertEqual(taxes, [Decimal(100), Decimal(125), Decimal(145)])

    def test_opening_includes_start_but_current_begins_with_next_bid(self):
        opening = BidLadder(self.assumptions(starting_hammer="975", fixed_increment="100"))
        current = BidLadder(self.assumptions(starting_hammer="975", starting_basis="current", fixed_increment="100"))
        self.assertEqual(opening.at(0), Decimal(975))
        self.assertEqual(current.at(0), Decimal(1075))
        self.assertEqual(current.at(1), Decimal(1175))

    def test_tier_boundary_and_one_more_bid(self):
        assumptions = self.assumptions(starting_hammer="975", increment_mode="tiers", tiers=[{"up_to": "1000", "increment": "50"}, {"up_to": None, "increment": "100"}])
        ladder = BidLadder(assumptions)
        self.assertEqual([ladder.at(i) for i in range(4)], list(map(Decimal, (975, 1000, 1100, 1200))))
        self.assertEqual(ceiling(ladder, Decimal("1099.99"), assumptions), Decimal(1000))
        self.assertEqual(detail_for(Decimal(975), Decimal(1500), assumptions, ladder)["one_more_bid"]["hammer_increment"], "25.00")
        self.assertEqual(detail_for(Decimal(1000), Decimal(1500), assumptions, ladder)["one_more_bid"]["hammer_increment"], "100.00")

    def test_ceiling_satisfies_both_and_next_bid_does_not(self):
        for resale in ("2000", "2499.99", "3000", "3999.99"):
            for target, minimum_return in (("500", "20"), ("1000", "0"), ("0", "40")):
                assumptions = self.assumptions(buyer_premium_pct="25", acquisition_costs="200", minimum_profit=target, minimum_return_pct=minimum_return)
                ladder = BidLadder(assumptions)
                bid = ceiling(ladder, Decimal(resale), assumptions)
                if bid is None:
                    self.assertFalse(cash_flow(ladder.at(0), Decimal(resale), assumptions)["qualifies"])
                else:
                    self.assertTrue(cash_flow(bid, Decimal(resale), assumptions)["qualifies"])
                    self.assertFalse(cash_flow(ladder.next(bid), Decimal(resale), assumptions)["qualifies"])

    def test_rounded_return_display_does_not_make_bid_qualify(self):
        assumptions = self.assumptions(starting_hammer="300.01", minimum_return_pct="20")
        detail = detail_for(Decimal("300.01"), Decimal("360.01"), assumptions, BidLadder(assumptions))
        self.assertEqual(detail["return_on_cost_pct"], "20.00")
        self.assertFalse(detail["meets_return"])
        self.assertFalse(detail["qualifies"])

    def test_break_even_is_lowest_cent_even_at_high_commission(self):
        for commission in ("0", "10", "33.33", "99.99"):
            assumptions = self.assumptions(selling_commission_pct=commission, selling_costs="27.31", buyer_premium_pct="25", purchase_tax_pct="8.88")
            result = detail_for(Decimal(1000), Decimal(3000), assumptions, BidLadder(assumptions))
            gross = Decimal(result["break_even_resale"])
            self.assertGreaterEqual(cash_flow(Decimal(1000), gross, assumptions)["net_profit"], 0)
            self.assertLess(cash_flow(Decimal(1000), gross - Decimal("0.01"), assumptions)["net_profit"], 0)

    def test_eight_rows_pagination_exposes_losses_and_conservative_downside(self):
        assumptions = self.assumptions(minimum_profit="500", minimum_return_pct="20", resale_overrides={"conservative": "2000", "working": "3000", "optimistic": "4000"})
        first = build_board(assumptions)
        self.assertEqual(len(first["rows"]), 8)
        self.assertTrue(first["pagination"]["has_next"])
        last = build_board(assumptions, page=first["pagination"]["page_count"] - 1)
        self.assertTrue(any(Decimal(cell["net_profit"]) < 0 for row in last["rows"] for cell in row["cells"]))
        optimistic = first["shortlist"][2]
        self.assertLess(Decimal(optimistic["conservative_downside"]["net_profit"]), 0)
        self.assertEqual(optimistic["detail"]["bid"], optimistic["conservative_downside"]["bid"])

    def test_missing_evidence_and_missing_start_do_not_use_demo_values(self):
        result = build_board({})
        self.assertFalse(result["rows"])
        self.assertTrue(all(case["resale_hammer"] is None for case in result["cases"]))
        with_start = build_board(self.assumptions())
        self.assertTrue(all(item["bid"] is None for item in with_start["shortlist"]))
        self.assertIsNone(with_start["detail"])

    def test_invalid_inputs_rejected(self):
        for values in ({"fixed_increment": "0"}, {"selling_commission_pct": "100"}, {"minimum_profit": "NaN"}, {"acquisition_costs": "1.001"}, {"starting_hammer": True}, {"purchase_tax_basis": "whatever"}, {"tiers": [{"up_to": "1000", "increment": "100"}]}):
            with self.subTest(values=values), self.assertRaises(BidBoardError):
                normalize_assumptions(values)

    def test_selection_focus_and_custom_profit_target(self):
        result = build_board(self.assumptions(minimum_profit="650", resale_overrides={"working": "5000"}), selected_bid="4100", focus_selected=True)
        self.assertEqual(result["selected_bid_index"], 31)
        self.assertEqual(result["pagination"]["page"], 3)
        self.assertIn("4100.00", [row["bid"] for row in result["rows"]])
        self.assertTrue(all("all_in_acquisition" in row for row in result["rows"]))
        self.assertIn("650.00", [target["minimum_profit"] for target in result["profit_targets"]])


class BidBoardAPITests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user("board-staff", is_staff=True)
        self.client.force_login(self.staff)
        self.lot = AuctionWatchLot.objects.create(source="test", source_lot_id="bid-board", artist="Artist", title="Print", currency="USD", current_bid="1000", bid_count=1)
        self.url = reverse("auction_lot_bid_board", args=(self.lot.pk,))

    def post(self, **payload):
        return self.client.post(self.url, json.dumps(payload), content_type="application/json")

    def candidate(self, identifier="501", **values):
        return {"id": identifier, "provider": "LiveArt", "category_id": "2", "credible": True, "status": "sold", "hammer_usd": "4000.00", "artist": "Artist", "title": "Print", **values}

    def save_research(self, candidates=None):
        session = self.client.session
        session[f"liveart_research_{self.lot.pk}"] = {"research_id": "session-proof", "candidates": candidates or [self.candidate()], "selected_ids": ["501"], "retrieved_at": timezone.now().isoformat(), "data_units_spent": 1.5, "search_category": {"id": "2", "label": "Prints & Multiples"}}
        session.save()

    def zar_conversion(self):
        return {"source_currency": "ZAR", "source_amount": "19000.00", "usd_amount": "1064.00", "rate": "0.056", "rate_date": "2026-10-16", "provider": "Frankfurter"}

    def use_zar_lot(self, bid_count=0):
        self.lot.currency = "ZAR"
        self.lot.current_bid = Decimal("19000")
        self.lot.bid_count = bid_count
        self.lot.save(update_fields=["currency", "current_bid", "bid_count"])

    def test_staff_and_csrf_required(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)
        ordinary = get_user_model().objects.create_user("ordinary")
        self.client.force_login(ordinary)
        self.assertEqual(self.client.get(self.url).status_code, 302)
        guarded = Client(enforce_csrf_checks=True)
        guarded.force_login(self.staff)
        self.assertEqual(guarded.post(self.url, "{}", content_type="application/json").status_code, 403)

    @patch("secondstateapp.calendar_views._research_liveart_lot")
    def test_get_and_preview_do_not_search_or_persist(self, paid_lookup):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["analysis"]["assumptions"]["starting_hammer"], "1000.00")
        self.assertEqual(response.json()["analysis"]["rows"][0]["bid"], "1100.00")
        preview = self.post(assumptions={"resale_overrides": {"working": "3000"}})
        self.assertEqual(preview.status_code, 200)
        self.assertFalse(AuctionBidBoardAnalysis.objects.exists())
        self.assertFalse(LiveArtResaleAnalysis.objects.exists())
        paid_lookup.assert_not_called()

    def test_save_reloads_assumptions_selections_and_trusted_provenance(self):
        self.save_research()
        response = self.post(action="save", research_id="session-proof", selected_ids=["501"], assumptions={"minimum_profit": "650", "purchase_tax_pct": "8.5"}, selected_case="optimistic")
        self.assertEqual(response.status_code, 200, response.content)
        board = response.json()["analysis"]
        self.assertTrue(board["saved"])
        self.assertEqual(board["source_summary"]["combined_comp_count"], 1)
        self.assertEqual(board["cases"][1]["resale_hammer"], "4000.00")
        self.assertEqual(LiveArtResaleAnalysis.objects.get(lot=self.lot).selected_ids, ["501"])
        stored = AuctionBidBoardAnalysis.objects.get(lot=self.lot)
        self.assertEqual(stored.evidence_snapshot["selected_records"][0]["hammer_usd"], "4000.00")
        loaded = self.client.get(self.url).json()["analysis"]
        self.assertEqual(loaded["assumptions"]["minimum_profit"], "650.00")
        self.assertEqual(loaded["selected_case"], "optimistic")
        self.assertEqual(loaded["selected_ids"], ["501"])

    def test_updated_workbench_selection_is_used_instead_of_stale_board_snapshot(self):
        self.save_research()
        self.assertEqual(self.post(action="save", research_id="session-proof", selected_ids=["501"]).status_code, 200)
        saved = LiveArtResaleAnalysis.objects.get(lot=self.lot)
        saved.selected_ids = []
        saved.save(update_fields=["selected_ids"])
        loaded = self.client.get(self.url).json()["analysis"]
        self.assertEqual(loaded["selected_ids"], [])
        self.assertEqual(loaded["source_summary"]["combined_comp_count"], 0)
        self.assertTrue(loaded["evidence_changed_since_save"])

    def test_forged_comp_values_and_stale_session_rejected(self):
        self.save_research()
        forged = self.post(research_id="session-proof", selected_ids=["forged"], candidates=[self.candidate("forged", hammer_usd="999999")])
        self.assertEqual(forged.status_code, 400)
        stale = self.post(research_id="replaced", selected_ids=["501"])
        self.assertEqual(stale.status_code, 409)
        changed_value = self.post(research_id="session-proof", selected_ids=["501"], candidates=[self.candidate(hammer_usd="999999")])
        self.assertEqual(changed_value.json()["analysis"]["cases"][1]["resale_hammer"], "4000.00")

    def test_equivalent_count_evidence_change_is_identified(self):
        self.save_research([self.candidate(), self.candidate("502", hammer_usd="6000.00")])
        self.assertEqual(self.post(action="save", research_id="session-proof", selected_ids=["501"]).status_code, 200)
        self.assertFalse(self.client.get(self.url).json()["analysis"]["evidence_changed_since_save"])
        saved = LiveArtResaleAnalysis.objects.get(lot=self.lot)
        saved.selected_ids = ["502"]
        saved.save(update_fields=["selected_ids"])
        result = self.client.get(self.url).json()["analysis"]
        self.assertTrue(result["evidence_changed_since_save"])
        self.assertEqual(result["cases"][1]["resale_hammer"], "6000.00")

    def test_category_eligibility_deduplication_and_selection_limit(self):
        self.save_research([self.candidate(), self.candidate(), self.candidate("502", category_id="1"), self.candidate("503", credible=False, artist="Other Artist")])
        duplicate = self.post(research_id="session-proof", selected_ids=["501", "501"])
        self.assertEqual(duplicate.json()["analysis"]["source_summary"]["combined_comp_count"], 1)
        self.assertEqual(self.post(research_id="session-proof", selected_ids=["502"]).status_code, 400)
        self.assertEqual(self.post(research_id="session-proof", selected_ids=["503"]).status_code, 400)
        self.assertEqual(self.post(research_id="session-proof", selected_ids=[str(i) for i in range(26)]).status_code, 400)

    def test_manual_review_sale_from_older_research_can_enter_bid_board(self):
        self.save_research([self.candidate(
            "503", credible=False, manual_selectable=False, title="Older print title",
            exclusion_reasons=["Related work has no matching category or specific medium"],
        )])
        response = self.post(action="save", research_id="session-proof", selected_ids=["503"])
        self.assertEqual(response.status_code, 200, response.content)
        board = response.json()["analysis"]
        self.assertEqual(board["selected_ids"], ["503"])
        self.assertEqual(board["cases"][1]["resale_hammer"], "4000.00")
        stored = LiveArtResaleAnalysis.objects.get(lot=self.lot)
        self.assertEqual(stored.selected_ids, ["503"])
        self.assertTrue(stored.candidates[0]["manual_selectable"])

    @patch("secondstateapp.bid_board_views.convert_to_usd")
    def test_non_usd_source_hammer_is_converted_with_opening_or_current_basis(self, convert):
        convert.return_value = self.zar_conversion()
        for bid_count, basis, first_bid in ((0, "opening", "1064.00"), (2, "current", "1164.00"), (None, "current", "1164.00")):
            with self.subTest(bid_count=bid_count):
                self.use_zar_lot(bid_count)
                result = self.client.get(self.url).json()["analysis"]
                self.assertEqual(result["assumptions"]["starting_hammer"], "1064.00")
                self.assertEqual(result["assumptions"]["starting_basis"], basis)
                self.assertEqual(result["rows"][0]["bid"], first_bid)
                self.assertEqual(result["source_current_hammer"], "1064.00")
                self.assertEqual(result["source_hammer_conversion"], self.zar_conversion())
                notices = " ".join(result["notices"])
                for attribution in ("ZAR", "Frankfurter", "2026-10-16"):
                    self.assertIn(attribution, notices)

    @patch("secondstateapp.currency.requests.get")
    def test_usd_source_hammer_does_not_fetch_rate(self, rate_request):
        result = self.client.get(self.url).json()["analysis"]
        self.assertEqual(result["assumptions"]["starting_hammer"], "1000.00")
        self.assertEqual(result["source_current_hammer"], "1000.00")
        self.assertNotIn("source_hammer_conversion", result)
        rate_request.assert_not_called()

    @patch("secondstateapp.bid_board_views.convert_to_usd", return_value=None)
    def test_unavailable_non_usd_conversion_leaves_new_board_empty(self, convert):
        self.lot.currency = "GBP"
        self.lot.save(update_fields=["currency"])
        result = self.client.get(self.url).json()["analysis"]
        self.assertIsNone(result["assumptions"]["starting_hammer"])
        self.assertFalse(result["rows"])
        self.assertNotIn("source_current_hammer", result)
        self.assertNotIn("source_hammer_conversion", result)
        self.assertTrue(any("USD conversion is unavailable" in notice for notice in result["notices"]))
        convert.assert_called_once()

    @patch("secondstateapp.currency.requests.get")
    def test_missing_or_zero_source_bid_does_not_convert_estimate(self, rate_request):
        self.use_zar_lot()
        self.lot.estimate_low = Decimal("20000")
        for current_bid in (None, Decimal("0")):
            with self.subTest(current_bid=current_bid):
                self.lot.current_bid = current_bid
                self.lot.save(update_fields=["current_bid", "estimate_low"])
                result = self.client.get(self.url).json()["analysis"]
                self.assertIsNone(result["assumptions"]["starting_hammer"])
                self.assertEqual(result["rows"], [])
                self.assertNotIn("source_current_hammer", result)
                self.assertNotIn("source_hammer_conversion", result)
        rate_request.assert_not_called()

    @patch("secondstateapp.bid_board_views.convert_to_usd")
    def test_converted_source_preserves_saved_and_explicit_starting_hammers(self, convert):
        self.use_zar_lot()
        convert.return_value = self.zar_conversion()
        response = self.post(action="save", assumptions={"starting_hammer": "900"})
        self.assertEqual(response.status_code, 200, response.content)
        loaded = self.client.get(self.url).json()["analysis"]
        self.assertEqual(loaded["assumptions"]["starting_hammer"], "900.00")
        self.assertEqual(loaded["source_current_hammer"], "1064.00")
        self.assertTrue(any("latest synced source" in notice for notice in loaded["notices"]))
        for supplied, expected in (("1500", "1500.00"), (None, None)):
            with self.subTest(supplied=supplied):
                result = self.post(assumptions={"starting_hammer": supplied}).json()["analysis"]
                self.assertEqual(result["assumptions"]["starting_hammer"], expected)
        self.assertEqual(AuctionBidBoardAnalysis.objects.get(lot=self.lot).assumptions["starting_hammer"], "900.00")

    @patch("secondstateapp.bid_board_views.convert_to_usd")
    def test_legacy_empty_start_is_backfilled_from_converted_source_on_get(self, convert):
        convert.return_value = None
        self.lot.current_bid = None
        self.lot.save(update_fields=["current_bid"])
        self.assertEqual(self.post(action="save").status_code, 200)
        stored = AuctionBidBoardAnalysis.objects.get(lot=self.lot)
        stored.analysis.pop("usd_normalization_version", None)
        stored.save(update_fields=["analysis"])
        self.use_zar_lot()
        convert.return_value = self.zar_conversion()
        result = self.client.get(self.url).json()["analysis"]
        self.assertEqual(result["assumptions"]["starting_hammer"], "1064.00")
        self.assertEqual(result["assumptions"]["starting_basis"], "opening")
        self.assertEqual(result["rows"][0]["bid"], "1064.00")
        self.assertIsNone(AuctionBidBoardAnalysis.objects.get(lot=self.lot).assumptions["starting_hammer"])

    def test_newly_saved_explicit_empty_usd_start_stays_empty(self):
        response = self.post(action="save", assumptions={"starting_hammer": None})
        self.assertEqual(response.status_code, 200, response.content)
        result = self.client.get(self.url).json()["analysis"]
        self.assertIsNone(result["assumptions"]["starting_hammer"])
        self.assertEqual(result["rows"], [])
        self.assertEqual(result["source_current_hammer"], "1000.00")

    @patch("secondstateapp.bid_board_views.convert_to_usd")
    def test_newly_saved_explicit_empty_non_usd_start_stays_empty(self, convert):
        self.use_zar_lot()
        convert.return_value = self.zar_conversion()
        response = self.post(action="save", assumptions={"starting_hammer": None})
        self.assertEqual(response.status_code, 200, response.content)
        result = self.client.get(self.url).json()["analysis"]
        self.assertIsNone(result["assumptions"]["starting_hammer"])
        self.assertEqual(result["rows"], [])
        self.assertEqual(result["source_current_hammer"], "1064.00")

    def test_legacy_saved_empty_usd_start_stays_empty(self):
        response = self.post(action="save", assumptions={"starting_hammer": None})
        self.assertEqual(response.status_code, 200, response.content)
        stored = AuctionBidBoardAnalysis.objects.get(lot=self.lot)
        stored.analysis.pop("usd_normalization_version", None)
        stored.save(update_fields=["analysis"])
        result = self.client.get(self.url).json()["analysis"]
        self.assertIsNone(result["assumptions"]["starting_hammer"])
        self.assertEqual(result["rows"], [])
        self.assertEqual(result["source_current_hammer"], "1000.00")

    @patch("secondstateapp.bid_board_views.convert_to_usd")
    def test_saved_snapshot_retains_conversion_without_refreshing_rate(self, convert):
        self.use_zar_lot()
        convert.return_value = self.zar_conversion()
        response = self.post(action="save")
        self.assertEqual(response.status_code, 200, response.content)
        stored = AuctionBidBoardAnalysis.objects.get(lot=self.lot)
        self.assertEqual(stored.analysis["source_hammer_conversion"], self.zar_conversion())
        convert.reset_mock()
        convert.return_value = None
        saved_url = reverse("auction_lot_saved_bid_board", args=(self.lot.pk,))
        snapshot = self.client.get(saved_url).json()["board"]
        self.assertEqual(snapshot["analysis"]["source_hammer_conversion"], self.zar_conversion())
        self.assertEqual(snapshot["assumptions"]["starting_hammer"], "1064.00")
        convert.assert_not_called()

    def test_euro_lot_retains_resale_cases_until_usd_start_is_entered(self):
        self.lot.currency = "EUR"
        self.lot.current_bid = None
        self.lot.save(update_fields=["currency", "current_bid"])
        candidates = [self.candidate(str(501 + index), hammer_usd=str(2000 + 100 * index)) for index in range(12)]
        self.save_research(candidates)
        evidence = {"research_id": "session-proof", "selected_ids": [item["id"] for item in candidates]}
        result = self.post(**evidence).json()["analysis"]
        self.assertEqual(result["source_summary"]["combined_comp_count"], 12)
        self.assertEqual([case["resale_hammer"] for case in result["cases"]], ["1600.00", "2550.00", "3410.00"])
        self.assertTrue(all(case["origin"] == "evidence" for case in result["cases"]))
        self.assertIsNone(result["assumptions"]["starting_hammer"])
        self.assertEqual(result["rows"], [])
        self.assertEqual(result["shortlist"], [])

        preview = self.post(**evidence, assumptions={"starting_hammer": "1000"}).json()["analysis"]
        self.assertEqual(preview["rows"][0]["bid"], "1000.00")
        self.assertEqual(len(preview["rows"]), 8)
        self.assertEqual(preview["cases"], result["cases"])
        cleared = self.post(**evidence, assumptions={"starting_hammer": None}).json()["analysis"]
        self.assertEqual(cleared["rows"], [])
        self.assertEqual(cleared["cases"], result["cases"])
        self.assertFalse(AuctionBidBoardAnalysis.objects.exists())

    def test_new_source_bid_warns_without_overwriting_saved_assumptions(self):
        response = self.post(action="save", assumptions={"starting_hammer": "900"})
        result = response.json()["analysis"]
        self.assertEqual(result["assumptions"]["starting_hammer"], "900.00")
        self.assertEqual(result["source_current_hammer"], "1000.00")
        self.assertTrue(any("latest synced source" in notice for notice in result["notices"]))
        self.lot.currency = "GBP"
        self.lot.save(update_fields=["currency"])
        with patch("secondstateapp.bid_board_views.convert_to_usd", return_value=None):
            result = self.client.get(self.url).json()["analysis"]
        self.assertEqual(result["assumptions"]["starting_hammer"], "900.00")
        self.assertNotIn("source_current_hammer", result)
