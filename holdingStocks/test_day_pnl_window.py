import unittest
from datetime import datetime
from day_pnl_window import apply_day_pnl_window, day_pnl_started


class TestDayPnlWindow(unittest.TestCase):
    def test_time_boundary(self):
        self.assertFalse(day_pnl_started(datetime(2026, 10, 20, 9, 14, 59)))
        self.assertTrue(day_pnl_started(datetime(2026, 10, 20, 9, 15)))
        self.assertFalse(day_pnl_started(datetime(2026, 10, 18, 10)))

    def test_preopen_does_not_show_yesterday_return(self):
        snap = dict(account=dict(dayPnl=123, dayPnlPct=2, totalPnl=500),
                    holdings=[{'当日盈亏': 123, '当日盈亏%': 2}])
        apply_day_pnl_window(snap, datetime(2026, 10, 20, 8))
        self.assertIsNone(snap['account']['dayPnl'])
        self.assertIsNone(snap['holdings'][0]['当日盈亏'])
        self.assertEqual(snap['account']['totalPnl'], 500)

    def test_after915_preserves_return(self):
        snap = dict(account=dict(dayPnl=-10))
        apply_day_pnl_window(snap, datetime(2026, 10, 20, 9, 15))
        self.assertEqual(snap['account']['dayPnl'], -10)
        self.assertTrue(snap['account']['dayPnlStarted'])
