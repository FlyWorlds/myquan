"""止损已记 / T+1 兑现语义单测。"""

from __future__ import annotations

import unittest
from datetime import datetime

import pandas as pd

from index import overnight_stop_should_fill, paper_exit_decision, resolve_stop_noted_hit
from strategy.pullback_wave_stop import simulate_factor26_day_1m


class TestOvernightStopFillAllHoldings(unittest.TestCase):
    def test_last_or_low_hits_stop(self) -> None:
        self.assertTrue(
            overnight_stop_should_fill(last=33.23, low=33.10, stop=34.02)
        )
        # 现价已回到止损上方：全日最低不再拿去撞抬高后的卖价
        self.assertFalse(
            overnight_stop_should_fill(last=34.50, low=33.90, stop=34.02)
        )
        self.assertFalse(
            overnight_stop_should_fill(last=34.50, low=34.20, stop=34.02)
        )
        self.assertFalse(
            overnight_stop_should_fill(
                last=34.50, low=34.20, stop=34.02, sticky_touched=True
            )
        )
        self.assertTrue(
            overnight_stop_should_fill(
                last=34.05, low=34.20, stop=34.02, sticky_touched=True
            )
        )


class TestPaperExitDecision(unittest.TestCase):
    def test_zhongtian_open_protect_fills(self) -> None:
        """中天：昨收已过 3%，今开低于回落一半 → 按开盘价平，不看现价是否回来。"""
        dec = paper_exit_decision(
            qty=2600,
            sellable=2600,
            t1_today=False,
            last=34.59,
            open_px=33.84,
            prev_close=34.49,
            cost=33.48,
            peak_high=34.78,
            working_stop=34.13,
            path_hit=False,
            signal_ok=True,
        )
        self.assertTrue(dec["hit"])
        self.assertTrue(dec["hit_show"])
        self.assertEqual(dec["kind"], "open_protect")
        self.assertAlmostEqual(dec["fill_px"], 33.84, places=2)

    def test_t1_shows_but_does_not_fill(self) -> None:
        dec = paper_exit_decision(
            qty=4300,
            sellable=0,
            t1_today=True,
            last=20.50,
            open_px=21.07,
            prev_close=20.80,
            cost=21.07,
            working_stop=20.54,
            path_hit=True,
            path_fill_px=20.54,
            signal_ok=True,
        )
        self.assertTrue(dec["hit_show"])
        self.assertFalse(dec["hit"])
        self.assertEqual(dec["reason"], "t1")

    def test_raised_stop_vs_morning_low_no_fill_if_open_safe(self) -> None:
        """开盘高于保护、现价也高于当前卖价：早盘低点不能事后拿来平仓。"""
        dec = paper_exit_decision(
            qty=1000,
            sellable=1000,
            t1_today=False,
            last=10.80,
            open_px=10.50,
            prev_close=10.20,
            cost=10.00,
            peak_high=10.20,
            working_stop=10.40,
            path_hit=False,
            signal_ok=True,
        )
        self.assertFalse(dec["hit"])
        self.assertFalse(dec["hit_show"])

    def test_last_through_stop_fills(self) -> None:
        dec = paper_exit_decision(
            qty=1000,
            sellable=1000,
            t1_today=False,
            last=9.70,
            open_px=10.20,
            prev_close=10.00,
            cost=10.00,
            working_stop=9.75,
            path_hit=False,
            signal_ok=True,
        )
        self.assertTrue(dec["hit"])
        self.assertEqual(dec["kind"], "last")
        self.assertAlmostEqual(dec["fill_px"], 9.75, places=2)

    def test_yuandong_open_protect_fills_at_open(self) -> None:
        """远东：昨收 25.35 已过 3%，今开 24.10 低于回落一半 → 平仓价=开盘，不是盘后止损 24.6。"""
        dec = paper_exit_decision(
            qty=3700,
            sellable=3700,
            t1_today=False,
            last=24.73,
            open_px=24.1,
            prev_close=25.35,
            cost=23.78,
            peak_high=24.68,
            working_stop=24.6,
            path_hit=False,
            signal_ok=True,
        )
        self.assertTrue(dec["hit"])
        self.assertEqual(dec["kind"], "open_protect")
        self.assertAlmostEqual(dec["fill_px"], 24.1, places=2)

    def test_tefa_open_protect_with_friday_peak(self) -> None:
        """特发：隔夜峰值 17.65，今开 16.93 跌破回落一半 → 按开盘 16.93。"""
        dec = paper_exit_decision(
            qty=5500,
            sellable=5500,
            t1_today=False,
            last=16.82,
            open_px=16.93,
            prev_close=17.16,
            cost=16.29,
            peak_high=17.65,
            working_stop=16.5,
            path_hit=False,
            signal_ok=True,
        )
        self.assertEqual(dec["kind"], "open_protect")
        self.assertAlmostEqual(dec["fill_px"], 16.93, places=2)


class TestClosedExitFreeze(unittest.TestCase):
    def test_freeze_stop_to_fill(self) -> None:
        from index import _freeze_closed_exit_levels

        row = {
            "持仓状态": "已平仓",
            "已实现": True,
            "成交价": 24.1,
            "止损": 24.6,
            "基础止损": 24.6,
            "卖出侧价": 24.6,
            "价位小数": 2,
        }
        _freeze_closed_exit_levels(row)
        self.assertEqual(row["止损"], 24.1)
        self.assertEqual(row["基础止损"], 24.1)
        self.assertEqual(row["卖出侧价"], 24.1)

    def test_closed_mark_open_protect_beats_raised_stop(self) -> None:
        from index import _closed_mark_px

        row = {
            "开盘": 24.1,
            "昨收": 25.35,
            "止损": 24.6,
            "最低": 23.68,
            "成交价": 24.1,
            "已触止损": "是",
        }
        fill = _closed_mark_px(row, cost=23.78)
        self.assertAlmostEqual(float(fill or 0), 24.1, places=2)


class TestCorrectRealizedOpenProtect(unittest.TestCase):
    def setUp(self) -> None:
        import index as idx

        self.idx = idx
        self.trades: list[dict] = []
        self.data: dict = {
            "account_cash": 36750.0,
            "positions": {
                "600522": {
                    "name": "中天科技",
                    "market": "上证",
                    "qty": 0,
                    "peak_high": 34.78,
                    "note": "止损成交@34.13 (2026-09-14)",
                }
            },
            "realized_today": {
                "600522": {
                    "session": "2026-09-14",
                    "name": "中天科技",
                    "qty": 2600,
                    "price": 34.13,
                    "cost": 33.48,
                    "pnl": 1690.0,
                    "full_exit": True,
                    "reason": "止损成交",
                }
            },
            "closed_today": {
                "600522": {
                    "session": "2026-09-14",
                    "price": 34.13,
                    "qty": 2600,
                }
            },
            "factor_memory": {"600522": {"last_sell_factor_px": 34.13}},
            "alert_sticky": {},
        }
        self._load = idx.load_holdings
        self._save = idx.save_holdings
        self._append = idx.append_trade
        idx.load_holdings = lambda: self.data
        idx.save_holdings = self._save_holdings
        idx.append_trade = self._append_trade

    def _save_holdings(self, data: dict) -> None:
        self.data = data

    def _append_trade(self, rec: dict) -> None:
        self.trades.append(rec)

    def tearDown(self) -> None:
        self.idx.load_holdings = self._load
        self.idx.save_holdings = self._save
        self.idx.append_trade = self._append

    def test_zhongtian_fill_rewritten_to_open(self) -> None:
        rec = self.idx.correct_realized_open_protect_fill(
            code="600522",
            session="2026-09-14",
            open_px=33.84,
            prev_close=34.49,
            cost=33.48,
            peak_high=34.78,
            px_digits=2,
        )
        self.assertIsNotNone(rec)
        self.assertAlmostEqual(float(rec["price"]), 33.84, places=2)
        self.assertAlmostEqual(float(self.data["account_cash"]), 36750.0 - 0.29 * 2600, places=2)
        self.assertTrue(self.trades)
        self.assertIn("开盘保护纠价", str(self.trades[-1].get("note") or ""))

    def test_yuandong_correct_is_noop(self) -> None:
        self.data["realized_today"]["600869"] = {
            "session": "2026-09-14",
            "qty": 3700,
            "price": 24.1,
            "cost": 23.78,
            "full_exit": True,
        }
        rec = self.idx.correct_realized_open_protect_fill(
            code="600869",
            session="2026-09-14",
            open_px=24.1,
            prev_close=25.35,
            cost=23.78,
            peak_high=24.68,
            px_digits=2,
        )
        self.assertIsNotNone(rec)
        self.assertAlmostEqual(float(rec["price"]), 24.1, places=2)
        self.assertFalse(self.trades)


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
