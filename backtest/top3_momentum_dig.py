"""评分 Top3 池 × 动量/反转截面 — 对比「近一月」vs「滚动12月」评分（2020→今）。

思路:
  1) 月末用因子1 打分 → Top3（次月生效）
     - month: 近一月指标
     - roll12: 滚动12个月指标
  2) 交易日仅在该 Top3 池内，用动量/反转选 TopK（K=1/2/3）
  3) 次日开盘买入，持有 hold_days，袖套轮动
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[1]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

from backtest.top20_momentum_dig import (  # noqa: E402
    PANEL,
    blend_factor,
    build_monthly_top_pool,
    build_panel,
    mask_factor_to_pool,
)
from backtest.zz1000_momentum_select import (  # noqa: E402
    INITIAL_CASH,
    compute_factor,
    load_zz1000_mainboard,
    simulate,
)

OUT = Path(__file__).resolve().parent / "top3_momentum"
TOP_POOL = 3
SCORE_MODES = ("month", "roll12")


def _period_months(index: pd.Index) -> pd.Series:
    idx = pd.DatetimeIndex(index)
    if idx.tz is not None:
        idx = idx.tz_convert("Asia/Shanghai").tz_localize(None)
    return pd.Series(idx).dt.to_period("M").astype(str)


def mask_factor_to_pool_fast(factor: pd.DataFrame, trade_pool: dict[str, list[str]]) -> pd.DataFrame:
    months = _period_months(factor.index)
    syms = list(factor.columns)
    sym_to_j = {s: j for j, s in enumerate(syms)}
    arr = factor.to_numpy(dtype=float, copy=True)
    valid = np.zeros(arr.shape, dtype=bool)
    for i, m in enumerate(months):
        for s in trade_pool.get(str(m), []):
            j = sym_to_j.get(s)
            if j is not None:
                valid[i, j] = True
    return pd.DataFrame(np.where(valid, arr, np.nan), index=factor.index, columns=factor.columns)


def equal_pool_picks(index: pd.Index, trade_pool: dict[str, list[str]], top_k: int) -> dict:
    months = _period_months(index)
    picks = {}
    for dt, m in zip(index, months):
        pool = trade_pool.get(str(m), [])[:top_k]
        if pool:
            picks[pd.Timestamp(dt)] = pool
    return picks


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    univ = load_zz1000_mainboard()
    symbols = univ["symbol"].tolist()
    opens, highs, lows, closes = build_panel(symbols, refresh=False)
    have = set(closes.columns)

    pools: dict[str, tuple[dict, dict]] = {}
    for sm in SCORE_MODES:
        trade_pool, score_by_trade = build_monthly_top_pool(sm, TOP_POOL)
        trade_pool = {m: [s for s in syms if s in have] for m, syms in trade_pool.items()}
        score_by_trade = {
            m: {s: v for s, v in mp.items() if s in have} for m, mp in score_by_trade.items()
        }
        pools[sm] = (trade_pool, score_by_trade)
        rows = []
        for m, syms in trade_pool.items():
            for i, s in enumerate(syms, 1):
                rows.append({"score_mode": sm, "trade_month": m, "rank": i, "symbol": s})
        pd.DataFrame(rows).to_csv(
            OUT / f"top3_{sm}_pool.csv", index=False, encoding="utf-8-sig"
        )

    bt_start = pd.Timestamp("2020-02-01", tz=closes.index.tz) if closes.index.tz is not None else pd.Timestamp("2020-02-01")

    kinds_ns = [
        ("rev", 20), ("rev", 40), ("rev", 60),
        ("roc", 60), ("roc", 120),
        ("ma_gap", 20), ("ma_gap", 60),
    ]
    top_ks = [1, 2, 3]
    holds = [5, 6, 10]
    combos = []
    for sm in SCORE_MODES:
        for kind, n in kinds_ns:
            for top_k in top_ks:
                for hold in holds:
                    for mode, w1, w2 in [("pool", 0.0, 1.0), ("blend", 0.4, 0.6)]:
                        combos.append((sm, mode, kind, n, top_k, hold, w1, w2))
        # 纯 Top3 等权（不看动量）：按池顺序取前 K
        for top_k in top_ks:
            for hold in holds:
                combos.append((sm, "equal", "score", 0, top_k, hold, 1.0, 0.0))

    print(f"网格 {len(combos)} (score_modes={SCORE_MODES}, top_pool={TOP_POOL})")
    results = []
    t0 = time.time()
    fac_cache: dict[tuple, pd.DataFrame] = {}
    pool_cache: dict[tuple, pd.DataFrame] = {}

    for i, (sm, mode, kind, n, top_k, hold, w1, w2) in enumerate(combos, 1):
        trade_pool, score_by_trade = pools[sm]
        if mode == "equal":
            picks = equal_pool_picks(closes.index, trade_pool, top_k)
            use = pd.DataFrame(1.0, index=closes.index, columns=closes.columns)
        else:
            key = (kind, n)
            if key not in fac_cache:
                fac_cache[key] = compute_factor(
                    opens, highs, lows, closes, kind=kind, n=n, min_score=None, ma_filter=None
                )
            fac = fac_cache[key]
            if mode == "pool":
                pkey = (sm, kind, n)
                if pkey not in pool_cache:
                    pool_cache[pkey] = mask_factor_to_pool_fast(fac, trade_pool)
                use = pool_cache[pkey]
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
                initial_cash=INITIAL_CASH, factor_label=f"{sm}_{mode}_{kind}{n}",
            )
        except Exception as e:
            print("fail", sm, mode, kind, n, e)
            continue
        if summary.get("error"):
            continue
        results.append({
            "score_mode": sm,
            "mode": mode,
            "kind": kind,
            "n": n,
            "top_k": top_k,
            "hold_days": hold,
            "w_f1": w1,
            "w_mom": w2,
            "sharpe": float(summary.get("sharpe", np.nan)),
            "ret_pct": float(summary.get("total_return_pct", np.nan)),
            "dd_pct": float(summary.get("max_drawdown_pct", np.nan)),
            "n_buys": int(summary.get("n_buys", 0)),
        })
        if i % 25 == 0 or i == len(combos):
            print(f"  {i}/{len(combos)} ({time.time()-t0:.0f}s)")
            if results:
                best = max(results, key=lambda x: (x["sharpe"], -x["dd_pct"]))
                print(
                    f"    best sharpe={best['sharpe']:.2f} ret={best['ret_pct']:.1f}% "
                    f"dd={best['dd_pct']:.1f}% {best['score_mode']} {best['mode']} "
                    f"{best['kind']}{best['n']} k={best['top_k']} h={best['hold_days']}"
                )

    res = pd.DataFrame(results)
    res.to_csv(OUT / "grid_results.csv", index=False, encoding="utf-8-sig")
    if res.empty:
        print("无结果")
        return

    print("\n===== 近一月 vs 滚动12月（均值） =====")
    print(res.groupby("score_mode")[["sharpe", "ret_pct", "dd_pct"]].mean().round(3).to_string())
    print("\n===== 近一月 vs 滚动12月（最佳夏普） =====")
    for sm in SCORE_MODES:
        sub = res[res["score_mode"] == sm].sort_values("sharpe", ascending=False)
        print(f"\n--- {sm} ---")
        print(sub.head(5).to_string(index=False))

    cand = res[(res["dd_pct"] < 50) & (res["n_buys"] > 30)].copy()
    if cand.empty:
        cand = res.copy()
    cand = cand.sort_values(["sharpe", "ret_pct"], ascending=False)
    print("\n===== Top10 by Sharpe (dd<50) =====")
    print(cand.head(10).to_string(index=False))

    best = cand.iloc[0].to_dict()
    sm = best["score_mode"]
    trade_pool, score_by_trade = pools[sm]
    if best["mode"] == "equal":
        use = pd.DataFrame(1.0, index=closes.index, columns=closes.columns)
        picks = equal_pool_picks(closes.index, trade_pool, int(best["top_k"]))
    else:
        fac = compute_factor(
            opens, highs, lows, closes,
            kind=best["kind"], n=int(best["n"]), min_score=None, ma_filter=None,
        )
        if best["mode"] == "pool":
            use = mask_factor_to_pool_fast(fac, trade_pool)
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

    # 两边各存一条最优权益，方便对比
    side_best = {}
    for sm in SCORE_MODES:
        sub = res[res["score_mode"] == sm].sort_values("sharpe", ascending=False)
        if sub.empty:
            continue
        b = sub.iloc[0].to_dict()
        side_best[sm] = b
        trade_pool, score_by_trade = pools[sm]
        if b["mode"] == "equal":
            use = pd.DataFrame(1.0, index=closes.index, columns=closes.columns)
            picks = equal_pool_picks(closes.index, trade_pool, int(b["top_k"]))
        else:
            fac = compute_factor(
                opens, highs, lows, closes,
                kind=b["kind"], n=int(b["n"]), min_score=None, ma_filter=None,
            )
            if b["mode"] == "pool":
                use = mask_factor_to_pool_fast(fac, trade_pool)
            else:
                use = blend_factor(fac, score_by_trade, trade_pool, float(b["w_f1"]), float(b["w_mom"]))
            picks = {}
            for dt_idx, row in use.iterrows():
                s = row.dropna()
                if len(s) >= int(b["top_k"]):
                    picks[pd.Timestamp(dt_idx)] = s.nlargest(int(b["top_k"])).index.tolist()
        eq_s, _, sum_s = simulate(
            factor=use, opens=opens, closes=closes, picks=picks,
            bt_start=bt_start, hold_days=int(b["hold_days"]), top_k=int(b["top_k"]),
            initial_cash=INITIAL_CASH, factor_label=f"best_{sm}",
        )
        eq_s.to_csv(OUT / f"equity_best_{sm}.csv", index=False, encoding="utf-8-sig")
        side_best[sm]["summary_ret"] = float(sum_s.get("total_return_pct", np.nan))
        side_best[sm]["summary_dd"] = float(sum_s.get("max_drawdown_pct", np.nan))
        side_best[sm]["summary_sharpe"] = float(sum_s.get("sharpe", np.nan))

    (OUT / "best_config.json").write_text(
        json.dumps(
            {
                "best": best,
                "by_score_mode": side_best,
                "compare_mean": res.groupby("score_mode")[["sharpe", "ret_pct", "dd_pct"]]
                .mean()
                .round(4)
                .to_dict(),
                "summary": {k: summary[k] for k in summary if k != "picks"},
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    print("\nBEST", best)
    print("by_score_mode", {k: {kk: vv for kk, vv in v.items() if kk != "summary"} for k, v in side_best.items()})
    print(f"输出目录 {OUT}")


if __name__ == "__main__":
    main()
