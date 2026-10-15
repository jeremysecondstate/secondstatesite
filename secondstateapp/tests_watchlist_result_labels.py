from decimal import Decimal

from django.test import SimpleTestCase

from catalogapp.watchlist_models import NormalizedLot
from secondstateapp.calendar_views import _bid_label
from secondstateapp.models import AuctionWatchLot


class EndedLotResultLabelTests(SimpleTestCase):
    def desktop_lot(self, **overrides):
        fields = {
            "source": "Invaluable",
            "source_lot_id": "ended-label",
            "artist": "Alexander Calder",
            "artist_watchlist_name": "Alexander Calder",
            "title": "Print",
            "currency": "USD",
            "status": "ended",
        }
        fields.update(overrides)
        return NormalizedLot(**fields)

    def test_ended_lots_hide_stale_bid_amounts_and_counts_on_desktop_and_calendar(self):
        for amount, count in ((3800, 0), (1700, 4), (None, None)):
            with self.subTest(current_bid=amount, bid_count=count):
                desktop = self.desktop_lot(current_bid=amount, bid_count=count)
                calendar = AuctionWatchLot(active=False, current_bid=amount, bid_count=count)

                self.assertEqual(desktop.bid_label, "Sale ended · Sold price unavailable")
                self.assertEqual(_bid_label(calendar), "Sale ended · Sold price unavailable")

    def test_posted_sold_amount_takes_precedence_over_ended_and_no_bid_states(self):
        desktop = self.desktop_lot(sold_price=11000, sold_currency="EUR", bid_count=0)
        calendar = AuctionWatchLot(
            active=False, sold_price=Decimal("11000"), sold_currency="EUR", bid_count=0,
        )

        self.assertEqual(desktop.bid_label, "Sold: 11,000 EUR")
        self.assertEqual(_bid_label(calendar), "Sold: €11,000 EUR")

    def test_active_lots_keep_current_bid_and_no_bid_labels(self):
        desktop = self.desktop_lot(status="changed", current_bid=1700, bid_count=4)
        calendar = AuctionWatchLot(active=True, current_bid=Decimal("1700"), currency="USD", bid_count=4)

        self.assertEqual(desktop.bid_label, "1,700 USD (4 bids)")
        self.assertEqual(_bid_label(calendar), "Current bid: $1,700 · 4 bids")
        desktop.bid_count = calendar.bid_count = 0
        self.assertEqual(desktop.bid_label, "No bids")
        self.assertEqual(_bid_label(calendar), "Current bid: No bids")
