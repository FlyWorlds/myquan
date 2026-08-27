"""因子3×因子1前置组合：离线规则/掩码回归（不拉行情）。"""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from strategy.f3_f1_combo import (
    apply_f1_precond_to_factor,
    build_factor1_entry_mask,
    simulate_f3_f1_combo,
)
from strategy.open_break import entry_filters_ok, entry_trigger_price


class F3F1ComboTests(unittest.TestCase):
    def _panel(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        idx = pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07"])
        # A: 阴→小阳，应允许次日开仓
        # B: 大阳→大阳且跨日≥5%，应禁止
        opens = pd.DataFrame(
            {
                "A": [10.0, 9.8, 10.0, 10.1],
                "B": [10.0, 10.3, 10.6, 10.8],
            },
            index=idx,
        )
        closes = pd.DataFrame(
            {
                "A": [9.7, 9.9, 10.05, 10.2],  # 阴；小阳(<2.5%)；…
                "B": [10.4, 10.8, 11.2, 11.0],  # 连续大阳
            },
            index=idx,
        )
        return opens, closes

    def test_mask_matches_entry_filters_ok(self) -> None:
        opens, closes = self._panel()
        mask = build_factor1_entry_mask(opens, closes, entry_pct=0.025)
        # 首日无前前日 → False
        self.assertFalse(bool(mask.iloc[0]["A"]))
        self.assertFalse(bool(mask.iloc[0]["B"]))

        for i in range(1, len(opens)):
            for sym in opens.columns:
                expect = entry_filters_ok(
                    float(opens.iloc[i][sym]),
                    float(closes.iloc[i][sym]),
                    float(opens.iloc[i - 1][sym]),
                    float(closes.iloc[i - 1][sym]),
                    entry_pct=0.025,
                )
                self.assertEqual(
                    bool(mask.iloc[i][sym]),
                    expect,
                    msg=f"{opens.index[i].date()} {sym}",
                )

    def test_apply_precond_nan_out_blocked(self) -> None:
        opens, closes = self._panel()
        factor = pd.DataFrame(1.0, index=opens.index, columns=opens.columns)
        masked, mask = apply_f1_precond_to_factor(
            factor, opens, closes, require_f1_precond=True, entry_pct=0.025
        )
        assert mask is not None
        # B 在双阳跨日日应被挖掉
        for i in range(len(opens)):
            for sym in opens.columns:
                if not bool(mask.iloc[i][sym]):
                    self.assertTrue(np.isnan(masked.iloc[i][sym]))
                else:
                    self.assertEqual(masked.iloc[i][sym], 1.0)

    def test_simulate_breakout_buy_and_stop(self) -> None:
        idx = pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07"])
        opens = pd.DataFrame({"A": [10.0, 10.0, 10.0, 10.0]}, index=idx)
        # day1 signal; day2 breakout high; day3 stop
        highs = pd.DataFrame({"A": [10.0, 10.40, 10.1, 10.1]}, index=idx)
        lows = pd.DataFrame({"A": [9.8, 9.9, 9.70, 9.8]}, index=idx)
        closes = pd.DataFrame({"A": [10.0, 10.2, 9.8, 9.9]}, index=idx)
        factor = pd.DataFrame({"A": [1.0, 1.0, 1.0, 1.0]}, index=idx)
        picks = {idx[0]: ["A"], idx[1]: ["A"]}
        eq, tr, stats = simulate_f3_f1_combo(
            factor=factor,
            opens=opens,
            highs=highs,
            lows=lows,
            closes=closes,
            picks=picks,
            bt_start=idx[0],
            top_k=1,
            entry_pct=0.025,
            stop_pct=0.025,
            initial_cash=100_000.0,
            factor_label="test",
            hold_days=None,
            take_profit_levels=(),  # 本用例只测止损
        )
        self.assertFalse(eq.empty)
        self.assertGreaterEqual(int(stats["n_buys"]), 1)
        self.assertGreaterEqual(int(stats["n_stop_exits"]), 1)
        buy_px = float(tr[tr["side"] == "buy"].iloc[0]["price"])
        # 触发价≈10.25，再加滑点
        expect = entry_trigger_price(10.0, entry_pct=0.025)
        self.assertGreaterEqual(buy_px, expect)

    def test_simulate_tiered_take_profit(self) -> None:
        idx = pd.to_datetime(
            ["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07", "2020-01-08"]
        )
        opens = pd.DataFrame({"A": [10.0, 10.0, 10.0, 10.0, 10.0]}, index=idx)
        # day2 buy @~10.25; day3 high hits +5%/+8%/+10%; day4 stop remainder
        highs = pd.DataFrame({"A": [10.0, 10.40, 11.40, 10.1, 10.1]}, index=idx)
        lows = pd.DataFrame({"A": [9.8, 9.9, 10.0, 9.70, 9.8]}, index=idx)
        closes = pd.DataFrame({"A": [10.0, 10.3, 11.5, 9.8, 9.9]}, index=idx)
        factor = pd.DataFrame({"A": [1.0] * 5}, index=idx)
        picks = {idx[0]: ["A"]}
        _eq, tr, stats = simulate_f3_f1_combo(
            factor=factor,
            opens=opens,
            highs=highs,
            lows=lows,
            closes=closes,
            picks=picks,
            bt_start=idx[0],
            top_k=1,
            entry_pct=0.025,
            stop_pct=0.025,
            initial_cash=100_000.0,
            factor_label="test_tp",
            take_profit_levels=(0.05, 0.08, 0.10),
            take_profit_reduce=0.20,
        )
        self.assertGreaterEqual(int(stats["n_buys"]), 1)
        self.assertGreaterEqual(int(stats["n_tp_exits"]), 1)
        self.assertTrue((tr["reason"] == "tp_5").any())
        self.assertGreaterEqual(int(stats["n_stop_exits"]), 1)


if __name__ == "__main__":
    unittest.main()
