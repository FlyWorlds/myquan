"""策略回放持有时买入信号叠加 — 回归测试。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_HS = Path(__file__).resolve().parent / "holdingStocks"
if str(_HS) not in sys.path:
    sys.path.insert(0, str(_HS))

from index import (  # noqa: E402
    _enrich_side_price_fields,
    _finalize_position_row,
    _overlay_buy_signal_on_hold,
)


class WatchBuyOverlayTests(unittest.TestCase):
    def test_paper_hold_hit_buy_overlays_trigger(self) -> None:
        sig = {
            "alert": "持有",
            "bg_class": "status-hold",
            "持仓状态": "持有",
            "因子侧": "持有",
            "pending_sell": False,
        }
        out = _overlay_buy_signal_on_hold(
            sig,
            hit_buy=True,
            allow_entry=True,
            paper_active=True,
            qty=0,
            buy_time=None,
            session="2026-09-01",
            buy_trigger=15.43,
            stop_px=14.67,
            last_px=15.50,
            px_digits=2,
        )
        self.assertEqual(out["alert"], "已触买")
        self.assertEqual(out["持仓状态"], "待买入")
        self.assertIn("买入侧@15.43", out["挂单说明"])
        self.assertIn("卖出侧(止损)@14.67", out["挂单说明"])

    def test_overnight_real_hold_skips_buy_overlay(self) -> None:
        sig = {"alert": "持有", "bg_class": "status-hold"}
        out = _overlay_buy_signal_on_hold(
            sig,
            hit_buy=True,
            allow_entry=True,
            paper_active=False,
            qty=100,
            buy_time="2026-08-30",
            session="2026-09-01",
            buy_trigger=15.43,
            stop_px=14.67,
            last_px=15.50,
            px_digits=2,
        )
        self.assertEqual(out["alert"], "持有")

    def test_finalize_keeps_buy_on_paper_hold(self) -> None:
        row = {
            "策略回放持有": True,
            "持仓": 0,
            "预警": "已触买",
            "持仓状态": "待买入",
            "因子侧": "买入",
            "bg_class": "warn-buy",
            "近买点": True,
            "买点": 15.43,
        }
        _finalize_position_row(row)
        self.assertEqual(row["持仓状态"], "待买入")
        self.assertTrue(row["可执行"])

    def test_enrich_side_prices(self) -> None:
        row = {
            "阈值就绪": True,
            "买点": 15.43,
            "止损": 14.67,
            "价位小数": 2,
            "挂单说明": "持有中",
        }
        _enrich_side_price_fields(row)
        self.assertEqual(row["买入侧价"], 15.43)
        self.assertEqual(row["卖出侧价"], 14.67)
        self.assertIn("买入侧@15.43", row["挂单说明"])
        self.assertIn("卖出侧@14.67", row["挂单说明"])


if __name__ == "__main__":
    unittest.main()
