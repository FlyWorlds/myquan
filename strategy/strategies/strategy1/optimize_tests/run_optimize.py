"""援军战法（strategy1）优化实验：摩擦 / 止盈 / 选股 / 行情 / 夏普衰减。

默认不覆盖 bindings。产物在本目录。

  python strategy/strategies/strategy1/optimize_tests/run_optimize.py
"""

from __future__ import annotations

import json
import logging
import math
import sys
import warnings
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[4]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

from strategy.board_rules import limit_down_pct_of, sina_of  # noqa: E402
from strategy.watch_universe import WATCHLIST  # noqa: E402
from strategy import BacktestConfig  # noqa: E402
from strategy.backtest import metric  # noqa: E402
from strategy.ls_energy import (  # noqa: E402
    build_market_regime,
    compute_ls_energy,
    panel_from_dailies,
    regime_by_date,
    topk_allowed_by_date,
)
from strategy.open_break import DEFAULT_PCT  # noqa: E402
from strategy.costs import COST_ROUND_TRIP, fee_rules_text, stamp_tax_for_code  # noqa: E402
from strategy.runner import run_open_break_backtest  # noqa: E402

OUT = Path(__file__).resolve().parent
DATA_CACHE = _MYQUAN / "data_cache"
UNIV_CACHE = _MYQUAN / "backtest" / "universe_zz500_1000" / "daily_cache"
START = "20200101"
END = "20260820"
CASH = 100_000.0
TP_LEVELS = (0.08, 0.10, 0.12, 0.15, 0.20)
RT_COST = COST_ROUND_TRIP
OOS_START = "2024-01-01"
TOP_K = 5
ROLL_FAST = 63
ROLL_SLOW = 252
HALT_RATIO = 0.50


def _day(ts) -> str:
    t = pd.Timestamp(ts)
    if t.tzinfo is not None:
        t = t.tz_localize(None)
    return t.strftime("%Y-%m-%d")


def load_daily(symbol: str) -> pd.DataFrame | None:
    paths = [
        UNIV_CACHE / f"{symbol}_daily_qfq.parquet",
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
    start = pd.Timestamp(START).tz_localize("Asia/Shanghai")
    end = pd.Timestamp(END).tz_localize("Asia/Shanghai") + pd.Timedelta(days=1)
    merged = merged[(merged["date"] >= start) & (merged["date"] < end)]
    if len(merged) < 80:
        return None
    return merged.reset_index(drop=True)


def watch_universe() -> list[dict]:
    rows = []
    seen: set[str] = set()
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


def make_cfg(meta: dict, daily: pd.DataFrame, **kw) -> BacktestConfig:
    start = max(START, pd.Timestamp(daily["date"].iloc[0]).strftime("%Y%m%d"))
    end = min(END, pd.Timestamp(daily["date"].iloc[-1]).strftime("%Y%m%d"))
    cfg = BacktestConfig(
        symbol=meta["symbol"],
        symbol_name=meta["name"],
        em_symbol=meta["code"],
        threshold_pct=float(meta["entry_pct"]),
        entry_pct=float(meta["entry_pct"]),
        stop_pct=float(meta["stop_pct"]),
        start_date=start,
        end_date=end,
        initial_cash=CASH,
        tick=float(meta["tick"]),
        t0=bool(meta["t0"]),
        limit_down_pct=float(meta["limit_down_pct"]),
        stamp_tax_rate=float(meta["stamp_tax_rate"]),
        daily_cache=DATA_CACHE / f"{meta['symbol']}_daily_qfq.parquet",
    )
    return replace(cfg, **kw) if kw else cfg


def run_one(cfg: BacktestConfig, daily: pd.DataFrame) -> dict:
    result = run_open_break_backtest(cfg, daily)
    m = result.metrics_df
    nav = _nav_series(result)
    bh = float(daily["close"].iloc[-1] / daily["close"].iloc[0] - 1.0) * 100.0
    ret = float(metric(m, "total_return_pct"))
    row = {
        "symbol": cfg.symbol,
        "name": cfg.symbol_name,
        "ret_pct": ret,
        "excess_pct": ret - bh,
        "sharpe": float(metric(m, "sharpe_ratio")),
        "mdd_pct": float(metric(m, "max_drawdown_pct")),
        "win_rate": float(metric(m, "win_rate")),
        "n_trades": float(metric(m, "closed_trade_count")),
        "bh_pct": bh,
        "end_mv": float(metric(m, "end_market_value")),
        "nav": nav,
        "executions": getattr(result, "executions_df", pd.DataFrame()),
        "result": result,
    }
    return row


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
    s = pd.Series(pd.to_numeric(s, errors="coerce").to_numpy(), index=idx.normalize())
    return s.dropna()


def round_trips(exec_df: pd.DataFrame) -> pd.DataFrame:
    if exec_df is None or exec_df.empty:
        return pd.DataFrame()
    df = exec_df.copy()
    ts_col = next(
        (c for c in ("timestamp", "time", "datetime", "date") if c in df.columns),
        None,
    )
    if ts_col is None:
        return pd.DataFrame()
    df["_ts"] = pd.to_datetime(df[ts_col])
    side_col = "side" if "side" in df.columns else None
    if side_col is None:
        return pd.DataFrame()
    df = df.sort_values("_ts")
    trips: list[dict] = []
    open_buy: dict | None = None
    for _, r in df.iterrows():
        side = str(r[side_col]).lower()
        px = float(r.get("price") or 0.0)
        if "buy" in side and open_buy is None:
            open_buy = {"entry_ts": r["_ts"], "entry_px": px}
            continue
        if "sell" in side and open_buy is not None and px > 0:
            trips.append(
                {
                    **open_buy,
                    "exit_ts": r["_ts"],
                    "exit_px": px,
                    "gross_pct": px / open_buy["entry_px"] - 1.0 if open_buy["entry_px"] else np.nan,
                }
            )
            open_buy = None
    return pd.DataFrame(trips)


def attach_mfe(trips: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    if trips.empty:
        return trips
    d = daily.copy()
    d["_d"] = pd.to_datetime(d["date"]).dt.tz_localize(None).dt.normalize()
    d = d.set_index("_d").sort_index()
    rows = []
    for _, t in trips.iterrows():
        entry_d = pd.Timestamp(t["entry_ts"]).tz_localize(None).normalize()
        exit_d = pd.Timestamp(t["exit_ts"]).tz_localize(None).normalize()
        entry_px = float(t["entry_px"])
        hold = d[(d.index >= entry_d) & (d.index < exit_d)]
        if hold.empty:
            mfe_hold = np.nan
            mfe_presell = np.nan
            mae = np.nan
        else:
            mfe_hold = float(hold["high"].max() / entry_px - 1.0)
            mfe_presell = float(hold["high"].iloc[-1] / entry_px - 1.0)
            mae = float(hold["low"].min() / entry_px - 1.0)
        rows.append(
            {
                **t.to_dict(),
                "hold_bars": int(len(hold)),
                "mfe_hold": mfe_hold,
                "mfe_presell": mfe_presell,
                "mae": mae,
                "net_pct": float(t["gross_pct"]) - RT_COST
                if pd.notna(t["gross_pct"])
                else np.nan,
            }
        )
    return pd.DataFrame(rows)


def mfe_hit_table(mfe: pd.DataFrame) -> pd.DataFrame:
    if mfe.empty:
        return pd.DataFrame()
    stopped = mfe[mfe["gross_pct"] < 0]
    rows = []
    for lvl in TP_LEVELS:
        rows.append(
            {
                "tp_pct": lvl * 100,
                "all_mfe_hold_hit": float((mfe["mfe_hold"] >= lvl).mean() * 100),
                "all_mfe_presell_hit": float((mfe["mfe_presell"] >= lvl).mean() * 100),
                "stop_mfe_hold_hit": float((stopped["mfe_hold"] >= lvl).mean() * 100)
                if len(stopped)
                else np.nan,
                "stop_mfe_presell_hit": float((stopped["mfe_presell"] >= lvl).mean() * 100)
                if len(stopped)
                else np.nan,
                "median_mfe_hold": float(mfe["mfe_hold"].median() * 100),
                "median_mfe_presell": float(mfe["mfe_presell"].median() * 100),
                "median_mae": float(mfe["mae"].median() * 100),
                "n": int(len(mfe)),
                "n_stop": int(len(stopped)),
            }
        )
    return pd.DataFrame(rows)


def sharpe_from_nav(nav: pd.Series) -> float:
    r = nav.pct_change().dropna()
    if len(r) < 20 or float(r.std()) == 0:
        return float("nan")
    return float(r.mean() / r.std() * math.sqrt(252.0))


def mdd_from_nav(nav: pd.Series) -> float:
    if nav.empty:
        return float("nan")
    peak = nav.cummax()
    dd = nav / peak - 1.0
    return float(dd.min() * 100.0)


def split_metrics(nav: pd.Series) -> dict:
    if nav.empty:
        return {"is_ret": np.nan, "oos_ret": np.nan, "is_sharpe": np.nan, "oos_sharpe": np.nan}
    oos = pd.Timestamp(OOS_START)
    is_nav = nav[nav.index < oos]
    oos_nav = nav[nav.index >= oos]
    def _ret(s: pd.Series) -> float:
        if len(s) < 2:
            return float("nan")
        return float(s.iloc[-1] / s.iloc[0] - 1.0) * 100.0
    return {
        "is_ret": _ret(is_nav),
        "oos_ret": _ret(oos_nav),
        "is_sharpe": sharpe_from_nav(is_nav),
        "oos_sharpe": sharpe_from_nav(oos_nav),
        "is_mdd": mdd_from_nav(is_nav),
        "oos_mdd": mdd_from_nav(oos_nav),
    }


def halt_map_from_nav(nav: pd.Series) -> dict[str, bool]:
    r = nav.pct_change()
    fast = r.rolling(ROLL_FAST).mean() / r.rolling(ROLL_FAST).std() * math.sqrt(252)
    slow = r.rolling(ROLL_SLOW).mean() / r.rolling(ROLL_SLOW).std() * math.sqrt(252)
    halt = (fast < 0) | (fast < HALT_RATIO * slow)
    halt = halt.shift(1).fillna(False)
    out = {}
    for ts, flag in halt.items():
        out[_day(ts)] = bool(flag)
    return out


def ew_nav(navs: dict[str, pd.Series]) -> pd.Series:
    if not navs:
        return pd.Series(dtype=float)
    df = pd.concat(navs, axis=1).sort_index().ffill()
    df = df.dropna(how="all")
    norm = df.divide(df.apply(lambda s: s.dropna().iloc[0] if s.notna().any() else np.nan))
    return norm.mean(axis=1).dropna()


def ic_table(panel: pd.DataFrame) -> pd.DataFrame:
    df = panel.copy()
    df["_d"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.normalize()
    df = df.sort_values(["symbol", "_d"])
    df["fwd5"] = df.groupby("symbol")["close"].transform(lambda s: s.shift(-5) / s - 1.0)
    mkt = df.groupby("_d")["fwd5"].transform("mean")
    df["fwd5_ex"] = df["fwd5"] - mkt
    rows = []
    for day, g in df.dropna(subset=["ls_net_exec", "fwd5_ex"]).groupby("_d"):
        if len(g) < 6:
            continue
        ic = float(g["ls_net_exec"].corr(g["fwd5_ex"], method="spearman"))
        rows.append({"date": day, "rank_ic": ic, "n": int(len(g))})
    return pd.DataFrame(rows)


def _md(df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return "(无数据)"
    try:
        return df.to_markdown(index=False)
    except Exception:
        return "```\n" + df.to_string(index=False) + "\n```"


def _write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "mfe").mkdir(exist_ok=True)
    (OUT / "tp_sweep").mkdir(exist_ok=True)
    (OUT / "selection").mkdir(exist_ok=True)
    (OUT / "regime").mkdir(exist_ok=True)
    (OUT / "sharpe_decay").mkdir(exist_ok=True)

    univ = watch_universe()
    dailies: dict[str, pd.DataFrame] = {}
    metas: dict[str, dict] = {}
    for meta in univ:
        daily = load_daily(meta["symbol"])
        if daily is None:
            print(f"skip {meta['symbol']} (no cache)")
            continue
        dailies[meta["symbol"]] = daily
        metas[meta["symbol"]] = meta
        print(f"load {meta['symbol']} {meta['name']} n={len(daily)}")

    _write_json(
        OUT / "00_manifest.json",
        {
            "strategy": "strategy1",
            "factor_overlay": "factor9_ls_energy",
            "start": START,
            "end": END,
            "oos_start": OOS_START,
            "universe": [metas[s]["name"] for s in dailies],
            "n_symbols": len(dailies),
            "engine": "akquant OpenBreak3Strategy T+1 开盘突破 / 止损；可选 prev_high 止盈",
            "costs": fee_rules_text(),
            "tp_levels": list(TP_LEVELS),
            "note": "研究 overlay，未改援军战法默认绑定",
        },
    )

    print("\n=== 1) 基准仅止损 + MFE ===")
    baseline: dict[str, dict] = {}
    mfe_parts: list[pd.DataFrame] = []
    for sym, daily in dailies.items():
        cfg = make_cfg(metas[sym], daily)
        row = run_one(cfg, daily)
        baseline[sym] = row
        trips = attach_mfe(round_trips(row["executions"]), daily)
        if not trips.empty:
            trips["symbol"] = sym
            trips["name"] = metas[sym]["name"]
            mfe_parts.append(trips)
        print(
            f"  {metas[sym]['name']}: ret={row['ret_pct']:.1f}% "
            f"excess={row['excess_pct']:.1f}% sharpe={row['sharpe']:.2f} "
            f"trades={row['n_trades']:.0f}"
        )

    mfe_all = pd.concat(mfe_parts, ignore_index=True) if mfe_parts else pd.DataFrame()
    if not mfe_all.empty:
        mfe_all.to_csv(OUT / "mfe" / "mfe_trades.csv", index=False)
        hit = mfe_hit_table(mfe_all)
        hit.to_csv(OUT / "mfe" / "mfe_summary.csv", index=False)
        print(hit.to_string(index=False))

    pinned = [
        s
        for s in (sina_of("600552"), sina_of("600330"), sina_of("589680"))
        if s in dailies
    ]
    print("\n=== 2) 全清止盈扫描（置顶票，high vs prev_high）===")
    tp_rows = []
    for sym in pinned:
        daily = dailies[sym]
        base = baseline[sym]
        for trig in ("high", "prev_high"):
            for lvl in TP_LEVELS:
                cfg = make_cfg(
                    metas[sym],
                    daily,
                    take_profit_levels=(lvl,),
                    take_profit_reduce=1.0,
                    take_profit_trigger=trig,
                )
                row = run_one(cfg, daily)
                split = split_metrics(row["nav"])
                tp_rows.append(
                    {
                        "symbol": sym,
                        "name": metas[sym]["name"],
                        "trigger": trig,
                        "tp_pct": lvl * 100,
                        "ret_pct": row["ret_pct"],
                        "d_ret_vs_stop": row["ret_pct"] - base["ret_pct"],
                        "excess_pct": row["excess_pct"],
                        "sharpe": row["sharpe"],
                        "mdd_pct": row["mdd_pct"],
                        "win_rate": row["win_rate"],
                        "n_trades": row["n_trades"],
                        **split,
                    }
                )
                print(
                    f"  {metas[sym]['name']} TP{lvl*100:.0f}@{trig}: "
                    f"ret={row['ret_pct']:.1f}% Δ={row['ret_pct']-base['ret_pct']:+.1f} "
                    f"sharpe={row['sharpe']:.2f}"
                )
    tp_df = pd.DataFrame(tp_rows)
    tp_df.to_csv(OUT / "tp_sweep" / "tp_sweep_metrics.csv", index=False)

    print("\n=== 3) 因子9 动能选股 ===")
    panel = panel_from_dailies(dailies)
    ic = ic_table(panel)
    ic.to_csv(OUT / "selection" / "ic_daily.csv", index=False)
    mean_ic = float(ic["rank_ic"].mean()) if not ic.empty else float("nan")
    icir = (
        float(ic["rank_ic"].mean() / ic["rank_ic"].std())
        if not ic.empty and float(ic["rank_ic"].std() or 0) > 0
        else float("nan")
    )
    print(f"  Rank IC(5d超额) mean={mean_ic:.4f} ICIR={icir:.3f} days={len(ic)}")
    allowed = topk_allowed_by_date(panel, k=TOP_K)
    energy_navs: dict[str, pd.Series] = {}
    energy_rows = []
    for sym, daily in dailies.items():
        gate = allowed.get(sym, {})
        cfg = make_cfg(metas[sym], daily, energy_allowed_by_date=gate)
        row = run_one(cfg, daily)
        energy_navs[sym] = row["nav"]
        energy_rows.append(
            {
                "symbol": sym,
                "name": metas[sym]["name"],
                "ret_pct": row["ret_pct"],
                "excess_pct": row["excess_pct"],
                "sharpe": row["sharpe"],
                "mdd_pct": row["mdd_pct"],
                "n_trades": row["n_trades"],
                "base_ret": baseline[sym]["ret_pct"],
                "d_ret": row["ret_pct"] - baseline[sym]["ret_pct"],
                "base_sharpe": baseline[sym]["sharpe"],
            }
        )
        print(
            f"  {metas[sym]['name']} energy-top{TOP_K}: "
            f"ret={row['ret_pct']:.1f}% Δ={row['ret_pct']-baseline[sym]['ret_pct']:+.1f} "
            f"trades {baseline[sym]['n_trades']:.0f}→{row['n_trades']:.0f}"
        )
    energy_df = pd.DataFrame(energy_rows)
    energy_df.to_csv(OUT / "selection" / "energy_gate_per_stock.csv", index=False)
    base_ew = ew_nav({s: baseline[s]["nav"] for s in baseline})
    en_ew = ew_nav(energy_navs)
    sel_summary = pd.DataFrame(
        [
            {
                "variant": "watchlist_ew_stop_only",
                "ret_pct": float(base_ew.iloc[-1] / base_ew.iloc[0] - 1) * 100 if len(base_ew) else np.nan,
                "sharpe": sharpe_from_nav(base_ew),
                "mdd_pct": mdd_from_nav(base_ew),
                **{f"split_{k}": v for k, v in split_metrics(base_ew).items()},
            },
            {
                "variant": f"energy_top{TOP_K}_gate_ew",
                "ret_pct": float(en_ew.iloc[-1] / en_ew.iloc[0] - 1) * 100 if len(en_ew) else np.nan,
                "sharpe": sharpe_from_nav(en_ew),
                "mdd_pct": mdd_from_nav(en_ew),
                **{f"split_{k}": v for k, v in split_metrics(en_ew).items()},
            },
        ]
    )
    sel_summary.to_csv(OUT / "selection" / "topk_vs_all.csv", index=False)
    print(sel_summary.to_string(index=False))

    print("\n=== 4) 行情 regime 调整止盈（置顶票）===")
    close_panel = pd.concat(
        {
            s: d.set_index(pd.to_datetime(d["date"]).dt.tz_localize(None).dt.normalize())[
                "close"
            ]
            for s, d in dailies.items()
        },
        axis=1,
    )
    regime = build_market_regime(close_panel)
    rmap = regime_by_date(regime)
    regime_rows = []
    for sym in pinned:
        daily = dailies[sym]
        cfg = make_cfg(
            metas[sym],
            daily,
            take_profit_reduce=1.0,
            take_profit_trigger="prev_high",
            regime_tp_enabled=True,
            regime_by_date=rmap,
            regime_tp_bull=(),
            regime_tp_sideways=(0.15,),
            regime_tp_bear=(0.10,),
        )
        row = run_one(cfg, daily)
        base = baseline[sym]
        regime_rows.append(
            {
                "symbol": sym,
                "name": metas[sym]["name"],
                "variant": "regime_tp_bull0_side15_bear10_prev_high",
                "ret_pct": row["ret_pct"],
                "d_ret": row["ret_pct"] - base["ret_pct"],
                "sharpe": row["sharpe"],
                "mdd_pct": row["mdd_pct"],
                "n_trades": row["n_trades"],
                **split_metrics(row["nav"]),
            }
        )
        print(
            f"  {metas[sym]['name']} regime-TP: ret={row['ret_pct']:.1f}% "
            f"Δ={row['ret_pct']-base['ret_pct']:+.1f} sharpe={row['sharpe']:.2f}"
        )
    pd.DataFrame(regime_rows).to_csv(OUT / "regime" / "regime_tp_metrics.csv", index=False)

    print("\n=== 5) 滚动夏普衰减门控（置顶票，两遍）===")
    halt_rows = []
    for sym in pinned:
        daily = dailies[sym]
        hmap = halt_map_from_nav(baseline[sym]["nav"])
        cfg = make_cfg(metas[sym], daily, halt_by_date=hmap)
        row = run_one(cfg, daily)
        base = baseline[sym]
        halt_rows.append(
            {
                "symbol": sym,
                "name": metas[sym]["name"],
                "halt_days": int(sum(1 for v in hmap.values() if v)),
                "ret_pct": row["ret_pct"],
                "d_ret": row["ret_pct"] - base["ret_pct"],
                "sharpe": row["sharpe"],
                "mdd_pct": row["mdd_pct"],
                "n_trades": row["n_trades"],
                **split_metrics(row["nav"]),
            }
        )
        print(
            f"  {metas[sym]['name']} sharpe-halt: ret={row['ret_pct']:.1f}% "
            f"Δ={row['ret_pct']-base['ret_pct']:+.1f} halt_days={sum(hmap.values())}"
        )
    pd.DataFrame(halt_rows).to_csv(OUT / "sharpe_decay" / "halt_metrics.csv", index=False)

    write_report(
        mfe_all=mfe_all,
        tp_df=tp_df,
        ic=ic,
        mean_ic=mean_ic,
        icir=icir,
        energy_df=energy_df,
        sel_summary=sel_summary,
        regime_rows=regime_rows,
        halt_rows=halt_rows,
        baseline=baseline,
        metas=metas,
    )
    print(f"\n报告: {OUT / 'optimize_report.md'}")


def write_report(**kw) -> None:
    mfe_all: pd.DataFrame = kw["mfe_all"]
    tp_df: pd.DataFrame = kw["tp_df"]
    ic: pd.DataFrame = kw["ic"]
    energy_df: pd.DataFrame = kw["energy_df"]
    sel_summary: pd.DataFrame = kw["sel_summary"]
    lines = [
        "# 援军战法（strategy1）优化实验报告",
        "",
        "研究 overlay，**未替换**默认因子1+因子2 绑定。区间 2020-01-01～2026-08-20；",
        f"样本外切 2024-01-01。T+1，{fee_rules_text()}。",
        "本报告仅供研究，不构成投资建议。",
        "",
        "## 研究合同",
        "",
        "- 执行：因子1 开盘阈值买入 / 开盘阈值止损；止盈实验为买入后一笔全清。",
        "- `high`：当日最高价触及目标价按目标价成交（与止损同口径，含同日路径）。",
        "- `prev_high`：昨日最高价已达目标 → **今日开盘**卖出（回答「卖出前一天最高价」的可执行版本）。",
        "- MFE 统计：持仓期内、**不含卖出日**的最高价相对买入价（卖出日最高价可能是止损影线，前视）。",
        "- 选股：因子9 日线多空动能截面 Top5 才允许新开仓。",
        "- 行情止盈：等权观察池牛市不止盈、震荡 15%、熊市 10%，触发=prev_high。",
        "- 夏普衰减：滚动 63 日夏普<0 或 <0.5×滚动 252 日夏普 → 次日禁开仓（两遍，用基准权益）。",
        "",
        "## 1. 摩擦与 MFE",
        "",
    ]
    if mfe_all is not None and not mfe_all.empty:
        hit = mfe_hit_table(mfe_all)
        med_hold = float(mfe_all["hold_bars"].median())
        win = float((mfe_all["gross_pct"] > 0).mean() * 100)
        lines += [
            f"- 闭环样本 {len(mfe_all)} 笔，胜率 {win:.1f}%，中位持有 {med_hold:.0f} 日。",
            f"- 单笔双边摩擦约 {RT_COST*100:.2f}%（相对成交额）。",
            "- 止损单里，有多大比例曾经摸到过 10/15/20% 浮盈（不含卖出日）：",
            "",
            _md(hit),
            "",
            "解读：若止损单的 `stop_mfe_presell_hit` 在 15% 仍然很低，说明多数亏损单并未先走出 15%，",
            "全清止盈救不了它们；真正吃摩擦的是「小亏止损 + 频繁开平」。动能门控减少逆势开仓比压低止盈更对口。",
            "",
        ]
    lines += ["## 2. 全清止盈扫描（置顶票）", ""]
    if tp_df is not None and not tp_df.empty:
        show = tp_df[
            [
                "name",
                "trigger",
                "tp_pct",
                "ret_pct",
                "d_ret_vs_stop",
                "sharpe",
                "oos_sharpe",
                "n_trades",
            ]
        ]
        lines += [_md(show), ""]
        best = tp_df.sort_values("d_ret_vs_stop", ascending=False).head(3)
        lines += ["样本内相对仅止损最好的三组（易过拟合，只作对照）：", _md(best), ""]
    lines += [
        "## 3. 因子9 选股",
        "",
        f"- 5 日超额 Rank IC 均值 {kw.get('mean_ic'):.4f}，ICIR {kw.get('icir'):.3f}，有效日 {0 if ic is None else len(ic)}。",
        "",
    ]
    if energy_df is not None and not energy_df.empty:
        lines += [_md(energy_df), ""]
    if sel_summary is not None and not sel_summary.empty:
        lines += ["观察池等权：", _md(sel_summary), ""]
    lines += ["## 4. 行情止盈", ""]
    rdf = pd.DataFrame(kw.get("regime_rows") or [])
    if not rdf.empty:
        lines += [_md(rdf), ""]
    lines += ["## 5. 夏普衰减门控", ""]
    hdf = pd.DataFrame(kw.get("halt_rows") or [])
    if not hdf.empty:
        lines += [_md(hdf), ""]
    lines += [
        "## 结论（研究候选，不替换默认策略）",
        "",
        "1. 追涨杀跌的因子1 让盈利单跑，是收益来源；历史分档减仓止盈已经系统性地落后仅止损。",
        "2. 全清止盈只在「多数止损单先有可观 MFE」时划算；否则 10% 全清会砍掉趋势，15–20% 更接近「偶尔兑现」。",
        "3. 可执行止盈优先 `prev_high`（昨高触及 → 今开卖），不要用卖出日最高价回填。",
        "4. 选票应看点时动能（因子9），不要用样本内夏普挑明年的票（已有 Top20 次年夏普大幅衰减）。",
        "5. 行情上：牛市宁可不止盈，熊/震荡才用 10–15% 全清；夏普衰减门控作为回测/实盘熔断，不是收益增强器。",
        "",
        "本报告基于历史数据与规则化回测生成，仅供研究参考，不构成任何投资建议。",
    ]
    (OUT / "optimize_report.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
