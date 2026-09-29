"""默认研究/交易宇宙（中立于 holdingStocks 运行时）。

公共自选池、因子27 冻结池路径、以及 research_watchlist()。
holdingStocks.watch_config 从此处导入并再导出，避免 strategy → holdingStocks。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from strategy.board_rules import code_key, limit_down_pct_of, market_of, sina_of
from strategy.open_break import DEFAULT_PCT, TICK_SIZE

_MYQUAN_ROOT = Path(__file__).resolve().parents[1]

CORE_LEADER_PICKS_PATH = _MYQUAN_ROOT / "backtest" / "strategy16_core_leader" / "picks_quarter.json"
STRATEGY16_THR_PATH = _MYQUAN_ROOT / "backtest" / "strategy16_core_leader" / "thr_2026.json"
ZIYANG_PICKS_PATH = _MYQUAN_ROOT / "backtest" / "strategy17_ziyang" / "picks_3m.json"

# 公共自选池（非因子选股）：所有策略交易/盯盘宇宙均并入。
SELF_WATCHLIST_PICKS: tuple[tuple[str, str], ...] = (
    ("600330", "天通股份"),
    ("600552", "凯盛科技"),
    ("601208", "东材科技"),
    ("002636", "金安国纪"),
)
STRATEGY16_EXTRA_PICKS = SELF_WATCHLIST_PICKS

POOL_SRC_FACTOR27 = "factor27"
POOL_SRC_FACTOR28 = "factor28"
POOL_SRC_SELF = "self"
POOL_SRC_LABEL = {
    POOL_SRC_FACTOR27: "因子27",
    POOL_SRC_FACTOR28: "紫阳真君",
    POOL_SRC_SELF: "自选",
}


def _watch_row(
    code: str,
    name: str,
    *,
    entry_pct: float | None = None,
    stop_pct: float | None = None,
    tick: float = TICK_SIZE,
    t0: bool = False,
    limit_down_pct: float | None = None,
    pool_src: str | None = None,
    concept: Any = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    c = code_key(code)
    ep = float(entry_pct if entry_pct is not None else DEFAULT_PCT)
    sp = float(stop_pct if stop_pct is not None else DEFAULT_PCT)
    ld = float(limit_down_pct if limit_down_pct is not None else limit_down_pct_of(c))
    item: dict[str, Any] = {
        "code": c,
        "sina": sina_of(c),
        "market": market_of(c),
        "name": name,
        "pct": ep,
        "entry_pct": ep,
        "stop_pct": sp,
        "tick": float(tick),
        "t0": bool(t0),
        "limit_down_pct": ld,
        "prev_entry_mode": "yin_or_small_yang",
    }
    if pool_src is not None:
        item["pool_src"] = pool_src
        item["池来源"] = POOL_SRC_LABEL.get(pool_src, pool_src)
    if concept is not None:
        item["concept"] = concept
    if extra:
        item.update(extra)
    return item


def load_core_leader_payload() -> dict[str, Any]:
    if not CORE_LEADER_PICKS_PATH.is_file():
        return {}
    try:
        raw = json.loads(CORE_LEADER_PICKS_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return dict(raw) if isinstance(raw, dict) else {}


_THR_MAP_CACHE: dict[str, Any] = {"mtime": None, "data": {}}


def load_strategy16_thr_map() -> dict[str, float]:
    """按 mtime 缓存：meta_for_code 每只票都会调，盯盘宇宙数百只。"""
    try:
        mtime = STRATEGY16_THR_PATH.stat().st_mtime
    except OSError:
        return {}
    if _THR_MAP_CACHE["mtime"] == mtime:
        return dict(_THR_MAP_CACHE["data"])
    out = _read_strategy16_thr_map()
    _THR_MAP_CACHE["mtime"] = mtime
    _THR_MAP_CACHE["data"] = out
    return dict(out)


def _read_strategy16_thr_map() -> dict[str, float]:
    try:
        raw = json.loads(STRATEGY16_THR_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    out: dict[str, float] = {}
    for code, rec in (raw.get("thrs") or {}).items():
        c = code_key(str(code))
        if not c:
            continue
        thr = rec.get("thr") if isinstance(rec, dict) else rec
        try:
            out[c] = float(thr)
        except (TypeError, ValueError):
            continue
    return out


def load_ziyang_payload() -> dict[str, Any]:
    if not ZIYANG_PICKS_PATH.is_file():
        return {"n_picks": 0, "picks": []}
    try:
        raw = json.loads(ZIYANG_PICKS_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"n_picks": 0, "picks": []}
    return dict(raw) if isinstance(raw, dict) else {"n_picks": 0, "picks": []}


def self_watchlist_pick_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for code, name in SELF_WATCHLIST_PICKS:
        rows.append(
            {
                "code": code_key(code),
                "name": name,
                "concept": "self_watch",
                "pool_src": POOL_SRC_SELF,
                "manual_add": True,
            }
        )
    return rows


def self_watchlist_codes() -> set[str]:
    return {
        code_key(c)
        for c, _ in SELF_WATCHLIST_PICKS
        if code_key(c) and code_key(c) != "000000"
    }


def factor27_codes() -> set[str]:
    out: set[str] = set()
    for it in load_core_leader_payload().get("picks") or []:
        if not isinstance(it, dict):
            continue
        c = code_key(str(it.get("code") or it.get("symbol") or ""))
        if c and c != "000000":
            out.add(c)
    return out


def factor28_codes() -> set[str]:
    out: set[str] = set()
    for it in load_ziyang_payload().get("picks") or []:
        if not isinstance(it, dict):
            continue
        c = code_key(str(it.get("code") or it.get("symbol") or ""))
        if c and c != "000000":
            out.add(c)
    return out


def core_leader_codes() -> set[str]:
    return factor27_codes() | self_watchlist_codes()


def ziyang_codes() -> set[str]:
    return factor28_codes() | self_watchlist_codes()


def research_watchlist() -> list[dict[str, Any]]:
    """默认研究宇宙 = 策略十六交易池（因子27 ∪ 公共自选），与盯盘默认 WATCHLIST 对齐。

    供 strategy 包内回测/优化脚本使用，禁止再从 holdingStocks 取池。
    """
    thrs = load_strategy16_thr_map()
    seen: set[str] = set()
    out: list[dict[str, Any]] = []

    for code, name in SELF_WATCHLIST_PICKS:
        c = code_key(code)
        if not c or c == "000000" or c in seen:
            continue
        seen.add(c)
        thr = thrs.get(c)
        row = _watch_row(
            c,
            name,
            entry_pct=float(thr) if thr is not None else None,
            stop_pct=DEFAULT_PCT,
            pool_src=POOL_SRC_SELF,
            concept="self_watch",
            extra={"self_watch": True, "manual_add": True, "universe": "strategy16"},
        )
        out.append(row)

    for it in load_core_leader_payload().get("picks") or []:
        if not isinstance(it, dict):
            continue
        code = code_key(str(it.get("code") or it.get("symbol") or ""))
        if not code or code in seen or code == "000000":
            continue
        seen.add(code)
        name = str(it.get("name") or code)
        thr = thrs.get(code)
        row = _watch_row(
            code,
            name,
            entry_pct=float(thr) if thr is not None else None,
            stop_pct=DEFAULT_PCT,
            pool_src=POOL_SRC_FACTOR27,
            concept=it.get("concept"),
            extra={"universe": "strategy16"},
        )
        out.append(row)

    return out


# 模块级缓存：与旧 WATCHLIST = strategy_watchlist() 用法兼容
WATCHLIST: list[dict[str, Any]] = research_watchlist()
