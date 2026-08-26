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
    def test_classify_bull_sideways_bear(self) -> None:
        idx = pd.bdate_range("2024-01-01", periods=120)
        # 先跌后涨：后段应出现 bull
        close = pd.Series(np.linspace(100, 70, 60).tolist() + np.linspace(70, 120, 60).tolist(), index=idx)
        regime = classify_market_regime(close, ma_n=20, roc_n=5)
        self.assertIn("bear", set(regime.iloc[25:55].astype(str)))
        self.assertIn("bull", set(regime.iloc[90:].astype(str)))

    def test_tp_policy_defaults(self) -> None:
        p = resolve_factor4_tp_policy()
        self.assertEqual(p["trigger"], "prev_high")
        self.assertEqual(p["bull_levels"], (0.20, 0.30, 0.40))
        self.assertEqual(p["sideways_levels"], (0.15,))
        self.assertEqual(p["bear_levels"], (0.08, 0.12, 0.18))
        self.assertAlmostEqual(p["bull_reduce"], 1.0 / 3.0)
        self.assertAlmostEqual(p["bear_reduce"], 1.0 / 3.0)
        # 显式空档可关闭牛市止盈；单档也可覆盖
        self.assertEqual(resolve_factor4_tp_policy({"tp_bull": ()})["bull_levels"], ())
        self.assertEqual(
            resolve_factor4_tp_policy({"tp_bull": (0.20,)})["bull_levels"], (0.20,)
        )

    def test_prepare_factor4_wires_regime_tp(self) -> None:
        idx = pd.bdate_range("2023-01-01", periods=200)
        daily = pd.DataFrame(
            {
                "date": idx,
                "open": np.linspace(10, 20, 200),
                "high": np.linspace(10.2, 20.4, 200),
                "low": np.linspace(9.8, 19.6, 200),
                "close": np.linspace(10, 20, 200),
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
        self.assertAlmostEqual(cfg.regime_tp_reduce_bull, 1.0 / 3.0)
        self.assertEqual(cfg.take_profit_trigger, "prev_high")
        strat = apply_strategy_config(OpenBreak3Strategy(), cfg)
        self.assertTrue(strat.regime_tp_enabled)
        self.assertAlmostEqual(strat.regime_tp_reduce_bull, 1.0 / 3.0)
        self.assertAlmostEqual(strat.regime_tp_reduce_bear, 1.0 / 3.0)

        bull_day = next(d for d, r in cfg._regime_by_date.items() if r == "bull")
        other_day = next(d for d, r in cfg._regime_by_date.items() if r != "bull")
        self.assertEqual(strat._effective_tp_levels(bull_day), (0.20, 0.30, 0.40))
        self.assertAlmostEqual(strat._effective_tp_reduce(bull_day), 1.0 / 3.0)
        self.assertTrue(len(strat._effective_tp_levels(other_day)) >= 1)

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
        mapping = market_regime_by_date(daily, ma_n=10, roc_n=5)
        # 次日生效：首日通常无 exec
        self.assertTrue(len(mapping) >= 50)


if __name__ == "__main__":
    unittest.main()
