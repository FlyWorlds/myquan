import unittest
from datetime import datetime, timedelta
from quote_exit import evaluate_quote_exit


class TestHoldingPeak(unittest.TestCase):
    def test_overnight_peak_never_decreases_and_tracks_daily_high(self):
        pos = dict(qty=100, available=100, cost=10., peak_high=11.,
                   buy_time='2026-10-16 09:35:00', hold_lock=True)
        now = datetime(2026, 10, 19, 10)
        for high, expected in ((10.5, 11.), (11.3, 11.3), (11.2, 11.3)):
            now += timedelta(seconds=1)
            q = dict(session='2026-10-19', last=10.2, open=10., high=high,
                     low=10., prev_close=10., last_ts=str(now))
            result = evaluate_quote_exit(pos, q, session='2026-10-19', now=now, received_at=now)
            self.assertEqual(result['updates']['peak_high'], expected)
            pos.update(result['updates'])
            pos['quote_exit_watermark'] = result['watermark']

    def test_same_day_high_before_purchase_is_excluded(self):
        pos = dict(qty=100, cost=10., peak_high=10., buy_time='2026-10-19 09:35:00')
        now = datetime(2026, 10, 19, 10)
        q = dict(session='2026-10-19', last=10.2, open=10., high=12., low=10.,
                 prev_close=10., last_ts=str(now))
        result = evaluate_quote_exit(pos, q, session='2026-10-19', now=now, received_at=now)
        self.assertEqual(result['updates']['peak_high'], 10.2)

    def test_pre925_quote_ignored(self):
        now = datetime(2026, 10, 19, 9, 24, 59)
        q = dict(session='2026-10-19', last=15., open=10., high=15., low=10.,
                 prev_close=10., last_ts=str(now))
        pos = dict(qty=100, cost=10., peak_high=11., buy_time='2026-10-16 10:00:00')
        self.assertIsNone(evaluate_quote_exit(pos, q, session='2026-10-19', now=now, received_at=now))


if __name__ == '__main__':
    unittest.main()
