"""策略七·缠论笔算盈亏比：注册、决策与笔归因确定性测试。"""

from __future__ import annotations

import unittest

import pandas as pd

import strategy.factors  # noqa: F401
import strategy.strategies.strategy7  # noqa: F401
from strategy.bi_pl_ratio import (
    aggregate_bi_vs_factor1,
    analyze_bi_pl_ratio,
    attribute_trades_to_bis,
    net_round_trip_return,
    replay_factor1_trades,
    year_pl_stats,
)
from strategy.core.context import MarketContext
from strategy.core.strategy_registry import get_strategy_spec, resolve_strategy_id
from strategy.costs import COST_ROUND_TRIP, ENGINE_COMMISSION_RATE, SLIPPAGE_VALUE, STAMP_TAX_RATE
from strategy.strategies.strategy7.decision import create_decision_engine


def _synthetic_daily() -> pd.DataFrame:
    """构造可触发买入与止损的简易日线（阴线后大阳突破，再回撤止损）。"""
    rows = [
        ("2024-01-02", 10.0, 10.1, 9.8, 9.9),
        ("2024-01-03", 9.9, 10.0, 9.7, 9.8),
        ("2024-01-04", 10.0, 10.40, 9.95, 10.30),
        ("2024-01-05", 10.30, 10.50, 10.20, 10.40),
        ("2024-01-08", 10.40, 10.45, 10.05, 10.10),
        ("2024-01-09", 10.10, 10.15, 9.90, 9.95),
        ("2024-01-10", 9.95, 10.00, 9.80, 9.85),
        ("2024-01-11", 9.90, 10.30, 9.85, 10.20),
        ("2024-01-12", 10.20, 10.25, 10.10, 10.15),
        ("2024-01-15", 10.00, 10.05, 9.60, 9.65),
    ]
    return pd.DataFrame(
        rows, columns=["date", "open", "high", "low", "close"]
    ).assign(volume=1_000_000.0, symbol="sh600330")


class Strategy7RegistryTests(unittest.TestCase):
    def test_registered_name_and_aliases(self) -> None:
        spec = get_strategy_spec("strategy7")
        self.assertEqual(spec.name, "策略七·缠论笔算盈亏比")
        self.assertEqual(resolve_strategy_id("缠论笔算盈亏比"), "strategy7")
        self.assertEqual(resolve_strategy_id("bi_pl_ratio"), "strategy7")
        self.assertEqual(resolve_strategy_id("s7"), "strategy7")
        self.assertEqual(resolve_strategy_id("strategy11"), "strategy7")
        self.assertEqual(resolve_strategy_id("s11"), "strategy7")
        self.assertEqual(resolve_strategy_id("策略七"), "strategy7")
        self.assertEqual(resolve_strategy_id("strategy3"), "strategy3")

    def test_decision_buy_and_stop(self) -> None:
        engine = create_decision_engine()
        flat = MarketContext(
            open=10.0,
            high=10.40,
            low=9.95,
            close=10.30,
            session="2024-01-04",
            prev_open=9.9,
            prev_close=9.8,
            prev2_open=10.0,
            prev2_close=9.9,
            position_qty=0.0,
        )
        buy = engine.decide(flat)
        self.assertEqual(buy.action, "buy")

        held = MarketContext(
            open=10.40,
            high=10.45,
            low=10.05,
            close=10.10,
            session="2024-01-08",
            prev_open=10.30,
            prev_close=10.40,
            position_qty=100.0,
            available_qty=100.0,
            buy_time="2024-01-05 10:00:00",
            meta={"t_plus_one": False},
        )
        sell = engine.decide(held)
        self.assertEqual(sell.action, "sell")


class BiPlRatioCoreTests(unittest.TestCase):
    def test_net_return_applies_project_fees(self) -> None:
        buy, sell = 10.0, 10.5
        gross = sell / buy - 1.0
        net = net_round_trip_return(buy, sell)
        self.assertLess(net, gross)
        buy_eff = buy * (1.0 + SLIPPAGE_VALUE)
        sell_eff = sell * (1.0 - SLIPPAGE_VALUE)
        expected = (
            sell_eff * (1.0 - ENGINE_COMMISSION_RATE - STAMP_TAX_RATE)
        ) / (buy_eff * (1.0 + ENGINE_COMMISSION_RATE)) - 1.0
        self.assertAlmostEqual(net, expected, places=10)
        self.assertGreater(gross - net, 0.002)
        self.assertLess(gross - net, COST_ROUND_TRIP + 0.001)

    def test_cross_bi_sell_attributed_to_buy_bi(self) -> None:
        bi_df = pd.DataFrame(
            [
                {
                    "bi_id": 1,
                    "direction": "up",
                    "sdt": pd.Timestamp("2024-01-01"),
                    "edt": pd.Timestamp("2024-01-10"),
                    "fx_a": 10.0,
                    "fx_b": 12.0,
                    "high": 12.0,
                    "low": 10.0,
                    "length": 6,
                    "struct_ret": 0.2,
                    "snr": 0.5,
                },
                {
                    "bi_id": 2,
                    "direction": "down",
                    "sdt": pd.Timestamp("2024-01-10"),
                    "edt": pd.Timestamp("2024-01-20"),
                    "fx_a": 12.0,
                    "fx_b": 11.0,
                    "high": 12.0,
                    "low": 11.0,
                    "length": 6,
                    "struct_ret": -1 / 12,
                    "snr": 0.5,
                },
            ]
        )
        trades = pd.DataFrame(
            [
                {
                    "buy_date": pd.Timestamp("2024-01-05"),
                    "buy_px": 10.5,
                    "sell_date": pd.Timestamp("2024-01-15"),
                    "sell_px": 11.0,
                    "ret_gross": 11.0 / 10.5 - 1,
                    "ret": 0.04,
                }
            ]
        )
        atr = attribute_trades_to_bis(trades, bi_df)
        self.assertTrue(bool(atr.iloc[0]["cross_bi"]))
        self.assertEqual(int(atr.iloc[0]["attrib_bi"]), 1)
        agg = aggregate_bi_vs_factor1(bi_df, atr)
        self.assertEqual(int(agg.loc[agg.bi_id == 1, "n_trades"].iloc[0]), 1)
        self.assertEqual(int(agg.loc[agg.bi_id == 2, "n_trades"].iloc[0]), 0)

    def test_replay_and_year_stats_on_synthetic(self) -> None:
        daily = _synthetic_daily()
        trades, holding = replay_factor1_trades(daily, entry_pct=0.025)
        self.assertGreaterEqual(len(trades), 1)
        self.assertFalse(holding)
        self.assertTrue((trades["ret"] < trades["ret_gross"]).all())
        years = year_pl_stats(
            attribute_trades_to_bis(
                trades,
                pd.DataFrame(
                    [
                        {
                            "bi_id": 1,
                            "direction": "up",
                            "sdt": pd.Timestamp("2024-01-01"),
                            "edt": pd.Timestamp("2024-12-31"),
                            "fx_a": 9.0,
                            "fx_b": 11.0,
                            "high": 11.0,
                            "low": 9.0,
                            "length": 10,
                            "struct_ret": 2 / 9,
                            "snr": 0.5,
                        }
                    ]
                ),
            )
        )
        self.assertTrue((years["year"] == 2024).any())

    def test_analyze_end_to_end_with_cached_bars(self) -> None:
        path = "/workspace/data_cache/sh600330_daily_qfq.parquet"
        daily = pd.read_parquet(path)
        daily = daily[pd.to_datetime(daily["date"]) >= "2024-01-01"].copy()
        result = analyze_bi_pl_ratio(
            daily,
            symbol="sh600330",
            symbol_name="天通股份",
            entry_pct=0.03,
            out_dir=None,
        )
        self.assertEqual(result.summary["symbol"], "sh600330")
        self.assertGreater(result.summary["n_bis"], 0)
        self.assertIn("pl_ratio", result.summary)
        self.assertTrue(len(result.year_stats) >= 1)


if __name__ == "__main__":
    unittest.main()
