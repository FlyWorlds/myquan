"""各注册策略的选股/信号产物加载（供 watch-ui /api/strategies）。"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

from stock_names import code_from_symbol, invalidate_name_cache, resolve_stock_name

_MYQUAN = Path(__file__).resolve().parents[1]

_PICK_SOURCES: dict[str, dict[str, Any]] = {
    "strategy1": {
        "kind": "pool",
        "paths": [
            _MYQUAN / "backtest/s1_f13_refit_2025/summary.json",
            _MYQUAN / "backtest/s1_f13_refit_2025/pool_detail.csv",
            _MYQUAN / "backtest/s1_f13_refit_2025/picks_2025_for_2026.csv",
            _MYQUAN / "backtest/factor13_bear_shield/LOCKED.json",
        ],
    },
    "strategy2": {
        "kind": "daily",
        "paths": [
            _MYQUAN / "backtest/strategy2_chan_daily_out/final_test_picks.csv",
            _MYQUAN / "backtest/strategy2_chan_out/final_test_picks.csv",
        ],
    },
    "strategy3": {
        "kind": "signals",
        "paths": [
            _MYQUAN / "backtest/strategy3_first_board/signals_0p0250_lag1_lb2_h2_5.parquet",
            _MYQUAN / "backtest/strategy3_first_board/signals_0p0300_lag1_lb2_h2_5.parquet",
        ],
    },
    "strategy8": {
        "kind": "signals",
        "paths": [
            _MYQUAN / "backtest/strategy8_theme_linkage/signals_0p0250_td0_tm3_linkage_tmax9_lag1_lb2_h2_5.parquet",
            _MYQUAN / "backtest/strategy8_theme_linkage/signals_0p0300_td0_tm3_linkage_tmax9_lag1_lb2_h2_5.parquet",
        ],
    },
    "strategy12": {
        "kind": "signals",
        "paths": [
            _MYQUAN / "backtest/strategy12_emotion_gate/signals.parquet",
        ],
    },
    "strategy4": {
        "kind": "weekly",
        "paths": [
            _MYQUAN / "strategy/strategies/strategy4/backtest_2025/weekly_picks.csv",
        ],
    },
    "strategy5": {
        "kind": "weekly",
        "paths": [
            _MYQUAN / "strategy/strategies/strategy5/backtest_mom3_high5_k5/weekly_picks.csv",
            _MYQUAN / "strategy/strategies/strategy5/backtest/weekly_picks.csv",
        ],
    },
    "strategy16": {
        "kind": "pool",
        "paths": [
            _MYQUAN / "backtest/strategy16_core_leader/picks_quarter.json",
        ],
    },
}


def _code_from_symbol(sym: str) -> str:
    return code_from_symbol(sym)


def _resolve_name(*, symbol: str = "", code: str = "", name: str = "") -> str:
    return resolve_stock_name(symbol=symbol, code=code, name=name)


def _empty_picks(kind: str = "none", *, note: str = "") -> dict[str, Any]:
    return {"kind": kind, "asOf": None, "source": None, "note": note, "items": []}


def _first_existing(paths: list[Path]) -> Path | None:
    for p in paths:
        if p.is_file():
            return p
    return None


def _load_factor13_locked(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    year = max((k for k in data if k.startswith("picks_")), default="picks_2026")
    raw = data.get(year) or data.get("picks_2026") or []
    items = []
    for row in raw:
        sym = str(row.get("symbol", ""))
        items.append(
            {
                "rank": int(row.get("rank", 0)),
                "symbol": sym,
                "code": _code_from_symbol(sym),
                "name": _resolve_name(symbol=sym, code=_code_from_symbol(sym), name=str(row.get("name", ""))),
                "thr": row.get("thr"),
            }
        )
    return {
        "kind": "locked",
        "asOf": str(data.get("locked_at") or year.replace("picks_", "")),
        "source": str(path.relative_to(_MYQUAN)),
        "note": "因子13 熊盾 Top3（strategy1 动态合格池研究，🔒锁定）",
        "items": items,
    }


def _load_s1_f13_refit_summary(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    raw = data.get("picks") or []
    items = []
    for i, row in enumerate(raw):
        code = str(row.get("code", "")).zfill(6)
        sym = f"sh{code}" if code.startswith("6") else f"sz{code}"
        thr = row.get("threshold_pct")
        items.append(
            {
                "rank": i + 1,
                "symbol": sym,
                "code": code,
                "name": _resolve_name(symbol=sym, code=code, name=str(row.get("name", ""))),
                "thr": float(thr) / 100.0 if thr is not None else None,
                "f13_pass": row.get("f13_pass"),
                "f13_score_quality": row.get("f13_score_quality"),
                "oos_pl_ratio": row.get("oos_pl_ratio"),
                "oos_win_rate_pct": row.get("oos_win_rate_pct"),
                "oos_profit_factor": row.get("oos_profit_factor"),
                "oos_n_trades": row.get("oos_n_trades"),
                "oos_excess_pct": row.get("oos_excess_pct"),
            }
        )
    chain = str(data.get("selection_chain") or "factor13a → factor16")
    return {
        "kind": "pool",
        "asOf": str(data.get("generated") or "")[:10] or None,
        "source": str(path.relative_to(_MYQUAN)),
        "note": (
            f"策略1 定盘池 Top{len(items)}：因子13A 质量带初选≤40 → 因子16 OOS盈亏比排序；"
            f"无置顶（{chain}）"
        ),
        "items": items,
    }


def _load_s1_f13_refit_pool_csv(path: Path) -> dict[str, Any]:
    df = pd.read_csv(path)
    if "oos_pl_ratio" in df.columns:
        df = df.sort_values("oos_pl_ratio", ascending=False)
    items = []
    for i, (_, r) in enumerate(df.iterrows()):
        code = str(r.get("code", "")).zfill(6)
        sym = f"sh{code}" if code.startswith("6") else f"sz{code}"
        thr = r.get("threshold_pct", r.get("thr"))
        thr_f = float(thr) / 100.0 if thr is not None and float(thr) > 1 else float(thr or 0)
        items.append(
            {
                "rank": i + 1,
                "symbol": sym,
                "code": code,
                "name": _resolve_name(symbol=sym, code=code, name=str(r.get("name", ""))),
                "thr": thr_f if thr_f > 0 else None,
                "f13_pass": r.get("f13_pass"),
                "f13_score_quality": r.get("f13_score_quality"),
                "oos_pl_ratio": r.get("oos_pl_ratio"),
                "oos_win_rate_pct": r.get("oos_win_rate_pct"),
                "oos_profit_factor": r.get("oos_profit_factor"),
                "oos_n_trades": r.get("oos_n_trades"),
                "oos_excess_pct": r.get("oos_excess_pct"),
            }
        )
    return {
        "kind": "pool",
        "asOf": None,
        "source": str(path.relative_to(_MYQUAN)),
        "note": "策略1 定盘池：因子13A 质量带 → 因子16 龙头排序 Top10（无置顶）",
        "items": items[:10],
    }


def _load_factor13_csv(path: Path) -> dict[str, Any]:
    df = pd.read_csv(path)
    items = []
    for _, r in df.iterrows():
        sym = str(r.get("symbol", ""))
        items.append(
            {
                "rank": int(r.get("rank", 0)),
                "symbol": sym,
                "code": _code_from_symbol(sym),
                "name": _resolve_name(symbol=sym, code=_code_from_symbol(sym), name=str(r.get("name", ""))),
                "thr": r.get("thr"),
            }
        )
    return {
        "kind": "locked",
        "asOf": None,
        "source": str(path.relative_to(_MYQUAN)),
        "note": "因子13 WF 选股 CSV",
        "items": items[:10],
    }


def _load_weekly_csv(path: Path, *, symbol_col: str) -> dict[str, Any]:
    df = pd.read_csv(path)
    if df.empty:
        return _empty_picks("weekly", note="weekly_picks 为空")
    row = df.iloc[-1]
    date_col = "week" if "week" in df.columns else "date"
    as_of = str(row.get(date_col, ""))
    raw = str(row.get(symbol_col, "") or "")
    syms = [s.strip() for s in raw.split(",") if s.strip()]
    items = []
    for i, sym in enumerate(syms):
        code = _code_from_symbol(sym)
        items.append(
            {
                "rank": i + 1,
                "symbol": sym,
                "code": code,
                "name": _resolve_name(symbol=sym, code=code),
            }
        )
    return {
        "kind": "weekly",
        "asOf": as_of,
        "source": str(path.relative_to(_MYQUAN)),
        "note": f"最近一周 Top{len(items)}（{date_col}={as_of}）",
        "items": items,
    }


def _load_strategy2_daily(path: Path) -> dict[str, Any]:
    df = pd.read_csv(path)
    if df.empty:
        return _empty_picks("daily")
    df["dt"] = pd.to_datetime(df["dt"])
    latest = df["dt"].max()
    sub = df[df["dt"] == latest].sort_values("score", ascending=False)
    demo = sub["symbol"].astype(str).str.startswith("SYN").any()
    items = []
    for i, (_, r) in enumerate(sub.iterrows()):
        sym = str(r["symbol"])
        code = _code_from_symbol(sym)
        items.append(
            {
                "rank": i + 1,
                "symbol": sym,
                "code": code,
                "name": _resolve_name(symbol=sym, code=code, name=sym if sym.startswith("SYN") else ""),
                "score": float(r.get("score", 0)),
                "weight": float(r.get("weight", 0)),
            }
        )
    note = "缠论截面 TopK 等权"
    if demo:
        note += "（当前文件为演示/合成标的 SYN*）"
    return {
        "kind": "daily",
        "asOf": str(latest.date()) if pd.notna(latest) else None,
        "source": str(path.relative_to(_MYQUAN)),
        "note": note,
        "items": items,
    }


def _load_strategy3_signals(path: Path) -> dict[str, Any]:
    df = pd.read_parquet(path)
    if df.empty or "entry" not in df.columns:
        return _empty_picks("signals", note="无信号缓存")
    entries = df[df["entry"] == True].copy()  # noqa: E712
    if entries.empty:
        return _empty_picks("signals", note="无可买信号")
    entries["trade_date"] = pd.to_datetime(entries["trade_date"])
    latest = entries["trade_date"].max()
    sub = entries[entries["trade_date"] == latest].sort_values(
        "rank_score", ascending=False
    )
    items = []
    for i, (_, r) in enumerate(sub.head(10).iterrows()):
        sym = str(r.get("symbol", ""))
        code = str(r.get("code", ""))
        items.append(
            {
                "rank": i + 1,
                "symbol": sym,
                "code": code,
                "name": _resolve_name(symbol=sym, code=code, name=str(r.get("name", ""))),
                "score": float(r.get("rank_score", 0)),
                "gap_pct": r.get("gap_pct"),
                "vol_ratio": r.get("vol_ratio"),
                "mkt_lianban": r.get("mkt_lianban"),
                "trade_date": str(r.get("trade_date", ""))[:10],
            }
        )
    return {
        "kind": "signals",
        "asOf": str(latest.date()) if pd.notna(latest) else None,
        "source": str(path.relative_to(_MYQUAN)),
        "note": f"首板晋级可买信号（晋级日 {str(latest.date())[:10]}，按 rank_score）",
        "items": items,
    }


def _load_strategy8_signals(path: Path) -> dict[str, Any]:
    df = pd.read_parquet(path)
    if df.empty or "entry" not in df.columns:
        return _empty_picks("signals", note="无信号缓存")
    entries = df[df["entry"] == True].copy()  # noqa: E712
    if entries.empty:
        return _empty_picks("signals", note="无可买信号")
    entries["trade_date"] = pd.to_datetime(entries["trade_date"])
    latest = entries["trade_date"].max()
    sub = entries[entries["trade_date"] == latest].sort_values(
        "rank_score", ascending=False
    )
    items = []
    for i, (_, r) in enumerate(sub.head(10).iterrows()):
        sym = str(r.get("symbol", ""))
        code = str(r.get("code", ""))
        items.append(
            {
                "rank": i + 1,
                "symbol": sym,
                "code": code,
                "name": _resolve_name(symbol=sym, code=code, name=str(r.get("name", ""))),
                "score": float(r.get("rank_score", 0)),
                "theme": r.get("theme_name"),
                "theme_lu": r.get("theme_lu_count"),
                "pool_tag": r.get("pool_tag"),
                "trade_date": str(r.get("trade_date", ""))[:10],
            }
        )
    return {
        "kind": "signals",
        "asOf": str(latest.date()) if pd.notna(latest) else None,
        "source": str(path.relative_to(_MYQUAN)),
        "note": f"题材联动可买信号（执行日 {str(latest.date())[:10]}，按 rank_score）",
        "items": items,
    }


def _load_s12_signals(path: Path) -> dict[str, Any]:
    df = pd.read_parquet(path)
    if df.empty:
        return _empty_picks("signals", note="无信号缓存")
    if "entry" in df.columns:
        df = df[df["entry"] == True].copy()  # noqa: E712
    if df.empty:
        return _empty_picks("signals", note="无可买信号")
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    latest = df["trade_date"].max()
    sub = df[df["trade_date"] == latest].sort_values("rank_score", ascending=False)
    items = []
    for i, (_, r) in enumerate(sub.head(10).iterrows()):
        sym = str(r.get("symbol", ""))
        code = str(r.get("code", ""))
        items.append(
            {
                "rank": i + 1,
                "symbol": sym,
                "code": code,
                "name": _resolve_name(symbol=sym, code=code, name=str(r.get("name", ""))),
                "score": float(r.get("rank_score", 0)),
                "gap_pct": r.get("gap_pct", (float(r["gap"]) * 100 if pd.notna(r.get("gap")) else None)),
                "ld_open": r.get("ld_open"),
                "trade_date": str(r.get("trade_date", ""))[:10],
            }
        )
    return {
        "kind": "signals",
        "asOf": str(latest.date()) if pd.notna(latest) else None,
        "source": str(path.relative_to(_MYQUAN)),
        "note": f"涨停次日低开候选（{str(latest.date())[:10]}，按低开越深优先）",
        "items": items,
    }


def _load_s16_quarter(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return _empty_picks("pool", note="核心龙头产物格式错误")
    items: list[dict[str, Any]] = []
    for i, it in enumerate(raw.get("picks") or [], 1):
        code = _code_from_symbol(str(it.get("code") or it.get("symbol") or ""))
        items.append(
            {
                "rank": int(it.get("rank") or i),
                "symbol": code,
                "code": code,
                "name": _resolve_name(code=code, name=str(it.get("name") or "")),
                "theme": it.get("concept") or it.get("theme"),
                "theme_lu": it.get("rank_in_concept"),
                "score": it.get("chg_pct"),
            }
        )
    window = str(raw.get("label") or raw.get("quarter") or "")
    until = str(raw.get("valid_until") or "")
    note = str(raw.get("note") or "")
    if not note:
        note = f"近3个月 {window} 冻结" + (f"至 {until}" if until else "") + " · 通达信活跃概念龙头 · 每概念≤3 · 池约20只"
    if not items:
        note = (note + " · 池为空，请先跑 python strategy/run_core_leader_pool.py").strip(" ·")
    return {
        "kind": "pool",
        "asOf": raw.get("as_of") or window,
        "source": str(path.relative_to(_MYQUAN)),
        "note": note,
        "items": items,
    }


@lru_cache(maxsize=16)
def load_strategy_picks(strategy_id: str) -> dict[str, Any]:
    """返回策略最新选股/信号快照。"""
    sid = str(strategy_id)
    if sid == "strategy6":
        return _empty_picks(
            "none",
            note="因子12 周频 gate 需截面面板；运行 strategy6 回测后自行导出 weekly_picks",
        )
    if sid == "strategy7":
        return _empty_picks("none", note="单票笔归因策略，无截面选股名单")

    spec = _PICK_SOURCES.get(sid)
    if not spec:
        return _empty_picks()

    path = _first_existing(list(spec["paths"]))
    if path is None:
        return _empty_picks(str(spec["kind"]), note="产物文件不存在，需先跑回测")

    try:
        if sid == "strategy1":
            if path.name == "summary.json":
                return _load_s1_f13_refit_summary(path)
            if path.name in ("pool_detail.csv", "picks_2025_for_2026.csv"):
                return _load_s1_f13_refit_pool_csv(path)
            if path.suffix == ".json":
                return _load_factor13_locked(path)
            return _load_factor13_csv(path)
        if sid == "strategy2":
            return _load_strategy2_daily(path)
        if sid == "strategy3":
            return _load_strategy3_signals(path)
        if sid == "strategy8":
            out = _load_strategy8_signals(path)
            note = str(out.get("note") or "")
            if "盯盘" not in note:
                out["note"] = (note + " · 回测截面；盯盘 Tab 用当日涨停实时重算").strip(" ·")
            return out
        if sid == "strategy12":
            return _load_s12_signals(path)
        if sid in ("strategy4", "strategy5"):
            col = "symbols" if sid == "strategy4" else "picks"
            return _load_weekly_csv(path, symbol_col=col)
        if sid == "strategy16":
            return _load_s16_quarter(path)
    except Exception as e:  # noqa: BLE001
        return _empty_picks(str(spec.get("kind", "none")), note=f"读取失败: {e}")

    return _empty_picks()


def invalidate_picks_cache() -> None:
    load_strategy_picks.cache_clear()
    invalidate_name_cache()
