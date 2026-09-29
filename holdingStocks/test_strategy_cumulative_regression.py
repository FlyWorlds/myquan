"""Strategy Cumulative Regression：FLAT ≠ cumulative 0；bootstrap 连续。"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

import pandas as pd

_ROOT = Path(__file__).resolve().parents[1]
_HOLD = Path(__file__).resolve().parent
for p in (str(_ROOT), str(_HOLD)):
    if p not in sys.path:
        sys.path.insert(0, p)

import strategy_simulator as sim  # noqa: E402

_TEST_NOW = datetime(2026, 9, 23, 9, 50, 0)


def _eval(**kw):
    kw.setdefault("now", _TEST_NOW)
    kw.setdefault("stale_after", 86400.0)
    return sim.evaluate_live_transition(**kw)


def _daily(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


class _Tmp(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        root = Path(self._td.name)
        self._p1 = mock.patch.object(sim, "STATE_FILE", root / "strategy_sim_state.json")
        self._p2 = mock.patch.object(sim, "EVENTS_FILE", root / "strategy_signal_events.json")
        self._p1.start()
        self._p2.start()
        sim.reset_memory_for_tests()

    def tearDown(self) -> None:
        self._p1.stop()
        self._p2.stop()
        sim.reset_memory_for_tests()
        self._td.cleanup()


class TestCumulativeInvariants(_Tmp):
    def test_never_traded_zero(self) -> None:
        book = sim.empty_book(strategy_id="strategy16", symbol="600001")
        sim.sync_flat_cumulative(book)
        self.assertEqual(book["state"], "FLAT")
        self.assertEqual(float(book["cumulative_return_pct"]), 0.0)

    def test_flat_profit_freeze(self) -> None:
        _eval(
            strategy_id="strategy16",
            symbol="600002",
            live_last=10.0,
            quote_ts="2026-09-23 09:31:00",
            buy_level=9.5,
            sell_level=8.0,
            allow_entry=True,
        )
        _eval(
            strategy_id="strategy16",
            symbol="600002",
            live_last=12.0,
            quote_ts="2026-09-24 09:40:00",
            buy_level=9.5,
            sell_level=12.5,
            allow_entry=False,
        )
        book = sim.get_book("strategy16", "600002")
        self.assertEqual(book["state"], "FLAT")
        cum = float(book["cumulative_return_pct"])
        self.assertGreater(cum, 0.0)
        sim.mark_book(book, 15.0)
        self.assertEqual(float(book["cumulative_return_pct"]), cum)
        sim.mark_book(book, 8.0)
        self.assertEqual(float(book["cumulative_return_pct"]), cum)

    def test_flat_loss_freeze(self) -> None:
        _eval(
            strategy_id="strategy16",
            symbol="600003",
            live_last=10.0,
            quote_ts="2026-09-23 09:31:00",
            buy_level=9.5,
            sell_level=8.0,
            allow_entry=True,
        )
        _eval(
            strategy_id="strategy16",
            symbol="600003",
            live_last=9.0,
            quote_ts="2026-09-24 09:40:00",
            buy_level=9.5,
            sell_level=9.5,
            allow_entry=False,
        )
        book = sim.get_book("strategy16", "600003")
        self.assertEqual(book["state"], "FLAT")
        cum = float(book["cumulative_return_pct"])
        self.assertLess(cum, 0.0)
        sim.mark_book(book, 20.0)
        self.assertEqual(float(book["cumulative_return_pct"]), cum)

    def test_long_mtm(self) -> None:
        _eval(
            strategy_id="strategy16",
            symbol="600004",
            live_last=10.0,
            quote_ts="2026-09-23 09:31:00",
            buy_level=9.5,
            sell_level=8.0,
            allow_entry=True,
        )
        book = sim.get_book("strategy16", "600004")
        sim.mark_book(book, 11.0)
        self.assertEqual(book["state"], "LONG")
        self.assertGreater(float(book["cumulative_return_pct"]), 0.0)

    def test_second_trade_compound(self) -> None:
        _eval(
            strategy_id="strategy16",
            symbol="600005",
            live_last=10.0,
            quote_ts="2026-09-23 09:31:00",
            buy_level=9.5,
            sell_level=8.0,
            allow_entry=True,
        )
        _eval(
            strategy_id="strategy16",
            symbol="600005",
            live_last=12.0,
            quote_ts="2026-09-24 09:40:00",
            buy_level=9.5,
            sell_level=12.5,
            allow_entry=False,
        )
        after_sell = float(sim.get_book("strategy16", "600005")["virtual_cash"])
        self.assertGreater(after_sell, sim.INITIAL_CASH)
        _eval(
            strategy_id="strategy16",
            symbol="600005",
            live_last=11.0,
            quote_ts="2026-09-25 10:00:00",
            buy_level=10.5,
            sell_level=9.0,
            allow_entry=True,
        )
        book = sim.get_book("strategy16", "600005")
        self.assertEqual(book["state"], "LONG")
        # 第二轮买入后现金应低于 after_sell，但高于「从 100000 重开」的典型路径
        self.assertLess(float(book["virtual_cash"]), after_sell)
        sim.mark_book(book, 12.0)
        # 不得静默回到仅基于 100000 的零附近（有第一轮利润）
        self.assertGreater(float(book["cumulative_return_pct"]), 5.0)

    def test_restart_flat_profit_preserve(self) -> None:
        _eval(
            strategy_id="strategy16",
            symbol="600006",
            live_last=10.0,
            quote_ts="2026-09-23 09:31:00",
            buy_level=9.5,
            sell_level=8.0,
            allow_entry=True,
        )
        _eval(
            strategy_id="strategy16",
            symbol="600006",
            live_last=12.0,
            quote_ts="2026-09-24 09:40:00",
            buy_level=9.5,
            sell_level=12.5,
            allow_entry=False,
        )
        before = dict(sim.get_book("strategy16", "600006"))
        sim.reset_memory_for_tests()
        after = sim.get_book("strategy16", "600006")
        self.assertEqual(after["state"], "FLAT")
        self.assertEqual(after["cumulative_return_pct"], before["cumulative_return_pct"])
        self.assertEqual(after["virtual_cash"], before["virtual_cash"])
        self.assertNotAlmostEqual(float(after["virtual_cash"]), sim.INITIAL_CASH)

    def test_restart_long_mtm_preserve(self) -> None:
        _eval(
            strategy_id="strategy16",
            symbol="600007",
            live_last=10.0,
            quote_ts="2026-09-23 09:31:00",
            buy_level=9.5,
            sell_level=8.0,
            allow_entry=True,
        )
        before = dict(sim.get_book("strategy16", "600007"))
        sim.reset_memory_for_tests()
        after = sim.get_book("strategy16", "600007")
        self.assertEqual(after["state"], "LONG")
        self.assertEqual(after["entry_price"], before["entry_price"])
        self.assertEqual(after["virtual_shares"], before["virtual_shares"])
        self.assertEqual(after["virtual_cash"], before["virtual_cash"])

    def test_no_reset_to_initial_equity(self) -> None:
        book = sim.get_book("strategy16", "600008")
        book["virtual_cash"] = 120000.0
        book["trades"] = 1
        book["state"] = "FLAT"
        book["bootstrapped"] = True
        sim.sync_flat_cumulative(book)
        sim.save_state()
        sim.reset_memory_for_tests()
        b2 = sim.get_book("strategy16", "600008")
        self.assertAlmostEqual(float(b2["virtual_cash"]), 120000.0)
        self.assertAlmostEqual(float(b2["cumulative_return_pct"]), 20.0)

    def test_ui_nonzero_flat(self) -> None:
        book = sim.empty_book(strategy_id="strategy16", symbol="600009")
        book["virtual_cash"] = 120000.0
        book["trades"] = 2
        book["state"] = "FLAT"
        sim.sync_flat_cumulative(book)
        row: dict = {}
        sim.apply_book_to_row(row, book)
        self.assertEqual(row["策略状态"], "空仓")
        self.assertEqual(row["策略收益%"], 20.0)

    def test_ui_zero_only_never_traded(self) -> None:
        book = sim.empty_book(strategy_id="strategy16", symbol="600010")
        row: dict = {}
        sim.apply_book_to_row(row, book)
        self.assertEqual(row["策略收益%"], 0.0)
        self.assertEqual(int(book.get("trades") or 0), 0)


class TestBootstrap(_Tmp):
    def test_bootstrap_seeds_nonzero_after_history(self) -> None:
        # 阴 → 触买 → 次日止损卖出，应留下非 0 累计
        from strategy.open_break import entry_trigger_price, stop_trigger_price

        ep = 0.025
        o2, o3 = 10.0, 10.5
        buy = entry_trigger_price(o2, entry_pct=ep, tick=0.01)
        stop3 = stop_trigger_price(o3, stop_pct=ep, tick=0.01)
        df = _daily(
            [
                {"date": "2026-09-16", "open": 10.0, "high": 10.1, "low": 9.9, "close": 10.0},
                {"date": "2026-09-17", "open": 10.0, "high": 10.2, "low": 9.8, "close": 9.7},
                {"date": "2026-09-18", "open": o2, "high": buy + 0.05, "low": 9.9, "close": buy + 0.02},
                {
                    "date": "2026-09-19",
                    "open": o3,
                    "high": o3 + 0.1,
                    "low": stop3 - 0.05,
                    "close": 10.0,
                },
            ]
        )
        info = sim.ensure_bootstrapped(
            "strategy16",
            "002636",
            df,
            start_date="2026-09-16",
            entry_pct=ep,
            stop_pct=ep,
            tick=0.01,
        )
        self.assertTrue(info.get("applied") or info.get("skipped") == "already_seeded")
        book = sim.get_book("strategy16", "002636")
        self.assertTrue(book.get("bootstrapped"))
        self.assertEqual(book["state"], "FLAT")
        self.assertGreaterEqual(int(book.get("trades") or 0), 1)
        # SELL 后 shares=0，cash 未必等于 initial
        self.assertEqual(float(book["virtual_shares"]), 0.0)
        # 累计可为正或负，但不应在有成交时被强制当成「从未交易」语义外的静默 0
        # （本路径止损卖出通常为小亏/小盈）
        sim.mark_book(book, 99.0)
        frozen = float(book["cumulative_return_pct"])
        sim.mark_book(book, 1.0)
        self.assertEqual(float(book["cumulative_return_pct"]), frozen)

    def test_bootstrap_once_no_double_count(self) -> None:
        df = _daily(
            [
                {"date": "2026-09-16", "open": 10.0, "high": 10.1, "low": 9.9, "close": 10.0},
                {"date": "2026-09-17", "open": 10.0, "high": 10.2, "low": 9.8, "close": 9.7},
                {"date": "2026-09-18", "open": 10.0, "high": 10.5, "low": 9.9, "close": 10.3},
            ]
        )
        a = sim.ensure_bootstrapped(
            "strategy16", "000049", df, start_date="2026-09-16", entry_pct=0.025, stop_pct=0.025
        )
        cash1 = float(sim.get_book("strategy16", "000049")["virtual_cash"])
        sh1 = float(sim.get_book("strategy16", "000049")["virtual_shares"])
        b = sim.ensure_bootstrapped(
            "strategy16", "000049", df, start_date="2026-09-16", entry_pct=0.025, stop_pct=0.025
        )
        self.assertEqual(b.get("skipped"), "already_seeded")
        self.assertEqual(float(sim.get_book("strategy16", "000049")["virtual_cash"]), cash1)
        self.assertEqual(float(sim.get_book("strategy16", "000049")["virtual_shares"]), sh1)
        self.assertTrue(a.get("applied"))


class TestNoFlatForcesZero(_Tmp):
    def test_sync_flat_not_force_zero_when_cash_moved(self) -> None:
        book = sim.empty_book(strategy_id="strategy16", symbol="600011")
        book["virtual_cash"] = 110000.0
        book["trades"] = 1
        book["state"] = "FLAT"
        sim.sync_flat_cumulative(book)
        self.assertEqual(book["cumulative_return_pct"], 10.0)


if __name__ == "__main__":
    unittest.main()
