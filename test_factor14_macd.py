"""因子14 MACD 基础单元测试。"""

from __future__ import annotations

import unittest

import pandas as pd

from strategy.core.factor_registry import get_factor
from strategy.macd_timing import compute_macd, macd_signals


class TestFactor14Macd(unittest.TestCase):
    def test_registered(self) -> None:
        import strategy.factors  # noqa: F401

        f = get_factor("factor14")
        self.assertEqual(f.id, "factor14")
        self.assertTrue(f.implemented)

    def test_golden_cross_detected(self) -> None:
        # 构造先跌后涨序列，确保出现 DIF 上穿
        n = 80
        px = pd.Series(
            [100 - i * 0.5 for i in range(40)]
            + [80 + i * 0.8 for i in range(40)]
        )
        sig = macd_signals(px, mode="cross")
        self.assertTrue(bool(sig["buy"].any()) or bool(sig["golden"].any()))
        macd = compute_macd(px)
        self.assertIn("dif", macd.columns)
        self.assertEqual(len(macd), n)

    def test_zero_cross_stricter(self) -> None:
        px = pd.Series(
            [100 - i * 0.3 for i in range(50)]
            + [85 + i * 0.5 for i in range(50)]
        )
        plain = macd_signals(px, mode="cross")
        zero = macd_signals(px, mode="zero_cross")
        # 零轴过滤买入次数应 ≤ 纯金叉
        self.assertLessEqual(int(zero["buy"].sum()), int(plain["buy"].sum()))


if __name__ == "__main__":
    unittest.main()
