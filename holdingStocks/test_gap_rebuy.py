"""隔夜止损已记 + 次日竞价低开：当日允许过门回买。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_HOLD = Path(__file__).resolve().parent
for p in (str(_ROOT), str(_HOLD)):
    if p not in sys.path:
        sys.path.insert(0, p)

import index as idx  # noqa: E402
from strategy.open_break import REASON_STOP  # noqa: E402


def _pos(
    *,
    qty: int = 400,
    stop_noted: bool = True,
    buy_time: str = "2026-10-07 10:15:00",
) -> dict:
    return {
        "name": "测试",
        "market": "上证",
        "qty": qty,
        "available": qty,
        "cost": 10.0,
        "buy_time": buy_time,
        "today_cost": None,
        "tp_stage": 0,
        "last_tp_ts": None,
        "note": "",
        "peak_high": 10.2,
        "stop_noted": stop_noted,
        "stop_noted_px": 9.75,
        "stop_noted_session": "2026-10-07",
    }


class TestOvernightGapRebuyAllowed(unittest.TestCase):
    def test_stamped_flag(self) -> None:
        rec = {
            "session": "2026-10-08",
            "full_exit": True,
            "allow_intraday_rebuy": True,
        }
        self.assertTrue(
            idx.overnight_gap_rebuy_allowed(rec, session="2026-10-08")
        )

    def test_fallback_open_protect_overnight_noted(self) -> None:
        rec = {
            "session": "2026-10-08",
            "full_exit": True,
            "exit_kind": "open_protect",
            "prior_stop_noted": True,
            "buy_time": "2026-10-07 10:15:00",
        }
        self.assertTrue(
            idx.overnight_gap_rebuy_allowed(rec, session="2026-10-08")
        )

    def test_path_stop_banned(self) -> None:
        rec = {
            "session": "2026-10-08",
            "full_exit": True,
            "exit_kind": "path",
            "prior_stop_noted": True,
            "buy_time": "2026-10-07 10:15:00",
        }
        self.assertFalse(
            idx.overnight_gap_rebuy_allowed(rec, session="2026-10-08")
        )

    def test_same_day_buy_banned(self) -> None:
        rec = {
            "session": "2026-10-08",
            "full_exit": True,
            "exit_kind": "open_protect",
            "prior_stop_noted": True,
            "buy_time": "2026-10-08 09:35:00",
        }
        self.assertFalse(
            idx.overnight_gap_rebuy_allowed(rec, session="2026-10-08")
        )

    def test_half_exit_banned(self) -> None:
        rec = {
            "session": "2026-10-08",
            "full_exit": False,
            "allow_intraday_rebuy": True,
            "exit_kind": "open_protect",
            "prior_stop_noted": True,
            "buy_time": "2026-10-07 10:15:00",
        }
        self.assertFalse(
            idx.overnight_gap_rebuy_allowed(rec, session="2026-10-08")
        )


class TestApplyExitFillGapRebuyStamp(unittest.TestCase):
    def setUp(self) -> None:
        self.book = {
            "updated_at": None,
            "account_total": 300000.0,
            "account_cash": 200000.0,
            "account_total_open": 300000.0,
            "account_total_open_session": "2026-10-08",
            "paper_equity_base": 300000.0,
            "paper_pnl_start": "2026-09-09",
            "positions": {},
            "realized_today": {},
            "closed_today": {},
            "daily_settlements": {},
            "factor2": {"equity": 300000.0, "dd_pct": 0.0, "action": "hold"},
        }
        self._load = idx.load_holdings
        self._save = idx.save_holdings
        self._append = idx.append_trade
        self._remember = idx.remember_factor_trigger
        idx.load_holdings = lambda: self.book
        idx.save_holdings = self._save_book
        idx.append_trade = lambda *_a, **_k: None
        idx.remember_factor_trigger = lambda *_a, **_k: None
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
        self._wx._WATCH_WECHAT_ENABLED = self._wx_flag

    def _fill(self, **kw):
        defaults = dict(
            code="600000",
            meta={"name": "测试", "market": "上证"},
            fill_px=9.50,
            qty=400,
            cost=10.0,
            session="2026-10-08",
            buy_time="2026-10-07 10:15:00",
            prev_close=10.2,
            open_px=9.50,
            px_digits=2,
            reason=REASON_STOP,
            trade_note="gap-rebuy",
            first_hit_ts="2026-10-08 09:30:00",
            exit_kind="open_protect",
        )
        defaults.update(kw)
        return idx.apply_exit_fill(**defaults)

    def test_open_protect_overnight_noted_stamps(self) -> None:
        self.book["positions"]["600000"] = _pos()
        rec = self._fill()
        self.assertTrue(rec.get("full_exit"))
        self.assertTrue(rec.get("prior_stop_noted"))
        self.assertTrue(rec.get("allow_intraday_rebuy"))
        self.assertTrue(
            idx.overnight_gap_rebuy_allowed(rec, session="2026-10-08")
        )

    def test_path_exit_does_not_stamp(self) -> None:
        self.book["positions"]["600000"] = _pos()
        rec = self._fill(exit_kind="path", first_hit_ts="2026-10-08 10:12:00")
        self.assertTrue(rec.get("full_exit"))
        self.assertFalse(rec.get("allow_intraday_rebuy"))
        self.assertFalse(
            idx.overnight_gap_rebuy_allowed(rec, session="2026-10-08")
        )

    def test_no_prior_note_does_not_stamp(self) -> None:
        self.book["positions"]["600000"] = _pos(stop_noted=False)
        rec = self._fill()
        self.assertFalse(rec.get("prior_stop_noted"))
        self.assertFalse(rec.get("allow_intraday_rebuy"))


class TestApplyTriggerGapRebuy(unittest.TestCase):
    def test_sold_today_without_flag_still_bans(self) -> None:
        row = {
            "持仓状态": "已平仓",
            "预警": "止损",
            "已触买": "否",
            "买点": 10.5,
            "止损": 9.8,
            "成交价": 9.8,
        }
        sig = {
            "hit_buy": False,
            "hit_stop": True,
            "因子触发": "已触发",
            "持仓状态": "已平仓",
        }
        idx._apply_trigger_date_fields(
            row,
            sig=sig,
            session="2026-10-08",
            last_px=10.2,
            px_digits=2,
            buy_time="2026-10-07",
            qty=0,
            replay={"holding": False},
            code="600000",
            allow_entry=True,
        )
        self.assertTrue(row.get("当日禁买"))

    def test_gap_rebuy_flag_clears_ban(self) -> None:
        row = {
            "持仓状态": "待买入",
            "预警": "竞价止损·允许回买",
            "已触买": "否",
            "买点": 10.5,
            "止损": 9.8,
            "成交价": 9.5,
            "隔夜竞价回买": True,
        }
        sig = {
            "hit_buy": False,
            "hit_stop": True,
            "因子触发": "已触发",
            "持仓状态": "待买入",
        }
        idx._apply_trigger_date_fields(
            row,
            sig=sig,
            session="2026-10-08",
            last_px=10.2,
            px_digits=2,
            buy_time=None,
            qty=0,
            replay={"holding": False},
            code="600000",
            allow_entry=True,
        )
        self.assertFalse(row.get("当日禁买"))
        self.assertTrue(row.get("隔夜竞价回买"))


if __name__ == "__main__":
    unittest.main()
