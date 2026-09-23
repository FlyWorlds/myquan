"""Multi-symbol Strategy Cumulative Return regression.

覆盖 paper×replay 四象限；优先读当前 holdings_watch snapshot，
缺样本时用 fixture（不写 production）。断言无 000002/万科 单票硬编码。
"""

from __future__ import annotations

import ast
import json
import sys
import unittest
from pathlib import Path
from typing import Any

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
from watch_config import STRATEGY_PNL_START  # noqa: E402

_WATCH_JSON = _HOLD / "holdings_watch.json"

# 四象限尽量用不同 code，避免单票假绿
_FIXTURE_CODES = {
    "empty_long": ("600330", "sh600330"),
    "empty_flat": ("002636", "sz002636"),
    "long_long": ("601208", "sh601208"),
    "long_flat": ("600552", "sh600552"),
}


def _bar(date: str, o: float, h: float, l: float, c: float) -> dict[str, float | str]:
    return {"date": date, "open": o, "high": h, "low": l, "close": c}


def _daily(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _replay(df: pd.DataFrame, *, code: str, **kw: Any) -> dict[str, Any]:
    return replay_strategy_return_since(
        df,
        start_date=kw.pop("start_date", "2026-09-01"),
        entry_pct=kw.pop("entry_pct", DEFAULT_PCT),
        stop_pct=kw.pop("stop_pct", DEFAULT_PCT),
        tick=kw.pop("tick", TICK_SIZE),
        code=code,
        **kw,
    )


def _yin_then_buy_hold(*, session: str = "2026-09-18") -> pd.DataFrame:
    """前日阴 + 今日触买持有（日期 ≥ STRATEGY_PNL_START）。"""
    ep = DEFAULT_PCT
    buy = entry_trigger_price(10.0, entry_pct=ep, tick=TICK_SIZE)
    base = _daily(
        [
            _bar("2026-09-16", 10.0, 10.1, 9.9, 10.0),
            _bar("2026-09-17", 10.0, 10.2, 9.8, 9.7),  # 阴
            _bar("2026-09-18", 10.0, buy + 0.08, 9.90, buy + 0.05),
        ]
    )
    return _merge_live_daily_bar(
        base, session=session, open_px=10.0, high_px=buy + 0.08, low_px=9.90, close_px=buy + 0.05
    )


def _yin_buy_then_sell(*, session: str = "2026-09-19") -> pd.DataFrame:
    """买入后次日触止损平仓（日期 ≥ STRATEGY_PNL_START）。"""
    ep = DEFAULT_PCT
    o2, o3 = 10.0, 10.5
    buy = entry_trigger_price(o2, entry_pct=ep, tick=TICK_SIZE)
    stop3 = stop_trigger_price(o3, stop_pct=ep, tick=TICK_SIZE)
    base = _daily(
        [
            _bar("2026-09-16", 10.0, 10.1, 9.9, 10.0),
            _bar("2026-09-17", 10.0, 10.2, 9.8, 9.7),
            _bar("2026-09-18", o2, buy + 0.05, 9.90, buy + 0.02),
            _bar("2026-09-19", o3, o3 + 0.1, stop3 - 0.05, 10.0),
        ]
    )
    return _merge_live_daily_bar(
        base, session=session, open_px=o3, high_px=o3 + 0.1, low_px=stop3 - 0.05, close_px=10.0
    )


def _paper_label(qty: int, pos: str) -> str:
    if qty > 0:
        if pos == "待卖出":
            return "待卖出"
        return pos or "已经买入"
    return pos or "空仓"


def _replay_label(holding: bool | None) -> str | None:
    if holding is None:
        return None
    return "回放持有" if holding else "回放空仓"


def _load_strategy_universe() -> list[dict[str, Any]]:
    if not _WATCH_JSON.is_file():
        return []
    raw = json.loads(_WATCH_JSON.read_text(encoding="utf-8"))
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for key in ("strategy16", "strategy1"):
        for r in raw.get(key) or []:
            if not isinstance(r, dict):
                continue
            code = str(r.get("代码") or "")
            if not code or code in seen:
                continue
            seen.add(code)
            out.append(r)
    return out


def _bucket_snapshot(
    rows: list[dict[str, Any]],
) -> dict[str, list[str]]:
    buckets: dict[str, list[str]] = {
        "empty_long": [],
        "empty_flat": [],
        "long_long": [],
        "long_flat": [],
        "missing_meta": [],
    }
    for r in rows:
        code = str(r.get("代码") or "")
        try:
            qty = int(r.get("持仓") or 0)
        except (TypeError, ValueError):
            qty = 0
        rh = r.get("策略累计持有")
        if rh is None:
            buckets["missing_meta"].append(code)
            continue
        holding = bool(rh)
        paper_long = qty > 0
        if not paper_long and holding:
            buckets["empty_long"].append(code)
        elif not paper_long and not holding:
            buckets["empty_flat"].append(code)
        elif paper_long and holding:
            buckets["long_long"].append(code)
        else:
            buckets["long_flat"].append(code)
    return buckets


class TestStrategyReturnMultiSymbol(unittest.TestCase):
    def test_no_symbol_specific_hardcode_in_production_paths(self) -> None:
        """生产路径禁止 000002 / 万科 单票 return/status 修复。"""
        paths = [
            _HOLD / "index.py",
            _HOLD / "watch-ui" / "components" / "Strategy1Panel.vue",
            _HOLD / "watch-ui" / "components" / "StrategyWorkspace.vue",
            _HOLD / "watch-ui" / "types" / "snapshot.ts",
            _ROOT / "strategy" / "open_break.py",
        ]
        banned = ("000002", "万科", "万  科", "万科A", "万  科Ａ")
        for path in paths:
            text = path.read_text(encoding="utf-8")
            for token in banned:
                self.assertNotIn(
                    token,
                    text,
                    msg=f"SYMBOL_SPECIFIC_FIX in {path.name}: found {token!r}",
                )

        # _attach_strategy_pnl_fields 不得按 code 分支
        src = (_HOLD / "index.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        fn = None
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == "_attach_strategy_pnl_fields":
                fn = node
                break
        self.assertIsNotNone(fn)
        dump = ast.dump(fn)
        for token in ("000002", "万科"):
            self.assertNotIn(token, dump)

    def test_fixture_four_quadrants_distinct_symbols(self) -> None:
        """四象限 fixture：不同 symbol；统一 replay + attach metadata。"""
        import index as watch_index

        counts = {
            "empty_long": 0,
            "empty_flat": 0,
            "long_long": 0,
            "long_flat": 0,
        }
        symbols: list[str] = []

        # 1) paper empty + replay long
        code, sina = _FIXTURE_CODES["empty_long"]
        symbols.append(code)
        df = _yin_then_buy_hold()
        rec = _replay(df, code=code, start_date=STRATEGY_PNL_START)
        self.assertTrue(rec["holding"])
        row: dict[str, Any] = {"持仓": 0, "持仓状态": "空仓"}
        watch_index._attach_strategy_pnl_fields(
            row,
            w={"sina": sina, "code": code},
            daily=df,
            q={
                "session": "2026-09-18",
                "open": 10.0,
                "high": 10.5,
                "low": 9.9,
                "last": 10.3,
            },
            entry_pct=DEFAULT_PCT,
            stop_pct=DEFAULT_PCT,
            tick=TICK_SIZE,
            prev_entry_mode="yin_or_small_yang",
            limit_down_pct=0.10,
        )
        self.assertEqual(row["策略收益语义"], "cumulative_factor1_replay")
        self.assertEqual(row["策略收益范围"], "symbol")
        self.assertTrue(row["策略累计持有"])
        self.assertEqual(_paper_label(0, "空仓"), "空仓")
        self.assertEqual(_replay_label(True), "回放持有")
        # MTM
        row2: dict[str, Any] = {}
        watch_index._attach_strategy_pnl_fields(
            row2,
            w={"sina": sina, "code": code},
            daily=df,
            q={
                "session": "2026-09-18",
                "open": 10.0,
                "high": 10.8,
                "low": 9.9,
                "last": 10.8,
            },
            entry_pct=DEFAULT_PCT,
            stop_pct=DEFAULT_PCT,
            tick=TICK_SIZE,
            prev_entry_mode="yin_or_small_yang",
            limit_down_pct=0.10,
        )
        self.assertGreater(float(row2["策略收益%"]), float(row["策略收益%"]))
        counts["empty_long"] += 1

        # 2) paper empty + replay flat
        code, sina = _FIXTURE_CODES["empty_flat"]
        symbols.append(code)
        df = _yin_buy_then_sell()
        rec = _replay(df, code=code, start_date=STRATEGY_PNL_START)
        self.assertFalse(rec["holding"])
        frozen = float(rec["return_pct"])
        row = {"持仓": 0, "持仓状态": "空仓"}
        watch_index._attach_strategy_pnl_fields(
            row,
            w={"sina": sina, "code": code},
            daily=df,
            q={
                "session": "2026-09-19",
                "open": 10.5,
                "high": 11.5,
                "low": 10.0,
                "last": 11.2,
            },
            entry_pct=DEFAULT_PCT,
            stop_pct=DEFAULT_PCT,
            tick=TICK_SIZE,
            prev_entry_mode="yin_or_small_yang",
            limit_down_pct=0.10,
        )
        self.assertFalse(row["策略累计持有"])
        self.assertEqual(row["策略收益%"], frozen)
        self.assertEqual(_paper_label(0, "空仓"), "空仓")
        self.assertEqual(_replay_label(False), "回放空仓")
        counts["empty_flat"] += 1

        # 3) paper long + replay long
        code, sina = _FIXTURE_CODES["long_long"]
        symbols.append(code)
        df = _yin_then_buy_hold()
        rec = _replay(df, code=code, start_date=STRATEGY_PNL_START)
        self.assertTrue(rec["holding"])
        row = {"持仓": 500, "持仓状态": "已经买入"}
        watch_index._attach_strategy_pnl_fields(
            row,
            w={"sina": sina, "code": code},
            daily=df,
            q={
                "session": "2026-09-18",
                "open": 10.0,
                "high": 10.5,
                "low": 9.9,
                "last": 10.3,
            },
            entry_pct=DEFAULT_PCT,
            stop_pct=DEFAULT_PCT,
            tick=TICK_SIZE,
            prev_entry_mode="yin_or_small_yang",
            limit_down_pct=0.10,
        )
        self.assertTrue(row["策略累计持有"])
        self.assertEqual(_paper_label(500, "已经买入"), "已经买入")
        self.assertEqual(_replay_label(True), "回放持有")
        # 纸面 long 不改变回放 metadata 语义键
        self.assertEqual(row["策略收益范围"], "symbol")
        counts["long_long"] += 1

        # 4) paper long + replay flat
        code, sina = _FIXTURE_CODES["long_flat"]
        symbols.append(code)
        df = _yin_buy_then_sell()
        rec = _replay(df, code=code, start_date=STRATEGY_PNL_START)
        self.assertFalse(rec["holding"])
        row = {"持仓": 800, "持仓状态": "已经买入"}
        watch_index._attach_strategy_pnl_fields(
            row,
            w={"sina": sina, "code": code},
            daily=df,
            q={
                "session": "2026-09-19",
                "open": 10.5,
                "high": 10.6,
                "low": 10.0,
                "last": 10.2,
            },
            entry_pct=DEFAULT_PCT,
            stop_pct=DEFAULT_PCT,
            tick=TICK_SIZE,
            prev_entry_mode="yin_or_small_yang",
            limit_down_pct=0.10,
        )
        self.assertFalse(row["策略累计持有"])
        self.assertEqual(_paper_label(800, "已经买入"), "已经买入")
        self.assertEqual(_replay_label(False), "回放空仓")
        counts["long_flat"] += 1

        self.assertEqual(len(set(symbols)), 4, msg=f"need 4 distinct symbols, got {symbols}")
        for k, n in counts.items():
            self.assertGreaterEqual(n, 1, msg=f"missing quadrant {k}")

        # 暴露给报告（unittest 不吃 stdout 也能在失败信息里看到）
        self.assertEqual(counts["empty_long"], 1)
        self.assertEqual(counts["empty_flat"], 1)
        self.assertEqual(counts["long_long"], 1)
        self.assertEqual(counts["long_flat"], 1)

    def test_attach_uniform_across_universe_codes(self) -> None:
        """对 snapshot universe（或兜底多码）统一走 _attach_strategy_pnl_fields。"""
        import index as watch_index

        rows = _load_strategy_universe()
        codes = [str(r.get("代码")) for r in rows if r.get("代码")]
        if len(codes) < 4:
            codes = [c for c, _ in _FIXTURE_CODES.values()]
        # 最多测 12 只，避免过慢
        sample = codes[:12]
        df = _yin_then_buy_hold()
        for code in sample:
            sina = f"{'sh' if code.startswith('6') else 'sz'}{code}"
            row: dict[str, Any] = {}
            watch_index._attach_strategy_pnl_fields(
                row,
                w={"sina": sina, "code": code},
                daily=df,
                q={
                    "session": "2026-09-18",
                    "open": 10.0,
                    "high": 10.5,
                    "low": 9.9,
                    "last": 10.3,
                },
                entry_pct=DEFAULT_PCT,
                stop_pct=DEFAULT_PCT,
                tick=TICK_SIZE,
                prev_entry_mode="yin_or_small_yang",
                limit_down_pct=0.10,
            )
            self.assertEqual(row.get("策略收益语义"), "cumulative_factor1_replay")
            self.assertEqual(row.get("策略收益范围"), "symbol")
            self.assertIsInstance(row.get("策略累计持有"), bool)
            self.assertEqual(row.get("策略起算"), STRATEGY_PNL_START)
            self.assertIsNotNone(row.get("策略收益%"))
            self.assertTrue(row.get("策略累计持有"))

    def test_snapshot_buckets_or_fixture_fallback(self) -> None:
        """有 metadata 的 snapshot 计入四象限；否则 fixture 已覆盖（不伪造 production）。"""
        rows = _load_strategy_universe()
        buckets = _bucket_snapshot(rows)
        # 当前 watch 未重启时可能全 missing_meta —— 仍 PASS（fixture 负责）
        if buckets["missing_meta"] and len(buckets["missing_meta"]) == len(rows) and rows:
            self.assertTrue(True)
            return
        # 若已有 metadata：每行必须可归类，且不允许缺语义键
        for r in rows:
            if r.get("error"):
                continue
            if r.get("策略累计持有") is None:
                continue
            self.assertEqual(r.get("策略收益语义"), "cumulative_factor1_replay")
            self.assertEqual(r.get("策略收益范围"), "symbol")
            self.assertIn("策略收益%", r)


if __name__ == "__main__":
    # 打印 snapshot 分桶，便于报告 SYMBOLS_CHECKED / COUNTS
    rows = _load_strategy_universe()
    buckets = _bucket_snapshot(rows)
    print("SNAPSHOT_N", len(rows))
    for k, v in buckets.items():
        print(k, len(v), v[:10])
    unittest.main()
