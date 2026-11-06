"""单元测试：策略三十五盯盘服务与择时判定接口 (test_strategy35_watch.py)。"""

from __future__ import annotations

import unittest
from holdingStocks.strategy35_watch import get_strategy35_timing_payload
from strategy.strategies.strategy35.decision import Strategy35Decision
from strategy.core.context import MarketContext


class TestStrategy35Watch(unittest.TestCase):
    def test_get_strategy35_timing_payload(self) -> None:
        p = get_strategy35_timing_payload(force_refresh=True)
        self.assertIsNotNone(p)
        self.assertIn("current", p)
        self.assertIn("thresholds", p)
        self.assertIn("history", p)
        self.assertIn("cash_intervals", p)
        self.assertIn("rules", p)

        cur = p["current"]
        self.assertIn("is_cash", cur)
        self.assertIn("status_label", cur)
        self.assertIn("reason", cur)
        self.assertIn("breakdown", cur)
        self.assertIn("macro_trend", cur["breakdown"])
        self.assertIn("market_breadth", cur["breakdown"])
        self.assertIn("extreme_panic", cur["breakdown"])
        self.assertIn("exit_progress", cur["breakdown"])

        self.assertGreater(len(p["history"]), 30)

    def test_strategy35_decision_engine(self) -> None:
        engine = Strategy35Decision()

        # 1. 模拟空仓触发场景
        ctx_cash = MarketContext(
            open=10.0,
            high=10.2,
            low=9.8,
            close=9.9,
            session="2026-11-05",
            position_qty=0.0,
        )
        ctx_cash.macro = {
            "index_close": 6000.0,
            "index_ma60": 7000.0,
            "market_breadth_ma20": 0.20,
            "current_cash_state": False,
        }
        dec = engine.decide(ctx_cash)
        self.assertIn("cash_defensive", dec.meta.get("tags", ()))

        # 2. 模拟正常多头场景
        ctx_normal = MarketContext(
            open=10.0,
            high=10.5,
            low=9.9,
            close=10.4,
            session="2026-11-05",
            position_qty=0.0,
        )
        ctx_normal.macro = {
            "index_close": 7500.0,
            "index_ma60": 7000.0,
            "market_breadth_ma20": 0.65,
            "current_cash_state": False,
        }
        dec_normal = engine.decide(ctx_normal)
        self.assertIn("risk_on", dec_normal.meta.get("tags", ()))


if __name__ == "__main__":
    unittest.main()
