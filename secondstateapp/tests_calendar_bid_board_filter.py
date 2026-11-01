from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import AuctionBidBoardAnalysis
from .tests_calendar import watch_lot


class CalendarBidBoardFilterTests(TestCase):
    def test_catalog_exposes_every_saved_outcome_without_recalculating(self):
        self.client.force_login(get_user_model().objects.create_user("board-filter", is_staff=True))
        outcomes = [
            {"selected_case": "working", "detail": {"qualifies": True},
             "shortlist": [{"case_key": "working", "bid": "500.00"}]},
            {"selected_case": "working", "detail": {"qualifies": False},
             "shortlist": [{"case_key": "working", "bid": None}]},
            {"selected_case": "working", "detail": None, "empty_reason": "Resale assumption unavailable"},
        ]
        saved_ids = []
        for index, analysis in enumerate(outcomes):
            lot = watch_lot(source_lot_id=f"board-outcome-{index}")
            AuctionBidBoardAnalysis.objects.create(lot=lot, analysis=analysis)
            saved_ids.append(lot.pk)
        unsaved = watch_lot(source_lot_id="no-saved-board")
        before = list(AuctionBidBoardAnalysis.objects.values("pk", "analysis", "updated_at"))
        with patch("secondstateapp.calendar_views.LiveArtClient", side_effect=AssertionError("No provider query")):
            response = self.client.get(reverse("auction_calendar"), {
                "month": "2026-07", "day": "2026-07-25", "view": "catalog", "filter": "bidboards",
            })
        self.assertEqual(response.status_code, 200)
        lots = {lot["id"]: lot for lot in response.context["calendar_data"]["2026-07-25"]}
        self.assertEqual({pk for pk, lot in lots.items() if lot["saved_bid_board"]}, set(saved_ids))
        self.assertEqual([lots[pk]["saved_bid_board"]["qualifies"] for pk in saved_ids], [True, False, None])
        self.assertIsNone(lots[unsaved.pk]["saved_bid_board"])
        self.assertTrue(all(lots[pk]["saved_bid_board_url"] for pk in saved_ids))
        self.assertEqual(list(AuctionBidBoardAnalysis.objects.values("pk", "analysis", "updated_at")), before)
