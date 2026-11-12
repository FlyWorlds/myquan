"""波段模式与尾盘提醒测试 (Boduan Mode & EOD Notify Test)。"""

from __future__ import annotations

from datetime import datetime
import unittest
from unittest.mock import MagicMock, patch

from holdingStocks.watch_config import is_boduan_mode, strategy_watchlist, STRATEGY_ID
from holdingStocks.index import _maybe_eod_boduan_notify
from strategy.strategies.strategy38.scanner import sync_candidates_to_self_watchlist


class TestBoduanMode(unittest.TestCase):
    def test_boduan_mode_enabled(self) -> None:
        self.assertTrue(is_boduan_mode())
        self.assertEqual(STRATEGY_ID, "strategy38")

    def test_eod_notify_message_generation(self) -> None:
        mock_rows = [
            {"代码": "002636", "名称": "金安国纪", "现价": 68.50, "涨跌幅": 1.2},
            {"代码": "600478", "名称": "科力远", "现价": 3.55, "涨跌幅": 2.0},
        ]
        with patch("wechat_notify.send_text") as mock_send:
            mock_send.return_value = (True, "ok")
            # 模拟在 14:45 进行测试调用
            test_time = datetime(2026, 11, 11, 14, 45, 0)
            ok = _maybe_eod_boduan_notify(mock_rows, wechat=True, now=test_time, force_test=True)
            self.assertTrue(ok)
            mock_send.assert_called_once()
            msg = mock_send.call_args[0][0]
            self.assertIn("14:40 尾盘波段决策提醒", msg)
            self.assertIn("半自动API提示", msg)

    def test_sync_to_self_watchlist(self) -> None:
        orders = [{
            "code": "600478",
            "name": "科力远",
            "last_close": 3.48,
            "breakout_close": 3.45,
            "confirm_logic": "测试底分型起爆",
        }]
        with patch("holdingStocks.runtime_documents.read_document") as mock_read, \
             patch("holdingStocks.runtime_documents.write_document") as mock_write:
            mock_read.return_value = (1, {"items": [], "removed": {}})
            mock_write.return_value = 2

            res = sync_candidates_to_self_watchlist(orders, replace=False, top_n=1)
            self.assertTrue(res["success"])
            self.assertEqual(res["revision"], 2)
            self.assertIn("600478", res["added_codes"])
            mock_write.assert_called_once()


if __name__ == "__main__":
    unittest.main()
