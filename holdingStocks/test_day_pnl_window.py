import unittest
from datetime import datetime
from day_pnl_window import apply_day_pnl_window, day_pnl_started


class TestDayPnlWindow(unittest.TestCase):
    def test_time_boundary(self):
        # 交易日 9:00 前保留上一交易日
        self.assertTrue(day_pnl_started(datetime(2026, 10, 20, 8, 59, 59)))
        # 交易日 9:00-9:15 之间为盘前待竞价
        self.assertFalse(day_pnl_started(datetime(2026, 10, 20, 9, 0, 0)))
        self.assertFalse(day_pnl_started(datetime(2026, 10, 20, 9, 14, 59)))
        # 交易日 9:15 之后进入竞价/盘中，正常展示
        self.assertTrue(day_pnl_started(datetime(2026, 10, 20, 9, 15)))
        # 周末/非交易日保留展示，不抹为 None
        self.assertTrue(day_pnl_started(datetime(2026, 10, 18, 10)))

    def test_post_reset_preopen_window(self):
        # 9:00 重置后到 9:15 之间，清空前日盈亏显示盘前待竞价
        snap = dict(account=dict(dayPnl=123, dayPnlPct=2, totalPnl=500),
                    holdings=[{'当日盈亏': 123, '当日盈亏%': 2}])
        apply_day_pnl_window(snap, datetime(2026, 10, 20, 9, 5))
        self.assertIsNone(snap['account']['dayPnl'])
        self.assertIsNone(snap['holdings'][0]['当日盈亏'])
        self.assertEqual(snap['account']['totalPnl'], 500)
        self.assertFalse(snap['account']['dayPnlStarted'])

    def test_weekend_preserves_return(self):
        snap = dict(account=dict(dayPnl=123, dayPnlPct=2, totalPnl=500),
                    holdings=[{'当日盈亏': 123, '当日盈亏%': 2}])
        apply_day_pnl_window(snap, datetime(2026, 10, 18, 10))
        self.assertEqual(snap['account']['dayPnl'], 123)
        self.assertEqual(snap['holdings'][0]['当日盈亏'], 123)
        self.assertTrue(snap['account']['dayPnlStarted'])

    def test_after915_preserves_return(self):
        snap = dict(account=dict(dayPnl=-10))
        apply_day_pnl_window(snap, datetime(2026, 10, 20, 9, 15))
        self.assertEqual(snap['account']['dayPnl'], -10)
        self.assertTrue(snap['account']['dayPnlStarted'])
