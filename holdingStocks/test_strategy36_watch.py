"""单元测试：策略三十六盯盘服务与择时判定接口 (test_strategy36_watch.py)。"""

from __future__ import annotations

import unittest
from holdingStocks.strategy36_watch import get_strategy36_timing_payload
from strategy.strategies.strategy36.decision import Strategy36Decision
from strategy.core.context import MarketContext


class TestStrategy36Watch(unittest.TestCase):
    def test_get_strategy36_timing_payload(self) -> None:
        p = get_strategy36_timing_payload(force_refresh=True)
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
        self.assertIn("cyb_trend", cur["breakdown"])
        self.assertIn("peer_indices", cur["breakdown"])
        self.assertIn("tech_breadth", cur["breakdown"])
        self.assertIn("extreme_panic", cur["breakdown"])
        self.assertIn("exit_progress", cur["breakdown"])

        self.assertGreater(len(p["history"]), 30)

    def test_strategy36_decision_engine(self) -> None:
        engine = Strategy36Decision()

        # 1. 模拟科技空仓触发场景 (持有创业板科技票 300017)
        ctx_cash = MarketContext(
            open=10.0,
            high=10.2,
            low=9.8,
            close=9.9,
            session="2026-11-05",
            position_qty=1000.0,
            meta={"symbol": "300017", "t_plus_one": False},
        )
        ctx_cash.macro = {
            "cyb_close": 2400.0,
            "cyb_ma60": 2600.0,
            "sz_close": 10500.0,
            "sz_ma60": 11000.0,
            "tech_breadth_ma20": 0.20,
            "current_tech_cash_state": False,
            "is_tech_sector": True,
        }
        dec = engine.decide(ctx_cash)
        self.assertEqual(dec.action, "sell")
        self.assertIn("tech_cash_gate", dec.meta.get("tags", ()))

        # 2. 模拟正常多头场景
        ctx_normal = MarketContext(
            open=10.0,
            high=10.5,
            low=9.9,
            close=10.4,
            session="2026-11-05",
            position_qty=0.0,
            meta={"symbol": "300017"},
        )
        ctx_normal.macro = {
            "cyb_close": 2700.0,
            "cyb_ma20": 2650.0,
            "cyb_ma60": 2550.0,
            "tech_breadth_ma20": 0.60,
            "current_tech_cash_state": False,
        }
        dec_normal = engine.decide(ctx_normal)
        self.assertIn("tech_risk_on", dec_normal.meta.get("tags", ()))


if __name__ == "__main__":
    unittest.main()
