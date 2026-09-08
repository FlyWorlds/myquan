# -*- coding: utf-8 -*-
"""回归：买入当日触止损须已记；次日低开按开盘价卖（非虚高止损价）。"""
from __future__ import annotations

import unittest

import pandas as pd

from backtest.strategy1_pool_1m.run import simulate_portfolio_3slots


class TestGapFillNoted(unittest.TestCase):
    def test_t1_note_then_gap_open_fill(self):
        daily = pd.DataFrame(
            [
                {"date": "2026-09-03", "open": 10.0, "high": 10.1, "low": 9.9, "close": 9.95},
                {"date": "2026-09-04", "open": 10.0, "high": 10.2, "low": 9.8, "close": 9.9},
                {"date": "2026-09-07", "open": 10.0, "high": 10.6, "low": 9.7, "close": 10.30},
                {"date": "2026-09-08", "open": 9.5, "high": 9.8, "low": 9.3, "close": 9.6},
            ]
        )
        mins = pd.DataFrame(
            [
                {
                    "ts": "2026-09-07 09:31:00",
                    "open": 10.00,
                    "high": 10.30,
                    "low": 10.00,
                    "close": 10.20,
                },
                {
                    "ts": "2026-09-07 09:32:00",
                    "open": 10.20,
                    "high": 10.60,
                    "low": 10.50,
                    "close": 10.55,
                },
                {
                    "ts": "2026-09-07 09:33:00",
                    "open": 10.50,
                    "high": 10.52,
                    "low": 10.35,
                    "close": 10.30,
                },
                {
                    "ts": "2026-09-08 09:31:00",
                    "open": 9.50,
                    "high": 9.60,
                    "low": 9.40,
                    "close": 9.55,
                },
            ]
        )
        out = simulate_portfolio_3slots(
            [
                {
                    "code": "000001",
                    "name": "测试",
                    "entry_pct": 0.025,
                    "pullback_pct": 0.025,
                    "daily": daily,
                    "minutes": mins,
                }
            ],
            days=2,
            initial_cash=100000,
        )
        sells = [t for t in out["trades"] if t["side"] == "sell"]
        self.assertTrue(sells, msg=out["trades"])
        s0 = sells[0]
        self.assertEqual(s0["exit_reason"], "hard_from_cost")
        self.assertAlmostEqual(float(s0["px"]), 9.50, places=2)
        self.assertNotEqual(s0.get("exit_reason"), "vol_giveback")


if __name__ == "__main__":
    unittest.main()
