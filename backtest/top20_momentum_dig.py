"""评分 Top20 池 × 动量/反转截面 — 挖参回测（2020→今）。

思路:
  1) 月末用因子1（开盘突破）滚动12个月指标打分 → Top20（次月生效，无前瞻）
  2) 交易日仅在该 Top20 池内，用动量/反转因子截面选 TopK
  3) 次日开盘买入，持有 hold_days，袖套轮动

对比基准: 全宇宙动量（不加 Top20 池）、仅 Top20 等权轮动
"""

from __future__ import annotations

import itertools
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[1]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

from backtest.zz1000_momentum_select import (  # noqa: E402
    CACHE_DIR,
    COMMISSION,
    INITIAL_CASH,
    LOT,
    SLIP,
    STAMP,
    compute_factor,
    load_zz1000_mainboard,
    simulate,
)
from strategy.data import fetch_daily  # noqa: E402

OUT = Path(__file__).resolve().parent / "top20_momentum"
METRICS = Path(__file__).resolve().parent / "factor1_monthly_top3" / "month_symbol_threshold_metrics.parquet"
PANEL = OUT / "panel_ohlc_2020.parquet"
W_EX, W_SH, W_DD = 5.0, 3.0, 2.0
TOP_POOL = 20


def build_panel(symbols: list[str], refresh: bool = False):
    OUT.mkdir(parents=True, exist_ok=True)
    if PANEL.exists() and not refresh:
        wide = pd.read_parquet(PANEL)
        print(f"载入面板 {PANEL} {wide['close'].shape}")
        return wide["open"], wide["high"], wide["low"], wide["close"]
    opens, highs, lows, closes = {}, {}, {}, {}
    t0 = time.time()
    end = pd.Timestamp.today().strftime("%Y%m%d")
    for i, sym in enumerate(symbols, 1):
        cache = CACHE_DIR / f"{sym}_daily_qfq.parquet"
        if not cache.exists():
            continue
        try:
            d = fetch_daily(sym, "20190101", end, cache_path=cache)
        except Exception:
            continue
        if d is None or d.empty or len(d) < 60:
            continue
        d = d.copy()
        d["d"] = pd.to_datetime(d["date"]).dt.tz_convert("Asia/Shanghai").dt.normalize()
        d = d.set_index("d")
        opens[sym] = d["open"].astype(float)
        highs[sym] = d["high"].astype(float)
        lows[sym] = d["low"].astype(float)
        closes[sym] = d["close"].astype(float)
        if i % 100 == 0:
            print(f"  panel {i}/{len(symbols)} ok={len(closes)} ({time.time()-t0:.0f}s)")
    op, hi, lo, cl = pd.DataFrame(opens), pd.DataFrame(highs), pd.DataFrame(lows), pd.DataFrame(closes)
    cols = sorted(set(op.columns) & set(hi.columns) & set(lo.columns) & set(cl.columns))
    op, hi, lo, cl = op[cols].sort_index(), hi[cols].sort_index(), lo[cols].sort_index(), cl[cols].sort_index()
    pd.concat({"open": op, "high": hi, "low": lo, "close": cl}, axis=1).to_parquet(PANEL)
    print(f"写入 {PANEL} {cl.shape}")
    return op, hi, lo, cl


def _pct_rank(s: pd.Series) -> pd.Series:
    return s.rank(method="average", pct=True)


def build_monthly_top_pool(mode: str = "roll12", top_n: int = TOP_POOL) -> dict[str, list[str]]:
    """score_month -> list of symbols (TopN). 交易月 = score_month+1。"""
    m = pd.read_parquet(METRICS)
    ok = f"{mode}_ok"
    ex, sh, dd = f"{mode}_excess_return_pct", f"{mode}_sharpe_ratio", f"{mode}_dd_improve_pct"
    sub = m[m[ok] == 1].copy()
    # 票×月择优阈值
    best_rows = []
    for (_, _), g in sub.groupby(["score_month", "symbol"]):
        g = g.copy()
        for col in (ex, sh, dd):
            v = g[col].astype(float)
            if v.nunique() <= 1 or float(v.std(ddof=0) or 0) == 0:
                g[f"r_{col}"] = 0.5
            else:
                g[f"r_{col}"] = (v - v.min()) / (v.max() - v.min())
        g["thr_score"] = W_EX * g[f"r_{ex}"] + W_SH * g[f"r_{sh}"] + W_DD * g[f"r_{dd}"]
        best_rows.append(g.loc[g["thr_score"].idxmax()])
    best = pd.DataFrame(best_rows)
    trade_pool: dict[str, list[str]] = {}
    score_by_trade: dict[str, dict[str, float]] = {}
    for month, g in best.groupby("score_month"):
        g = g.copy()
        g["score"] = (
            W_EX * _pct_rank(g[ex].astype(float))
            + W_SH * _pct_rank(g[sh].astype(float))
            + W_DD * _pct_rank(g[dd].astype(float))
        )
        g = g.sort_values("score", ascending=False).head(top_n)
        p = pd.Period(str(month), freq="M")
        trade_m = str(p + 1)
        trade_pool[trade_m] = g["symbol"].tolist()
        score_by_trade[trade_m] = dict(zip(g["symbol"], g["score"].astype(float)))
    print(f"Top{top_n} 池月数 {len(trade_pool)} mode={mode}")
    return trade_pool, score_by_trade


def mask_factor_to_pool(factor: pd.DataFrame, trade_pool: dict[str, list[str]]) -> pd.DataFrame:
    """非池内股票因子置 NaN（向量化）。"""
    months = pd.Series(factor.index).dt.tz_localize(None).dt.to_period("M").astype(str)
    syms = list(factor.columns)
    sym_to_j = {s: j for j, s in enumerate(syms)}
    arr = factor.to_numpy(dtype=float, copy=True)
    valid = np.zeros(arr.shape, dtype=bool)
    for i, m in enumerate(months):
        pool = trade_pool.get(str(m), [])
        for s in pool:
            j = sym_to_j.get(s)
            if j is not None:
                valid[i, j] = True
    arr = np.where(valid, arr, np.nan)
    return pd.DataFrame(arr, index=factor.index, columns=factor.columns)


def blend_factor(
    mom_fac: pd.DataFrame,
    score_by_trade: dict[str, dict[str, float]],
    trade_pool: dict[str, list[str]],
    w_f1: float,
    w_mom: float,
) -> pd.DataFrame:
    """双评分: w_f1 * 因子1月度分位 + w_mom * 动量截面分位，仅池内。"""
    months = pd.Series(mom_fac.index).dt.tz_localize(None).dt.to_period("M").astype(str)
    cols = set(mom_fac.columns)
    out = pd.DataFrame(np.nan, index=mom_fac.index, columns=mom_fac.columns)
    for dt, m in zip(mom_fac.index, months):
        pool = [s for s in trade_pool.get(str(m), []) if s in cols]
        if len(pool) < 2:
            continue
        row = mom_fac.loc[dt, pool].dropna()
        if len(row) < 2:
            continue
        mom_pct = row.rank(pct=True)
        f1_map = score_by_trade.get(str(m), {})
        f1_s = pd.Series({s: f1_map.get(s, np.nan) for s in row.index}).astype(float)
        if f1_s.notna().sum() >= 2:
            f1_pct = f1_s.rank(pct=True)
        else:
            f1_pct = pd.Series(0.5, index=row.index)
        blended = w_f1 * f1_pct.reindex(row.index).fillna(0.5) + w_mom * mom_pct
        out.loc[dt, blended.index] = blended.values
    return out


def run_one(
    *,
    opens, highs, lows, closes,
    trade_pool, score_by_trade,
    kind: str, n: int, top_k: int, hold_days: int,
    mode: str,  # pool | blend | universe
    w_f1: float = 0.4, w_mom: float = 0.6,
    bt_start: pd.Timestamp,
) -> dict:
    fac = compute_factor(opens, highs, lows, closes, kind=kind, n=n, min_score=None, ma_filter=None)
    if mode == "universe":
        use = fac
    elif mode == "pool":
        use = mask_factor_to_pool(fac, trade_pool)
    else:
        use = blend_factor(fac, score_by_trade, trade_pool, w_f1, w_mom)

    # picks
    picks = {}
    for dt_idx, row in use.iterrows():
        s = row.dropna()
        if len(s) < top_k:
            continue
        picks[pd.Timestamp(dt_idx)] = s.nlargest(top_k).index.tolist()

    if len(picks) < 30:
        return {"ok": 0, "sharpe": -9, "ret": -9, "dd": 9}

    _, _, summary = simulate(
        factor=use,
        opens=opens,
        closes=closes,
        picks=picks,
        bt_start=bt_start,
        hold_days=hold_days,
        top_k=top_k,
        initial_cash=INITIAL_CASH,
        factor_label=f"{mode}:{kind}{n}",
    )
    # simulate returns summary keys - check
    return {
        "ok": 1,
        "mode": mode,
        "kind": kind,
        "n": n,
        "top_k": top_k,
        "hold_days": hold_days,
        "w_f1": w_f1,
        "w_mom": w_mom,
        "sharpe": float(summary.get("sharpe", summary.get("sharpe_ratio", np.nan))),
        "ret": float(summary.get("total_return", summary.get("total_return_pct", np.nan))),
        "dd": float(summary.get("max_drawdown", summary.get("max_drawdown_pct", np.nan))),
        "n_buys": int(summary.get("n_buys", summary.get("buy_count", 0))),
        "summary": summary,
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    univ = load_zz1000_mainboard()
    symbols = univ["symbol"].tolist()
    opens, highs, lows, closes = build_panel(symbols, refresh=False)
    # 对齐到有 Top20 的区间
    trade_pool, score_by_trade = build_monthly_top_pool("roll12", TOP_POOL)
    # 只保留面板里有的票
    have = set(closes.columns)
    trade_pool = {m: [s for s in syms if s in have] for m, syms in trade_pool.items()}
    score_by_trade = {
        m: {s: v for s, v in mp.items() if s in have} for m, mp in score_by_trade.items()
    }
    # 存一份 top20
    rows = []
    for m, syms in trade_pool.items():
        for i, s in enumerate(syms, 1):
            rows.append({"trade_month": m, "rank": i, "symbol": s})
    pd.DataFrame(rows).to_csv(OUT / "top20_roll12_pool.csv", index=False, encoding="utf-8-sig")

    bt_start = pd.Timestamp("2020-02-01", tz=closes.index.tz)
    # 面板可能无 tz
    if closes.index.tz is None:
        bt_start = pd.Timestamp("2020-02-01")

    kinds_ns = [
        ("rev", 20), ("rev", 40), ("rev", 60), ("rev", 120),
        ("roc", 20), ("roc", 60), ("roc", 120),
        ("ma_gap", 20), ("ma_gap", 60),
    ]
    top_ks = [2, 3, 5]
    holds = [3, 5, 6, 10]
    # 精简网格
    combos = []
    for kind, n in kinds_ns:
        for top_k in top_ks:
            for hold in holds:
                for mode, w1, w2 in [("pool", 0.0, 1.0), ("blend", 0.4, 0.6)]:
                    combos.append((mode, kind, n, top_k, hold, w1, w2))
    for kind, n in [("rev", 60), ("roc", 60)]:
        for top_k, hold in [(2, 6), (3, 5)]:
            combos.append(("universe", kind, n, top_k, hold, 0.0, 1.0))

    print(f"网格 {len(combos)}")
    results = []
    t0 = time.time()
    fac_cache: dict[tuple, pd.DataFrame] = {}
    pool_cache: dict[tuple, pd.DataFrame] = {}
    for i, (mode, kind, n, top_k, hold, w1, w2) in enumerate(combos, 1):
        key = (kind, n)
        if key not in fac_cache:
            fac_cache[key] = compute_factor(
                opens, highs, lows, closes, kind=kind, n=n, min_score=None, ma_filter=None
            )
        fac = fac_cache[key]
        if mode == "universe":
            use = fac
        elif mode == "pool":
            if key not in pool_cache:
                pool_cache[key] = mask_factor_to_pool(fac, trade_pool)
            use = pool_cache[key]
        else:
            use = blend_factor(fac, score_by_trade, trade_pool, w1, w2)
        picks = {}
        for dt_idx, row in use.iterrows():
            s = row.dropna()
            if len(s) < top_k:
                continue
            picks[pd.Timestamp(dt_idx)] = s.nlargest(top_k).index.tolist()
        if len(picks) < 40:
            continue
        try:
            eq, tr, summary = simulate(
                factor=use, opens=opens, closes=closes, picks=picks,
                bt_start=bt_start, hold_days=hold, top_k=top_k,
                initial_cash=INITIAL_CASH, factor_label=f"{mode}_{kind}{n}",
            )
        except Exception as e:
            print("fail", mode, kind, n, e)
            continue
        if summary.get("error"):
            continue
        sharpe = float(summary.get("sharpe", np.nan))
        ret = float(summary.get("total_return_pct", np.nan))
        dd = float(summary.get("max_drawdown_pct", np.nan))
        nb = int(summary.get("n_buys", 0))
        results.append({
            "mode": mode, "kind": kind, "n": n, "top_k": top_k, "hold_days": hold,
            "w_f1": w1, "w_mom": w2, "sharpe": sharpe, "ret_pct": ret, "dd_pct": dd, "n_buys": nb,
        })
        if i % 20 == 0 or i == len(combos):
            print(f"  {i}/{len(combos)} ({time.time()-t0:.0f}s)")
            if results:
                best = max(results, key=lambda x: (x["sharpe"], -x["dd_pct"]))
                print(
                    f"    best sharpe={best['sharpe']:.2f} ret={best['ret_pct']:.1f}% "
                    f"dd={best['dd_pct']:.1f}% {best['mode']} {best['kind']}{best['n']} "
                    f"k={best['top_k']} h={best['hold_days']}"
                )

    res = pd.DataFrame(results)
    res.to_csv(OUT / "grid_results.csv", index=False, encoding="utf-8-sig")
    if res.empty:
        print("无结果")
        return
    # 过滤：回撤不要太大
    cand = res[(res["dd_pct"] < 45) & (res["n_buys"] > 50)].copy()
    if cand.empty:
        cand = res.copy()
    cand = cand.sort_values(["sharpe", "ret_pct"], ascending=False)
    print("\n===== Top10 by Sharpe (dd<45) =====")
    print(cand.head(10).to_string(index=False))
    print("\n===== Top5 by return =====")
    print(cand.sort_values("ret_pct", ascending=False).head(5).to_string(index=False))

    best = cand.iloc[0].to_dict()
    # 复跑最优存权益
    fac = compute_factor(opens, highs, lows, closes, kind=best["kind"], n=int(best["n"]), min_score=None, ma_filter=None)
    if best["mode"] == "universe":
        use = fac
    elif best["mode"] == "pool":
        use = mask_factor_to_pool(fac, trade_pool)
    else:
        use = blend_factor(fac, score_by_trade, trade_pool, float(best["w_f1"]), float(best["w_mom"]))
    picks = {}
    for dt_idx, row in use.iterrows():
        s = row.dropna()
        if len(s) >= int(best["top_k"]):
            picks[pd.Timestamp(dt_idx)] = s.nlargest(int(best["top_k"])).index.tolist()
    eq, tr, summary = simulate(
        factor=use, opens=opens, closes=closes, picks=picks,
        bt_start=bt_start, hold_days=int(best["hold_days"]), top_k=int(best["top_k"]),
        initial_cash=INITIAL_CASH, factor_label="best",
    )
    eq.to_csv(OUT / "equity_best.csv", index=False, encoding="utf-8-sig")
    tr.to_csv(OUT / "trades_best.csv", index=False, encoding="utf-8-sig")
    (OUT / "best_config.json").write_text(
        json.dumps({"best": best, "summary": {k: summary[k] for k in summary if k != "picks"}}, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print("\nBEST", best)
    print("summary", summary)
    print(f"输出目录 {OUT}")


if __name__ == "__main__":
    main()
