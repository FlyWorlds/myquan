"""持仓 Tab 过滤：定盘池（含协鑫能科）应出现。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_HS = Path(__file__).resolve().parent / "holdingStocks"
if str(_HS) not in sys.path:
    sys.path.insert(0, str(_HS))

from quote_feed import fill_preopen_ohlc  # noqa: E402
from watch_snapshot import (  # noqa: E402
    filter_portfolio_holdings,
    retain_last_snapshot,
    should_keep_last_snapshot,
    _strip_holdings_pnl,
)


class TestHoldingsTabFilter(unittest.TestCase):
    def test_fit_pool_xiexin_shown(self) -> None:
        rows = [
            {"代码": "600338", "名称": "西藏珠峰", "持仓": 700, "持仓状态": "持有"},
            {
                "代码": "002015",
                "名称": "协鑫能科",
                "持仓": 0,
                "持仓状态": "待买入",
                "当日预警": True,
            },
            {"代码": "999999", "名称": "场外", "持仓": 0, "持仓状态": "空仓"},
        ]
        out = filter_portfolio_holdings(
            rows,
            phase="continuous",
            strategy_codes={"600338", "002015"},
        )
        codes = [str(r["代码"]) for r in out]
        self.assertIn("600338", codes)
        self.assertIn("002015", codes)
        self.assertNotIn("999999", codes)

    def test_error_qty_kept_pre_auction(self) -> None:
        rows = [
            {
                "代码": "000070",
                "名称": "特发信息",
                "持仓": 5500,
                "持仓状态": "持有",
                "error": "无实时行情: sz000070",
            },
            {
                "代码": "600999",
                "名称": "空壳",
                "持仓": 0,
                "持仓状态": "空仓",
                "error": "无实时行情",
            },
        ]
        out = filter_portfolio_holdings(
            rows, phase="pre_auction", strategy_codes=set()
        )
        codes = [str(r["代码"]) for r in out]
        self.assertIn("000070", codes)
        self.assertNotIn("600999", codes)

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


class TestPreopenQuote(unittest.TestCase):
    def test_fill_preopen_uses_prev_close(self) -> None:
        filled = fill_preopen_ohlc(
            open_px=0.0,
            high_px=0.0,
            low_px=0.0,
            last_px=0.0,
            bid=0.0,
            ask=0.0,
            prev_close=16.29,
        )
        self.assertIsNotNone(filled)
        assert filled is not None
        open_px, high_px, low_px, last_px = filled
        self.assertEqual(last_px, 16.29)
        self.assertEqual(open_px, 16.29)
        self.assertEqual(high_px, 16.29)
        self.assertEqual(low_px, 16.29)

    def test_fill_preopen_rejects_no_prev(self) -> None:
        self.assertIsNone(
            fill_preopen_ohlc(
                open_px=0.0,
                high_px=0.0,
                low_px=0.0,
                last_px=0.0,
                prev_close=0.0,
            )
        )


class TestTiantongAlertOnHoldings(unittest.TestCase):
    def test_hit_buy_shows_in_holdings_alert(self) -> None:
        from watch_buy_signal import is_today_alert_row
        from watch_snapshot import filter_portfolio_holdings

        row = {
            "代码": "600330",
            "名称": "天通股份",
            "持仓": 0,
            "持仓状态": "待买入",
            "预警": "已触买",
            "已触买": "是",
            "过门OK": True,
            "当日禁买": False,
            "pool_src": "self",
        }
        self.assertTrue(is_today_alert_row(row))
        out = filter_portfolio_holdings(
            [row],
            phase="continuous",
            strategy_codes={"600330"},
        )
        self.assertIn("600330", [str(r["代码"]) for r in out])

    def test_replay_stop_does_not_hide_hit_buy(self) -> None:
        from watch_buy_signal import is_today_alert_row

        row = {
            "代码": "600330",
            "持仓": 0,
            "持仓状态": "已平仓",
            "预警": "已触买",
            "已触买": "是",
            "过门OK": True,
            "当日禁买": False,
        }
        self.assertTrue(is_today_alert_row(row))

    def test_apply_trigger_replay_stop_not_ban_when_hit_buy(self) -> None:
        from index import _apply_trigger_date_fields

        row = {
            "持仓状态": "待买入",
            "预警": "已触买",
            "已触买": "是",
            "已触止损": "是",
            "买点": 27.81,
            "止损": 26.0,
        }
        sig = {
            "hit_buy": True,
            "hit_stop": True,
            "因子触发": "已触发",
            "持仓状态": "待买入",
        }
        _apply_trigger_date_fields(
            row,
            sig=sig,
            session="2026-09-14",
            last_px=29.61,
            px_digits=2,
            buy_time=None,
            qty=0,
            replay={"holding": True},
            code="600330",
            allow_entry=True,
        )
        self.assertFalse(row.get("当日禁买"))
        self.assertNotEqual(row.get("持仓状态"), "已平仓")


class TestWatchHeal(unittest.TestCase):
    def test_quotes_ready_requires_position_px(self) -> None:
        from index import _position_quotes_ready

        self.assertTrue(_position_quotes_ready([{"持仓": 0}]))
        self.assertFalse(
            _position_quotes_ready(
                [{"持仓": 5500, "error": "无实时行情", "市值": None, "现价": None}]
            )
        )
        self.assertTrue(
            _position_quotes_ready(
                [{"持仓": 5500, "市值": 90000.0, "现价": 16.4}]
            )
        )


class TestIndexAndAccount(unittest.TestCase):
    def test_index_code_match_strips_prefix(self) -> None:
        from index import _index_codes_match

        self.assertTrue(_index_codes_match("000001", "sh000001"))
        self.assertTrue(_index_codes_match("sz399001", "399001"))
        self.assertFalse(_index_codes_match("000001", "sz399001"))

    def test_keep_last_index_when_one_fails(self) -> None:
        from index import _merge_index_keep_last

        prev = [
            {
                "code": "sh000001",
                "price": 3888.0,
                "chg_points": -1.0,
                "chg_pct": -0.03,
                "error": None,
            },
            {
                "code": "sz399001",
                "price": 12900.0,
                "chg_points": 10.0,
                "chg_pct": 0.08,
                "error": None,
            },
        ]
        fresh = [
            {"code": "sh000001", "price": 3889.0, "error": None},
            {"code": "sz399001", "price": None, "error": "未找到指数"},
        ]
        out = _merge_index_keep_last(fresh, prev)
        self.assertEqual(out[0]["price"], 3889.0)
        self.assertEqual(out[1]["price"], 12900.0)

    def test_equity_cash_only_with_positions(self) -> None:
        from index import _equity_is_cash_only

        data = {
            "account_cash": 35371.0,
            "positions": {"000070": {"qty": 5500}},
        }
        self.assertTrue(_equity_is_cash_only(data, 35371.0))
        self.assertFalse(_equity_is_cash_only(data, 304543.0))

    def test_account_summary_uses_float_pnl_not_cash_open(self) -> None:
        from index import _build_watch_account_summary

        acc = _build_watch_account_summary(
            [
                {
                    "代码": "000070",
                    "持仓": 5500,
                    "浮盈": 1155.0,
                    "当日盈亏": -3630.0,
                    "当日基数": 94500.0,
                    "市值": 90750.0,
                    "成本额": 89595.0,
                }
            ]
        )
        self.assertAlmostEqual(acc["totalPnl"], 1155.0)
        self.assertLess(abs(float(acc["totalPnlPct"])), 20.0)
        self.assertAlmostEqual(acc["dayPnl"], -3630.0)
        self.assertGreater(acc["dayPnlPct"], -10.0)
        self.assertLess(acc["dayPnlPct"], 0.0)


class TestKeepLastSnapshot(unittest.TestCase):
    def _prev(self) -> dict:
        return {
            "type": "snapshot",
            "holdings": [{"代码": "000070", "持仓": 5500}],
            "strategy16": [{"代码": "600869"}],
            "slotMeta": {"occupied": ["000070", "600522", "600869"]},
        }

    def test_keep_when_all_quotes_fail(self) -> None:
        prev = self._prev()
        snapshot = {
            "holdings": [],
            "strategy16": [],
            "slotMeta": {"occupied": ["000070", "600522", "600869"]},
        }
        rows = [
            {"代码": "000070", "持仓": 5500, "error": "无实时行情"},
            {"代码": "600869", "持仓": 3700, "error": "无实时行情"},
        ]
        self.assertTrue(
            should_keep_last_snapshot(rows=rows, snapshot=snapshot, prev=prev)
        )

    def test_publish_when_slots_changed(self) -> None:
        prev = self._prev()
        snapshot = {
            "holdings": [],
            "strategy16": [],
            "slotMeta": {"occupied": ["000070"]},
        }
        rows = [{"代码": "000070", "持仓": 5500, "error": "无实时行情"}]
        self.assertFalse(
            should_keep_last_snapshot(rows=rows, snapshot=snapshot, prev=prev)
        )

    def test_ignore_boot_placeholder(self) -> None:
        prev = {"type": "snapshot", "boot": True, "holdings": [], "strategy16": []}
        snapshot = {"holdings": [], "strategy16": [], "slotMeta": {"occupied": []}}
        self.assertFalse(
            should_keep_last_snapshot(rows=[], snapshot=snapshot, prev=prev)
        )

    def test_retain_marks_stale(self) -> None:
        out = retain_last_snapshot(
            self._prev(),
            clock="2026-09-14 09:18:00",
            phase="集合竞价",
            phase_key="auction",
        )
        self.assertTrue(out["quoteStale"])
        self.assertEqual(out["holdings"][0]["代码"], "000070")
        self.assertEqual(out["clock"], "2026-09-14 09:18:00")


if __name__ == "__main__":
    unittest.main()
