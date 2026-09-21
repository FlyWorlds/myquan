"""Paper P&L 账户合计：成本口径、现金允许为负、买卖权益恒等。"""

from __future__ import annotations

import copy
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
from strategy.akq_math import mark_unrealized, session_day_pnl  # noqa: E402


def _book(
    *,
    cash: float | None = 300000.0,
    total: float | None = 300000.0,
    open_eq: float | None = 300000.0,
    session: str = "2026-09-18",
    positions: dict | None = None,
) -> dict:
    return {
        "updated_at": None,
        "account_total": total,
        "account_cash": cash,
        "account_total_open": open_eq,
        "account_total_open_session": session,
        "paper_equity_base": 300000.0,
        "paper_pnl_start": "2026-09-09",
        "positions": positions or {},
        "realized_today": {},
        "closed_today": {},
        "daily_settlements": {},
        "factor2": {
            "equity": 300000.0,
            "dd_pct": 0.0,
            "action": "hold",
            "thresholds": {
                "hist_max_dd": 0.26,
                "avg_yearly_max_dd": 0.19,
                "add_alert_dd": 0.20,
                "reduce_alert_dd": 0.10,
            },
        },
    }


class TestPaperPnl(unittest.TestCase):
    def setUp(self) -> None:
        self.book = _book()
        self._load = idx.load_holdings
        self._save = idx.save_holdings
        self._append = idx.append_trade
        self._remember = idx.remember_factor_trigger
        self._cal = idx._calendar_signal_session
        idx.load_holdings = lambda: self.book
        idx.save_holdings = self._save_book
        idx.append_trade = lambda *_a, **_k: None
        idx.remember_factor_trigger = lambda *_a, **_k: None
        idx._calendar_signal_session = lambda: "2026-09-18"
        self._wx = __import__("wechat_notify")
        self._wx_flag = self._wx._WATCH_WECHAT_ENABLED
        self._wx.set_watch_wechat_enabled(False)

    def _save_book(self, data: dict) -> None:
        self.book = data

    def tearDown(self) -> None:
        idx.load_holdings = self._load
        idx.save_holdings = self._save
        idx.append_trade = self._append
        idx.remember_factor_trigger = self._remember
        idx._calendar_signal_session = self._cal
        self._wx._WATCH_WECHAT_ENABLED = self._wx_flag

    def test_negative_cash_is_readable(self) -> None:
        self.book["account_cash"] = -10862.0
        self.assertEqual(idx._account_cash(self.book), -10862.0)
        self.assertEqual(idx._as_cash(0), 0.0)
        self.assertEqual(idx._as_cash(-20.0), -20.0)
        self.assertIsNone(idx._as_cash(None))
        self.assertIsNone(idx._as_money(0))
        self.assertIsNone(idx._as_money(-10862.0))

    def test_cash_execution_invariant_buy_negative_then_sell(self) -> None:
        self.book["account_cash"] = 100.0
        self.book["account_total"] = 100.0
        idx.apply_paper_slot_buy(
            code="600000",
            meta={"name": "测试", "market": "上证"},
            price=12.0,
            qty=10,
            note="unit-cash-inv",
            buy_time="2026-09-18 09:35:00",
        )
        self.assertEqual(self.book["account_cash"], -20.0)
        rec = idx.apply_exit_fill(
            code="600000",
            meta={"name": "测试", "market": "上证"},
            fill_px=5.0,
            qty=10,
            cost=12.0,
            session="2026-09-18",
            buy_time="2026-09-18 09:35:00",
            prev_close=12.0,
            open_px=12.0,
            px_digits=2,
            reason="unit-cash-inv",
            trade_note="unit-cash-inv",
        )
        self.assertEqual(rec.get("qty"), 10)
        self.assertEqual(self.book["account_cash"], 30.0)

    def test_zero_cash_sell_credits(self) -> None:
        self.book["account_cash"] = 0.0
        self.book["positions"]["600000"] = {
            "name": "测试",
            "market": "上证",
            "qty": 10,
            "available": 10,
            "cost": 10.0,
            "buy_time": "2026-09-11 09:35:00",
            "today_cost": None,
            "tp_stage": 0,
            "last_tp_ts": None,
            "note": "",
            "peak_high": 10.0,
        }
        idx.apply_exit_fill(
            code="600000",
            meta={"name": "测试", "market": "上证"},
            fill_px=5.0,
            qty=10,
            cost=10.0,
            session="2026-09-18",
            buy_time="2026-09-11 09:35:00",
            prev_close=10.0,
            open_px=10.0,
            px_digits=2,
            reason="unit-zero-cash",
            trade_note="unit-zero-cash",
        )
        self.assertEqual(self.book["account_cash"], 50.0)

    def test_negative_cash_sell_from_minus_100(self) -> None:
        self.book["account_cash"] = -100.0
        self.book["positions"]["600000"] = {
            "name": "测试",
            "market": "上证",
            "qty": 10,
            "available": 10,
            "cost": 10.0,
            "buy_time": "2026-09-11 09:35:00",
            "today_cost": None,
            "tp_stage": 0,
            "last_tp_ts": None,
            "note": "",
            "peak_high": 10.0,
        }
        idx.apply_exit_fill(
            code="600000",
            meta={"name": "测试", "market": "上证"},
            fill_px=5.0,
            qty=10,
            cost=10.0,
            session="2026-09-18",
            buy_time="2026-09-11 09:35:00",
            prev_close=10.0,
            open_px=10.0,
            px_digits=2,
            reason="unit-neg100",
            trade_note="unit-neg100",
        )
        self.assertEqual(self.book["account_cash"], -50.0)

    def test_negative_cash_buy_still_debits(self) -> None:
        self.book["account_cash"] = -20.0
        self.book["account_total"] = -20.0
        idx.apply_paper_slot_buy(
            code="600000",
            meta={"name": "测试", "market": "上证"},
            price=3.0,
            qty=10,
            note="unit-neg-buy",
            buy_time="2026-09-18 09:35:00",
        )
        self.assertEqual(self.book["account_cash"], -50.0)

    def test_screenshot_display_cost_excludes_closed(self) -> None:
        self.book["account_total_open"] = 290545.0
        acc = idx._build_watch_account_summary(
            [
                {
                    "代码": "000021",
                    "持仓": 1900,
                    "市值": 307462.0,
                    "成本额": 306742.0,
                    "当日盈亏": 3109.0,
                    "当日基数": 304353.0,
                    "交易日": "2026-09-18",
                },
                {
                    "代码": "002636",
                    "持仓": 0,
                    "已实现": True,
                    "卖出数量": 800,
                    "成本": 83.54,
                    "成本额": 213103.0,
                    "当日盈亏": 0.0,
                    "浮盈": -2560.0,
                    "交易日": "2026-09-18",
                },
            ]
        )
        self.assertEqual(acc["cost"], 306742.0)
        self.assertNotEqual(acc["cost"], 519845.0)
        self.assertEqual(acc["accountTotal"], 293654.0)
        self.assertEqual(acc["totalPnl"], -6346.0)
        self.assertEqual(acc["totalPnlPct"], round(-6346.0 / 300000.0 * 100.0, 2))

    def test_zero_position_summary(self) -> None:
        acc = idx._build_watch_account_summary([])
        self.assertEqual(acc["accountTotal"], 300000.0)
        self.assertEqual(acc["availableCash"], 300000.0)
        self.assertIsNone(acc["cost"])
        self.assertIsNone(acc["marketValue"])
        self.assertEqual(acc["totalPnl"], 0.0)
        self.assertEqual(acc["totalPnlPct"], 0.0)

    def test_display_cost_is_remaining_only(self) -> None:
        acc = idx._build_watch_account_summary(
            [
                {
                    "代码": "000021",
                    "持仓": 1900,
                    "市值": 70000.0,
                    "成本额": 70262.0,
                    "当日盈亏": 100.0,
                    "当日基数": 70000.0,
                    "交易日": "2026-09-18",
                },
                {
                    "代码": "002636",
                    "持仓": 0,
                    "已实现": True,
                    "卖出数量": 800,
                    "成本": 83.54,
                    "当日盈亏": 752.0,
                    "浮盈": -2560.0,
                    "交易日": "2026-09-18",
                },
            ]
        )
        self.assertEqual(acc["cost"], 70262.0)
        self.assertEqual(acc["settledCount"], 1)
        self.assertNotEqual(acc["cost"], 70262.0 + 83.54 * 800)

    def test_total_return_pct_denominator_is_paper_base(self) -> None:
        self.book["account_total_open"] = 290545.0
        acc = idx._build_watch_account_summary(
            [
                {
                    "代码": "000021",
                    "持仓": 100,
                    "市值": 1000.0,
                    "成本额": 900.0,
                    "当日盈亏": 3109.0,
                    "当日基数": 290545.0,
                    "交易日": "2026-09-18",
                }
            ]
        )
        self.assertEqual(acc["accountTotal"], 293654.0)
        self.assertEqual(acc["totalPnl"], -6346.0)
        self.assertEqual(acc["totalPnlPct"], round(-6346.0 / 300000.0 * 100.0, 2))
        self.assertEqual(acc["dayPnl"], 3109.0)
        self.assertEqual(acc["equityDayPnl"], 3109.0)
        self.assertEqual(acc["dayPnlPct"], round(3109.0 / 290545.0 * 100.0, 2))

    def test_account_today_return_uses_open_equity_not_row_bases(self) -> None:
        self.book["account_total_open"] = 290545.0
        acc = idx._build_watch_account_summary(
            [
                {
                    "代码": "000021",
                    "持仓": 1900,
                    "市值": 70205.0,
                    "成本额": 70262.0,
                    "当日盈亏": -57.0,
                    "当日基数": 70262.0,
                    "交易日": "2026-09-18",
                },
                {
                    "代码": "000034",
                    "持仓": 3900,
                    "市值": 91572.0,
                    "成本额": 90051.0,
                    "当日盈亏": 2067.0,
                    "当日基数": 89505.0,
                    "交易日": "2026-09-18",
                },
                {
                    "代码": "000055",
                    "持仓": 19300,
                    "市值": 72375.0,
                    "成本额": 73533.0,
                    "当日盈亏": -1158.0,
                    "当日基数": 73533.0,
                    "交易日": "2026-09-18",
                },
                {
                    "代码": "600234",
                    "持仓": 3400,
                    "市值": 73440.0,
                    "成本额": 72896.0,
                    "当日盈亏": 544.0,
                    "当日基数": 72896.0,
                    "交易日": "2026-09-18",
                },
                {
                    "代码": "002636",
                    "持仓": 0,
                    "已实现": True,
                    "卖出数量": 800,
                    "成本": 83.54,
                    "当日盈亏": 752.0,
                    "当日基数": 63520.0,
                    "交易日": "2026-09-18",
                },
                {
                    "代码": "600869",
                    "持仓": 0,
                    "已实现": True,
                    "卖出数量": 3300,
                    "成本": 22.07,
                    "当日盈亏": 1419.0,
                    "当日基数": 70290.0,
                    "交易日": "2026-09-18",
                },
                {
                    "代码": "603115",
                    "持仓": 0,
                    "已实现": True,
                    "卖出数量": 800,
                    "成本": 91.8,
                    "当日盈亏": -328.0,
                    "当日基数": 76328.0,
                    "交易日": "2026-09-18",
                },
            ]
        )
        self.assertEqual(acc["dayPnl"], 3239.0)
        self.assertEqual(acc["accountOpen"], 290545.0)
        self.assertEqual(acc["dayPnlPct"], round(3239.0 / 290545.0 * 100.0, 2))
        self.assertEqual(acc["dayPnlPct"], 1.11)
        self.assertNotEqual(acc["dayPnlPct"], round(3239.0 / 516334.0 * 100.0, 2))
        self.assertNotEqual(acc["dayPnlPct"], 0.63)
        self.assertEqual(acc["totalPnlPct"], round(acc["totalPnl"] / 300000.0 * 100.0, 2))

    def test_cross_day_preopen_uses_prev_settle_not_stale_open(self) -> None:
        """周一盘前：日初=上周五收盘结算；上周五平仓不进今日盈亏；昨仓按昨收。"""
        self.book = _book(
            cash=-15000.0,
            total=293784.0,
            open_eq=290545.0,
            session="2026-09-18",
        )
        self.book["daily_settlements"] = {
            "2026-09-17": {"account_total": 290545.0, "total_pnl": -9455.0},
            "2026-09-18": {
                "account_total": 293784.0,
                "total_pnl": -6216.0,
                "day_pnl": 3239.0,
            },
        }
        idx._calendar_signal_session = lambda: "2026-09-21"
        # 盘前现价=昨收 → 昨仓今日盈亏应为 0；周五平仓残留不得计入
        acc = idx._build_watch_account_summary(
            [
                {
                    "代码": "000021",
                    "持仓": 1900,
                    "现价": 36.95,
                    "昨收": 36.95,
                    "成本": 36.98,
                    "市值": 70205.0,
                    "成本额": 70262.0,
                    "当日盈亏": -57.0,
                    "交易日": "2026-09-18",
                },
                {
                    "代码": "600869",
                    "持仓": 0,
                    "已实现": True,
                    "三槽平仓": True,
                    "浮盈": -1122.0,
                    "当日盈亏": 1419.0,
                    "交易日": "2026-09-18",
                },
            ]
        )
        self.assertEqual(acc["accountOpen"], 293784.0)
        self.assertEqual(self.book["account_total_open_session"], "2026-09-21")
        self.assertEqual(acc["dayPnl"], 0.0)
        self.assertEqual(acc["settledCount"], 0)
        self.assertEqual(acc["totalPnl"], round(293784.0 - 300000.0, 2))
        self.assertEqual(acc["totalPnl"], -6216.0)

    def test_account_today_return_zero_or_invalid_open_is_none(self) -> None:
        from watch_snapshot import account_today_return_pct, apply_day_linked_account_equity

        self.assertIsNone(account_today_return_pct(3239.0, 0))
        self.assertIsNone(account_today_return_pct(3239.0, None))
        self.assertIsNone(account_today_return_pct(3239.0, "x"))
        self.assertIsNone(account_today_return_pct(3239.0, float("nan")))
        self.assertIsNone(account_today_return_pct(3239.0, float("inf")))
        self.assertEqual(account_today_return_pct(3239.0, 290545.0), 1.11)
        linked = apply_day_linked_account_equity(
            {"dayPnl": 3239.0, "accountOpen": 0, "marketValue": 1.0}
        )
        self.assertIsNone(linked.get("dayPnlPct"))
        linked = apply_day_linked_account_equity(
            {"dayPnl": 3239.0, "accountOpen": None, "marketValue": 1.0}
        )
        self.assertIsNone(linked.get("dayPnlPct"))

    def test_today_pnl_day_baseline_is_account_open(self) -> None:
        self.book["account_total_open"] = 290000.0
        acc = idx._build_watch_account_summary(
            [
                {
                    "代码": "000021",
                    "持仓": 100,
                    "市值": 1100.0,
                    "成本额": 1000.0,
                    "当日盈亏": 50.0,
                    "当日基数": 1050.0,
                    "交易日": "2026-09-18",
                }
            ]
        )
        self.assertEqual(acc["accountOpen"], 290000.0)
        self.assertEqual(acc["accountTotal"], 290050.0)
        self.assertEqual(acc["totalPnl"], round(290050.0 - 300000.0, 2))

    def test_buy_equity_invariant_at_fill(self) -> None:
        cash_before = 100000.0
        self.book["account_cash"] = cash_before
        self.book["account_total"] = cash_before
        pos = idx.apply_paper_slot_buy(
            code="600000",
            meta={"name": "测试", "market": "上证"},
            price=10.0,
            qty=100,
            note="unit",
            buy_time="2026-09-18 09:35:00",
        )
        cash = float(self.book["account_cash"])
        mv = 10.0 * int(pos["qty"])
        self.assertEqual(cash, 99000.0)
        self.assertEqual(round(cash + mv, 2), cash_before)

    def test_price_rise_unrealized_profit(self) -> None:
        pnl, pct = mark_unrealized(12.0, 10.0, 100)
        self.assertEqual(pnl, 200.0)
        self.assertEqual(pct, 20.0)

    def test_price_fall_unrealized_loss(self) -> None:
        pnl, pct = mark_unrealized(9.0, 10.0, 100)
        self.assertEqual(pnl, -100.0)
        self.assertEqual(pct, -10.0)

    def test_full_sell_realized_pnl(self) -> None:
        self.book["positions"]["600000"] = {
            "name": "测试",
            "market": "上证",
            "qty": 400,
            "available": 400,
            "cost": 10.0,
            "buy_time": "2026-09-11 09:35:00",
            "today_cost": None,
            "tp_stage": 0,
            "last_tp_ts": None,
            "note": "",
            "peak_high": 10.0,
        }
        self.book["account_cash"] = 200000.0
        rec = idx.apply_exit_fill(
            code="600000",
            meta={"name": "测试", "market": "上证"},
            fill_px=11.0,
            qty=400,
            cost=10.0,
            session="2026-09-18",
            buy_time="2026-09-11 09:35:00",
            prev_close=10.2,
            open_px=10.3,
            px_digits=2,
            reason="unit-full",
            trade_note="unit-full",
        )
        self.assertTrue(rec.get("full_exit"))
        self.assertEqual(rec.get("pnl"), 400.0)
        self.assertEqual(self.book["positions"]["600000"]["qty"], 0)
        self.assertIsNone(self.book["positions"]["600000"]["cost"])
        self.assertEqual(self.book["account_cash"], 204400.0)

    def test_partial_sell_keeps_remaining_cost(self) -> None:
        self.book["positions"]["600000"] = {
            "name": "测试",
            "market": "上证",
            "qty": 400,
            "available": 400,
            "cost": 10.0,
            "buy_time": "2026-09-11 09:35:00",
            "today_cost": None,
            "tp_stage": 0,
            "last_tp_ts": None,
            "note": "",
            "peak_high": 10.0,
        }
        self.book["account_cash"] = 200000.0
        rec = idx.apply_exit_fill(
            code="600000",
            meta={"name": "测试", "market": "上证"},
            fill_px=11.0,
            qty=200,
            cost=10.0,
            session="2026-09-18",
            buy_time="2026-09-11 09:35:00",
            prev_close=10.2,
            open_px=10.3,
            px_digits=2,
            reason="unit-half",
            trade_note="unit-half",
            action_kind="half",
        )
        self.assertEqual(rec.get("after_qty"), 200)
        self.assertEqual(rec.get("pnl"), 200.0)
        pos = self.book["positions"]["600000"]
        self.assertEqual(pos["qty"], 200)
        self.assertEqual(pos["cost"], 10.0)
        self.assertEqual(self.book["account_cash"], 202200.0)
        remain_unreal, _ = mark_unrealized(12.0, 10.0, 200)
        self.assertEqual(remain_unreal, 400.0)

    def test_multiple_buy_cost_is_per_slot_fill(self) -> None:
        idx.apply_paper_slot_buy(
            code="600000",
            meta={"name": "A", "market": "上证"},
            price=10.0,
            qty=100,
            buy_time="2026-09-18 09:35:00",
        )
        idx.apply_paper_slot_buy(
            code="600001",
            meta={"name": "B", "market": "上证"},
            price=20.0,
            qty=200,
            buy_time="2026-09-18 09:36:00",
        )
        self.assertEqual(self.book["positions"]["600000"]["cost"], 10.0)
        self.assertEqual(self.book["positions"]["600001"]["cost"], 20.0)
        self.assertEqual(self.book["account_cash"], 300000.0 - 1000.0 - 4000.0)

    def test_buy_and_sell_same_day(self) -> None:
        idx.apply_paper_slot_buy(
            code="600000",
            meta={"name": "测试", "market": "上证"},
            price=10.0,
            qty=100,
            buy_time="2026-09-18 09:35:00",
        )
        rec = idx.apply_exit_fill(
            code="600000",
            meta={"name": "测试", "market": "上证"},
            fill_px=11.0,
            qty=100,
            cost=10.0,
            session="2026-09-18",
            buy_time="2026-09-18 09:35:00",
            prev_close=9.5,
            open_px=10.0,
            px_digits=2,
            reason="unit-same-day",
            trade_note="unit-same-day",
        )
        day, _, base = session_day_pnl(
            mark=11.0, qty=100, cost=10.0, prev_close=9.5, bought_today=True, fallback=10.0
        )
        self.assertEqual(rec.get("day_pnl"), day)
        self.assertEqual(base, 1000.0)
        self.assertEqual(self.book["account_cash"], 300000.0 + 100.0)

    def test_t1_hold_has_no_realized(self) -> None:
        self.book["positions"]["600000"] = {
            "name": "测试",
            "market": "上证",
            "qty": 100,
            "available": 0,
            "cost": 10.0,
            "buy_time": "2026-09-18 09:35:00",
            "today_cost": 10.0,
            "tp_stage": 0,
            "last_tp_ts": None,
            "note": "",
            "peak_high": 10.0,
        }
        acc = idx._build_watch_account_summary(
            [
                {
                    "代码": "600000",
                    "持仓": 100,
                    "市值": 1100.0,
                    "成本额": 1000.0,
                    "当日盈亏": 100.0,
                    "当日基数": 1000.0,
                    "已实现": False,
                    "交易日": "2026-09-18",
                }
            ]
        )
        self.assertEqual(acc["settledCount"], 0)
        self.assertIsNone(acc["settledPnl"])
        self.assertEqual(acc["dayPnl"], 100.0)

    def test_restart_stable_from_persisted_fixture(self) -> None:
        rows = [
            {
                "代码": "000021",
                "持仓": 100,
                "市值": 1100.0,
                "成本额": 1000.0,
                "当日盈亏": 80.0,
                "当日基数": 1020.0,
                "交易日": "2026-09-18",
            }
        ]
        a = copy.deepcopy(idx._build_watch_account_summary(rows))
        b = copy.deepcopy(idx._build_watch_account_summary(rows))
        for key in (
            "accountTotal",
            "totalPnl",
            "totalPnlPct",
            "dayPnl",
            "cost",
            "marketValue",
        ):
            self.assertEqual(a.get(key), b.get(key), key)

    def test_negative_cash_sell_still_credits(self) -> None:
        self.book["account_cash"] = -500.0
        self.book["positions"]["600000"] = {
            "name": "测试",
            "market": "上证",
            "qty": 100,
            "available": 100,
            "cost": 10.0,
            "buy_time": "2026-09-11 09:35:00",
            "today_cost": None,
            "tp_stage": 0,
            "last_tp_ts": None,
            "note": "",
            "peak_high": 10.0,
        }
        idx.apply_exit_fill(
            code="600000",
            meta={"name": "测试", "market": "上证"},
            fill_px=10.0,
            qty=100,
            cost=10.0,
            session="2026-09-18",
            buy_time="2026-09-11 09:35:00",
            prev_close=10.0,
            open_px=10.0,
            px_digits=2,
            reason="unit-neg-cash",
            trade_note="unit-neg-cash",
        )
        self.assertEqual(self.book["account_cash"], 500.0)

    def test_position_over_100_pct(self) -> None:
        self.book["account_cash"] = -13808.0
        self.book["account_total_open"] = 290545.0
        acc = idx._build_watch_account_summary(
            [
                {
                    "代码": "000021",
                    "持仓": 100,
                    "市值": 307462.0,
                    "成本额": 306742.0,
                    "当日盈亏": 3109.0,
                    "当日基数": 304353.0,
                    "交易日": "2026-09-18",
                }
            ]
        )
        self.assertGreater(acc["positionPct"], 100.0)
        self.assertEqual(acc["accountTotal"], 293654.0)
        self.assertEqual(
            round(acc["availableCash"] + acc["marketValue"], 2),
            acc["accountTotal"],
        )

    def test_historical_realized_plus_current_holdings(self) -> None:
        acc = idx._build_watch_account_summary(
            [
                {
                    "代码": "000021",
                    "持仓": 100,
                    "市值": 1100.0,
                    "成本额": 1000.0,
                    "当日盈亏": 50.0,
                    "当日基数": 1050.0,
                    "浮盈": 100.0,
                    "交易日": "2026-09-18",
                },
                {
                    "代码": "002636",
                    "持仓": 0,
                    "已实现": True,
                    "卖出数量": 800,
                    "成本": 83.54,
                    "当日盈亏": 10.0,
                    "浮盈": -2560.0,
                    "交易日": "2026-09-18",
                },
            ]
        )
        self.assertEqual(acc["dayPnl"], 60.0)
        self.assertEqual(acc["cost"], 1000.0)
        self.assertEqual(acc["settledPnl"], -2560.0)


if __name__ == "__main__":
    unittest.main()
