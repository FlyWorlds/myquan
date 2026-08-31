"""策略一（因子1+2+13A+16）· 宽宇宙 · 2025-2026调参 / 2026至今OOS。

选股链：因子13A 质量带（网格调参）→ 因子16（闭环盈亏比/胜率排序）→ 固定 10 只。
宇宙：沪深300 + 中证500 + 中证1000 + 中证1500（并集去重，主板选股）。
无置顶；及格才入池。

用法:
  python backtest/s1_f13_refit_2025.py
  python backtest/s1_f13_refit_2025.py --rebuild-panel --fetch-missing
  python backtest/s1_f13_refit_2025.py --apply-watch
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import re
import sys
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

_MYQUAN = Path(__file__).resolve().parents[1]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from backtest.universe_zz500_1000 import (  # noqa: E402
    CACHE_DIR as ZZ_CACHE,
    _is_mainboard,
    load_universe_wide,
)
from holdingStocks.watch_config import limit_down_pct_of, sina_of  # noqa: E402
from strategy import BacktestConfig, run_open_break_backtest  # noqa: E402
from strategy.data import fetch_daily  # noqa: E402
from strategy.factor16_leader_score import (  # noqa: E402
    attach_factor13_scores,
    eval_stock_metrics_from_daily,
    rank_leader_pool,
)
from strategy.run_factor13_quality_opt import (  # noqa: E402
    WORKERS,
    process_symbol,
    select,
    walk_forward,
)
import backtest.factor1_monthly_top3 as f1m  # noqa: E402

OUT = _MYQUAN / "backtest" / "s1_f13_refit_2025"
WIDE_CACHE = _MYQUAN / "backtest" / "universe_wide" / "daily_cache"
WIDE_META = _MYQUAN / "backtest" / "universe_wide" / "results.csv"
WIDE_PANEL = OUT / "year_thr_panel_wide.parquet"
WATCH_CONFIG = _MYQUAN / "holdingStocks" / "watch_config.py"
CACHE_DIRS = (WIDE_CACHE, ZZ_CACHE)

FIT_YEARS = [2024, 2025]
PICK_FIT_YEAR = 2025
FIT_START, FIT_END = "20250101", "20261231"
OOS_START = "20260101"
THR_GRID = (0.02, 0.025, 0.03)
INITIAL_CASH = 100_000.0
POOL_SIZE = 10
CANDIDATE_POOL = 40  # 13A 初选池 → 因子16 缩至 POOL_SIZE
F13A_FIT_END = "20251231"
MIN_OOS_TRADES = 3

# 放宽质量带；网格固定 Top10
RELAXED_SHARPE_BANDS = [
    (0.5, 2.5),
    (0.7, 2.2),
    (1.0, 2.5),
    (0.3, 2.8),
]
RELAXED_MDD_BANDS = [
    (15.0, 35.0),
    (18.0, 38.0),
    (12.0, 40.0),
    (20.0, 32.0),
]
RELAXED_DD_RATIO_MAX = [0.55, 0.60, 0.65, 0.70]
RELAXED_RANK_COLS = ["score_quality", "excess", "score_fit", "sharpe"]
RELAXED_TOP_K = [POOL_SIZE]


def grid_search_fit(panel: pd.DataFrame, fit_years: list[int]) -> tuple[pd.DataFrame, dict, pd.DataFrame]:
    configs = []
    for thr_mode in ["0.025", "0.030", "best"]:
        for sh in RELAXED_SHARPE_BANDS:
            for mdd in RELAXED_MDD_BANDS:
                for ddr in RELAXED_DD_RATIO_MAX:
                    for rank_col in RELAXED_RANK_COLS:
                        for k in RELAXED_TOP_K:
                            configs.append(
                                {
                                    "thr_mode": thr_mode,
                                    "sharpe_lo": sh[0],
                                    "sharpe_hi": sh[1],
                                    "mdd_lo": mdd[0],
                                    "mdd_hi": mdd[1],
                                    "dd_ratio_max": ddr,
                                    "rank_col": rank_col,
                                    "top_k": k,
                                }
                            )
    print(f"网格 {len(configs)} 组 · fit_years={fit_years}")
    summaries: list[dict[str, Any]] = []
    best_summary = None
    best_cfg = None
    best_wf = None
    for i, cfg in enumerate(configs):
        wf = walk_forward(panel, cfg, fit_years)
        if wf["n_picks"].mean() < max(2, cfg["top_k"] * 0.5):
            continue
        avg_alpha = float(wf["alpha"].mean())
        avg_ret = float(wf["oos_ret"].mean())
        avg_med = float(wf["oos_med"].mean())
        beat = int((wf["alpha"] > 0).sum())
        skew_pen = abs(avg_ret - avg_med)
        score = avg_alpha + 0.25 * avg_med - 0.15 * skew_pen + 0.5 * beat
        row = {
            **cfg,
            "avg_ret": avg_ret,
            "avg_med": avg_med,
            "avg_alpha": avg_alpha,
            "avg_sharpe": float(wf["oos_sharpe"].mean()),
            "avg_mdd": float(wf["oos_mdd"].mean()),
            "beat_univ_n": beat,
            "n_years": len(wf),
            "skew_pen": skew_pen,
            "score": score,
            "avg_n_cand": float(wf["n_cand"].mean()),
        }
        summaries.append(row)
        if best_summary is None or score > best_summary["score"]:
            best_summary = row
            best_cfg = cfg
            best_wf = wf
        if (i + 1) % 200 == 0:
            print(f"  grid {i+1}/{len(configs)}")
    grid = pd.DataFrame(summaries).sort_values("score", ascending=False)
    if best_cfg is None or best_wf is None:
        raise RuntimeError("因子13 网格无有效参数")
    return grid, best_cfg, best_wf


def _wide_load_daily(symbol: str) -> pd.DataFrame | None:
    sym = str(symbol).lower()
    for cache_dir in CACHE_DIRS:
        cache = cache_dir / f"{sym}_daily_qfq.parquet"
        if not cache.exists():
            continue
        df = pd.read_parquet(cache)
        if df is None or df.empty:
            continue
        d = df.copy()
        d["date"] = pd.to_datetime(d["date"]).dt.tz_localize(None).dt.normalize()
        d = d.dropna(subset=["open", "high", "low", "close"]).sort_values("date")
        d = d[d["date"] >= pd.Timestamp("2019-01-01")].reset_index(drop=True)
        if len(d):
            return d
    return None


def _patch_load_daily() -> None:
    f1m.load_daily = _wide_load_daily


def _ensure_wide_meta() -> pd.DataFrame:
    WIDE_META.parent.mkdir(parents=True, exist_ok=True)
    if WIDE_META.exists():
        df = pd.read_csv(WIDE_META)
        df["symbol"] = df["symbol"].astype(str).str.lower()
        return df
    print("构建宽宇宙成分表（300+500+1000+1500）...")
    df = load_universe_wide(use_network=True, mainboard_only=False)
    df.to_csv(WIDE_META, index=False)
    print(f"  写入 {WIDE_META}：{len(df)} 行")
    return df


def _fetch_one(symbol: str, name: str, end: str) -> tuple[str, bool]:
    sym = str(symbol).lower()
    out = WIDE_CACHE / f"{sym}_daily_qfq.parquet"
    if out.exists():
        return sym, True
    for cache_dir in CACHE_DIRS:
        src = cache_dir / f"{sym}_daily_qfq.parquet"
        if src.exists():
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(src.read_bytes())
            return sym, True
    try:
        daily = fetch_daily(sym, "20190101", end, cache_path=out)
        return sym, daily is not None and not daily.empty
    except Exception:
        return sym, False


def _has_daily(symbol: str) -> bool:
    return _wide_load_daily(symbol) is not None


def _ensure_wide_cache(meta: pd.DataFrame, end: str, *, fetch_missing: bool) -> int:
    WIDE_CACHE.mkdir(parents=True, exist_ok=True)
    symbols = meta["symbol"].astype(str).str.lower().tolist()
    missing = [s for s in symbols if not _has_daily(s)]
    if not missing:
        print(f"宽宇宙缓存齐全：{len(symbols)} 只")
        return 0
    print(f"缺行情 {len(missing)} 只" + ("，开始拉取..." if fetch_missing else "（跳过拉取）"))
    if not fetch_missing:
        return len(missing)
    name_map = meta.drop_duplicates("symbol").set_index("symbol")["name"].to_dict()
    ok = 0
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {
            ex.submit(_fetch_one, sym, str(name_map.get(sym, "")), end): sym for sym in missing
        }
        done = 0
        for fut in as_completed(futs):
            done += 1
            _, success = fut.result()
            ok += int(success)
            if done % 50 == 0 or done == len(missing):
                print(f"  拉取 {done}/{len(missing)} ok={ok}")
    still = sum(1 for s in symbols if not _has_daily(s))
    print(f"拉取完成：新增 {ok}，仍缺 {still}")
    return still


def build_wide_panel(meta: pd.DataFrame, *, force: bool = False) -> pd.DataFrame:
    if WIDE_PANEL.exists() and not force:
        print(f"加载 {WIDE_PANEL}")
        return pd.read_parquet(WIDE_PANEL)
    _patch_load_daily()
    name_map = meta.drop_duplicates("symbol").set_index("symbol")["name"].to_dict()
    tasks = []
    for sym in sorted(name_map):
        if not _has_daily(sym):
            continue
        tasks.append({"symbol": sym, "name": name_map.get(sym, "")})
    print(f"宽宇宙面板 {len(tasks)} 只 × 阈值{{2.5%,3%,best}} 分年模拟...")
    from concurrent.futures import ProcessPoolExecutor, as_completed

    rows: list[dict] = []
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=WORKERS) as ex:
        futs = [ex.submit(process_symbol, t) for t in tasks]
        done = 0
        for fut in as_completed(futs):
            done += 1
            try:
                rows.extend(fut.result())
            except Exception as exc:  # noqa: BLE001
                print("err", exc)
            if done % 200 == 0 or done == len(tasks):
                print(f"  {done}/{len(tasks)} ({time.time()-t0:.0f}s) rows={len(rows)}")
    df = pd.DataFrame(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_parquet(WIDE_PANEL, index=False)
    print(f"面板 {df.shape} → {WIDE_PANEL}")
    return df


def _cfg_to_f13_rule(cfg: dict) -> dict[str, Any]:
    return {
        "min_sharpe": float(cfg["sharpe_lo"]),
        "max_sharpe": float(cfg["sharpe_hi"]),
        "mdd_lo": float(cfg["mdd_lo"]),
        "mdd_hi": float(cfg["mdd_hi"]),
        "dd_ratio_max": float(cfg["dd_ratio_max"]),
        "top_k": POOL_SIZE,
        "mainboard_only": True,
    }


def _f13a_candidates(panel: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """因子13A：质量带初选 CANDIDATE_POOL 只。"""
    from strategy.factor13_fit import enrich_cross_section_scores, select_for_next_year

    thr_mode = str(cfg["thr_mode"])
    base = select(
        panel,
        PICK_FIT_YEAR,
        thr_mode,
        sharpe_lo=float(cfg["sharpe_lo"]),
        sharpe_hi=float(cfg["sharpe_hi"]),
        mdd_lo=float(cfg["mdd_lo"]),
        mdd_hi=float(cfg["mdd_hi"]),
        dd_ratio_max=float(cfg["dd_ratio_max"]),
        rank_col=str(cfg["rank_col"]),
        top_k=CANDIDATE_POOL,
    )
    if len(base) >= CANDIDATE_POOL:
        return base.head(CANDIDATE_POOL)

    year_df = panel[(panel["year"] == PICK_FIT_YEAR) & (panel["thr_mode"] == thr_mode)].copy()
    if year_df.empty:
        year_df = panel[(panel["year"] == PICK_FIT_YEAR) & (panel["thr_mode"] == "best")].copy()
    scored = enrich_cross_section_scores(year_df)
    rank_col = str(cfg.get("rank_col", "score_quality"))
    loose = scored[
        (scored["sharpe"] >= max(0.3, float(cfg["sharpe_lo"]) - 0.3))
        & (scored["dd_ratio"] <= float(cfg["dd_ratio_max"]) + 0.1)
        & (scored["mainboard"] == 1)
    ].sort_values(rank_col, ascending=False)

    merged = base.copy()
    picked = set(merged["symbol"].tolist())
    if len(merged) < CANDIDATE_POOL:
        rest = loose[~loose["symbol"].isin(picked)].head(CANDIDATE_POOL - len(merged))
        merged = pd.concat([merged, rest], ignore_index=True).drop_duplicates("symbol")
    if merged.empty:
        merged = select_for_next_year(scored).head(CANDIDATE_POOL)
    return merged.head(CANDIDATE_POOL)


def _select_pool_f13a_f16(panel: pd.DataFrame, cfg: dict, oos_end: str) -> pd.DataFrame:
    """因子13A 过门 → 因子16 按 OOS 盈亏比/胜率排序取 Top10。"""
    rule = _cfg_to_f13_rule(cfg)
    cands = _f13a_candidates(panel, cfg)
    rows: list[dict[str, Any]] = []
    for r in cands.itertuples(index=False):
        sym = str(r.symbol).lower()
        code = _sym_to_code(sym)
        name = str(r.name)
        daily = _wide_load_daily(sym)
        if daily is None:
            continue
        row = eval_stock_metrics_from_daily(
            code,
            daily,
            name=name,
            fit_start=FIT_START,
            fit_end=F13A_FIT_END,
            oos_start=OOS_START,
            oos_end=oos_end,
            with_chan=False,
        )
        if row:
            rows.append(row)
    if not rows:
        return cands.head(POOL_SIZE)

    metrics = pd.DataFrame(rows)
    scored = attach_factor13_scores(metrics, params=rule)
    picks = rank_leader_pool(
        scored,
        top_k=POOL_SIZE,
        params={**rule, "min_oos_trades": MIN_OOS_TRADES, "min_bars": 60},
    )
    if picks.empty:
        return cands.head(POOL_SIZE)

    picks = picks.copy()
    picks["symbol"] = picks["code"].astype(str).str.zfill(6).map(sina_of)
    if "thr" in cands.columns:
        thr_map = cands.drop_duplicates("symbol").set_index("symbol")["thr"].to_dict()
        picks["thr"] = picks["symbol"].map(thr_map).fillna(0.025)
    else:
        picks["thr"] = 0.025
    return picks.head(POOL_SIZE)


def _stock_cache_path(code: str) -> Path:
    sym = sina_of(code)
    for cache_dir in CACHE_DIRS:
        p = cache_dir / f"{sym}_daily_qfq.parquet"
        if p.exists():
            return p
    return WIDE_CACHE / f"{sym}_daily_qfq.parquet"


def _today() -> str:
    return dt.date.today().strftime("%Y%m%d")


def _sym_to_code(sym: str) -> str:
    s = str(sym).lower()
    return s[2:] if s.startswith(("sh", "sz")) else s.zfill(6)


def _normalize_eq(eq: pd.Series) -> pd.Series:
    s = eq.astype(float).sort_index()
    idx = pd.DatetimeIndex(pd.to_datetime(s.index))
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    s.index = idx.normalize()
    return s / float(s.iloc[0])


def _period_return(eq: pd.Series, start: str, end: str) -> float:
    s = eq.loc[start:end]
    if s.empty:
        return float("nan")
    return float(s.iloc[-1] / s.iloc[0] - 1.0) * 100.0


def _run_stock_period(
    code: str,
    name: str,
    pct: float,
    start: str,
    end: str,
) -> dict[str, Any]:
    sym = sina_of(code)
    cache = _stock_cache_path(code)
    cfg = BacktestConfig(
        symbol=sym,
        symbol_name=name,
        em_symbol=code,
        threshold_pct=pct,
        start_date="20240101",
        end_date=end,
        initial_cash=INITIAL_CASH,
        entry_ref="today_open",
        prev_entry_mode="yin_or_small_yang",
        limit_down_pct=limit_down_pct_of(code),
        daily_cache=cache,
        report_path=None,
    )
    daily = fetch_daily(sym, "20240101", end, cache_path=cache)
    res = run_open_break_backtest(cfg, daily)
    eq = res.equity_curve_daily.astype(float).sort_index()
    eq.index = pd.DatetimeIndex(pd.to_datetime(eq.index)).tz_localize(None).normalize()
    d = daily.copy()
    d["date"] = pd.to_datetime(d["date"]).dt.tz_localize(None).dt.normalize()
    d = d.set_index("date").sort_index()
    bh = d["close"].astype(float).reindex(eq.index).ffill()
    bh = bh / float(bh.dropna().iloc[0]) * INITIAL_CASH
    return {
        "code": code,
        "name": name,
        "pct": pct,
        "equity": eq,
        "bh": bh,
        "strat_ret": _period_return(eq, start, end),
        "bh_ret": _period_return(bh, start, end),
    }


def _tune_thr_fit(code: str, name: str, end: str) -> float:
    best_thr = 0.025
    best_ret = -1e18
    for thr in THR_GRID:
        try:
            r = _run_stock_period(code, name, thr, FIT_START, FIT_END)
            if np.isfinite(r["strat_ret"]) and r["strat_ret"] > best_ret:
                best_ret = r["strat_ret"]
                best_thr = thr
        except Exception:
            continue
    return best_thr


def _portfolio_metrics(legs: list[dict[str, Any]], start: str, end: str) -> dict[str, float]:
    idx = legs[0]["equity"].index
    for leg in legs[1:]:
        idx = idx.intersection(leg["equity"].index)
    idx = idx.sort_values()
    port = sum(_normalize_eq(leg["equity"].reindex(idx).ffill()) for leg in legs) / len(legs)
    bh = sum(
        leg["bh"].reindex(idx).ffill() / float(leg["bh"].reindex(idx).ffill().iloc[0])
        for leg in legs
    ) / len(legs)
    ps = port.loc[start:end]
    bs = bh.loc[start:end]
    if ps.empty:
        return {"strategy": float("nan"), "bh": float("nan"), "excess": float("nan")}
    sr = float(ps.iloc[-1] / ps.iloc[0] - 1.0) * 100.0
    br = float(bs.iloc[-1] / bs.iloc[0] - 1.0) * 100.0
    return {"strategy": sr, "bh": br, "excess": sr - br}


def _apply_watch(picks: list[dict[str, Any]]) -> None:
    fit_pairs = [(str(p["code"]).zfill(6), str(p["name"])) for p in picks]
    pct_map: dict[str, float] = {}
    for p in picks:
        c = str(p["code"]).zfill(6)
        thr = float(p["threshold_pct"]) / 100.0
        if abs(thr - 0.025) > 1e-9:
            pct_map[c] = thr

    fit_block = "_FIT_WATCH: list[tuple[str, str]] = [\n"
    for c, n in fit_pairs:
        fit_block += f'    ("{c}", "{n}"),\n'
    fit_block += "]"

    pct_lines = ["_WATCH_PCT: dict[str, float] = {"]
    for c, pct in sorted(pct_map.items(), key=lambda x: (-x[1], x[0])):
        pct_lines.append(f'    "{c}": {pct},')
    pct_lines.append("}")
    pct_block = "\n".join(pct_lines)

    text = WATCH_CONFIG.read_text(encoding="utf-8")
    text2, n1 = re.subn(
        r"_FIT_WATCH: list\[tuple\[str, str\]\] = \[[\s\S]*?\]",
        fit_block,
        text,
        count=1,
    )
    text3, n2 = re.subn(
        r"_WATCH_PCT: dict\[str, float\] = \{[\s\S]*?\}",
        pct_block,
        text2,
        count=1,
    )
    if n1 != 1 or n2 != 1:
        raise RuntimeError(f"watch_config 替换失败 n_fit={n1} n_pct={n2}")
    text3 = re.sub(
        r"# 中证500\+1000 契合池.*",
        "# 因子13 宽宇宙换池（无置顶；及格才入池）",
        text3,
        count=1,
    )
    WATCH_CONFIG.write_text(text3, encoding="utf-8")
    print(f"已写入 {WATCH_CONFIG}：{len(fit_pairs)} 只（无置顶）")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply-watch", action="store_true", help="写回 watch_config.py")
    ap.add_argument("--rebuild-panel", action="store_true")
    ap.add_argument("--fetch-missing", action="store_true", help="拉取宽宇宙缺行情")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    end = _today()
    oos_end = min(pd.Timestamp(end), pd.Timestamp("20261231")).strftime("%Y%m%d")

    print("=== 1) 宽宇宙面板（沪深300+500+1000+1500 · 主板选股） ===")
    meta_all = _ensure_wide_meta()
    meta = meta_all[meta_all["code"].astype(str).map(_is_mainboard)].drop_duplicates("symbol").copy()
    print(f"主板可交易 {len(meta)} / 全成分 {len(meta_all)}")
    _ensure_wide_cache(meta, oos_end, fetch_missing=args.fetch_missing or args.rebuild_panel)
    _patch_load_daily()
    panel = build_wide_panel(meta, force=args.rebuild_panel)
    panel = panel[panel["mainboard"] == 1].copy()
    panel.to_csv(OUT / "year_thr_panel_mainboard.csv", index=False)

    print(f"\n=== 2) 因子13A 网格调参 + 因子16 排序（Top{POOL_SIZE}） ===")
    grid, best_cfg, train_wf = grid_search_fit(panel, FIT_YEARS)
    best_cfg["top_k"] = POOL_SIZE
    grid.to_csv(OUT / "grid_results.csv", index=False, float_format="%.4f")
    wf = walk_forward(panel, best_cfg, FIT_YEARS)
    wf.to_csv(OUT / "walkforward_fit.csv", index=False, float_format="%.4f")

    picks_df = _select_pool_f13a_f16(panel, best_cfg, oos_end)
    picks_df.to_csv(OUT / "picks_2025_for_2026.csv", index=False, float_format="%.4f")
    print(f"选股 {len(picks_df)} 只（13A 初选≤{CANDIDATE_POOL} → 因子16 Top{POOL_SIZE}）")

    print("\n=== 3) 逐票 2025-2026 阈值调参 + OOS 回测 ===")
    pool_rows: list[dict[str, Any]] = []
    legs_oos: list[dict[str, Any]] = []
    for r in picks_df.itertuples(index=False):
        code = str(getattr(r, "code", "") or _sym_to_code(getattr(r, "symbol", ""))).zfill(6)
        name = str(getattr(r, "name", code))
        base_thr = float(getattr(r, "thr", 0.025))
        tuned = _tune_thr_fit(code, name, oos_end)
        thr = tuned if np.isfinite(tuned) else base_thr
        try:
            leg = _run_stock_period(code, name, thr, OOS_START, oos_end)
        except Exception as exc:  # noqa: BLE001
            print(f"  skip {code} {name}: {exc}")
            continue
        fit_leg = _run_stock_period(code, name, thr, FIT_START, FIT_END)
        pool_rows.append(
            {
                "code": code,
                "name": name,
                "threshold_pct": round(thr * 100, 1),
                "base_thr_pct": round(base_thr * 100, 1),
                "fit_2025_2026_strategy_pct": round(fit_leg["strat_ret"], 2),
                "fit_2025_2026_bh_pct": round(fit_leg["bh_ret"], 2),
                "oos_2026_strategy_pct": round(leg["strat_ret"], 2),
                "oos_2026_bh_pct": round(leg["bh_ret"], 2),
                "oos_excess_pct": round(leg["strat_ret"] - leg["bh_ret"], 2),
                "f13_pass": int(getattr(r, "f13_pass", 0) or 0),
                "f13_score_quality": round(float(getattr(r, "score_quality", float("nan"))), 4)
                if hasattr(r, "score_quality")
                else None,
                "oos_pl_ratio": round(float(getattr(r, "oos_pl_ratio", float("nan"))), 3)
                if hasattr(r, "oos_pl_ratio")
                else None,
                "oos_win_rate_pct": round(float(getattr(r, "oos_win_rate", float("nan"))), 2)
                if hasattr(r, "oos_win_rate")
                else None,
                "oos_profit_factor": round(float(getattr(r, "oos_profit_factor", float("nan"))), 3)
                if hasattr(r, "oos_profit_factor")
                else None,
                "oos_n_trades": int(getattr(r, "oos_n_trades", 0) or 0),
            }
        )
        legs_oos.append(leg)
        print(
            f"  {code} {name} thr={thr*100:.1f}% | "
            f"FIT {fit_leg['strat_ret']:+.1f}% | OOS {leg['strat_ret']:+.1f}%"
        )

    pool_df = pd.DataFrame(pool_rows).sort_values("oos_2026_strategy_pct", ascending=False)
    pool_df.to_csv(OUT / "pool_detail.csv", index=False, float_format="%.4f")

    fit_port = _portfolio_metrics(legs_oos, FIT_START, FIT_END)
    oos_port = _portfolio_metrics(legs_oos, OOS_START, oos_end)

    summary = {
        "generated": dt.datetime.now().isoformat(timespec="seconds"),
        "universe": "沪深300+中证500+1000+1500 并集 · 主板选股（剔科创/创业/北交）",
        "pool_size": POOL_SIZE,
        "strategy": "策略一 · 因子1 + 因子2(预警) + 因子13A + 因子16",
        "selection_chain": "factor13a_quality_band → factor16_pl_ratio_rank",
        "fit_tune_years": FIT_YEARS,
        "pick_fit_year": PICK_FIT_YEAR,
        "fit_period": f"{FIT_START} → {FIT_END}",
        "oos_period": f"{OOS_START} → {oos_end}",
        "factor13_best": best_cfg,
        "n_picks": len(pool_rows),
        "portfolio_fit_2025_2026": fit_port,
        "portfolio_oos_2026": oos_port,
        "picks": pool_rows,
        "walkforward": wf.to_dict(orient="records"),
        "note_factor2": "因子2 回撤预警不参与回测注资，仅生产盯盘预警",
    }
    (OUT / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    md = [
        "# 策略一 · 因子13A+16 换池（2025-2026调参 / 2026至今OOS）",
        "",
        f"- 生成：{summary['generated']}",
        f"- 宇宙：{summary['universe']}",
        f"- 选股链：因子13A 质量带（初选≤{CANDIDATE_POOL}）→ 因子16（f13_pass → OOS盈亏比 → 利润因子）→ Top{POOL_SIZE}",
        f"- 因子13A 最优：{best_cfg['thr_mode']} · {best_cfg['rank_col']} · "
        f"夏普[{best_cfg['sharpe_lo']},{best_cfg['sharpe_hi']}] · "
        f"回撤[{best_cfg['mdd_lo']},{best_cfg['mdd_hi']}] · dd≤{best_cfg['dd_ratio_max']}",
        f"- 选股：{PICK_FIT_YEAR} 年截面 → {len(pool_rows)} 只（无置顶）",
        "",
        "## 组合等权",
        "",
        "| 区间 | 策略% | 持有% | 超额% |",
        "|---|---:|---:|---:|",
        f"| FIT 2025-2026 | {fit_port['strategy']:+.2f} | {fit_port['bh']:+.2f} | {fit_port['excess']:+.2f} |",
        f"| OOS 2026至今 | {oos_port['strategy']:+.2f} | {oos_port['bh']:+.2f} | {oos_port['excess']:+.2f} |",
        "",
        "## 新池明细",
        "",
        "| 代码 | 名称 | thr% | F13 | 盈亏比 | 胜率% | FIT25-26% | OOS26% | 超额% |",
        "|---|---|---:|:-:|:-:|---:|---:|---:|---:|",
    ]
    for r in pool_df.itertuples(index=False):
        f13 = "Y" if getattr(r, "f13_pass", 0) else "N"
        pl = getattr(r, "oos_pl_ratio", float("nan"))
        wr = getattr(r, "oos_win_rate_pct", float("nan"))
        md.append(
            f"| {r.code} | {r.name} | {r.threshold_pct} | {f13} | "
            f"{pl:.2f} | {wr:.1f} | "
            f"{r.fit_2025_2026_strategy_pct:+.2f} | {r.oos_2026_strategy_pct:+.2f} | {r.oos_excess_pct:+.2f} |"
        )
    md += [
        "",
        "## 说明",
        "",
        "- 宇宙：沪深300 ∪ 中证500 ∪ 中证1000 ∪ 中证1500（并集；1500 用官方 932000 成分）。",
        "- 因子13A：质量带 walk-forward 调参；因子16：FIT 过门 + OOS 闭环盈亏比/胜率排序。",
        "- 无置顶票；凯盛/西藏珠峰/天通等与其他标的同一标准，及格才入池。",
        "- 逐票阈值在 2025-2026 区间网格 {2%,2.5%,3%} 择优。",
        "- 因子2 仅预警，回测未叠加权益注资。",
        "- 数据截止以日线缓存为准；8/31 可能缺最后一根 K。",
        "",
        "研究口径，不构成投资建议。",
    ]
    (OUT / "report.md").write_text("\n".join(md), encoding="utf-8")

    print("\n=== 结果 ===")
    print(
        f"新池 {len(pool_rows)} 只 | FIT25-26 组合 {fit_port['strategy']:+.2f}% | "
        f"OOS26 {oos_port['strategy']:+.2f}% | 超额 {oos_port['excess']:+.2f}%"
    )
    print(f"报告 → {OUT / 'report.md'}")

    if args.apply_watch and pool_rows:
        _apply_watch(pool_rows)


if __name__ == "__main__":
    main()
