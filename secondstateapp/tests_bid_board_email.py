from copy import deepcopy
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .auction_email import compose_auction_email
from .bid_board import build_board
from .models import AuctionBidBoardAnalysis, AuctionEmailBatch, AuctionEmailBatchItem, AuctionWatchLot


@override_settings(CALENDAR_TIME_ZONE="America/New_York", SECONDSTATE_PUBLIC_URL="https://secondstate.art")
class SavedBidBoardEmailTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user("board-email-staff", is_staff=True)
        self.client.force_login(self.staff)
        self.lot = AuctionWatchLot.objects.create(
            source="test", source_lot_id="saved-board-email", title="Fleurs dans un vase", artist="Pablo Picasso",
            currency="USD", current_bid="1000", bid_count=1,
            event_at=datetime(2026, 10, 15, 10, tzinfo=ZoneInfo("America/New_York")),
            artprice_url="https://www.artprice.com/artist/1/picasso/lots/pasts",
        )

    def saved_board(self, *, include=True, selected_bid="1800", **overrides):
        assumptions = {
            "starting_hammer": "1000", "starting_basis": "current", "buyer_premium_pct": "25",
            "acquisition_costs": "200", "minimum_profit": "500", "minimum_return_pct": "20",
            "resale_overrides": {"conservative": "800", "working": "3000", "optimistic": "7000"},
            **overrides,
        }
        board = build_board(assumptions, selected_bid=selected_bid)
        return AuctionBidBoardAnalysis.objects.create(
            lot=self.lot, assumptions=board["assumptions"], analysis=board,
            evidence_snapshot={"selected_records": [{"id": "saved-evidence", "hammer_usd": "3000.00"}]},
            include_in_email=include,
        )

    def test_missing_and_unchecked_boards_are_absent_from_both_email_parts(self):
        email = compose_auction_email([self.lot])
        self.assertNotIn("bid_board", email.lot_snapshots[self.lot.pk])
        self.assertNotIn("Saved Bid Board", email.text_body)
        self.assertNotIn("Saved Bid Board", email.html_body)
        self.saved_board(include=False)
        email = compose_auction_email([self.lot])
        self.assertNotIn("bid_board", email.lot_snapshots[self.lot.pk])
        self.assertNotIn("Saved Bid Board", email.text_body)
        self.assertNotIn("Saved Bid Board", email.html_body)

    @patch("secondstateapp.bid_board.build_board", side_effect=AssertionError("Saved email must not recalculate"))
    def test_email_uses_saved_values_and_retains_an_independent_audit_snapshot(self, recalculate):
        record = self.saved_board()
        before = deepcopy(record.analysis)
        # Live source changes must not rewrite a saved decision in the email.
        self.lot.current_bid = "5000"
        self.lot.save(update_fields=("current_bid",))
        email = compose_auction_email([self.lot])
        saved = email.lot_snapshots[self.lot.pk]["bid_board"]
        self.assertEqual(saved["analysis"]["selected_bid"], "1800.00")
        self.assertEqual(saved["evidence_snapshot"], record.evidence_snapshot)
        self.assertEqual(saved["summary"]["qualifying_bid"], "1800.00")
        self.assertIn("$1,800.00", email.text_body)
        self.assertIn("$2,450.00", email.text_body)
        self.assertIn("$550.00", email.html_body)
        self.assertIn("-$775.00", email.html_body)
        self.assertIn("22.45%", email.html_body)
        self.assertIn("Meets both minimums", email.text_body)
        self.assertIn("Saved grid page 1", email.text_body)
        self.assertIn(f"saved_bid_board={self.lot.pk}", email.text_body)
        self.assertIn("See latest saved Bid Board", email.html_body)
        self.assertIn("minimum_profit", saved["assumptions"])
        record.analysis["detail"]["net_profit"] = "99999.00"
        self.assertEqual(saved["analysis"]["detail"]["net_profit"], "550.00")
        record.refresh_from_db()
        self.assertEqual(record.analysis, before)
        recalculate.assert_not_called()

    def test_nonqualifying_selection_is_distinguished_from_qualifying_ceiling(self):
        self.saved_board(selected_bid="2000")
        email = compose_auction_email([self.lot])
        self.assertIn("Selected bid: $2,000.00 hammer", email.text_body)
        self.assertIn("Qualifying bid ceiling (Working): $1,800.00", email.text_body)
        self.assertIn("Does not meet both minimums", email.text_body)
        self.assertIn("Does not meet both minimums", email.html_body)

    def test_saved_board_text_is_escaped_in_html(self):
        record = self.saved_board()
        record.analysis["cases"][0]["basis"] = '<script>alert("unsafe")</script>'
        record.analysis["notices"] = ["<img src=x onerror=alert(1)>"]
        record.save(update_fields=("analysis",))
        email = compose_auction_email([self.lot])
        self.assertIn("&lt;script&gt;", email.html_body)
        self.assertIn("&lt;img", email.html_body)
        self.assertNotIn("<script>", email.html_body)
        self.assertNotIn("<img src=x", email.html_body)

    def test_board_without_selected_cash_flows_reports_unavailable(self):
        self.saved_board(selected_bid="1100", resale_overrides={})
        email = compose_auction_email([self.lot])
        self.assertIn("Qualification unavailable", email.text_body)
        self.assertNotIn("No qualifying bid", email.text_body)
        self.assertNotIn("Meets both minimums", email.text_body)

    def test_tray_shows_saved_preference_and_exact_email_board_preview(self):
        self.saved_board()
        batch = AuctionEmailBatch.objects.create()
        AuctionEmailBatchItem.objects.create(batch=batch, lot=self.lot, selected_by=self.staff)
        response = self.client.get(reverse("auction_email_tray"))
        self.assertContains(response, "Include saved Bid Board and qualifying bid")
        self.assertContains(response, 'name="include_in_email" value="true" checked')
        self.assertContains(response, "$1,800.00 selected hammer")
        self.assertContains(response, "Saved grid page 1")

    @override_settings(
        AUCTION_EMAIL_SENDING_ENABLED=True, AUCTION_EMAIL_SENDER="jeremy@secondstate.art",
        AUCTION_EMAIL_RECIPIENT_JEREMY="jeremy@secondstate.art",
        GOOGLE_GMAIL_CLIENT_ID="test-client", GOOGLE_GMAIL_CLIENT_SECRET="test-secret",
        GOOGLE_GMAIL_REFRESH_TOKEN="test-token",
    )
    @patch("secondstateapp.calendar_views.send_auction_email", return_value="test-message-id")
    def test_delivery_audit_freezes_included_board_at_send_time(self, send):
        record = self.saved_board()
        batch = AuctionEmailBatch.objects.create()
        item = AuctionEmailBatchItem.objects.create(batch=batch, lot=self.lot, selected_by=self.staff)
        response = self.client.post(reverse("auction_email_send"), {"recipients": ["jeremy"]})
        self.assertEqual(response.status_code, 302)
        send.assert_called_once()
        self.assertIn("$1,800.00", send.call_args.kwargs["html_body"])
        item.refresh_from_db()
        frozen = deepcopy(item.lot_snapshot["bid_board"])
        record.analysis["selected_bid"] = "2000.00"
        record.include_in_email = False
        record.save(update_fields=("analysis", "include_in_email"))
        item.refresh_from_db()
        self.assertEqual(item.lot_snapshot["bid_board"], frozen)
