"""纸面整笔交易收益口径。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[1]
_HOLD = Path(__file__).resolve().parent
for p in (str(_ROOT), str(_HOLD)):
    if p not in sys.path:
        sys.path.insert(0, p)

import index as idx  # noqa: E402
import strategy_simulator as sim  # noqa: E402


class TestComprehensiveTradeReturn(unittest.TestCase):
    def test_replay_partial_exits_use_total_profit_over_original_cost(self) -> None:
        book = sim.empty_book(strategy_id="strategy16", symbol="123456")
        sim.bootstrap_book_from_factor26_replay(book, {
            "source": "1m",
            "trades": [
                {"side": "buy", "px": 10, "ts": "2026-10-12 10:00:00"},
                {"side": "sell", "px": 11, "shares": 4000, "ts": "2026-10-13 10:00:00"},
                {"side": "sell", "px": 12, "ts": "2026-10-13 11:00:00"},
            ],
        }, persist=False)
        row = {"代码": "123456", "持仓": 0, "持仓状态": "今日平仓"}
        sim.apply_book_to_row(row, book)
        with patch.object(idx, "_paper_trade_cycle_return", return_value=None):
            idx._enrich_comprehensive_trade_return(row)
        self.assertEqual(row["综合单笔成本额"], 95000)
        self.assertEqual(row["综合单笔收入"], 15000)
        self.assertEqual(row["综合单笔收入%"], 15.79)
        self.assertEqual(row["综合单笔来源"], "strategy_simulator_cycle")

    def test_virtual_holding_marks_without_paper_trades(self) -> None:
        row = {"代码": "123456", "持仓": 0, "策略入场价": 10,
               "策略虚拟股数": 1000, "现价": 11, "持仓状态": "今日平仓"}
        with patch.object(idx, "_paper_trade_cycle_return", return_value=None):
            idx._enrich_comprehensive_trade_return(row)
        self.assertEqual(row["综合单笔收入"], 1000)
        self.assertEqual(row["综合单笔收入%"], 10)

    def test_virtual_partial_exit_marks_latest_quote(self) -> None:
        row = {"代码": "123456", "持仓": 0, "策略入场价": 10,
               "策略虚拟股数": 600, "现价": 12, "策略单笔成本额": 10000,
               "策略单笔收益": 1000, "策略单笔已实现收益": 400}
        with patch.object(idx, "_paper_trade_cycle_return", return_value=None):
            idx._enrich_comprehensive_trade_return(row)
        self.assertEqual(row["综合单笔收入"], 1600)
        self.assertEqual(row["综合单笔收入%"], 16)

    def test_missing_cycle_clears_stale_comprehensive_value(self) -> None:
        row = {"代码": "123456", "综合单笔收入%": 14.99, "综合单笔收入": 1234}
        with patch.object(idx, "_paper_trade_cycle_return", return_value=None):
            idx._enrich_comprehensive_trade_return(row)
        self.assertNotIn("综合单笔收入%", row)

    def test_comprehensive_return_merges_partial_sells(self) -> None:
        text = "\n".join(
            [
                '{"time":"2026-10-13 09:32:00","side":"buy","code":"002636","price":61.50,"qty":900,"after_qty":900,"avg_cost":61.50}',
                '{"time":"2026-10-14 09:31:00","side":"sell","code":"002636","price":67.65,"qty":400,"after_qty":500,"cost":61.50,"pnl":2460.0,"session":"2026-10-14","action_kind":"half","buy_time":"2026-10-13 09:32:00"}',
                '{"time":"2026-10-14 09:31:00","side":"sell","code":"002636","price":67.65,"qty":200,"after_qty":300,"cost":61.50,"pnl":1230.0,"session":"2026-10-14","action_kind":"half","buy_time":"2026-10-13 09:32:00"}',
                '{"time":"2026-10-14 10:01:00","side":"sell","code":"002636","price":70.72,"qty":300,"after_qty":0,"cost":61.50,"pnl":2766.0,"session":"2026-10-14","action_kind":"full","buy_time":"2026-10-13 09:32:00"}',
            ]
        )
        row = {"代码": "002636", "持仓": 0, "买入时间": "2026-10-13 09:32:00"}

        rec = idx._paper_trade_cycle_return(row, trades_text=text)

        self.assertIsNotNone(rec)
        assert rec is not None
        self.assertEqual(rec["pnl"], 6456.0)
        self.assertEqual(rec["base"], 55350.0)
        self.assertEqual(rec["pnl_pct"], 11.66)
        self.assertEqual(rec["sold_qty"], 900)
        self.assertEqual(rec["legs"], 3)

    def test_comprehensive_return_includes_open_mark_to_market(self) -> None:
        text = "\n".join(
            [
                '{"time":"2026-10-13 09:32:00","side":"buy","code":"002636","price":61.50,"qty":900,"after_qty":900,"avg_cost":61.50}',
                '{"time":"2026-10-14 09:31:00","side":"sell","code":"002636","price":67.65,"qty":400,"after_qty":500,"cost":61.50,"pnl":2460.0,"session":"2026-10-14","action_kind":"half","buy_time":"2026-10-13 09:32:00"}',
            ]
        )
        row = {
            "代码": "002636",
            "持仓": 500,
            "成本": 61.50,
            "现价": 68.00,
            "买入时间": "2026-10-13 09:32:00",
        }

        rec = idx._paper_trade_cycle_return(row, trades_text=text)

        self.assertIsNotNone(rec)
        assert rec is not None
        self.assertEqual(rec["pnl"], 5710.0)
        self.assertEqual(rec["base"], 55350.0)
        self.assertEqual(rec["pnl_pct"], 10.32)
        self.assertEqual(rec["sold_qty"], 400)
        self.assertEqual(rec["open_qty"], 500)
        self.assertEqual(rec["legs"], 2)

    def test_comprehensive_return_accepts_code_alias(self) -> None:
        text = "\n".join(
            [
                '{"time":"2026-10-13 09:32:00","side":"buy","code":"002636","price":61.50,"qty":900,"after_qty":900,"avg_cost":61.50}',
                '{"time":"2026-10-14 10:01:00","side":"sell","code":"002636","price":70.72,"qty":900,"after_qty":0,"cost":61.50,"pnl":8298.0,"session":"2026-10-14","action_kind":"full","buy_time":"2026-10-13 09:32:00"}',
            ]
        )
        row = {"code": "002636", "持仓": 0, "buy_time": "2026-10-13 09:32:00"}

        rec = idx._paper_trade_cycle_return(row, trades_text=text)

        self.assertIsNotNone(rec)
        assert rec is not None
        self.assertEqual(rec["pnl_pct"], 14.99)

    def test_snapshot_outbound_enriches_strategy16_rows(self) -> None:
        snap = {
            "holdings": [],
            "strategy16": [
                {
                    "代码": "002636",
                    "名称": "金安国纪",
                    "持仓状态": "今日平仓",
                    "持仓": 0,
                    "单笔收入%": 14.99,
                }
            ],
            "strategy16b": [],
        }
        with patch.object(
            idx,
            "_paper_trade_cycle_return",
            return_value={
                "pnl": 6456.0,
                "pnl_pct": 11.66,
                "base": 55350.0,
                "sold_qty": 900,
                "open_qty": 0,
                "legs": 3,
                "source": "trades_jsonl_cycle",
            },
        ):
            changed = idx._enrich_snapshot_comprehensive_trade_returns(snap)

        row = snap["strategy16"][0]
        self.assertTrue(changed)
        self.assertEqual(row["综合单笔收入%"], 11.66)
        self.assertEqual(row["综合单笔收入"], 6456.0)
        self.assertEqual(row["综合单笔腿数"], 3)


if __name__ == "__main__":
    unittest.main()
