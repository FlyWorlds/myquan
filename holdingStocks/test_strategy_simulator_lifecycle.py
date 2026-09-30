"""Strategy Simulator Lifecycle + Live Quote Intraminute Trigger.

Layer A 与 Paper 严格隔离。不写 holdings / capital / exit engine。
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parents[1]
_HOLD = Path(__file__).resolve().parent
for p in (str(_ROOT), str(_HOLD)):
    if p not in sys.path:
        sys.path.insert(0, p)

import strategy_simulator as sim  # noqa: E402

_TEST_NOW = datetime(2026, 9, 23, 9, 50, 0)


def _eval(**kw):
    kw.setdefault("now", _TEST_NOW)
    kw.setdefault("stale_after", 86400.0)  # 测试默认放宽；stale 用例显式覆盖
    return sim.evaluate_live_transition(**kw)


class _TmpSim(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        root = Path(self._td.name)
        self._state = root / "strategy_sim_state.json"
        self._events = root / "strategy_signal_events.json"
        self._p_state = mock.patch.object(sim, "STATE_FILE", self._state)
        self._p_events = mock.patch.object(sim, "EVENTS_FILE", self._events)
        self._p_state.start()
        self._p_events.start()
        self._p_pnl = mock.patch("watch_config.STRATEGY_PNL_START", "2026-01-01")
        self._p_pnl.start()
        sim.reset_memory_for_tests()

    def tearDown(self) -> None:
        self._p_state.stop()
        self._p_events.stop()
        self._p_pnl.stop()
        sim.reset_memory_for_tests()
        self._td.cleanup()


class TestSimulatorLifecycle(_TmpSim):
    def test_flat_no_mark(self) -> None:
        book = sim.empty_book(strategy_id="strategy16", symbol="600330")
        sim.mark_book(book, 10.0)
        a = book["cumulative_return_pct"]
        sim.mark_book(book, 12.0)
        self.assertEqual(book["state"], "FLAT")
        self.assertEqual(float(book["virtual_shares"]), 0.0)
        self.assertEqual(book["cumulative_return_pct"], a)

    def test_buy_transition(self) -> None:
        r = _eval(
            strategy_id="strategy16",
            symbol="600330",
            live_last=10.08,
            quote_ts="2026-09-23 09:31:05",
            buy_level=10.0,
            sell_level=9.5,
            allow_entry=True,
            reason="test",
        )
        self.assertEqual(r["transition"], "BUY")
        self.assertEqual(r["book"]["state"], "LONG")
        self.assertEqual(r["book"]["entry_price"], 10.08)
        self.assertEqual(r["book"]["entry_time"], "2026-09-23 09:31:05")
        self.assertGreater(float(r["book"]["virtual_shares"]), 0)

    def test_before_pnl_start_skips_buy(self) -> None:
        with mock.patch("watch_config.STRATEGY_PNL_START", "2026-10-08"):
            r = _eval(
                strategy_id="strategy16",
                symbol="002273",
                live_last=24.72,
                quote_ts="2026-09-30 10:00:00",
                buy_level=20.0,
                sell_level=19.0,
                allow_entry=True,
                reason="test",
            )
        self.assertEqual(r["skipped"], "before_pnl_start")
        self.assertIsNone(r["transition"])
        self.assertEqual(r["book"]["state"], "FLAT")
        self.assertEqual(float(r["book"]["trades"]), 0)

    def test_long_live_mark(self) -> None:
        _eval(
            strategy_id="strategy16",
            symbol="600330",
            live_last=10.08,
            quote_ts="2026-09-23 09:31:05",
            buy_level=10.0,
            sell_level=9.5,
            allow_entry=True,
        )
        b1 = sim.get_book("strategy16", "600330")
        r1 = float(b1["cumulative_return_pct"])
        sim.mark_book(b1, 10.50, quote_ts="2026-09-23 09:31:20")
        sim.save_state()
        b2 = sim.get_book("strategy16", "600330")
        self.assertGreater(float(b2["cumulative_return_pct"]), r1)
        self.assertAlmostEqual(
            float(b2["single_return_pct"]), (10.50 / 10.08 - 1) * 100, places=2
        )

    def test_sell_transition_and_freeze(self) -> None:
        _eval(
            strategy_id="strategy16",
            symbol="600330",
            live_last=10.08,
            quote_ts="2026-09-23 09:31:05",
            buy_level=10.0,
            sell_level=9.5,
            allow_entry=True,
        )
        r = _eval(
            strategy_id="strategy16",
            symbol="600330",
            live_last=9.40,
            quote_ts="2026-09-24 09:45:00",
            buy_level=10.0,
            sell_level=9.5,
            allow_entry=False,
        )
        self.assertEqual(r["transition"], "SELL")
        self.assertEqual(r["book"]["state"], "FLAT")
        frozen = float(r["book"]["cumulative_return_pct"])
        book = sim.get_book("strategy16", "600330")
        sim.mark_book(book, 20.0)
        self.assertEqual(float(book["cumulative_return_pct"]), frozen)
        self.assertEqual(float(book["virtual_shares"]), 0.0)

    def test_second_trade(self) -> None:
        _eval(
            strategy_id="strategy16",
            symbol="002636",
            live_last=10.0,
            quote_ts="2026-09-23 09:31:05",
            buy_level=9.9,
            sell_level=9.5,
            allow_entry=True,
        )
        _eval(
            strategy_id="strategy16",
            symbol="002636",
            live_last=9.4,
            quote_ts="2026-09-24 10:00:00",
            buy_level=9.9,
            sell_level=9.5,
            allow_entry=False,
        )
        r = _eval(
            strategy_id="strategy16",
            symbol="002636",
            live_last=10.2,
            quote_ts="2026-09-25 09:40:00",
            buy_level=10.0,
            sell_level=9.6,
            allow_entry=True,
        )
        self.assertEqual(r["transition"], "BUY")
        self.assertEqual(r["book"]["entry_price"], 10.2)
        self.assertEqual(int(r["book"]["trades"]), 1)

    def test_ten_signals_all_simulated(self) -> None:
        codes = [f"{600000 + i}" for i in range(10)]
        for i, code in enumerate(codes):
            r = _eval(
                strategy_id="strategy16",
                symbol=code,
                live_last=10.0 + i * 0.01,
                quote_ts=f"2026-09-23 09:31:{i:02d}",
                buy_level=10.0,
                sell_level=9.0,
                allow_entry=True,
            )
            self.assertEqual(r["transition"], "BUY", msg=code)
            self.assertEqual(r["book"]["state"], "LONG", msg=code)
        books = sim.snapshot_books("strategy16")
        self.assertEqual(sum(1 for b in books.values() if b.get("state") == "LONG"), 10)

    def test_paper_limit_does_not_block_simulator(self) -> None:
        for i in range(5):
            code = f"60120{i}"
            r = _eval(
                strategy_id="strategy16",
                symbol=code,
                live_last=11.0,
                quote_ts="2026-09-23 09:35:00",
                buy_level=10.5,
                sell_level=10.0,
                allow_entry=True,
            )
            self.assertEqual(r["transition"], "BUY")

    def test_zero_paper_cash_does_not_block_simulator(self) -> None:
        r = _eval(
            strategy_id="strategy16",
            symbol="600552",
            live_last=10.5,
            quote_ts="2026-09-23 09:35:00",
            buy_level=10.0,
            sell_level=9.5,
            allow_entry=True,
        )
        self.assertEqual(r["transition"], "BUY")
        self.assertGreater(float(r["book"]["virtual_shares"]), 0)

    def test_paper_stop_does_not_close_strategy(self) -> None:
        _eval(
            strategy_id="strategy16",
            symbol="603328",
            live_last=15.0,
            quote_ts="2026-09-23 09:35:00",
            buy_level=14.0,
            sell_level=13.0,
            allow_entry=True,
        )
        book = sim.get_book("strategy16", "603328")
        self.assertEqual(book["state"], "LONG")
        sim.mark_book(book, 13.5)
        self.assertEqual(book["state"], "LONG")

    def test_strategy_sell_does_not_force_paper_exit(self) -> None:
        _eval(
            strategy_id="strategy16",
            symbol="000070",
            live_last=18.0,
            quote_ts="2026-09-23 09:35:00",
            buy_level=17.0,
            sell_level=16.0,
            allow_entry=True,
        )
        r = _eval(
            strategy_id="strategy16",
            symbol="000070",
            live_last=15.5,
            quote_ts="2026-09-24 10:00:00",
            buy_level=17.0,
            sell_level=16.0,
            allow_entry=False,
        )
        self.assertEqual(r["transition"], "SELL")
        self.assertNotIn("持仓", r["book"])
        self.assertNotIn("account_cash", r["book"])


class TestLiveRealtime(_TmpSim):
    def test_live_buy_intraminute(self) -> None:
        r0 = _eval(
            strategy_id="strategy16",
            symbol="600540",
            live_last=10.18,
            quote_ts="2026-09-23 09:31:02",
            buy_level=10.20,
            sell_level=9.8,
            allow_entry=True,
        )
        self.assertIsNone(r0["transition"])
        r1 = _eval(
            strategy_id="strategy16",
            symbol="600540",
            live_last=10.21,
            quote_ts="2026-09-23 09:31:05",
            buy_level=10.20,
            sell_level=9.8,
            allow_entry=True,
        )
        self.assertEqual(r1["transition"], "BUY")
        self.assertEqual(r1["book"]["entry_time"], "2026-09-23 09:31:05")
        self.assertEqual(r1["book"]["entry_price"], 10.21)

    def test_live_sell_intraminute(self) -> None:
        _eval(
            strategy_id="strategy16",
            symbol="600540",
            live_last=10.30,
            quote_ts="2026-09-23 09:31:05",
            buy_level=10.20,
            sell_level=9.80,
            allow_entry=True,
        )
        r = _eval(
            strategy_id="strategy16",
            symbol="600540",
            live_last=9.75,
            quote_ts="2026-09-24 09:31:18",
            buy_level=10.20,
            sell_level=9.80,
            allow_entry=False,
        )
        self.assertEqual(r["transition"], "SELL")
        self.assertEqual(r["book"]["exit_time"], "2026-09-24 09:31:18")

    def test_no_duplicate_buy(self) -> None:
        for px, sec in ((10.01, "01"), (10.02, "02"), (10.03, "03"), (10.04, "04")):
            r = _eval(
                strategy_id="strategy16",
                symbol="603042",
                live_last=px,
                quote_ts=f"2026-09-23 09:32:{sec}",
                buy_level=10.0,
                sell_level=9.5,
                allow_entry=True,
            )
            if sec == "01":
                self.assertEqual(r["transition"], "BUY")
            else:
                self.assertIsNone(r["transition"])
                self.assertEqual(r["book"]["state"], "LONG")

    def test_no_duplicate_sell(self) -> None:
        _eval(
            strategy_id="strategy16",
            symbol="603042",
            live_last=10.5,
            quote_ts="2026-09-23 09:32:00",
            buy_level=10.0,
            sell_level=9.5,
            allow_entry=True,
        )
        first = True
        for px, sec in ((9.40, "10"), (9.30, "11"), (9.20, "12")):
            r = _eval(
                strategy_id="strategy16",
                symbol="603042",
                live_last=px,
                quote_ts=f"2026-09-24 09:40:{sec}",
                buy_level=10.0,
                sell_level=9.5,
                allow_entry=False,
            )
            if first:
                self.assertEqual(r["transition"], "SELL")
                first = False
            else:
                self.assertIsNone(r["transition"])

    def test_gap_up_trigger(self) -> None:
        r = _eval(
            strategy_id="strategy16",
            symbol="603663",
            live_last=10.30,
            quote_ts="2026-09-23 09:31:00",
            buy_level=10.0,
            sell_level=9.5,
            allow_entry=True,
        )
        self.assertEqual(r["transition"], "BUY")
        self.assertEqual(r["book"]["entry_price"], 10.30)

    def test_gap_down_trigger(self) -> None:
        _eval(
            strategy_id="strategy16",
            symbol="603663",
            live_last=10.5,
            quote_ts="2026-09-23 09:31:00",
            buy_level=10.0,
            sell_level=9.80,
            allow_entry=True,
        )
        r = _eval(
            strategy_id="strategy16",
            symbol="603663",
            live_last=9.60,
            quote_ts="2026-09-24 09:35:00",
            buy_level=10.0,
            sell_level=9.80,
            allow_entry=False,
        )
        self.assertEqual(r["transition"], "SELL")

    def test_stale_quote_no_trigger(self) -> None:
        old = (_TEST_NOW - timedelta(seconds=60)).strftime("%Y-%m-%d %H:%M:%S")
        r = _eval(
            strategy_id="strategy16",
            symbol="000002",
            live_last=10.5,
            quote_ts=old,
            buy_level=10.0,
            sell_level=9.5,
            allow_entry=True,
            stale_after=15.0,
        )
        self.assertEqual(r["skipped"], "stale_quote")
        self.assertIsNone(r["transition"])
        self.assertEqual(sim.get_book("strategy16", "000002")["state"], "FLAT")

    def test_quote_timestamp(self) -> None:
        r = _eval(
            strategy_id="strategy16",
            symbol="000002",
            live_last=10.5,
            quote_ts="2026-09-23 09:31:05",
            buy_level=10.0,
            sell_level=9.5,
            allow_entry=True,
        )
        self.assertEqual(r["telemetry"]["quote_time"], "2026-09-23 09:31:05")
        self.assertIsNotNone(r["telemetry"]["evaluation_time"])
        self.assertEqual(r["event"]["quote_timestamp"], "2026-09-23 09:31:05")


class TestT1AndNoSameDayReentry(_TmpSim):
    """与 open_break / 日线 bootstrap 同口径：买入当日不卖；卖出当日不再买回。"""

    def _buy(self, code: str, ts: str = "2026-09-23 09:33:22") -> None:
        r = _eval(
            strategy_id="strategy16",
            symbol=code,
            live_last=14.04,
            quote_ts=ts,
            buy_level=14.04,
            sell_level=13.5,
            allow_entry=True,
        )
        self.assertEqual(r["transition"], "BUY")

    def test_same_day_sell_blocked_keeps_long(self) -> None:
        self._buy("600100")
        r = _eval(
            strategy_id="strategy16",
            symbol="600100",
            live_last=13.72,
            quote_ts="2026-09-23 09:38:42",
            buy_level=14.04,
            sell_level=13.93,
            allow_entry=True,
        )
        self.assertIsNone(r["transition"])
        self.assertEqual(r["skipped"], "t1_locked")
        self.assertEqual(r["book"]["state"], "LONG")
        self.assertEqual(int(r["book"]["trades"]), 0)
        self.assertLess(float(r["book"]["cumulative_return_pct"]), 0.0)

    def test_next_day_sell_allowed(self) -> None:
        self._buy("600101")
        r = _eval(
            strategy_id="strategy16",
            symbol="600101",
            live_last=13.72,
            quote_ts="2026-09-24 09:31:00",
            buy_level=14.04,
            sell_level=13.93,
            allow_entry=False,
        )
        self.assertEqual(r["transition"], "SELL")

    def test_t0_symbol_can_sell_same_day(self) -> None:
        self._buy("510300")
        r = _eval(
            strategy_id="strategy16",
            symbol="510300",
            live_last=13.72,
            quote_ts="2026-09-23 09:38:42",
            buy_level=14.04,
            sell_level=13.93,
            allow_entry=False,
            t0=True,
        )
        self.assertEqual(r["transition"], "SELL")

    def test_no_rebuy_on_exit_day(self) -> None:
        self._buy("600102")
        _eval(
            strategy_id="strategy16",
            symbol="600102",
            live_last=13.4,
            quote_ts="2026-09-24 09:40:00",
            buy_level=14.0,
            sell_level=13.5,
            allow_entry=False,
        )
        r = _eval(
            strategy_id="strategy16",
            symbol="600102",
            live_last=14.2,
            quote_ts="2026-09-24 10:30:00",
            buy_level=14.0,
            sell_level=13.5,
            allow_entry=True,
        )
        self.assertIsNone(r["transition"])
        self.assertEqual(r["skipped"], "exited_today")
        r2 = _eval(
            strategy_id="strategy16",
            symbol="600102",
            live_last=14.2,
            quote_ts="2026-09-25 09:31:00",
            buy_level=14.0,
            sell_level=13.5,
            allow_entry=True,
        )
        self.assertEqual(r2["transition"], "BUY")

    def test_crossed_levels_do_not_flip_flop(self) -> None:
        """买点≤现价≤卖点（交叉）时逐 tick 评估：当日只允许一次 BUY。"""
        n_events = 0
        for sec in range(30):
            r = _eval(
                strategy_id="strategy16",
                symbol="600103",
                live_last=55.03,
                quote_ts=f"2026-09-23 14:25:{sec:02d}",
                buy_level=55.0,
                sell_level=55.04,
                allow_entry=True,
            )
            if r["transition"]:
                n_events += 1
        self.assertEqual(n_events, 1)
        self.assertEqual(sim.get_book("strategy16", "600103")["state"], "LONG")


class TestRestartPreserve(_TmpSim):
    def test_live_buy_restart_preserve(self) -> None:
        _eval(
            strategy_id="strategy16",
            symbol="603328",
            live_last=15.2,
            quote_ts="2026-09-23 09:31:05",
            buy_level=14.0,
            sell_level=13.0,
            allow_entry=True,
        )
        entry = sim.get_book("strategy16", "603328")["entry_price"]
        et = sim.get_book("strategy16", "603328")["entry_time"]
        cum = sim.get_book("strategy16", "603328")["cumulative_return_pct"]
        sim.reset_memory_for_tests()
        book = sim.get_book("strategy16", "603328")
        self.assertEqual(book["state"], "LONG")
        self.assertEqual(book["entry_price"], entry)
        self.assertEqual(book["entry_time"], et)
        self.assertEqual(book["cumulative_return_pct"], cum)

    def test_live_sell_restart_preserve(self) -> None:
        _eval(
            strategy_id="strategy16",
            symbol="603328",
            live_last=15.2,
            quote_ts="2026-09-23 09:31:05",
            buy_level=14.0,
            sell_level=13.0,
            allow_entry=True,
        )
        _eval(
            strategy_id="strategy16",
            symbol="603328",
            live_last=12.5,
            quote_ts="2026-09-24 10:00:00",
            buy_level=14.0,
            sell_level=13.0,
            allow_entry=False,
        )
        cum = sim.get_book("strategy16", "603328")["cumulative_return_pct"]
        sim.reset_memory_for_tests()
        book = sim.get_book("strategy16", "603328")
        self.assertEqual(book["state"], "FLAT")
        self.assertEqual(book["cumulative_return_pct"], cum)
        self.assertEqual(float(book["virtual_shares"]), 0.0)

    def test_no_duplicate_event_after_restart(self) -> None:
        _eval(
            strategy_id="strategy16",
            symbol="600330",
            live_last=10.5,
            quote_ts="2026-09-23 09:31:05",
            buy_level=10.0,
            sell_level=9.5,
            allow_entry=True,
        )
        sim.reset_memory_for_tests()
        before = json.loads(self._events.read_text(encoding="utf-8"))
        n0 = len(before.get("events") or [])
        _eval(
            strategy_id="strategy16",
            symbol="600330",
            live_last=10.5,
            quote_ts="2026-09-23 09:31:05",
            buy_level=10.0,
            sell_level=9.5,
            allow_entry=True,
        )
        after = json.loads(self._events.read_text(encoding="utf-8"))
        self.assertEqual(len(after.get("events") or []), n0)
        self.assertEqual(sim.get_book("strategy16", "600330")["state"], "LONG")


class TestSessionGatesPaperUntouched(_TmpSim):
    def test_auction_observe_simulator_buy_ok(self) -> None:
        r = _eval(
            strategy_id="strategy16",
            symbol="601208",
            live_last=12.0,
            quote_ts="2026-09-23 09:20:00",
            buy_level=11.5,
            sell_level=11.0,
            allow_entry=True,
        )
        self.assertEqual(r["transition"], "BUY")

    def test_auction_observe_simulator_sell_blocked(self) -> None:
        """9:30 前不得模拟卖出；等到开盘铃按开盘价。"""
        _eval(
            strategy_id="strategy16",
            symbol="000009",
            live_last=6.72,
            quote_ts="2026-09-29 09:31:00",
            buy_level=6.72,
            sell_level=6.50,
            allow_entry=True,
        )
        blocked = _eval(
            strategy_id="strategy16",
            symbol="000009",
            live_last=6.88,
            quote_ts="2026-09-30 09:25:38",
            buy_level=7.06,
            sell_level=6.98,
            allow_entry=False,
            day_open=6.88,
        )
        self.assertIsNone(blocked["transition"])
        self.assertEqual(blocked["skipped"], "wait_auction")
        self.assertEqual(sim.get_book("strategy16", "000009")["state"], "LONG")
        filled = _eval(
            strategy_id="strategy16",
            symbol="000009",
            live_last=6.88,
            quote_ts="2026-09-30 09:30:01",
            buy_level=7.06,
            sell_level=6.98,
            allow_entry=False,
            day_open=6.88,
        )
        self.assertEqual(filled["transition"], "SELL")
        book = sim.get_book("strategy16", "000009")
        self.assertEqual(book["state"], "FLAT")
        self.assertAlmostEqual(float(book["exit_price"]), 6.88, places=2)
        self.assertEqual(book["exit_time"], "2026-09-30 09:30:00")

    def test_no_symbol_hardcode_in_simulator(self) -> None:
        text = Path(sim.__file__).read_text(encoding="utf-8")
        for token in ("000002", "万科", "603328"):
            self.assertNotIn(token, text)


class TestApplyRow(_TmpSim):
    def test_apply_book_to_row_semantics(self) -> None:
        _eval(
            strategy_id="strategy16",
            symbol="600330",
            live_last=10.5,
            quote_ts="2026-09-23 09:31:05",
            buy_level=10.0,
            sell_level=9.5,
            allow_entry=True,
        )
        row: dict = {"持仓": 0, "持仓状态": "空仓"}
        sim.apply_book_to_row(row, sim.get_book("strategy16", "600330"))
        self.assertEqual(row["策略状态"], "策略持有")
        self.assertEqual(row["策略模拟状态"], "LONG")
        self.assertEqual(row["策略收益语义"], "strategy_simulator_ledger")
        self.assertTrue(row["策略累计持有"])
        self.assertEqual(row["持仓"], 0)
        self.assertEqual(row["持仓状态"], "空仓")

    def test_apply_book_does_not_clobber_paper_signal_time(self) -> None:
        _eval(
            strategy_id="strategy16",
            symbol="600330",
            live_last=10.5,
            quote_ts="2026-09-23 09:31:05",
            buy_level=10.0,
            sell_level=9.5,
            allow_entry=True,
        )
        row: dict = {"持仓": 0, "持仓状态": "今日平仓", "信号时间": "09:30:00"}
        sim.apply_book_to_row(row, sim.get_book("strategy16", "600330"))
        self.assertEqual(row["信号时间"], "09:30:00")


if __name__ == "__main__":
    unittest.main()
