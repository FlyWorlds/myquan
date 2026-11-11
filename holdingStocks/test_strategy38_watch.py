"""策略三十八盯盘服务与快照集成测试。"""

from __future__ import annotations

import sys
from pathlib import Path
import unittest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
_HOLDING = _ROOT / "holdingStocks"
if str(_HOLDING) not in sys.path:
    sys.path.insert(0, str(_HOLDING))

from holdingStocks.strategy38_watch import (
    get_strategy38_watch_payload,
    load_backtest_summary,
)
from holdingStocks.index import _load_watch_strategy_tabs, WATCH_LIVE_TAB_IDS


class TestStrategy38Watch(unittest.TestCase):
    def test_watch_live_tab_ids(self) -> None:
        self.assertIn("strategy38", WATCH_LIVE_TAB_IDS)

    def test_load_watch_tabs_contains_s38(self) -> None:
        tabs = _load_watch_strategy_tabs()
        s38 = next((t for t in tabs if t["id"] == "strategy38"), None)
        self.assertIsNotNone(s38)
        self.assertTrue(s38.get("watch_tab"))
        self.assertEqual(s38.get("reportPath"), "docs/STRATEGY38.md")
        self.assertIsInstance(s38.get("backtest"), dict)
        self.assertEqual(s38["backtest"].get("strategyId"), "strategy38")

    def test_strategy38_watch_payload(self) -> None:
        payload = get_strategy38_watch_payload()
        self.assertEqual(payload["strategyId"], "strategy38")
        self.assertIn("step1", payload)
        self.assertIn("step2", payload)
        self.assertIn("step3", payload)
        self.assertIn("step4", payload)
        self.assertIn("orders", payload)
        self.assertIn("rows", payload)
        self.assertIn("kpi", payload)

        # 检查四步结果
        step1 = payload["step1"]
        self.assertIn(step1["status"], ("PASS", "VETO_CASH"))
        self.assertIn("veto_cash", step1)

        # 检查 Step 4 买单结构
        if payload["orders"]:
            first_order = payload["orders"][0]
            self.assertIn("code", first_order)
            self.assertIn("name", first_order)
            self.assertIn("buy_trigger_price", first_order)
            self.assertIn("support_buy_price", first_order)
            self.assertIn("stop_loss_price", first_order)
            self.assertIn("confirm_logic", first_order)


if __name__ == "__main__":
    unittest.main()
