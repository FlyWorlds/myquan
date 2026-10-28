"""Read-only latency and cache regressions; never execute trades or mutate accounts."""
from __future__ import annotations

import time
import unittest
from unittest.mock import patch

import pandas as pd
import index
from watch_buy_signal import annotate_unfilled_buy_signals


class TestSignalLatency(unittest.TestCase):
    def test_live_display_gate_is_reused_and_daily_refresh_invalidates_it(self):
        item = dict(code='000070', sina='sz000070', pct=.025, tick=.01)
        first, refreshed = ('2026-10-27', object()), ('2026-10-27', object())
        with patch.dict(index._QUOTE_GATE_CACHE, {}, clear=True), \
             patch.object(index, '_prev_bars_from_daily', return_value=(10,9,10,9)) as prev, \
             patch.object(index, '_entry_gate_detail', return_value=(True,'gate','yin')):
            index._quote_runtime_gate(item, '2026-10-27', first)
            index._quote_runtime_gate(item, '2026-10-27', first)
            self.assertEqual(prev.call_count, 1)
            index._quote_runtime_gate(item, '2026-10-27', refreshed)
            self.assertEqual(prev.call_count, 2)
            item['pct'] = .03
            index._quote_runtime_gate(item, '2026-10-27', refreshed)
            self.assertEqual(prev.call_count, 3)

    def test_readonly_refresh_preserves_the_execution_clock_in_quote_mode(self):
        from unittest.mock import Mock
        executor = Mock(last_evaluated_at="2026-10-15 09:30:01")
        with patch.object(index, "_CONDITION_BUY_ACTIVE", True), \
             patch.object(index, "_CONDITION_EXECUTOR", executor), \
             patch.object(index, "collect_rows", return_value=[]), \
             patch.object(index, "_now", return_value="2026-10-15 09:35:00"), \
             patch.object(index, "publish_watch_snapshot", return_value=(None, False)) as publish:
            index._refresh_once(5)
        self.assertEqual(publish.call_args.kwargs["signal_updated_at"], "2026-10-15 09:30:01")

    def test_heartbeat_advances_phase_without_faking_signal_evaluation(self):
        row = {"代码": "002580", "预警": "竞价观察", "阈值就绪": False}
        snap = {"phaseKey": "auction", "signalUpdatedAt": "2026-10-15 09:24:00", "holdings": [row]}
        with patch.object(index, "market_phase", return_value="continuous"), \
             patch.object(index, "market_phase_label", return_value="连续竞价"), \
             patch.object(index, "_current_feed_health", return_value={}):
            index._stamp_snapshot_liveness(snap, clock="2026-10-15 09:35:00")
        self.assertEqual(snap["phaseKey"], "continuous")
        self.assertEqual(snap["signalAgeSec"], 660)
        self.assertTrue(snap["signalStale"])
        self.assertEqual(snap["holdings"][0]["预警"], "盘中·信号待刷新")
        self.assertFalse(snap["holdings"][0]["阈值就绪"])
        self.assertEqual(row["预警"], "竞价观察")

    def test_condition_note_stays_chinese_and_does_not_repeat(self):
        note = index._condition_display_note(
            "报价条件单 FILLED；条件买单@8.32 · 已成交；买入侧@8.32 · 卖出侧@7.90",
            {"status": "FILLED", "price": 8.32},
        )
        self.assertEqual(note, "条件买单@8.32 · 已成交；买入侧@8.32 · 卖出侧@7.90")
        self.assertNotIn("FILLED", note)

    def test_missing_signal_clock_is_not_zero_latency(self):
        with patch.object(index, "_current_feed_health", return_value={}):
            snap = index._stamp_snapshot_liveness({}, clock="2026-10-15 09:35:00")
        self.assertIsNone(snap["signalAgeSec"])
        self.assertTrue(snap["signalStale"])

    def bars(self):
        return pd.DataFrame({"ts": pd.to_datetime(["2026-10-14 10:00:00", "2026-10-15 09:31:00"]),
                             "open": [10., 11.], "high": [11., 12.], "low": [9., 10.], "close": [10., 11.]})

    def test_today_bars_reuse_lookback_without_extending_cache_age(self):
        fetched_at = time.monotonic() - 2
        with patch.dict(index._M1_CACHE, {"lookback:sz002580": (fetched_at, "2026-10-15", self.bars())}, clear=True), \
             patch.object(index, "pull_akshare_1m") as pull:
            bars = index._today_1m_bars("sz002580", "2026-10-15")
            self.assertEqual(len(bars), 1)
            self.assertEqual(index._M1_CACHE["sz002580"][0], fetched_at)
            pull.assert_not_called()

    def test_wrong_session_lookback_is_not_reused(self):
        with patch.dict(index._M1_CACHE, {"lookback:sz002580": (time.monotonic(), "2026-10-14", self.bars())}, clear=True), \
             patch.object(index, "pull_akshare_1m", return_value=self.bars()) as pull:
            self.assertEqual(len(index._today_1m_bars("sz002580", "2026-10-15")), 1)
            pull.assert_called_once()

    def test_forced_minutes_still_refetch(self):
        with patch.dict(index._M1_CACHE, {"lookback:sz002580": (time.monotonic(), "2026-10-15", self.bars())}, clear=True), \
             patch.object(index, "pull_akshare_1m", return_value=self.bars()) as pull:
            index._today_1m_bars("sz002580", "2026-10-15", force=True)
            pull.assert_called_once()

    def test_failed_minutes_are_negative_cached(self):
        with patch.dict(index._M1_CACHE, {}, clear=True), \
             patch.object(index, "pull_akshare_1m", return_value=pd.DataFrame()) as pull:
            self.assertTrue(index._m1_lookback_bars("sz002580", session="2026-10-15").empty)
            self.assertTrue(index._m1_lookback_bars("sz002580", session="2026-10-15").empty)
            pull.assert_called_once()

    def test_open_audit_cache_cannot_validate_changed_open(self):
        quote = dict(session="2026-10-15", open=11., last_ts="2026-10-15 09:35:00")
        with patch.dict(index._OPEN_AUDIT_CACHE, {("2026-10-15", "002580"): {"ok": True, "audited_open": 10.}}, clear=True), \
             patch.object(index, "fetch_sina_spot", return_value=quote) as pull:
            audit = index.audit_single_stock_open(code="002580", expected_open=11., session="2026-10-15")
            pull.assert_called_once()
            self.assertTrue(audit["ok"])
            self.assertEqual(audit["audited_open"], 11.)

    def test_daily_limit_is_not_displayed_as_full_positions(self):
        row = {"代码": "001266", "持仓": 0, "过门OK": True, "已触买": "是"}
        annotate_unfilled_buy_signals([row], {"freeBuy": 3, "buysLeft": 0})
        self.assertEqual(row["预警"], "已触买·当日新增额度已满")
        self.assertNotIn("槽满", row["挂单说明"])

    def test_explicit_zero_buy_slots_does_not_fall_back_to_free(self):
        row = {"代码": "001266", "持仓": 0, "过门OK": True, "已触买": "是"}
        annotate_unfilled_buy_signals([row], {"freeBuy": 0, "free": 3, "buysLeft": 1})
        self.assertEqual(row["预警"], "已触买·槽满")


if __name__ == "__main__":
    unittest.main()
