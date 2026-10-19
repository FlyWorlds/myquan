import unittest
from holding_peak_history import history_peak


class TestHoldingPeakHistory(unittest.TestCase):
    def test_only_holding_days_and_postbuy_minutes(self):
        daily = [dict(date='2026-10-15', high=20), dict(date='2026-10-16', high=15),
                 dict(date='2026-10-19', high=7.2), dict(date='2026-10-20', high=30)]
        minutes = [dict(ts='2026-10-16 09:31:00', high=15),
                   dict(ts='2026-10-16 13:01:00', high=7.14)]
        peak = history_peak('2026-10-16 09:30:05', daily, session='2026-10-20', buy_day_rows=minutes)
        self.assertEqual(peak[0], 7.2)
        self.assertEqual(history_peak('2026-10-16 09:30:05', daily, session='2026-10-19', buy_day_rows=minutes)[0], 7.14)

    def test_no_unverified_buyday_daily_high(self):
        self.assertIsNone(history_peak('2026-10-16 10:00:00', [dict(date='2026-10-16', high=50)], session='2026-10-19'))


if __name__ == '__main__':
    unittest.main()
