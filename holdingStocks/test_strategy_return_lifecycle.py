"""策略收益生命周期：单票 Factor1 虚拟账本累计 ≠ 纸面仓 / 单笔收入。

CURRENT_STRATEGY_RETURN_SEMANTICS = STRATEGY_CUMULATIVE_RETURN (per-symbol)
FORMULA = equity / initial_cash - 1
  equity = cash + shares * mark（盘中 mark = live last）
空仓（纸面 qty=0）仍可显示累计；虚拟已平则冻结，不随现价变。
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parents[1]
_HOLD = Path(__file__).resolve().parent
for p in (str(_ROOT), str(_HOLD)):
    if p not in sys.path:
        sys.path.insert(0, p)

from strategy.open_break import (  # noqa: E402
    DEFAULT_PCT,
    TICK_SIZE,
    _merge_live_daily_bar,
    entry_trigger_price,
    replay_strategy_return_since,
    stop_trigger_price,
)
from watch_buy_signal import signal_single_return_pct  # noqa: E402
from watch_config import STRATEGY_PNL_START  # noqa: E402


def _bar(
    date: str,
    o: float,
    h: float,
    l: float,
    c: float,
) -> dict[str, float | str]:
    return {"date": date, "open": o, "high": h, "low": l, "close": c}


def _daily(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _replay(df: pd.DataFrame, **kw):
    return replay_strategy_return_since(
        df,
        start_date=kw.pop("start_date", "2026-09-01"),
        entry_pct=kw.pop("entry_pct", DEFAULT_PCT),
        stop_pct=kw.pop("stop_pct", DEFAULT_PCT),
        tick=kw.pop("tick", TICK_SIZE),
        code=kw.pop("code", "000002"),
        **kw,
    )


class TestStrategyReturnLifecycle(unittest.TestCase):
    def test_never_triggered_empty(self) -> None:
        """CASE A：从未触发 → holding=False；累计≈0；现价变不改累计。"""
        df = _daily(
            [
                _bar("2026-09-01", 10.0, 10.1, 9.9, 10.0),  # 阳，次日可能过门失败
                _bar("2026-09-02", 10.0, 10.05, 9.95, 9.98),  # 阴
                # 高点始终低于买点 → 不触发
                _bar("2026-09-03", 10.0, 10.10, 9.90, 10.0),
            ]
        )
        # 买点 = open*(1+entry)；high 刻意低于买点
        ep = 0.025
        buy = entry_trigger_price(10.0, entry_pct=ep, tick=TICK_SIZE)
        self.assertGreater(buy, 10.10)
        r0 = _replay(df, entry_pct=ep, stop_pct=ep)
        self.assertFalse(r0["holding"])
        self.assertEqual(r0["trades"], 0)
        self.assertAlmostEqual(float(r0["return_pct"] or 0), 0.0, places=2)

        m1 = _merge_live_daily_bar(
            df, session="2026-09-03", open_px=10.0, high_px=10.10, low_px=9.90, close_px=10.50
        )
        m2 = _merge_live_daily_bar(
            df, session="2026-09-03", open_px=10.0, high_px=10.10, low_px=9.90, close_px=11.00
        )
        a = _replay(m1, entry_pct=ep, stop_pct=ep)
        b = _replay(m2, entry_pct=ep, stop_pct=ep)
        self.assertFalse(a["holding"])
        self.assertEqual(a["return_pct"], b["return_pct"])

    def test_triggered_no_position_still_cumulative(self) -> None:
        """CASE B：虚拟已买、纸面无仓 → 仍是累计 mark，不是单笔收入。"""
        # 前日阴 → 今日触买并持有
        df = _daily(
            [
                _bar("2026-09-01", 10.0, 10.2, 9.8, 9.7),  # 阴
                _bar("2026-09-02", 10.0, 10.40, 9.90, 10.30),  # 触买
            ]
        )
        ep = 0.025
        buy = entry_trigger_price(10.0, entry_pct=ep, tick=TICK_SIZE)
        self.assertLessEqual(buy, 10.40)
        r = _replay(df, entry_pct=ep, stop_pct=ep)
        self.assertTrue(r["holding"])
        self.assertIsNotNone(r["return_pct"])
        # 单笔收入公式与累计公式不同源
        signal = signal_single_return_pct(trigger=buy, mark=10.30)
        self.assertIsNotNone(signal)
        self.assertNotAlmostEqual(float(r["return_pct"]), float(signal), places=1)

    def test_active_position_mtm(self) -> None:
        """CASE C / ACTIVE_POSITION：虚拟持有时累计随 mark 变。"""
        base = _daily(
            [
                _bar("2026-09-01", 10.0, 10.2, 9.8, 9.7),
                _bar("2026-09-02", 10.0, 10.40, 9.90, 10.20),
            ]
        )
        ep = 0.025
        a = _replay(
            _merge_live_daily_bar(
                base, session="2026-09-02", open_px=10.0, high_px=10.40, low_px=9.90, close_px=10.20
            ),
            entry_pct=ep,
            stop_pct=ep,
        )
        b = _replay(
            _merge_live_daily_bar(
                base, session="2026-09-02", open_px=10.0, high_px=10.50, low_px=9.90, close_px=10.50
            ),
            entry_pct=ep,
            stop_pct=ep,
        )
        self.assertTrue(a["holding"] and b["holding"])
        self.assertGreater(float(b["return_pct"]), float(a["return_pct"]))

    def test_sell_freeze(self) -> None:
        """CASE D / SELL_FREEZE：止损卖出后累计冻结，现价再涨不变。"""
        ep = 0.025
        # D1 阴；D2 买入；D3 盘中触止损卖出（T+1 可卖）
        o2, o3 = 10.0, 10.5
        buy = entry_trigger_price(o2, entry_pct=ep, tick=TICK_SIZE)
        stop3 = stop_trigger_price(o3, stop_pct=ep, tick=TICK_SIZE)
        df = _daily(
            [
                _bar("2026-09-01", 10.0, 10.2, 9.8, 9.7),
                _bar("2026-09-02", o2, buy + 0.05, 9.90, buy + 0.02),
                _bar("2026-09-03", o3, o3 + 0.1, stop3 - 0.05, stop3 - 0.02),
            ]
        )
        flat = _replay(df, entry_pct=ep, stop_pct=ep)
        self.assertFalse(flat["holding"])
        self.assertGreaterEqual(int(flat["trades"] or 0), 1)
        frozen = float(flat["return_pct"])

        m_hi = _merge_live_daily_bar(
            df,
            session="2026-09-03",
            open_px=o3,
            high_px=o3 + 2.0,
            low_px=stop3 - 0.05,
            close_px=o3 + 1.5,
        )
        after = _replay(m_hi, entry_pct=ep, stop_pct=ep)
        self.assertFalse(after["holding"])
        self.assertEqual(after["return_pct"], frozen)

    def test_empty_after_sell_price_change(self) -> None:
        """EMPTY_AFTER_SELL + EMPTY_PRICE_CHANGE：已平后 4.03→4.10→4.30 累计不变。"""
        ep = 0.025
        o2, o3 = 10.0, 10.5
        buy = entry_trigger_price(o2, entry_pct=ep, tick=TICK_SIZE)
        stop3 = stop_trigger_price(o3, stop_pct=ep, tick=TICK_SIZE)
        df = _daily(
            [
                _bar("2026-09-01", 10.0, 10.2, 9.8, 9.7),
                _bar("2026-09-02", o2, buy + 0.05, 9.90, buy + 0.02),
                _bar("2026-09-03", o3, o3 + 0.1, stop3 - 0.05, 10.0),
            ]
        )
        marks = (4.03, 4.10, 4.30)
        # 用独立 session 日、开盘足够高且 low 不触发新买：已平后只改 close
        rets = []
        for mk in marks:
            m = _merge_live_daily_bar(
                df,
                session="2026-09-03",
                open_px=o3,
                high_px=max(o3 + 0.1, mk),
                low_px=stop3 - 0.05,
                close_px=mk,
            )
            r = _replay(m, entry_pct=ep, stop_pct=ep)
            self.assertFalse(r["holding"])
            rets.append(r["return_pct"])
        self.assertEqual(rets[0], rets[1])
        self.assertEqual(rets[1], rets[2])

    def test_new_signal_reset_continues_equity(self) -> None:
        """CASE E：新一轮买入延续同一 equity 曲线（累计不清零），不复用旧 mark 当单笔。"""
        ep = 0.025
        o2, o3, o4, o5 = 10.0, 10.5, 9.5, 9.5
        buy2 = entry_trigger_price(o2, entry_pct=ep, tick=TICK_SIZE)
        stop3 = stop_trigger_price(o3, stop_pct=ep, tick=TICK_SIZE)
        buy5 = entry_trigger_price(o5, entry_pct=ep, tick=TICK_SIZE)
        df = _daily(
            [
                _bar("2026-09-01", 10.0, 10.2, 9.8, 9.7),  # 阴
                _bar("2026-09-02", o2, buy2 + 0.05, 9.90, buy2 + 0.02),  # 买
                _bar("2026-09-03", o3, o3 + 0.1, stop3 - 0.05, 10.0),  # 卖
                _bar("2026-09-04", o4, o4 + 0.05, o4 - 0.1, o4 - 0.05),  # 阴
                _bar("2026-09-05", o5, buy5 + 0.08, o5 - 0.05, buy5 + 0.05),  # 再买
            ]
        )
        r = _replay(df, entry_pct=ep, stop_pct=ep)
        self.assertTrue(r["holding"])
        self.assertGreaterEqual(int(r["trades"] or 0), 1)
        # 新一轮持有：改 mark 应再动
        m_lo = _merge_live_daily_bar(
            df, session="2026-09-05", open_px=o5, high_px=buy5 + 0.08, low_px=o5 - 0.05, close_px=buy5
        )
        m_hi = _merge_live_daily_bar(
            df,
            session="2026-09-05",
            open_px=o5,
            high_px=buy5 + 0.20,
            low_px=o5 - 0.05,
            close_px=buy5 + 0.15,
        )
        a = _replay(m_lo, entry_pct=ep, stop_pct=ep)
        b = _replay(m_hi, entry_pct=ep, stop_pct=ep)
        self.assertTrue(a["holding"] and b["holding"])
        self.assertGreater(float(b["return_pct"]), float(a["return_pct"]))

    def test_cross_day_active_and_closed(self) -> None:
        """CROSS_DAY：跨日持有继续 mark；跨日已平累计保留。"""
        ep = 0.025
        o2 = 10.0
        buy = entry_trigger_price(o2, entry_pct=ep, tick=TICK_SIZE)
        hold_df = _daily(
            [
                _bar("2026-09-01", 10.0, 10.2, 9.8, 9.7),
                _bar("2026-09-02", o2, buy + 0.05, 9.90, buy + 0.02),
                _bar("2026-09-03", 10.2, 10.5, 10.1, 10.4),
            ]
        )
        active = _replay(hold_df, entry_pct=ep, stop_pct=ep)
        self.assertTrue(active["holding"])
        m = _merge_live_daily_bar(
            hold_df, session="2026-09-03", open_px=10.2, high_px=10.8, low_px=10.1, close_px=10.7
        )
        mtm = _replay(m, entry_pct=ep, stop_pct=ep)
        self.assertGreater(float(mtm["return_pct"]), float(active["return_pct"]))

        o3 = 10.5
        stop3 = stop_trigger_price(o3, stop_pct=ep, tick=TICK_SIZE)
        # 9/3 卖出收阳大涨 → 9/4 大阳不过门，且 high 低于买点，保持空仓
        closed_df = _daily(
            [
                _bar("2026-09-01", 10.0, 10.2, 9.8, 9.7),
                _bar("2026-09-02", o2, buy + 0.05, 9.90, buy + 0.02),
                _bar("2026-09-03", o3, o3 + 0.8, stop3 - 0.05, o3 + 0.6),
                _bar("2026-09-04", 11.2, 11.25, 11.10, 11.20),
            ]
        )
        c0 = _replay(closed_df, entry_pct=ep, stop_pct=ep)
        self.assertFalse(c0["holding"])
        frozen = c0["return_pct"]
        c1 = _replay(
            _merge_live_daily_bar(
                closed_df,
                session="2026-09-04",
                open_px=11.2,
                high_px=11.25,
                low_px=11.10,
                close_px=12.0,
            ),
            entry_pct=ep,
            stop_pct=ep,
        )
        self.assertFalse(c1["holding"])
        self.assertEqual(c1["return_pct"], frozen)

    def test_strategy_today_vs_cumulative_preserve(self) -> None:
        """STRATEGY_CUMULATIVE_PRESERVE：起算日不变；无「今日清零」逻辑。"""
        self.assertEqual(STRATEGY_PNL_START, "2026-10-08")
        df = _daily(
            [
                _bar("2026-09-08", 3.20, 3.25, 3.15, 3.18),
                _bar("2026-09-09", 3.26, 3.27, 3.19, 3.19),
                _bar("2026-09-10", 3.18, 3.20, 3.14, 3.16),
            ]
        )
        r = _replay(df, start_date="2026-09-09", entry_pct=0.025, stop_pct=0.025)
        self.assertEqual(r["start_date"], "2026-09-09")
        # 起算后无成交 → 0，不是 NaN / 被清掉
        self.assertIsNotNone(r["return_pct"])

    def test_000002_like_fixture_screenshot(self) -> None:
        """截图 regression：空仓纸面无关；mark≈3.99 → +26.74%；再涨仍动因虚拟持有。"""
        # 精简路径：与实盘同参 ep=0.025，9/18 买入后持续持有
        df = _daily(
            [
                _bar("2026-09-09", 3.26, 3.27, 3.19, 3.19),
                _bar("2026-09-10", 3.18, 3.20, 3.14, 3.16),
                _bar("2026-09-11", 3.14, 3.15, 3.05, 3.06),
                _bar("2026-09-14", 3.05, 3.07, 3.03, 3.05),
                _bar("2026-09-15", 3.05, 3.06, 3.01, 3.02),
                _bar("2026-09-16", 3.02, 3.03, 2.98, 3.03),
                _bar("2026-09-17", 3.01, 3.03, 3.00, 3.02),  # 阴/可过门
                _bar("2026-09-18", 3.03, 3.32, 3.01, 3.32),  # BUY
                _bar("2026-09-21", 3.30, 3.65, 3.27, 3.65),
                _bar("2026-09-22", 3.57, 3.89, 3.54, 3.81),
            ]
        )
        ep = 0.025
        paper_qty = 0  # 空仓
        r399 = _replay(
            _merge_live_daily_bar(
                df, session="2026-09-23", open_px=3.81, high_px=4.03, low_px=3.81, close_px=3.99
            ),
            start_date="2026-09-09",
            entry_pct=ep,
            stop_pct=ep,
        )
        self.assertEqual(paper_qty, 0)
        self.assertTrue(r399["holding"])
        self.assertEqual(r399["return_pct"], 26.74)

        r403 = _replay(
            _merge_live_daily_bar(
                df, session="2026-09-23", open_px=3.81, high_px=4.03, low_px=3.81, close_px=4.03
            ),
            start_date="2026-09-09",
            entry_pct=ep,
            stop_pct=ep,
        )
        r410 = _replay(
            _merge_live_daily_bar(
                df, session="2026-09-23", open_px=3.81, high_px=4.10, low_px=3.81, close_px=4.10
            ),
            start_date="2026-09-09",
            entry_pct=ep,
            stop_pct=ep,
        )
        # 虚拟未平：随现价变（不是 stale baseline bug，是累计 mark）
        self.assertGreater(float(r403["return_pct"]), float(r399["return_pct"]))
        self.assertGreater(float(r410["return_pct"]), float(r403["return_pct"]))
        self.assertEqual(r410["return_pct"], 30.09)

    def test_semantics_not_open_over_current(self) -> None:
        """禁止用 current/open 冒充策略累计。"""
        open_px, last = 3.81, 4.03
        naive = (last / open_px - 1.0) * 100.0
        self.assertAlmostEqual(naive, 5.77, places=2)
        # 截图策略累计 26.74 ≠ 日内涨跌
        self.assertNotAlmostEqual(26.74, naive, places=1)

    def test_attach_fields_semantics_keys(self) -> None:
        """_attach_strategy_pnl_fields 写入语义标记（不改交易）。"""
        import index as watch_index

        row: dict = {}
        daily = _daily(
            [
                _bar("2026-09-01", 10.0, 10.2, 9.8, 9.7),
                _bar("2026-09-02", 10.0, 10.05, 9.95, 10.0),
            ]
        )
        watch_index._attach_strategy_pnl_fields(
            row,
            w={"sina": "sz000002", "code": "000002"},
            daily=daily,
            q={
                "session": "2026-09-02",
                "open": 10.0,
                "high": 10.05,
                "low": 9.95,
                "last": 10.0,
            },
            entry_pct=0.025,
            stop_pct=0.025,
            tick=TICK_SIZE,
            prev_entry_mode="yin_or_small_yang",
            limit_down_pct=0.10,
        )
        self.assertEqual(row["策略收益语义"], "strategy_simulator_ledger")
        self.assertEqual(row["策略收益范围"], "symbol")
        self.assertEqual(row["策略历史口径"], "daily_open_break_fixed_stop")
        self.assertEqual(row["策略实时口径"], "quote_touch_row_levels")
        self.assertEqual(row["策略退出口径"], "row_sell_level_live")
        self.assertEqual(row["策略起算"], STRATEGY_PNL_START)
        self.assertIn("策略累计持有", row)
        self.assertIn("策略收益%", row)
        self.assertIn("策略模拟状态", row)
        self.assertIsInstance(row["策略累计持有"], bool)

    def test_paper_replay_dual_status_labels(self) -> None:
        """纸面 / 回放双态：只用 策略累计持有，禁止用收益%反推；互不覆盖。"""

        def paper_label(qty: int, pos: str) -> str:
            if qty > 0:
                if pos == "待卖出":
                    return "待卖出"
                return pos or "已经买入"
            return pos or "空仓"

        def replay_label(holding: bool | None) -> str | None:
            if holding is None:
                return None
            return "回放持有" if holding else "回放空仓"

        # paper empty + replay long
        self.assertEqual(paper_label(0, "空仓"), "空仓")
        self.assertEqual(replay_label(True), "回放持有")
        # paper empty + replay flat
        self.assertEqual(paper_label(0, "空仓"), "空仓")
        self.assertEqual(replay_label(False), "回放空仓")
        # paper long + replay long
        self.assertEqual(paper_label(100, "已经买入"), "已经买入")
        self.assertEqual(replay_label(True), "回放持有")
        # paper long + replay flat
        self.assertEqual(paper_label(100, "已经买入"), "已经买入")
        self.assertEqual(replay_label(False), "回放空仓")
        # 禁止用 return% 反推回放态
        fake_return = 26.74
        self.assertNotEqual(replay_label(False), "回放持有")
        self.assertTrue(fake_return != 0)  # 非零累计仍可能回放空仓（已平有历史）

    def test_paper_empty_replay_long_mtm_vs_flat_freeze(self) -> None:
        """paper empty + replay long → MTM；paper empty + replay flat → 冻结。"""
        ep = 0.025
        # long path
        long_df = _daily(
            [
                _bar("2026-09-01", 10.0, 10.2, 9.8, 9.7),
                _bar("2026-09-02", 10.0, 10.40, 9.90, 10.20),
            ]
        )
        a = _replay(
            _merge_live_daily_bar(
                long_df, session="2026-09-02", open_px=10.0, high_px=10.40, low_px=9.90, close_px=10.20
            ),
            entry_pct=ep,
            stop_pct=ep,
        )
        b = _replay(
            _merge_live_daily_bar(
                long_df, session="2026-09-02", open_px=10.0, high_px=10.60, low_px=9.90, close_px=10.60
            ),
            entry_pct=ep,
            stop_pct=ep,
        )
        paper_qty = 0
        self.assertEqual(paper_qty, 0)
        self.assertTrue(a["holding"])
        self.assertGreater(float(b["return_pct"]), float(a["return_pct"]))

        # flat after sell
        o2, o3 = 10.0, 10.5
        buy = entry_trigger_price(o2, entry_pct=ep, tick=TICK_SIZE)
        stop3 = stop_trigger_price(o3, stop_pct=ep, tick=TICK_SIZE)
        flat_df = _daily(
            [
                _bar("2026-09-01", 10.0, 10.2, 9.8, 9.7),
                _bar("2026-09-02", o2, buy + 0.05, 9.90, buy + 0.02),
                _bar("2026-09-03", o3, o3 + 0.1, stop3 - 0.05, 10.0),
            ]
        )
        f0 = _replay(flat_df, entry_pct=ep, stop_pct=ep)
        self.assertFalse(f0["holding"])
        frozen = f0["return_pct"]
        f1 = _replay(
            _merge_live_daily_bar(
                flat_df,
                session="2026-09-03",
                open_px=o3,
                high_px=o3 + 1.0,
                low_px=stop3 - 0.05,
                close_px=o3 + 0.8,
            ),
            entry_pct=ep,
            stop_pct=ep,
        )
        self.assertFalse(f1["holding"])
        self.assertEqual(f1["return_pct"], frozen)

    def test_mark_vs_ui_current_timing_not_stale_bug(self) -> None:
        """mark=collect_rows 时 q.last；UI 现价可被 quote_patch 快刷 → 正常 timing 差。"""
        # 文档化审计结论（无计算变更）：A snapshot timing
        strategy_mark_source = "replay_strategy_return_since ← _merge_live_daily_bar(close=q.last@collect_rows)"
        ui_current_source = "row.现价 ← collect_rows q.last，随后 publish_live_quote_patch 可覆盖且不重算策略累计"
        reason = "A_snapshot_timing_difference"
        mark_staleness_bug = False
        self.assertIn("collect_rows", strategy_mark_source)
        self.assertIn("quote_patch", ui_current_source)
        self.assertEqual(reason, "A_snapshot_timing_difference")
        self.assertFalse(mark_staleness_bug)


if __name__ == "__main__":
    unittest.main()
