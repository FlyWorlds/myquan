import unittest
from datetime import datetime, timedelta

from manual_peak import update_peak
from quote_exit import evaluate_quote_exit


class TestManualPeak(unittest.TestCase):
    def setUp(self):
        self.at = datetime(2026, 10, 19, 10)
        self.pos = dict(qty=100, available=0, cost=10., peak_high=11.,
                        buy_time='2026-10-19 09:35:00')
        self.data = dict(positions={'600000': self.pos})
        self.payload = dict(code='600000', buyTime=self.pos['buy_time'], peak=10.5, expectedPeak=11.)

    def test_manual_correction_and_following_quotes(self):
        update_peak(self.data, self.payload, now=self.at)
        self.assertEqual(self.pos['peak_high'], 10.5)
        for price, expected in ((10.2, 10.5), (10.8, 10.8), (10.6, 10.8)):
            self.at += timedelta(seconds=1)
            q = dict(session="2026-10-19", last=price, open=10., high=12., low=10., prev_close=10., last_ts=str(self.at))
            result = evaluate_quote_exit(self.pos, q, session='2026-10-19', now=self.at, received_at=self.at)
            self.assertIsNotNone(result)
            self.pos.update(result['updates'])
            self.assertEqual(self.pos['peak_high'], expected)

    def test_preauction_edit_blocked(self):
        with self.assertRaises(ValueError):
            update_peak(self.data, self.payload, now=self.at.replace(hour=9, minute=24, second=59))
        self.assertEqual(self.pos['peak_high'], 11.)
        update_peak(self.data, self.payload, now=self.at.replace(hour=9, minute=25))
        self.assertEqual(self.pos['peak_high'], 10.5)

    def test_auction_quotes_cannot_update_peak_or_trigger_exits(self):
        for hour, minute in ((9, 15), (9, 24), (9, 25), (9, 29)):
            now = self.at.replace(hour=hour, minute=minute)
            q = dict(session='2026-10-19', last=15., open=10., high=15., low=10.,
                     prev_close=10., last_ts=str(now))
            self.assertIsNone(evaluate_quote_exit(self.pos, q, session='2026-10-19', now=now, received_at=now))
        self.assertEqual(self.pos['peak_high'], 11.)

    def test_overnight_position_includes_daily_high(self):
        self.pos['buy_time'] = '2026-10-16 09:35:00'
        q = dict(session='2026-10-19', last=10.2, open=10., high=11.3,
                 low=10., prev_close=10., last_ts=str(self.at))
        result = evaluate_quote_exit(self.pos, q, session='2026-10-19', now=self.at, received_at=self.at)
        self.assertEqual(result['updates']['peak_high'], 11.3)
        self.pos.update(result['updates'])
        self.pos['quote_exit_watermark'] = result['watermark']
        q['high'] = 11.5
        result = evaluate_quote_exit(self.pos, q, session='2026-10-19', now=self.at, received_at=self.at)
        self.assertEqual(result['updates']['peak_high'], 11.5)

    def test_invalid_prices_do_not_change_position(self):
        for value in (0, -1, 'bad', float('nan'), float('inf'), True):
            with self.assertRaises(ValueError):
                update_peak(self.data, dict(self.payload, peak=value), now=self.at)
            self.assertEqual(self.pos['peak_high'], 11.)

    def test_reject_concurrent_quote_or_new_cycle(self):
        for change in (dict(expectedPeak=10.), dict(buyTime='old')):
            with self.assertRaises(ValueError):
                update_peak(self.data, dict(self.payload, **change), now=self.at)
        self.pos['qty'] = 0
        with self.assertRaises(ValueError):
            update_peak(self.data, self.payload, now=self.at)


if __name__ == '__main__':
    unittest.main()
