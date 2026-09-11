"""止损已记 / T+1 兑现语义单测。"""

from __future__ import annotations

import unittest
from datetime import datetime

import pandas as pd

from index import resolve_stop_noted_hit
from strategy.pullback_wave_stop import simulate_factor26_day_1m


class TestStopNoted(unittest.TestCase):
    def test_t1_cannot_fill(self):
        pos = {"stop_noted": True, "stop_noted_px": 10.0}
        self.assertFalse(
            resolve_stop_noted_hit(
                pos,
                open_px=9.5,
                low_px=9.0,
                last_px=9.2,
                sellable=0,
                t1_buy_day=True,
                now=datetime(2026, 9, 9, 9, 31),
            )["hit"]
        )

    def test_gap_down_fills_open_dump(self):
        """低开已破买点硬保护：按开盘卖，不是继续等到 T1 回落。"""
        pos = {"stop_noted": True, "stop_noted_px": 10.0, "cost": 10.0}
        hit = resolve_stop_noted_hit(
            pos,
            open_px=9.5,
            low_px=9.0,
            last_px=9.2,
            sellable=100,
            t1_buy_day=False,
            now=datetime(2026, 9, 9, 9, 31),
        )
        self.assertTrue(hit["hit"])
        self.assertEqual(hit["kind"], "hard_from_cost")
        self.assertAlmostEqual(hit["fill_px"], 9.5, places=2)
        self.assertNotAlmostEqual(hit["fill_px"], 10.0)

    def test_gap_up_no_dump_does_not_force_sell(self):
        """次日高开且未从开盘回落 2.5%：不强制开盘卖。"""
        pos = {"stop_noted": True, "stop_noted_px": 10.0}
        hit = resolve_stop_noted_hit(
            pos,
            open_px=10.8,
            low_px=10.75,
            last_px=10.78,
            sellable=100,
            t1_buy_day=False,
            now=datetime(2026, 9, 9, 9, 31),
        )
        self.assertFalse(hit["hit"])

    def test_gap_up_profit_over_2_skips_open_dump(self):
        """高开且浮盈>3%：不走峰值回落 2.5%，交给波动回落/档位。"""
        pos = {"stop_noted": True, "stop_noted_px": 10.0, "cost": 10.0}
        hit = resolve_stop_noted_hit(
            pos,
            open_px=10.8,
            low_px=10.60,
            last_px=10.65,
            sellable=100,
            t1_buy_day=False,
            now=datetime(2026, 9, 9, 9, 40),
        )
        self.assertFalse(hit["hit"])

    def test_gap_up_dump_from_open_sells(self):
        """高开但浮盈未过 3%：从当日峰值回落 2.5% 才卖。"""
        pos = {"stop_noted": True, "stop_noted_px": 10.0, "cost": 10.0}
        hit = resolve_stop_noted_hit(
            pos,
            open_px=10.15,
            low_px=9.85,
            last_px=9.90,
            sellable=100,
            t1_buy_day=False,
            now=datetime(2026, 9, 9, 9, 40),
        )
        self.assertTrue(hit["hit"])
        self.assertLess(hit["fill_px"], 10.15)

    def test_missed_open_uses_dump_stop(self):
        pos = {"stop_noted": True, "stop_noted_px": 10.0, "cost": 10.0}
        hit = resolve_stop_noted_hit(
            pos,
            open_px=9.5,
            low_px=9.0,
            last_px=9.8,
            sellable=100,
            t1_buy_day=False,
            now=datetime(2026, 9, 9, 13, 5),
        )
        self.assertTrue(hit["hit"])
        self.assertAlmostEqual(hit["fill_px"], 9.5, places=2)

    def test_limit_down_locked_waits(self):
        pos = {"stop_noted": True, "stop_noted_px": 10.0}
        hit = resolve_stop_noted_hit(
            pos,
            open_px=9.0,
            low_px=9.0,
            last_px=9.0,
            sellable=100,
            t1_buy_day=False,
            locked=True,
            now=datetime(2026, 9, 9, 9, 31),
        )
        self.assertFalse(hit["hit"])

    def test_simulate_notes_on_t1_and_exits_next_open(self):
        bars1 = pd.DataFrame(
            {
                "ts": pd.date_range("2024-01-02 09:31", periods=5, freq="min"),
                "open": [10.0, 10.5, 10.4, 10.1, 9.8],
                "high": [10.5, 10.8, 10.6, 10.2, 10.0],
                "low": [10.0, 10.4, 10.1, 9.7, 9.5],
            }
        )
        d1 = simulate_factor26_day_1m(
            bars1,
            open_px=10.0,
            entry_pct=0.025,
            pullback_pct=0.025,
            holding_in=False,
            can_sell=False,
            allow_entry=True,
        )
        self.assertIsNotNone(d1.get("buy_px"))
        noted = d1.get("stop_noted_out")
        self.assertIsNotNone(noted)
        # 次日高开、全天低点仍高于已记价 → 仍按开盘市价卖掉
        bars2 = pd.DataFrame(
            {
                "ts": pd.date_range("2024-01-03 09:31", periods=3, freq="min"),
                "open": [10.4, 10.3, 10.2],
                "high": [10.5, 10.4, 10.3],
                "low": [10.3, 10.2, 10.1],
            }
        )
        from strategy.pullback_wave_stop import NOTED_MODE_SELL_OPEN

        d2 = simulate_factor26_day_1m(
            bars2,
            open_px=10.4,
            entry_pct=0.025,
            pullback_pct=0.025,
            holding_in=True,
            can_sell=True,
            allow_entry=False,
            cost_px=float(d1["buy_px"] or 10.3),
            peak_high_in=10.8,
            stop_noted_px_in=float(noted),
            noted_mode=NOTED_MODE_SELL_OPEN,
        )
        self.assertIsNotNone(d2.get("sell_px"))
        self.assertAlmostEqual(float(d2["sell_px"]), 10.4)
        self.assertFalse(d2.get("holding_out"))

    def test_simulate_gap_down_fill_open(self):
        bars = pd.DataFrame(
            {
                "ts": pd.date_range("2024-01-03 09:31", periods=2, freq="min"),
                "open": [9.2, 9.1],
                "high": [9.3, 9.2],
                "low": [9.0, 8.9],
            }
        )
        out = simulate_factor26_day_1m(
            bars,
            open_px=9.2,
            holding_in=True,
            can_sell=True,
            allow_entry=False,
            cost_px=10.0,
            peak_high_in=10.0,
            stop_noted_px_in=9.75,
        )
        self.assertAlmostEqual(float(out["sell_px"]), 9.20, places=2)
        self.assertNotAlmostEqual(float(out["sell_px"]), 9.75)

    def test_gap_dump_high_open_no_dump_holds(self):
        from strategy.pullback_wave_stop import NOTED_MODE_GAP_DUMP

        bars = pd.DataFrame(
            {
                "ts": pd.date_range("2024-01-03 09:31", periods=3, freq="min"),
                "open": [10.5, 10.6, 10.7],
                "high": [10.6, 10.7, 10.8],
                "low": [10.4, 10.5, 10.6],
            }
        )
        out = simulate_factor26_day_1m(
            bars,
            open_px=10.5,
            holding_in=True,
            can_sell=True,
            allow_entry=False,
            cost_px=10.0,
            peak_high_in=10.2,
            stop_noted_px_in=9.75,
            noted_mode=NOTED_MODE_GAP_DUMP,
            noted_dump_pct=0.01,
        )
        self.assertIsNone(out.get("sell_px"))
        self.assertTrue(out.get("holding_out"))

    def test_gap_dump_sells_when_dumps_from_open(self):
        from strategy.pullback_wave_stop import NOTED_MODE_GAP_DUMP

        bars = pd.DataFrame(
            {
                "ts": pd.date_range("2024-01-03 09:31", periods=3, freq="min"),
                "open": [10.5, 10.4, 10.3],
                "high": [10.55, 10.45, 10.35],
                "low": [10.45, 10.35, 10.20],
            }
        )
        out = simulate_factor26_day_1m(
            bars,
            open_px=10.5,
            holding_in=True,
            can_sell=True,
            allow_entry=False,
            cost_px=10.0,
            peak_high_in=10.2,
            stop_noted_px_in=9.75,
            noted_mode=NOTED_MODE_GAP_DUMP,
            noted_dump_pct=0.01,
            vol20_daily=0.05,
        )
        self.assertIsNotNone(out.get("sell_px"))
        self.assertLess(float(out["sell_px"]), 10.5)


if __name__ == "__main__":
    unittest.main()
