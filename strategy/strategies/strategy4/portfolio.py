"""策略四组合回测：因子1 + 因子4 + 20%昨高止盈 + 周频动量 Top5。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd

from strategy.board_rules import limit_down_pct_of, sina_of
from strategy.watch_universe import WATCHLIST
from strategy.backtest import metric
from strategy.config import BacktestConfig, resolve_factor4_repair
from strategy.costs import stamp_tax_for_code
from strategy.open_break import DEFAULT_PCT
from strategy.runner import prepare_factor4, run_open_break_backtest
from strategy.s1_price_select import panel_price_factors, weekly_topk_allowed
from strategy.strategies.strategy4.bindings import (
    MOM_TOP_K,
    MOM_VALUE_COL,
    TAKE_PROFIT_LEVELS,
    TAKE_PROFIT_REDUCE,
    TAKE_PROFIT_TRIGGER,
)

_MYQUAN = Path(__file__).resolve().parents[3]
DATA_CACHE = _MYQUAN / "data_cache"
UNIV_CACHE = _MYQUAN / "backtest" / "universe_zz500_1000" / "daily_cache"
ABC_CACHE = _MYQUAN / "backtest" / "universe_abc" / "daily_cache"
WARM_START = "20200101"
TRADE_START = "20250101"
END = "20260820"
CASH = 100_000.0
PINNED = {"sh600552", "sh600330"}


def load_daily(symbol: str) -> pd.DataFrame | None:
    paths = [
        UNIV_CACHE / f"{symbol}_daily_qfq.parquet",
        ABC_CACHE / f"{symbol}_daily_qfq.parquet",
        DATA_CACHE / f"{symbol}_daily_qfq.parquet",
    ]
    parts: list[pd.DataFrame] = []
    for path in paths:
        if not path.exists():
            continue
        df = pd.read_parquet(path)
        if df.empty or "date" not in df.columns:
            continue
        df = df.copy()
        df["date"] = pd.to_datetime(df["date"])
        if df["date"].dt.tz is not None:
            df["date"] = df["date"].dt.tz_convert("Asia/Shanghai")
        else:
            df["date"] = df["date"].dt.tz_localize("Asia/Shanghai")
        for col in ("open", "high", "low", "close", "volume"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["open", "high", "low", "close"])
        df["symbol"] = symbol
        parts.append(df)
    if not parts:
        return None
    merged = (
        pd.concat(parts, ignore_index=True)
        .sort_values("date")
        .drop_duplicates(subset=["date"], keep="last")
    )
    start = pd.Timestamp(WARM_START).tz_localize("Asia/Shanghai")
    end = pd.Timestamp(END).tz_localize("Asia/Shanghai") + pd.Timedelta(days=1)
    merged = merged[(merged["date"] >= start) & (merged["date"] < end)]
    if len(merged) < 80:
        return None
    return merged.reset_index(drop=True)


def watch_universe() -> list[dict]:
    rows, seen = [], set()
    for item in list(WATCHLIST):
        code = str(item["code"]).zfill(6)
        if code in seen:
            continue
        seen.add(code)
        rows.append(
            {
                "code": code,
                "symbol": sina_of(code),
                "name": item["name"],
                "entry_pct": float(item.get("entry_pct") or item.get("pct") or DEFAULT_PCT),
                "stop_pct": float(item.get("stop_pct") or item.get("pct") or DEFAULT_PCT),
                "tick": float(item.get("tick") or 0.01),
                "t0": bool(item.get("t0", False)),
                "limit_down_pct": float(
                    item.get("limit_down_pct") or limit_down_pct_of(code)
                ),
                "stamp_tax_rate": stamp_tax_for_code(code),
            }
        )
    return rows


def apply_s9_overlay(cfg: BacktestConfig) -> BacktestConfig:
    cfg = resolve_factor4_repair(cfg)
    return replace(
        cfg,
        take_profit_levels=TAKE_PROFIT_LEVELS,
        take_profit_reduce=TAKE_PROFIT_REDUCE,
        take_profit_trigger=TAKE_PROFIT_TRIGGER,
    )


def _nav_series(result) -> pd.Series:
    eq = getattr(result, "equity_curve", None)
    if eq is None or getattr(eq, "empty", True):
        return pd.Series(dtype=float)
    if isinstance(eq, pd.DataFrame):
        col = "equity" if "equity" in eq.columns else eq.columns[0]
        s = eq[col]
    else:
        s = eq
    idx = pd.to_datetime(s.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    return (
        pd.Series(pd.to_numeric(s, errors="coerce").to_numpy(), index=idx.normalize())
        .dropna()
        .sort_index()
    )


def window_metrics(eq: pd.Series, start=None, end=None) -> dict[str, float]:
    s = eq.dropna().astype(float).sort_index()
    if start is not None:
        s = s[s.index >= pd.Timestamp(start)]
    if end is not None:
        s = s[s.index <= pd.Timestamp(end)]
    if len(s) < 5:
        return {
            "ret_pct": float("nan"),
            "ann_pct": float("nan"),
            "sharpe": float("nan"),
            "mdd_pct": float("nan"),
        }
    tot = float(s.iloc[-1] / s.iloc[0] - 1.0)
    years = max((s.index[-1] - s.index[0]).days / 365.25, 1e-9)
    ann = (1.0 + tot) ** (1.0 / years) - 1.0
    rets = s.pct_change().dropna()
    vol = float(rets.std() * (252**0.5)) if len(rets) else 0.0
    sharpe = float(ann / vol) if vol > 1e-12 else 0.0
    dd = 1.0 - s / s.cummax()
    return {
        "ret_pct": tot * 100.0,
        "ann_pct": ann * 100.0,
        "sharpe": sharpe,
        "mdd_pct": float(dd.max()) * 100.0,
        "start": str(s.index[0].date()),
        "end": str(s.index[-1].date()),
    }


def active_nav(
    navs: dict[str, pd.Series],
    allowed: dict[str, dict[str, bool]] | None,
    *,
    always: set[str] | None = None,
) -> pd.Series:
    df = pd.concat(navs, axis=1).sort_index().ffill()
    rets = df.pct_change()
    always = {str(x) for x in (always or set())}
    out = []
    for ts, row in rets.iterrows():
        key = pd.Timestamp(ts).strftime("%Y-%m-%d")
        names = []
        for c in rets.columns:
            ok = allowed is None or c in always or bool((allowed.get(c) or {}).get(key, False))
            if ok and pd.notna(row.get(c)):
                names.append(c)
        out.append(float(row[names].mean()) if names else 0.0)
    nav = (1.0 + pd.Series(out, index=rets.index)).cumprod()
    if len(nav):
        nav.iloc[0] = 1.0
    return nav


def _bh_nav(dailies: dict[str, pd.DataFrame], symbols: set[str] | None = None) -> pd.Series:
    series = []
    for sym, daily in dailies.items():
        if symbols is not None and sym not in symbols:
            continue
        idx = pd.to_datetime(daily["date"])
        if getattr(idx.dt, "tz", None) is not None:
            idx = idx.dt.tz_localize(None)
        idx = pd.DatetimeIndex(idx).normalize()
        c = pd.Series(pd.to_numeric(daily["close"], errors="coerce").to_numpy(), index=idx)
        series.append(c.dropna())
    if not series:
        return pd.Series(dtype=float)
    df = pd.concat(series, axis=1).sort_index().ffill()
    norm = df.divide(df.iloc[0])
    return norm.mean(axis=1).dropna()


def _trade_slice(full: pd.DataFrame, slice_from: str = "2024-12-01") -> pd.DataFrame:
    cut = pd.Timestamp(slice_from)
    if cut.tzinfo is None:
        cut = cut.tz_localize("Asia/Shanghai")
    return full[full["date"] >= cut].reset_index(drop=True)


def run_one(
    meta: dict,
    full: pd.DataFrame,
    *,
    s9: bool,
    allowed: dict[str, bool] | None,
    start_date: str | None = None,
    slice_from: str | None = None,
):
    daily = _trade_slice(full, slice_from or "2024-12-01")
    cfg = BacktestConfig(
        symbol=meta["symbol"],
        symbol_name=meta["name"],
        em_symbol=meta["code"],
        threshold_pct=float(meta["entry_pct"]),
        entry_pct=float(meta["entry_pct"]),
        stop_pct=float(meta["stop_pct"]),
        start_date=start_date or TRADE_START,
        end_date=END,
        initial_cash=CASH,
        tick=float(meta["tick"]),
        t0=bool(meta["t0"]),
        limit_down_pct=float(meta["limit_down_pct"]),
        stamp_tax_rate=float(meta["stamp_tax_rate"]),
        energy_allowed_by_date=dict(allowed or {}),
    )
    if s9:
        cfg = apply_s9_overlay(cfg)
        prepare_factor4(cfg, full)
    result = run_open_break_backtest(cfg, daily)
    return {
        "nav": _nav_series(result),
        "n_trades": float(metric(result.metrics_df, "closed_trade_count")),
        "ret_pct": float(metric(result.metrics_df, "total_return_pct")),
        "name": meta["name"],
        "symbol": meta["symbol"],
    }


def _year_ret(nav: pd.Series, year: int) -> float:
    s = nav[nav.index.year == year]
    if len(s) < 2:
        return float("nan")
    return float(s.iloc[-1] / s.iloc[0] - 1.0) * 100.0


def run_strategy4_portfolio(
    *,
    verbose: bool = True,
) -> dict[str, Any]:
    metas = {m["symbol"]: m for m in watch_universe()}
    dailies: dict[str, pd.DataFrame] = {}
    for sym in metas:
        daily = load_daily(sym)
        if daily is not None:
            dailies[sym] = daily
    metas = {k: v for k, v in metas.items() if k in dailies}
    panel = panel_price_factors(dailies)
    mom_gate = weekly_topk_allowed(panel, value_col=MOM_VALUE_COL, k=MOM_TOP_K)

    if verbose:
        print(
            "策略四：因子1 开盘突破 + 因子4 牛市放宽止损 + "
            f"{TAKE_PROFIT_LEVELS[0]*100:.0f}% {TAKE_PROFIT_TRIGGER} 全清 + "
            f"周频 {MOM_VALUE_COL} Top{MOM_TOP_K}"
        )
        print(f"宇宙 {len(dailies)}  报告区间 {TRADE_START}~{END}")

    s1_all = {}
    s9_sel = {}
    for sym, daily in dailies.items():
        if verbose:
            print(f"  {metas[sym]['name']}")
        s1_all[sym] = run_one(metas[sym], daily, s9=False, allowed=None)
        s9_sel[sym] = run_one(metas[sym], daily, s9=True, allowed=mom_gate.get(sym))

    nav_s9 = active_nav({s: r["nav"] for s, r in s9_sel.items()}, mom_gate)
    nav_p2 = active_nav({s: s1_all[s]["nav"] for s in PINNED if s in s1_all}, None)
    nav_26 = active_nav({s: r["nav"] for s, r in s1_all.items()}, None)
    bh_p2 = _bh_nav(dailies, PINNED)
    bh_26 = _bh_nav(dailies, None)

    report_from = "2025-01-02"
    books = {
        "s9_f4_tp_mom": nav_s9,
        "s1_pinned2": nav_p2,
        "s1_watch26": nav_26,
        "bh_pinned2": bh_p2,
        "bh_watch26": bh_26,
    }
    rows = []
    for vid, nav in books.items():
        m = window_metrics(nav, start=report_from)
        rows.append(
            {
                "id": vid,
                "ret_2025_now": round(m["ret_pct"], 2),
                "ann_pct": round(m["ann_pct"], 2),
                "sharpe": round(m["sharpe"], 3),
                "mdd_pct": round(m["mdd_pct"], 2),
                "y2025": round(_year_ret(nav[nav.index >= pd.Timestamp(report_from)], 2025), 2),
                "y2026": round(_year_ret(nav[nav.index >= pd.Timestamp(report_from)], 2026), 2),
                "start": m.get("start"),
                "end": m.get("end"),
            }
        )
    table = pd.DataFrame(rows)
    names_2025 = []
    for day, g in panel.groupby(pd.to_datetime(panel["date"]).dt.tz_localize(None).dt.normalize()):
        key = pd.Timestamp(day).strftime("%Y-%m-%d")
        if key < report_from:
            continue
        picked = [s for s, mp in mom_gate.items() if mp.get(key)]
        names_2025.append({"date": key, "n": len(picked), "symbols": ",".join(sorted(picked))})
    pick_df = pd.DataFrame(names_2025)
    return {
        "table": table,
        "navs": books,
        "picks": pick_df,
        "s9_trades": sum(r["n_trades"] for r in s9_sel.values()),
        "s1_p2_trades": sum(s1_all[s]["n_trades"] for s in PINNED if s in s1_all),
        "s9_per_stock": {
            s: {"name": r["name"], "ret_pct": r["ret_pct"], "n_trades": r["n_trades"]}
            for s, r in s9_sel.items()
        },
    }


run_strategy9_portfolio = run_strategy4_portfolio
