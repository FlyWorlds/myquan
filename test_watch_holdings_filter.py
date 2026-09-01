"""持仓 Tab 过滤：定盘池（含协鑫能科）应出现。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_HS = Path(__file__).resolve().parent / "holdingStocks"
if str(_HS) not in sys.path:
    sys.path.insert(0, str(_HS))

from watch_snapshot import filter_portfolio_holdings  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
