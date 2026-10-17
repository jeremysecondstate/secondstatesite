"""Look-ahead boundaries must match the bounded source query."""

from datetime import datetime, timedelta, timezone
from unittest import TestCase

from catalogapp.watchlist_models import NormalizedLot, lot_within_horizon


class LookAheadBoundaryTests(TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 17, 15, tzinfo=timezone.utc)

    def lot(self, when):
        return NormalizedLot(
            source='Invaluable', source_lot_id='test', artist='Test artist', artist_watchlist_name='Test artist',
            title='Test print', lot_url='https://www.invaluable.com/auction-lot/test-c-test/',
            start_at=when,
        )

    def test_seven_days_does_not_include_an_eighth_day(self):
        cutoff = self.now + timedelta(days=7)
        self.assertTrue(lot_within_horizon(self.lot(cutoff.isoformat()), self.now, 7))
        self.assertFalse(lot_within_horizon(self.lot((cutoff + timedelta(seconds=1)).isoformat()), self.now, 7))

    def test_lot_close_time_controls_the_window(self):
        lot = self.lot(self.now.isoformat())
        lot.end_at = (self.now + timedelta(days=8)).isoformat()
        self.assertFalse(lot_within_horizon(lot, self.now, 7))

    def test_date_only_today_remains_included(self):
        self.assertTrue(lot_within_horizon(self.lot('2026-10-17'), self.now, 7))
        self.assertFalse(lot_within_horizon(self.lot('2026-10-25'), self.now, 7))
