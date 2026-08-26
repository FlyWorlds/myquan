"""因子4 行情三态与止盈政策单测。"""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from strategy.bull_regime import (
    classify_market_regime,
    market_regime_by_date,
    resolve_factor4_tp_policy,
)
from strategy.config import BacktestConfig
from strategy.factors.factor4 import factor4_signal, is_bull_regime
from strategy.runner import apply_strategy_config, prepare_factor4
from strategy.backtest import OpenBreak3Strategy


class Factor4RegimeTests(unittest.TestCase):
    def test_classify_ma_cross_bull_bear(self) -> None:
        idx = pd.bdate_range("2024-01-01", periods=120)
        # 先跌后涨：后段应出现 bull，中段 bear
        close = pd.Series(
            np.linspace(100, 70, 60).tolist() + np.linspace(70, 120, 60).tolist(),
            index=idx,
        )
        regime = classify_market_regime(
            close, method="ma_cross", ma_fast=5, ma_slow=10, entangle_pct=0.005
        )
        self.assertIn("bear", set(regime.iloc[20:50].astype(str)))
        self.assertIn("bull", set(regime.iloc[90:].astype(str)))

    def test_classify_legacy_roc_ma_still_works(self) -> None:
        idx = pd.bdate_range("2024-01-01", periods=120)
        close = pd.Series(
            np.linspace(100, 70, 60).tolist() + np.linspace(70, 120, 60).tolist(),
            index=idx,
        )
        regime = classify_market_regime(close, method="roc_ma", ma_n=20, roc_n=5)
        self.assertIn("bear", set(regime.iloc[25:55].astype(str)))
        self.assertIn("bull", set(regime.iloc[90:].astype(str)))

    def test_tp_policy_defaults(self) -> None:
        p = resolve_factor4_tp_policy()
        self.assertEqual(p["trigger"], "prev_high")
        self.assertEqual(p["regime_method"], "ma_cross")
        self.assertEqual(p["ma_fast"], 5)
        self.assertEqual(p["ma_slow"], 10)
        self.assertEqual(p["bull_levels"], (0.20, 0.30, 0.40))
        self.assertEqual(p["sideways_levels"], (0.10, 0.15, 0.20))
        self.assertEqual(p["bear_levels"], (0.05, 0.10, 0.15))
        self.assertAlmostEqual(p["bull_reduce"], 1.0 / 3.0)
        self.assertAlmostEqual(p["sideways_reduce"], 1.0 / 3.0)
        self.assertAlmostEqual(p["bear_reduce"], 1.0 / 3.0)
        self.assertEqual(resolve_factor4_tp_policy({"tp_bull": ()})["bull_levels"], ())
        self.assertEqual(
            resolve_factor4_tp_policy({"tp_bull": (0.20,)})["bull_levels"], (0.20,)
        )

    def test_prepare_factor4_wires_regime_tp(self) -> None:
        idx = pd.bdate_range("2023-01-01", periods=200)
        # 制造金叉：前半跌后半涨
        close = np.concatenate(
            [np.linspace(20, 10, 100), np.linspace(10, 22, 100)]
        )
        daily = pd.DataFrame(
            {
                "date": idx,
                "open": close,
                "high": close * 1.01,
                "low": close * 0.99,
                "close": close,
                "volume": 1_000_000,
            }
        )
        cfg = BacktestConfig(
            symbol="sh600552",
            symbol_name="凯盛科技",
            em_symbol="600552",
            factor4_enabled=True,
            factor4_regime_tp=True,
        )
        prepare_factor4(cfg, daily)
        self.assertTrue(cfg.regime_tp_enabled)
        self.assertTrue(bool(cfg._regime_by_date))
        self.assertEqual(cfg.regime_tp_bull, (0.20, 0.30, 0.40))
        self.assertEqual(cfg.regime_tp_sideways, (0.10, 0.15, 0.20))
        self.assertEqual(cfg.regime_tp_bear, (0.05, 0.10, 0.15))
        self.assertAlmostEqual(cfg.regime_tp_reduce_bull, 1.0 / 3.0)
        self.assertAlmostEqual(cfg.regime_tp_reduce_sideways, 1.0 / 3.0)
        self.assertEqual(cfg.take_profit_trigger, "prev_high")
        strat = apply_strategy_config(OpenBreak3Strategy(), cfg)
        self.assertTrue(strat.regime_tp_enabled)

        bull_day = next(d for d, r in cfg._regime_by_date.items() if r == "bull")
        self.assertEqual(strat._effective_tp_levels(bull_day), (0.20, 0.30, 0.40))
        self.assertAlmostEqual(strat._effective_tp_reduce(bull_day), 1.0 / 3.0)

    def test_legacy_repair_disables_auto_tp(self) -> None:
        idx = pd.bdate_range("2023-01-01", periods=100)
        daily = pd.DataFrame(
            {
                "date": idx,
                "open": np.linspace(10, 12, 100),
                "high": np.linspace(10.2, 12.2, 100),
                "low": np.linspace(9.8, 11.8, 100),
                "close": np.linspace(10, 12, 100),
                "volume": 1_000_000,
            }
        )
        cfg = BacktestConfig(
            symbol="sh600552",
            symbol_name="凯盛科技",
            em_symbol="600552",
            factor4_enabled=True,
            factor4_regime_tp=False,
            factor4_stop_widen_mult=2.0,
        )
        prepare_factor4(cfg, daily)
        self.assertFalse(cfg.regime_tp_enabled)

    def test_signal_and_bull_helper(self) -> None:
        self.assertTrue(is_bull_regime(1.0))
        self.assertFalse(is_bull_regime(0.0))
        sig = factor4_signal(regime="bear", params={"tp_bear": (0.1, 0.2)})
        self.assertEqual(sig["regime"], "bear")
        self.assertEqual(sig["stop_policy"], "threshold_full_exit")
        self.assertEqual(sig["tp_policy"]["bear_levels"], (0.1, 0.2))

    def test_market_regime_by_date_shift(self) -> None:
        idx = pd.bdate_range("2024-01-01", periods=80)
        close = pd.Series(np.linspace(50, 100, 80), index=idx)
        daily = pd.DataFrame({"date": idx, "close": close})
        mapping = market_regime_by_date(
            daily, method="ma_cross", ma_fast=5, ma_slow=10
        )
        self.assertTrue(len(mapping) >= 50)


if __name__ == "__main__":
    unittest.main()
