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
        self.assertLessEqual(int(zero["buy"].sum()), int(plain["buy"].sum()))

    def test_relaxed_has_extra_columns_and_more_buys(self) -> None:
        px = pd.Series(
            [100 - i * 0.4 for i in range(60)]
            + [76 + i * 0.6 for i in range(60)]
        )
        strict = macd_signals(px, mode="cross")
        soft = macd_signals(px, mode="relaxed")
        for col in (
            "near_golden",
            "almost_golden",
            "golden_trend",
            "near_death",
            "almost_death",
            "death_trend",
        ):
            self.assertIn(col, soft.columns)
        self.assertGreaterEqual(int(soft["buy"].sum()), int(strict["buy"].sum()))


if __name__ == "__main__":
    unittest.main()
