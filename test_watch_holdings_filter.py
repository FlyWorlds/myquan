"""持仓 Tab 过滤：定盘池（含协鑫能科）应出现。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_HS = Path(__file__).resolve().parent / "holdingStocks"
if str(_HS) not in sys.path:
    sys.path.insert(0, str(_HS))

from watch_snapshot import filter_portfolio_holdings, _strip_holdings_pnl  # noqa: E402


class TestHoldingsTabFilter(unittest.TestCase):
    def test_fit_pool_xiexin_shown(self) -> None:
        rows = [
            {"代码": "600338", "名称": "西藏珠峰", "持仓": 700, "持仓状态": "持有"},
            {"代码": "002015", "名称": "协鑫能科", "持仓": 0, "持仓状态": "待买入"},
            {"代码": "999999", "名称": "场外", "持仓": 0, "持仓状态": "空仓"},
        ]
        out = filter_portfolio_holdings(rows)
        codes = [str(r["代码"]) for r in out]
        self.assertIn("600338", codes)
        self.assertIn("002015", codes)
        self.assertNotIn("999999", codes)

    def test_strip_holdings_pnl_for_strategy_tab(self) -> None:
        row = {
            "代码": "600967",
            "名称": "内蒙一机",
            "浮盈": 120.5,
            "浮盈%": 3.2,
            "策略收益": 88.0,
            "策略收益%": 2.1,
            "盈亏状态": "浮盈",
            "bg_class": "warn-buy",
        }
        out = _strip_holdings_pnl(row)
        self.assertNotIn("浮盈", out)
        self.assertNotIn("策略收益", out)
        self.assertEqual(out["策略收益%"], 2.1)
        self.assertEqual(out["bgClass"], "warn-buy")


if __name__ == "__main__":
    unittest.main()
