import unittest
from datetime import datetime
from open_peak_sell import draft_open_peak_sell, open_peak_sell_ready


class TestOpenPeakSell(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 20, 9, 25)
        self.pos = dict(qty=1500, cost=36.49, peak_high=39.5, buy_time='2026-10-19 09:30:11')
        self.q = dict(session='2026-10-20', last=37.67, open=37.67, prev_close=37.75,
                      high=37.67, low=37.67, last_ts=str(self.now))

    def draft(self):
        return draft_open_peak_sell(self.pos, self.q, session='2026-10-20', now=self.now)

    def test_prepare_then_execute_at_open(self):
        order = self.draft()
        self.assertIsNotNone(order)
        self.assertFalse(open_peak_sell_ready(order, self.pos, self.q, session='2026-10-20', now=self.now))
        self.now = self.now.replace(minute=30, second=2)
        self.q.update(last_ts=str(self.now), last=37.6, low=37.6)
        self.assertTrue(open_peak_sell_ready(order, self.pos, self.q, session='2026-10-20', now=self.now))
        self.assertEqual(order['open'], 37.67)

    def test_before925_and_same_day_entry_and_lock_block(self):
        self.now = self.now.replace(minute=24, second=59)
        self.q['last_ts'] = str(self.now)
        self.assertIsNone(self.draft())
        self.now = self.now.replace(minute=25, second=0)
        self.q['last_ts'] = str(self.now)
        self.pos['hold_lock'] = True
        self.assertIsNone(self.draft())
        self.pos.update(hold_lock=False, buy_time='2026-10-20 09:25:00')
        self.assertIsNone(self.draft())

    def test_no_gap_or_no_threshold_breach(self):
        self.q['prev_close'] = 37.
        self.assertIsNone(self.draft())
        self.q['prev_close'] = 40.
        self.q.update(open=39.4, last=39.4, high=39.4, low=39.4)
        self.assertIsNone(self.draft())

    def test_stale_changed_open_and_late_execution_block(self):
        order = self.draft()
        self.now = self.now.replace(minute=30, second=2)
        self.assertFalse(open_peak_sell_ready(order, self.pos, self.q, session='2026-10-20', now=self.now))
        self.q.update(last_ts=str(self.now), open=37.68, last=37.68, high=37.68, low=37.68)
        self.assertFalse(open_peak_sell_ready(order, self.pos, self.q, session='2026-10-20', now=self.now))
        self.now = self.now.replace(second=6)
        self.q.update(open=37.67, last_ts=str(self.now))
        self.assertFalse(open_peak_sell_ready(order, self.pos, self.q, session='2026-10-20', now=self.now))

    def test_runtime_fills_pending_order_at_open_not_latest(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        from datetime import date
        with patch('stock_names.resolve_stock_name', return_value='测试'):
            import index
        self.pos['open_peak_sell_order'] = self.draft()
        self.now = self.now.replace(minute=30, second=2)
        self.q.update(last_ts=str(self.now), last=37.6, low=37.6)
        with patch.object(index, 'datetime') as clock, \
             patch.object(index, 'trading_session_date', return_value=date(2026,10,20)), \
             patch.object(index, 'is_signal_window', return_value=True), \
             patch.object(index, '_execution_quote', return_value=self.q), \
             patch.object(index, 'limit_down_state', return_value={'locked': False}), \
             patch.object(index, '_sellable_qty', return_value=1500), \
             patch.object(index, 'freeze_overnight_peak_for_session', return_value=39.5), \
             patch('quote_exit.overnight_note_updates', return_value={}), \
             patch('strategy.exit_rules.overnight_open_protect.evaluate_overnight_open_protect', return_value=SimpleNamespace(triggered=False)), \
             patch.object(index, 'apply_exit_fill') as fill:
            clock.now.return_value = self.now
            index._settle_condition_open_protect({'positions': {'001266': self.pos}}, self.now)
            self.assertEqual(fill.call_args.kwargs['fill_px'], 37.67)
            self.assertEqual(fill.call_args.kwargs['exit_kind'], 'open_peak_sell')
            self.assertEqual(self.pos['open_peak_sell_order']['status'], 'FILLED')


if __name__ == '__main__':
    unittest.main()
