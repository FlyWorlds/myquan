"""Quote-only formula and IO-boundary regression, no production database access."""
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch, Mock

from condition_buy import auction_entry_blocked
from quote_exit import evaluate_quote_exit, overnight_note_updates
from test_condition_buy import quote

NOW = datetime(2026, 10, 15, 10, 1)


class TestQuoteExit(unittest.TestCase):
    def evaluate(self, price, **changes):
        pos = dict(qty=900, available=900, cost=10., buy_time="2026-10-14 10:00:00", peak_high=10.)
        pos.update(changes)
        q = quote(last=price, high=max(price, 12.), low=min(price, 9.), last_ts=str(NOW))
        return evaluate_quote_exit(pos, q, session="2026-10-15", now=NOW, received_at=NOW)

    def test_daily_extremes_do_not_invent_an_exit(self):
        result = self.evaluate(10.01)
        self.assertIsNone(result["action"])
        self.assertEqual(result["updates"]["peak_high"], 10.01)

    def test_ladder_half_then_remaining_peak_exit(self):
        first = self.evaluate(11.)
        self.assertEqual(first["action"]["kind"], "half")
        self.assertEqual(first["action"]["shares"], 400)
        second = self.evaluate(10.7, qty=500, available=500, tp_stage=1, peak_high=11.)
        self.assertEqual(second["action"]["kind"], "full")
        self.assertEqual(second["action"]["shares"], 500)
        self.assertEqual(second["action"]["fill_px"], 10.7)

    def test_buy_day_never_sells(self):
        self.assertIsNone(self.evaluate(9., buy_time="2026-10-15 09:31:00")["action"])

    def test_manual_hold_lock_and_limit_down_lock_prevent_exit(self):
        self.assertIsNone(self.evaluate(9., hold_lock=True)["action"])
        pos = dict(code="000070", qty=900, cost=10., buy_time="2026-10-14 10:00:00", peak_high=10.)
        q = quote(open=9., high=9., low=9., last=9., last_ts=str(NOW))
        result = evaluate_quote_exit(pos, q, session="2026-10-15", now=NOW, received_at=NOW)
        self.assertIsNone(result["action"])

    def test_half_exit_respects_explicit_sellable_quantity(self):
        self.assertEqual(self.evaluate(11., available=300)["action"]["shares"], 100)

    def test_quote_older_than_persisted_peak_is_not_executable(self):
        self.assertIsNone(self.evaluate(9., peak_high_at=str(NOW + timedelta(seconds=1))))

    def test_buy_day_close_sentinel_and_profit_recovery(self):
        pos = dict(qty=900, cost=10., buy_time="2026-10-15 09:31:00", peak_high=10.)
        now = NOW.replace(hour=14, minute=58)
        q = quote(last=10.1, last_ts=str(now))
        result = evaluate_quote_exit(pos, q, session="2026-10-15", now=now, received_at=now)
        self.assertIsNone(result["action"])
        self.assertTrue(result["updates"]["stop_noted"])
        pos.update(result["updates"])
        q.update(last=10.4, high=10.4)
        result = evaluate_quote_exit(pos, q, session="2026-10-15", now=now, received_at=now)
        self.assertFalse(result["updates"]["stop_noted"])

    def test_restart_recovers_prior_close_note_without_minute_history(self):
        pos = dict(cost=10., peak_high=10.2, buy_time="2026-10-14 09:31:00")
        updates = overnight_note_updates(pos, dict(prev_close=10.2), "2026-10-15")
        self.assertTrue(updates["stop_noted"])
        self.assertEqual(updates["stop_noted_px"], 10.)
        self.assertEqual(updates["stop_note_source"], "official_previous_close")
        self.assertIsNone(updates["stop_noted_session"])
        pos["quote_exit_session"] = "2026-10-15"
        self.assertEqual(overnight_note_updates(pos, dict(prev_close=10.2), "2026-10-15"), {})

    def test_duplicate_and_out_of_order_checkpoints_rejected(self):
        mark = dict(cycle="2026-10-14 10:00:00", time=str(NOW), price=10.)
        self.assertIsNone(self.evaluate(10., quote_exit_watermark=mark))
        mark["time"] = str(NOW + timedelta(seconds=1))
        self.assertIsNone(self.evaluate(9., quote_exit_watermark=mark))

    def test_auction_near_limit_exclusion_not_all_boards_fixed_ten_percent(self):
        self.assertTrue(auction_entry_blocked(10.97, 10.))
        self.assertFalse(auction_entry_blocked(10.96, 10.))
        self.assertFalse(auction_entry_blocked(10.97, 10., limit_up_pct=.20))
        self.assertTrue(auction_entry_blocked(11.97, 10., limit_up_pct=.20))

    def test_malformed_or_stale_quote_fails_closed(self):
        pos = dict(qty=100, cost=10., buy_time="2026-10-14 10:00:00")
        for q in (quote(last="bad"), quote(last_ts="2026-10-15 09:59:00")):
            self.assertIsNone(evaluate_quote_exit(pos, q, session="2026-10-15", now=NOW, received_at=NOW))

    def test_collect_runtime_dispatch_never_calls_minute_or_daily_io(self):
        import index
        fake = Mock(return_value=[{"代码": "000070"}])
        with patch.object(index, "_CONDITION_BUY_ACTIVE", True), \
                patch.object(index, "_collect_quote_runtime_rows", fake), \
                patch.object(index, "_today_1m_bars", side_effect=AssertionError("minute IO")), \
                patch.object(index, "_m1_lookback_bars", side_effect=AssertionError("minute replay")), \
                patch.object(index, "_watch_daily", side_effect=AssertionError("daily IO")):
            self.assertEqual(index.collect_rows(), [{"代码": "000070"}])

    def test_runtime_minute_provider_boundary_rejects_accidental_reentry(self):
        import index
        with patch.object(index, "_CONDITION_BUY_ACTIVE", True):
            with self.assertRaisesRegex(RuntimeError, "独立回测"):
                index._today_1m_bars("sz000070", "2026-10-15")
            with self.assertRaisesRegex(RuntimeError, "独立回测"):
                index._m1_lookback_bars("sz000070", session="2026-10-15")


if __name__ == "__main__":
    unittest.main()
