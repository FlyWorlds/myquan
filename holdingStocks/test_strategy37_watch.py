"""策略三十七盯盘服务与快照集成测试。"""

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

from holdingStocks.strategy37_watch import (
    get_strategy37_watch_payload,
    load_backtest_summary,
    load_recent_signals,
)
from holdingStocks.index import _load_watch_strategy_tabs, WATCH_LIVE_TAB_IDS



class TestStrategy37Watch(unittest.TestCase):
    def test_watch_live_tab_ids(self) -> None:
        self.assertIn("strategy37", WATCH_LIVE_TAB_IDS)

    def test_load_watch_tabs_contains_s37(self) -> None:
        tabs = _load_watch_strategy_tabs()
        s37 = next((t for t in tabs if t["id"] == "strategy37"), None)
        self.assertIsNotNone(s37)
        self.assertTrue(s37.get("watch_tab"))
        self.assertEqual(s37.get("reportPath"), "docs/STRATEGY37.md")
        self.assertIsInstance(s37.get("backtest"), dict)

    def test_strategy37_watch_payload(self) -> None:
        payload = get_strategy37_watch_payload()
        self.assertEqual(payload["strategyId"], "strategy37")
        self.assertIn("kpi", payload)
        self.assertIn("rows", payload)
        self.assertGreaterEqual(len(payload["rows"]), 1)
        # 检验首个信号格式
        first = payload["rows"][0]
        self.assertIn("代码", first)
        self.assertIn("名称", first)
        self.assertIn("买入价", first)
        self.assertIn("跌停价", first)
        self.assertIn("脱离中枢天数", first)


if __name__ == "__main__":
    unittest.main()
