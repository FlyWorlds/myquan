"""交易日生命周期：15:00 POSITION_SETTLEMENT / 跨日 rollover / P&L 基线。"""

from __future__ import annotations

import copy
import datetime as dt
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
import trading_day as td  # noqa: E402
from strategy.akq_math import mark_unrealized, session_day_pnl  # noqa: E402


def _book(
    *,
    cash: float = 283784.0,
    total: float = 293784.0,
    open_eq: float = 290545.0,
    session: str = "2026-09-18",
    positions: dict | None = None,
) -> dict:
    return {
        "updated_at": None,
        "account_total": total,
        "account_cash": cash,
        "account_total_open": open_eq,
        "account_total_open_session": session,
        "last_session": session,
        "paper_equity_base": 300000.0,
        "paper_pnl_start": "2026-09-09",
        "positions": positions
        or {
            "000021": {
                "code": "000021",
                "name": "深科技",
                "qty": 1000,
                "cost": 10.0,
                "available": 1000,
                "buy_time": "2026-09-17 10:00:00",
            }
        },
        "realized_today": {},
        "closed_today": {},
        "daily_settlements": {},
        "factor2": {
            "equity": total,
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


class TestTradingDayHelpers(unittest.TestCase):
    def test_weekend_anchors_friday(self) -> None:
        fri = dt.date(2026, 9, 18)
        self.assertEqual(td.current_trading_session(dt.datetime(2026, 9, 19, 10)), str(fri))
        self.assertEqual(td.current_trading_session(dt.datetime(2026, 9, 20, 10)), str(fri))
        self.assertEqual(
            td.current_trading_session(dt.datetime(2026, 9, 21, 8, 0)),
            "2026-09-21",
        )
        self.assertEqual(td.previous_trading_session("2026-09-21"), "2026-09-18")

    def test_day_change_resets_across_session(self) -> None:
        # 周五涨幅不得带到周一
        self.assertEqual(
            td.sanitize_day_change_for_session(
                quote_session="2026-09-18",
                calendar_session="2026-09-21",
                mark=10.5,
                previous_close=10.0,
                day_chg_pct=5.0,
            ),
            0.0,
        )
        self.assertEqual(
            td.stock_day_change_pct(10.60, 10.50),
            0.95,  # round((10.6/10.5-1)*100, 2) = 0.95
        )
        # 精确 +1%
        self.assertEqual(td.stock_day_change_pct(10.10, 10.00), 1.0)

    def test_position_cost_vs_day_pnl(self) -> None:
        # DAY1 close 10.50 → DAY2 mark 10.60
        self.assertEqual(td.position_cumulative_pnl(10.60, 10.0, 1000), 600.0)
        self.assertEqual(
            td.position_day_pnl(
                mark=10.60, qty=1000, previous_close=10.50, bought_today=False
            ),
            100.0,
        )
        self.assertEqual(
            td.position_day_pnl(mark=10.60, qty=1000, cost=10.0, bought_today=True),
            600.0,
        )
        # cost 不得被日结改掉
        cost = 10.0
        _ = td.position_day_pnl(
            mark=10.50, qty=1000, previous_close=10.0, bought_today=False
        )
        self.assertEqual(cost, 10.0)

    def test_account_layers(self) -> None:
        self.assertEqual(td.account_today_pnl(297023.0, 293784.0), 3239.0)
        self.assertEqual(
            td.account_today_return_pct(3239.0, 293784.0),
            round(3239.0 / 293784.0 * 100.0, 2),
        )
        self.assertEqual(td.account_total_pnl(293784.0, 300000.0), -6216.0)


class TestDailySettlement(unittest.TestCase):
    def setUp(self) -> None:
        self.book = _book()
        self._load = idx.load_holdings
        self._save = idx.save_holdings
        self._cal = idx._calendar_signal_session
        idx.load_holdings = lambda: self.book
        idx.save_holdings = self._save_book
        idx._calendar_signal_session = lambda: "2026-09-18"

    def _save_book(self, data: dict) -> None:
        self.book = data

    def tearDown(self) -> None:
        idx.load_holdings = self._load
        idx.save_holdings = self._save
        idx._calendar_signal_session = self._cal

    def test_1500_position_settlement_not_exit(self) -> None:
        """15:00 日结：盯市记账，不改 qty/cost，不写 SELL。"""
        rows = [
            {
                "代码": "000021",
                "名称": "深科技",
                "持仓": 1000,
                "成本": 10.0,
                "现价": 10.50,
                "当日盈亏": 500.0,
                "浮盈": 500.0,
                "市值": 10500.0,
                "成本额": 10000.0,
                "交易日": "2026-09-18",
            }
        ]
        with patch("index.market_phase", return_value="closed"):
            ok = idx.record_daily_settlement(
                session="2026-09-18",
                account={
                    "accountTotal": 293784.0,
                    "accountOpen": 290545.0,
                    "paperEquityBase": 300000.0,
                    "totalPnlStart": "2026-09-09",
                    "dayPnl": 3239.0,
                    "dayPnlPct": 1.11,
                    "equityDayPnl": 3239.0,
                    "totalPnl": -6216.0,
                    "totalPnlPct": -2.07,
                    "settledCount": 0,
                },
                rows=rows,
                force=False,
            )
        self.assertTrue(ok)
        rec = self.book["daily_settlements"]["2026-09-18"]
        self.assertTrue(rec["final"])
        self.assertEqual(rec["settle_kind"], td.SETTLE_KIND_POSITION)
        self.assertEqual(rec["account_total"], 293784.0)
        marks = rec["closing_marks"]
        self.assertEqual(len(marks), 1)
        self.assertEqual(marks[0]["qty"], 1000)
        self.assertEqual(marks[0]["cost"], 10.0)
        self.assertEqual(marks[0]["close"], 10.50)
        # 仓位未变
        pos = self.book["positions"]["000021"]
        self.assertEqual(pos["qty"], 1000)
        self.assertEqual(pos["cost"], 10.0)
        self.assertFalse(self.book.get("realized_today"))

    def test_settlement_idempotent_after_close_restart(self) -> None:
        with patch("index.market_phase", return_value="closed"):
            acc = {
                "accountTotal": 293784.0,
                "accountOpen": 290545.0,
                "paperEquityBase": 300000.0,
                "dayPnl": 3239.0,
                "equityDayPnl": 3239.0,
                "totalPnl": -6216.0,
            }
            self.assertTrue(
                idx.record_daily_settlement(
                    session="2026-09-18", account=acc, rows=[], force=False
                )
            )
            first = copy.deepcopy(self.book["daily_settlements"]["2026-09-18"])
            self.assertFalse(
                idx.record_daily_settlement(
                    session="2026-09-18", account=acc, rows=[], force=False
                )
            )
            second = self.book["daily_settlements"]["2026-09-18"]
        self.assertEqual(first["account_total"], second["account_total"])
        self.assertEqual(first["final"], second["final"])

    def test_friday_monday_account_open_and_realized_reset(self) -> None:
        self.book["daily_settlements"] = {
            "2026-09-18": {
                "session": "2026-09-18",
                "final": True,
                "settle_kind": td.SETTLE_KIND_POSITION,
                "account_total": 293784.0,
                "total_pnl": -6216.0,
                "day_pnl": 3239.0,
            }
        }
        self.book["realized_today"] = {
            "600869": {
                "session": "2026-09-18",
                "qty": 3300,
                "price": 21.41,
                "day_pnl": 1419.0,
            }
        }
        self.book["closed_today"] = {
            "600869": {"session": "2026-09-18", "qty": 3300, "day_pnl": 1419.0}
        }
        self.book["account_total_open"] = 290545.0
        self.book["account_total_open_session"] = "2026-09-18"
        idx._calendar_signal_session = lambda: "2026-09-21"
        with patch("index.trading_session_date", return_value=dt.date(2026, 9, 21)):
            healed = idx.heal_watch_ledger(session="2026-09-21")
        self.assertEqual(healed["account_total_open"], 293784.0)
        self.assertEqual(healed["account_total_open_session"], "2026-09-21")
        self.assertEqual(healed.get("realized_today") or {}, {})
        self.assertEqual(healed.get("closed_today") or {}, {})
        # 同日再 heal 不二次滚动
        healed2 = idx.heal_watch_ledger(session="2026-09-21")
        self.assertEqual(healed2["account_total_open"], 293784.0)

    def test_same_day_restart_keeps_open(self) -> None:
        self.book["account_total_open"] = 293784.0
        self.book["account_total_open_session"] = "2026-09-21"
        self.book["account_total"] = 297023.0
        self.book["daily_settlements"] = {
            "2026-09-18": {"final": True, "account_total": 293784.0}
        }
        idx._calendar_signal_session = lambda: "2026-09-21"
        with patch("index.trading_session_date", return_value=dt.date(2026, 9, 21)):
            healed = idx.heal_watch_ledger(session="2026-09-21")
        self.assertEqual(healed["account_total_open"], 293784.0)
        # 模拟 10:30 当前权益更高，重启不得把 open 改成当前权益
        self.book["account_total"] = 297023.0
        healed = idx.heal_watch_ledger(session="2026-09-21")
        self.assertEqual(healed["account_total_open"], 293784.0)

    def test_preopen_account_summary_excludes_friday_closed(self) -> None:
        self.book = _book(
            total=293784.0,
            open_eq=290545.0,
            session="2026-09-18",
        )
        self.book["daily_settlements"] = {
            "2026-09-18": {"final": True, "account_total": 293784.0, "total_pnl": -6216.0}
        }
        idx._calendar_signal_session = lambda: "2026-09-21"
        acc = idx._build_watch_account_summary(
            [
                {
                    "代码": "000021",
                    "持仓": 1000,
                    "现价": 10.50,
                    "昨收": 10.50,
                    "成本": 10.0,
                    "市值": 10500.0,
                    "成本额": 10000.0,
                    "当日盈亏": 500.0,  # 周五残留；应按昨收重算为 0
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
        self.assertEqual(acc["dayPnl"], 0.0)
        self.assertEqual(acc["settledCount"], 0)
        self.assertEqual(acc["totalPnl"], -6216.0)

    def test_monday_first_quote_day_pnl(self) -> None:
        day, _, base = session_day_pnl(
            mark=10.60,
            qty=1000,
            cost=10.0,
            prev_close=10.50,
            bought_today=False,
            fallback=None,
        )
        upnl, _ = mark_unrealized(10.60, 10.0, 1000)
        self.assertEqual(day, 100.0)
        self.assertEqual(upnl, 600.0)
        self.assertEqual(base, 10500.0)

    def test_today_buy_day_pnl_uses_cost(self) -> None:
        day, _, _ = session_day_pnl(
            mark=10.60,
            qty=1000,
            cost=10.0,
            prev_close=9.5,
            bought_today=True,
            fallback=10.0,
        )
        self.assertEqual(day, 600.0)

    def test_partial_sell_today_counts_realized_only_same_session(self) -> None:
        idx._calendar_signal_session = lambda: "2026-09-21"
        acc = idx._build_watch_account_summary(
            [
                {
                    "代码": "000021",
                    "持仓": 500,
                    "现价": 10.60,
                    "昨收": 10.50,
                    "成本": 10.0,
                    "市值": 5300.0,
                    "成本额": 5000.0,
                    "当日盈亏": 50.0,
                    "交易日": "2026-09-21",
                },
                {
                    "代码": "000021",
                    "持仓": 0,
                    "已实现": True,
                    "三槽平仓": True,
                    "卖出数量": 500,
                    "当日盈亏": 40.0,
                    "浮盈": 300.0,
                    "交易日": "2026-09-21",
                },
            ],
            session="2026-09-21",
        )
        self.assertEqual(acc["dayPnl"], 90.0)
        self.assertEqual(acc["settledCount"], 1)


class TestWeekendNoNewSession(unittest.TestCase):
    def test_saturday_does_not_roll_to_saturday(self) -> None:
        self.assertEqual(
            td.promote_quote_session("2026-09-18", now=dt.datetime(2026, 9, 19, 12)),
            "2026-09-18",
        )
        # 周六日历信号日仍是周五，不得升到周六
        self.assertEqual(
            td.current_trading_session(dt.datetime(2026, 9, 19, 12)),
            "2026-09-18",
        )


if __name__ == "__main__":
    unittest.main()
