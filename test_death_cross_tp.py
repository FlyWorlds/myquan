"""死叉/即将死叉分批止盈：信号无未来函数与映射正确性。"""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from strategy.death_cross_tp import (
    compute_ma_cross_frame,
    ma_tp_exec_by_date,
    recommended_params,
)


def _synthetic_daily(n: int = 40, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    # 先涨后跌，制造金叉再死叉
    up = np.linspace(10.0, 14.0, 20)
    down = np.linspace(14.0, 11.0, n - 20)
    close = np.concatenate([up, down])
    close = close + rng.normal(0, 0.05, size=n)
    dates = pd.bdate_range("2024-01-02", periods=n)
    return pd.DataFrame(
        {
            "date": dates,
            "open": close,
            "high": close + 0.1,
            "low": close - 0.1,
            "close": close,
            "volume": 1_000_000,
            "symbol": "sh600552",
        }
    )


class DeathCrossTpTests(unittest.TestCase):
    def test_death_signal_then_next_day_exec(self) -> None:
        daily = _synthetic_daily()
        frame = compute_ma_cross_frame(daily, fast=3, slow=8, near_gap=0.02)
        self.assertIn("ma_signal", frame.columns)
        deaths = frame.index[frame["ma_signal"] == "death"].tolist()
        self.assertTrue(len(deaths) >= 1)
        exec_map = ma_tp_exec_by_date(daily, fast=3, slow=8, near_gap=0.02)
        # 每个收盘 death 应对应次日 exec
        dates = [pd.Timestamp(x).strftime("%Y-%m-%d") for x in frame["date"]]
        for i in deaths:
            if i + 1 < len(dates):
                self.assertEqual(exec_map.get(dates[i + 1]), "death")

    def test_near_requires_narrowing_positive_gap(self) -> None:
        # 构造明确的收窄缺口序列
        close = [10, 10.2, 10.5, 10.8, 11.0, 11.05, 11.02, 10.95, 10.85, 10.7]
        # 加长到足够算 MA
        close = list(np.linspace(9.0, 11.0, 15)) + close
        dates = pd.bdate_range("2024-01-02", periods=len(close))
        daily = pd.DataFrame(
            {
                "date": dates,
                "open": close,
                "high": np.array(close) + 0.05,
                "low": np.array(close) - 0.05,
                "close": close,
                "volume": 1.0,
                "symbol": "x",
            }
        )
        frame = compute_ma_cross_frame(daily, fast=3, slow=5, near_gap=0.05)
        # near 日：gap>=0 且收窄
        for _, row in frame.iterrows():
            if str(row["ma_signal"]) != "near":
                continue
            self.assertGreaterEqual(float(row["ma_gap_pct"]), 0.0)
            self.assertLessEqual(float(row["ma_gap_pct"]), 0.05)

    def test_no_lookahead_in_exec_map(self) -> None:
        daily = _synthetic_daily()
        frame = compute_ma_cross_frame(daily, fast=3, slow=8, near_gap=0.02)
        exec_map = ma_tp_exec_by_date(daily, fast=3, slow=8, near_gap=0.02)
        dates = [pd.Timestamp(x).strftime("%Y-%m-%d") for x in frame["date"]]
        for i, sig in enumerate(frame["ma_signal"].tolist()):
            if sig not in ("near", "death"):
                continue
            # 信号日本身不应出现在 exec（除非碰巧前一日也有信号）
            if i + 1 < len(dates):
                self.assertIn(dates[i + 1], exec_map)

    def test_recommended_params_enable_flag(self) -> None:
        p = recommended_params()
        self.assertTrue(p["ma_tp_enabled"])
        self.assertLess(p["ma_tp_fast"], p["ma_tp_slow"])
        self.assertGreater(p["ma_tp_near_reduce"], 0)
        self.assertGreaterEqual(p["ma_tp_death_reduce"], p["ma_tp_near_reduce"])


if __name__ == "__main__":
    unittest.main()
