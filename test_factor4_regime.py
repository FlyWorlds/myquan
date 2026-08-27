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
    def test_weak_cross_stays_sideways(self) -> None:
        """开启力度门槛时，弱交叉可不切入粘性状态。"""
        idx = pd.bdate_range("2024-01-01", periods=40)
        close = pd.Series(100 + 0.2 * np.sin(np.linspace(0, 8 * np.pi, 40)), index=idx)
        regime = classify_market_regime(
            close,
            method="ma_cross",
            ma_fast=5,
            ma_slow=10,
            strength_min=0.015,
        )
        share_side = float((regime.astype(str) == "sideways").mean())
        self.assertGreaterEqual(share_side, 0.7)

    def test_sticky_after_golden_cross(self) -> None:
        """有效金叉后应保持牛市，即使中途价差收窄。"""
        idx = pd.bdate_range("2024-01-01", periods=80)
        down = np.linspace(100, 70, 30)
        up = np.linspace(70, 110, 25)
        flat = np.full(25, 110.0) + 0.05 * np.sin(np.linspace(0, 4 * np.pi, 25))
        close = pd.Series(np.concatenate([down, up, flat]), index=idx)
        regime = classify_market_regime(
            close, method="ma_cross", ma_fast=5, ma_slow=10, strength_min=0.01
        )
        self.assertIn("bull", set(regime.iloc[50:].astype(str)))
        bull_share = float((regime.iloc[55:].astype(str) == "bull").mean())
        self.assertGreaterEqual(bull_share, 0.8)

    def test_classify_ma_cross_bull_bear(self) -> None:
        idx = pd.bdate_range("2024-01-01", periods=120)
        # 先涨→再跌→再涨，确保出现死叉与金叉事件
        close = pd.Series(
            np.linspace(80, 110, 30).tolist()
            + np.linspace(110, 70, 40).tolist()
            + np.linspace(70, 130, 50).tolist(),
            index=idx,
        )
        regime = classify_market_regime(
            close,
            method="ma_cross",
            ma_fast=5,
            ma_slow=10,
            strength_min=0.005,
        )
        self.assertIn("bear", set(regime.astype(str)))
        self.assertIn("bull", set(regime.iloc[80:].astype(str)))
        last_flip = None
        for i, v in enumerate(regime.astype(str)):
            if v == "bull" and (i == 0 or str(regime.iloc[i - 1]) != "bull"):
                last_flip = i
        self.assertIsNotNone(last_flip)
        self.assertTrue(all(str(x) == "bull" for x in regime.iloc[last_flip:]))

    def test_classify_legacy_roc_ma_still_works(self) -> None:
        idx = pd.bdate_range("2024-01-01", periods=120)
        close = pd.Series(
            np.linspace(100, 70, 60).tolist() + np.linspace(70, 120, 60).tolist(),
            index=idx,
        )
        regime = classify_market_regime(close, method="roc_ma", ma_n=20, roc_n=5)
        self.assertIn("bear", set(regime.iloc[25:55].astype(str)))
        self.assertIn("bull", set(regime.iloc[90:].astype(str)))

    def test_classify_macd_cross_sticky(self) -> None:
        """MACD 金叉后粘性保持牛市，直到死叉。"""
        idx = pd.bdate_range("2024-01-01", periods=160)
        close = pd.Series(
            np.linspace(120, 80, 50).tolist()
            + np.linspace(80, 140, 60).tolist()
            + np.linspace(140, 90, 50).tolist(),
            index=idx,
        )
        regime = classify_market_regime(close, method="macd_cross")
        states = set(regime.astype(str))
        self.assertIn("bull", states)
        self.assertIn("bear", states)
        # 中段上涨后应进入 bull 并粘性保持一段
        bull_idx = [i for i, v in enumerate(regime.astype(str)) if v == "bull"]
        self.assertGreaterEqual(len(bull_idx), 10)
        first_bull = bull_idx[0]
        # 从首个 bull 起直到首次 bear，中间不应跳到 sideways
        mid = regime.iloc[first_bull:]
        for v in mid.astype(str):
            if v == "bear":
                break
            self.assertEqual(v, "bull")

    def test_classify_macd_pattern_stages(self) -> None:
        """水下金叉→震，上穿零轴/水上金叉→牛，死叉降档。"""
        idx = pd.bdate_range("2024-01-01", periods=200)
        # 深跌 → 反弹过零轴 → 再冲高 → 回落
        close = pd.Series(
            np.linspace(120, 60, 60).tolist()
            + np.linspace(60, 100, 50).tolist()
            + np.linspace(100, 140, 40).tolist()
            + np.linspace(140, 90, 50).tolist(),
            index=idx,
        )
        regime = classify_market_regime(close, method="macd_pattern")
        self.assertIn("sideways", set(regime.astype(str)))
        self.assertIn("bull", set(regime.astype(str)))
        self.assertIn("bear", set(regime.astype(str)))
        p = resolve_factor4_tp_policy({"regime_method": "macd_pattern"})
        self.assertEqual(p["regime_method"], "macd_pattern")
        self.assertEqual(p["macd_div_lookback"], 30)

    def test_ma_entry_gate_blocks_death(self) -> None:
        """死叉区间不允许开仓；金叉后允许。"""
        from strategy.bull_regime import ma_cross_entry_gate_series

        idx = pd.bdate_range("2024-01-01", periods=80)
        close = pd.Series(
            np.linspace(100, 70, 35).tolist() + np.linspace(70, 120, 45).tolist(),
            index=idx,
        )
        gate = ma_cross_entry_gate_series(close, approach_gap=0.01, require_gap_shrink=False)
        # 前段下跌应大量 death_block / 不允许
        early = gate.iloc[15:30]
        self.assertGreaterEqual(float((~early["entry_allowed_raw"]).mean()), 0.7)
        # 后段上涨金叉后应允许
        late = gate.iloc[55:]
        self.assertGreaterEqual(float(late["entry_allowed_raw"].mean()), 0.5)
        self.assertTrue(bool(late["golden_trend"].any()))

    def test_tp_policy_defaults(self) -> None:
        p = resolve_factor4_tp_policy()
        self.assertEqual(p["trigger"], "prev_high")
        self.assertEqual(p["regime_method"], "ma_cross")
        self.assertEqual(p["ma_fast"], 5)
        self.assertEqual(p["ma_slow"], 10)
        self.assertEqual(p["macd_fast"], 12)
        self.assertEqual(p["macd_slow"], 26)
        self.assertEqual(p["macd_signal"], 9)
        self.assertAlmostEqual(p["strength_min"], 0.0)
        self.assertAlmostEqual(p["slope_weight"], 0.5)
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
        # 先涨后跌再涨，保证有有效金叉切入牛
        close = np.concatenate(
            [
                np.linspace(12, 18, 40),
                np.linspace(18, 10, 60),
                np.linspace(10, 22, 100),
            ]
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
            factor4_params={"regime_strength_min": 0.005},
        )
        prepare_factor4(cfg, daily)
        self.assertTrue(cfg.regime_tp_enabled)
        self.assertTrue(bool(cfg._regime_by_date))
        self.assertEqual(cfg.regime_tp_bull, (0.20, 0.30, 0.40))
        self.assertEqual(cfg.regime_tp_sideways, (0.10, 0.15, 0.20))
        self.assertEqual(cfg.regime_tp_bear, (0.05, 0.10, 0.15))
        self.assertTrue(any(r == "bull" for r in cfg._regime_by_date.values()))
        strat = apply_strategy_config(OpenBreak3Strategy(), cfg)
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
            daily, method="ma_cross", ma_fast=5, ma_slow=10, strength_min=0.005
        )
        self.assertTrue(len(mapping) >= 50)


if __name__ == "__main__":
    unittest.main()
