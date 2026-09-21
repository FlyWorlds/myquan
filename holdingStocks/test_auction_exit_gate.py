"""集合竞价止损门控：09:30 前不可执行 SELL，UI 不得冒充「待卖出」。"""

from __future__ import annotations

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
from watch_config import (  # noqa: E402
    is_auction_observe,
    is_auction_result,
    is_exit_executable,
    is_signal_window,
    is_threshold_ready,
    market_phase,
    pre_continuous_stop_ui,
)


def _at(h: int, m: int, s: int = 0) -> dt.datetime:
    return dt.datetime(2026, 9, 21, h, m, s)


class TestMarketPhaseAuctionGates(unittest.TestCase):
    def test_phase_boundaries(self) -> None:
        self.assertEqual(market_phase(_at(9, 14, 59)), "pre_auction")
        self.assertEqual(market_phase(_at(9, 15, 0)), "auction_cancel")
        self.assertEqual(market_phase(_at(9, 20, 0)), "auction_locked")
        self.assertEqual(market_phase(_at(9, 24, 59)), "auction_locked")
        self.assertEqual(market_phase(_at(9, 25, 0)), "open_set")
        self.assertEqual(market_phase(_at(9, 29, 59)), "open_set")
        self.assertEqual(market_phase(_at(9, 30, 0)), "continuous")
        self.assertEqual(market_phase(_at(9, 30, 1)), "continuous")

    def test_executable_only_continuous(self) -> None:
        for t in (
            _at(9, 14, 59),
            _at(9, 15),
            _at(9, 20),
            _at(9, 24, 59),
            _at(9, 25),
            _at(9, 29, 59),
        ):
            self.assertFalse(is_exit_executable(t), t)
            self.assertFalse(is_signal_window(t), t)
        self.assertTrue(is_exit_executable(_at(9, 30)))
        self.assertTrue(is_exit_executable(_at(9, 30, 1)))
        self.assertTrue(is_auction_observe(_at(9, 20)))
        self.assertTrue(is_auction_result(_at(9, 26)))
        self.assertFalse(is_threshold_ready(_at(9, 20)))
        self.assertTrue(is_threshold_ready(_at(9, 25)))


class TestPreContinuousUi(unittest.TestCase):
    def test_demote_never_pending_sell_status(self) -> None:
        for ph in ("auction_cancel", "auction_locked", "open_set"):
            out = idx._demote_pre_signal_window(
                {
                    "alert": "已触止损",
                    "hit_stop": True,
                    "因子触发": "已触发",
                    "持仓状态": "待卖出",
                },
                phase=ph,
            )
            self.assertEqual(out["持仓状态"], "已经买入", ph)
            self.assertFalse(out["hit_stop"])
            self.assertTrue(out["pending_sell"])
            self.assertNotEqual(out["alert"], "待卖出")
            if ph in ("auction_cancel", "auction_locked"):
                self.assertEqual(out["alert"], "竞价观察")
            else:
                self.assertEqual(out["alert"], "竞价止损预警")

    def test_pre_continuous_stop_ui_labels(self) -> None:
        obs = pre_continuous_stop_ui(phase="auction_locked")
        self.assertEqual(obs["持仓状态"], "已经买入")
        self.assertEqual(obs["alert"], "竞价观察")
        res = pre_continuous_stop_ui(phase="open_set")
        self.assertEqual(res["alert"], "竞价止损预警")


class TestPaperExitAuctionGate(unittest.TestCase):
    """三类规则：竞价期 hit_show 可有，hit（可成交）必须 False。"""

    def _dec(
        self,
        *,
        signal_ok: bool,
        open_px: float = 3.66,
        last: float = 3.66,
        working_stop: float = 3.71,
        path_hit: bool = False,
        path_fill_px: float = 0.0,
        t1: bool = False,
    ) -> dict:
        return idx.paper_exit_decision(
            qty=19300,
            sellable=0 if t1 else 19300,
            t1_today=t1,
            last=last,
            open_px=open_px,
            prev_close=3.75,
            cost=3.81,
            peak_high=3.90,
            working_stop=working_stop,
            path_hit=path_hit,
            path_fill_px=path_fill_px,
            path_action_kind="full",
            signal_ok=signal_ok,
            buy_time="2026-09-18 10:00:00",
            session="2026-09-21",
        )

    def test_0920_open_protect_no_fill(self) -> None:
        # 竞价指示价低于保护 → 展示可有，成交禁止
        dec = self._dec(signal_ok=False, open_px=3.66, last=3.70, working_stop=3.80)
        self.assertFalse(dec.get("hit"))
        self.assertEqual(dec.get("reason"), "wait_auction")

    def test_0920_working_stop_no_fill(self) -> None:
        dec = self._dec(signal_ok=False, open_px=3.80, last=3.66, working_stop=3.71)
        self.assertFalse(dec.get("hit"))
        self.assertEqual(dec.get("reason"), "wait_auction")

    def test_0920_path_no_fill(self) -> None:
        dec = self._dec(
            signal_ok=False,
            open_px=3.80,
            last=3.70,
            working_stop=3.71,
            path_hit=True,
            path_fill_px=3.71,
        )
        self.assertFalse(dec.get("hit"))
        self.assertEqual(dec.get("reason"), "wait_auction")

    def test_0926_all_rules_no_fill(self) -> None:
        for kwargs in (
            {"open_px": 3.66, "last": 3.70, "working_stop": 3.80},
            {"open_px": 3.80, "last": 3.66, "working_stop": 3.71},
            {
                "open_px": 3.80,
                "last": 3.70,
                "working_stop": 3.71,
                "path_hit": True,
                "path_fill_px": 3.71,
            },
        ):
            dec = self._dec(signal_ok=False, **kwargs)
            self.assertFalse(dec.get("hit"), kwargs)
            self.assertEqual(dec.get("reason"), "wait_auction")

    def test_0930_working_stop_fills(self) -> None:
        dec = self._dec(signal_ok=True, open_px=3.80, last=3.66, working_stop=3.71)
        self.assertTrue(dec.get("hit"))
        self.assertEqual(dec.get("kind"), "last")
        self.assertAlmostEqual(float(dec["fill_px"]), 3.71, places=4)

    def test_0930_open_protect_fills(self) -> None:
        dec = self._dec(signal_ok=True, open_px=3.66, last=3.80, working_stop=3.90)
        self.assertTrue(dec.get("hit"))
        self.assertEqual(dec.get("kind"), "open_protect")
        self.assertAlmostEqual(float(dec["fill_px"]), 3.66, places=4)

    def test_0930_path_fills(self) -> None:
        dec = self._dec(
            signal_ok=True,
            open_px=3.80,
            last=3.70,
            working_stop=3.90,
            path_hit=True,
            path_fill_px=3.72,
        )
        self.assertTrue(dec.get("hit"))
        self.assertEqual(dec.get("kind"), "path")
        self.assertAlmostEqual(float(dec["fill_px"]), 3.72, places=4)

    def test_t1_after_0930_blocks(self) -> None:
        dec = self._dec(
            signal_ok=True,
            open_px=3.66,
            last=3.66,
            working_stop=3.71,
            t1=True,
        )
        self.assertFalse(dec.get("hit"))
        self.assertEqual(dec.get("reason"), "t1")


class TestSettleDueRespectsSignalOk(unittest.TestCase):
    def setUp(self) -> None:
        self.book = {
            "positions": {
                "000055": {
                    "code": "000055",
                    "name": "方大集团",
                    "qty": 19300,
                    "cost": 3.81,
                    "available": 19300,
                    "buy_time": "2026-09-18 10:00:00",
                }
            },
            "realized_today": {},
            "closed_today": {},
            "account_cash": 0.0,
            "account_total": 300000.0,
            "paper_equity_base": 300000.0,
        }
        self._load = idx.load_holdings
        self._save = idx.save_holdings
        self._append = idx.append_trade
        idx.load_holdings = lambda: self.book
        idx.save_holdings = lambda d: setattr(self, "book", d) or None
        idx.append_trade = lambda *_a, **_k: None

    def tearDown(self) -> None:
        idx.load_holdings = self._load
        idx.save_holdings = self._save
        idx.append_trade = self._append

    def test_settle_due_noop_when_not_signal_ok(self) -> None:
        rows = [
            {
                "代码": "000055",
                "现价": 3.66,
                "开盘": 3.66,
                "昨收": 3.75,
                "止损": 3.71,
                "成本": 3.81,
                "已触止损": "是",
                "_path_hit": True,
                "_path_fill_px": 3.71,
            }
        ]
        n = idx.settle_due_paper_stops(
            rows, session="2026-09-21", signal_ok=False
        )
        self.assertEqual(n, 0)
        self.assertEqual(self.book["positions"]["000055"]["qty"], 19300)
        self.assertFalse(self.book.get("realized_today"))


class TestFinalizeStatusAuction(unittest.TestCase):
    def test_hit_stop_during_auction_stays_holding(self) -> None:
        row = {
            "持仓": 19300,
            "可用": 19300,
            "已触止损": "是",
            "预警": "竞价观察",
            "买入时间": "2026-09-18 10:00:00",
            "交易日": "2026-09-21",
            "t0": False,
        }
        with patch("index.market_phase", return_value="auction_locked"):
            with patch("index.is_exit_executable", return_value=False):
                idx._finalize_position_row(row)
        self.assertEqual(row["持仓状态"], "已经买入")
        self.assertFalse(row.get("可执行"))

    def test_hit_stop_continuous_pending_sell(self) -> None:
        row = {
            "持仓": 19300,
            "可用": 19300,
            "已触止损": "是",
            "预警": "已触止损",
            "买入时间": "2026-09-18 10:00:00",
            "交易日": "2026-09-21",
            "t0": False,
        }
        with patch("index.market_phase", return_value="continuous"):
            with patch("index.is_exit_executable", return_value=True):
                idx._finalize_position_row(row)
        self.assertEqual(row["持仓状态"], "待卖出")
        self.assertTrue(row.get("可执行"))


if __name__ == "__main__":
    unittest.main()
