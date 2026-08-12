"""Top50 尾部切片（如 rank 47-50 / 48-50）× 池内反转，对比尖端 Top3。"""

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
    METRICS,
    W_DD,
    W_EX,
    W_SH,
    _pct_rank,
    build_panel,
)
from backtest.top3_momentum_dig import (  # noqa: E402
    _period_months,
    equal_pool_picks,
    mask_factor_to_pool_fast,
)
from backtest.zz1000_momentum_select import (  # noqa: E402
    INITIAL_CASH,
    compute_factor,
    load_zz1000_mainboard,
    simulate,
)

OUT = Path(__file__).resolve().parent / "top50_tail_momentum"
SCORE_MODE = "roll12"


def build_ranked_pool(mode: str = SCORE_MODE, top_n: int = 50):
    """trade_month -> DataFrame[symbol, rank, score]（rank=1 最好）。"""
    m = pd.read_parquet(METRICS)
    ok = f"{mode}_ok"
    ex, sh, dd = f"{mode}_excess_return_pct", f"{mode}_sharpe_ratio", f"{mode}_dd_improve_pct"
    sub = m[m[ok] == 1].copy()
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
    by_month: dict[str, pd.DataFrame] = {}
    for month, g in best.groupby("score_month"):
        g = g.copy()
        g["score"] = (
            W_EX * _pct_rank(g[ex].astype(float))
            + W_SH * _pct_rank(g[sh].astype(float))
            + W_DD * _pct_rank(g[dd].astype(float))
        )
        g = g.sort_values("score", ascending=False).head(top_n).reset_index(drop=True)
        g["rank"] = np.arange(1, len(g) + 1)
        trade_m = str(pd.Period(str(month), freq="M") + 1)
        by_month[trade_m] = g[["symbol", "rank", "score"]]
    print(f"Top{top_n} 排名池月数 {len(by_month)} mode={mode}")
    return by_month


def slice_pool(ranked: dict[str, pd.DataFrame], rank_lo: int, rank_hi: int, have: set[str]):
    trade_pool, score_by_trade = {}, {}
    for m, g in ranked.items():
        sub = g[(g["rank"] >= rank_lo) & (g["rank"] <= rank_hi)]
        syms = [s for s in sub["symbol"].tolist() if s in have]
        trade_pool[m] = syms
        score_by_trade[m] = {
            s: float(sc) for s, sc in zip(sub["symbol"], sub["score"]) if s in have
        }
    return trade_pool, score_by_trade


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    univ = load_zz1000_mainboard()
    opens, highs, lows, closes = build_panel(univ["symbol"].tolist(), refresh=False)
    have = set(closes.columns)
    ranked = build_ranked_pool(SCORE_MODE, 50)

    # 切片：尖端1-3、尾部48-50（最后3名）、尾部47-50（你说的区间）
    slices = {
        "tip_1_3": (1, 3),
        "tail_48_50": (48, 50),
        "tail_47_50": (47, 50),
    }
    pools = {}
    for name, (lo, hi) in slices.items():
        tp, sc = slice_pool(ranked, lo, hi, have)
        pools[name] = (tp, sc)
        rows = []
        for m, g in ranked.items():
            sub = g[(g["rank"] >= lo) & (g["rank"] <= hi)]
            for _, r in sub.iterrows():
                if r["symbol"] in have:
                    rows.append(
                        {
                            "slice": name,
                            "trade_month": m,
                            "rank": int(r["rank"]),
                            "symbol": r["symbol"],
                            "score": float(r["score"]),
                        }
                    )
        pd.DataFrame(rows).to_csv(OUT / f"pool_{name}.csv", index=False, encoding="utf-8-sig")
        avg_n = np.mean([len(v) for v in tp.values()]) if tp else 0
        print(f"  slice {name} ranks {lo}-{hi} avg_size={avg_n:.2f}")

    bt_start = (
        pd.Timestamp("2020-02-01", tz=closes.index.tz)
        if closes.index.tz is not None
        else pd.Timestamp("2020-02-01")
    )

    kinds_ns = [("rev", 20), ("rev", 40), ("roc", 60), ("roc", 120), ("ma_gap", 60)]
    top_ks = [1, 2, 3]
    holds = [5, 10]
    combos = []
    for slice_name in slices:
        for kind, n in kinds_ns:
            for top_k in top_ks:
                for hold in holds:
                    combos.append((slice_name, "pool", kind, n, top_k, hold))
        for top_k in top_ks:
            for hold in holds:
                combos.append((slice_name, "equal", "score", 0, top_k, hold))

    print(f"网格 {len(combos)}")
    fac_cache = {}
    pool_cache = {}
    results = []
    t0 = time.time()

    for i, (slice_name, mode, kind, n, top_k, hold) in enumerate(combos, 1):
        trade_pool, _ = pools[slice_name]
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
            pkey = (slice_name, kind, n)
            if pkey not in pool_cache:
                pool_cache[pkey] = mask_factor_to_pool_fast(fac, trade_pool)
            use = pool_cache[pkey]
            picks = {}
            for dt_idx, row in use.iterrows():
                s = row.dropna()
                if len(s) < top_k:
                    continue
                picks[pd.Timestamp(dt_idx)] = s.nlargest(top_k).index.tolist()

        if len(picks) < 40:
            continue
        try:
            _, _, summary = simulate(
                factor=use,
                opens=opens,
                closes=closes,
                picks=picks,
                bt_start=bt_start,
                hold_days=hold,
                top_k=top_k,
                initial_cash=INITIAL_CASH,
                factor_label=f"{slice_name}_{mode}_{kind}{n}",
            )
        except Exception as e:
            print("fail", slice_name, mode, kind, n, e)
            continue
        if summary.get("error"):
            continue
        results.append(
            {
                "slice": slice_name,
                "mode": mode,
                "kind": kind,
                "n": n,
                "top_k": top_k,
                "hold_days": hold,
                "sharpe": float(summary.get("sharpe", np.nan)),
                "ret_pct": float(summary.get("total_return_pct", np.nan)),
                "dd_pct": float(summary.get("max_drawdown_pct", np.nan)),
                "n_buys": int(summary.get("n_buys", 0)),
            }
        )
        if i % 20 == 0 or i == len(combos):
            print(f"  {i}/{len(combos)} ({time.time()-t0:.0f}s)")

    res = pd.DataFrame(results)
    res.to_csv(OUT / "grid_results.csv", index=False, encoding="utf-8-sig")
    if res.empty:
        print("无结果")
        return

    print("\n===== 切片均值 =====")
    print(res.groupby("slice")[["sharpe", "ret_pct", "dd_pct"]].mean().round(3).to_string())
    print("\n===== 各切片最优夏普 =====")
    side = {}
    for name in slices:
        sub = res[res["slice"] == name].sort_values("sharpe", ascending=False)
        print(f"\n--- {name} ---")
        print(sub.head(5).to_string(index=False))
        if sub.empty:
            continue
        b = sub.iloc[0].to_dict()
        side[name] = b
        trade_pool, _ = pools[name]
        if b["mode"] == "equal":
            use = pd.DataFrame(1.0, index=closes.index, columns=closes.columns)
            picks = equal_pool_picks(closes.index, trade_pool, int(b["top_k"]))
        else:
            fac = compute_factor(
                opens, highs, lows, closes,
                kind=b["kind"], n=int(b["n"]), min_score=None, ma_filter=None,
            )
            use = mask_factor_to_pool_fast(fac, trade_pool)
            picks = {}
            for dt_idx, row in use.iterrows():
                s = row.dropna()
                if len(s) >= int(b["top_k"]):
                    picks[pd.Timestamp(dt_idx)] = s.nlargest(int(b["top_k"])).index.tolist()
        eq, _, sum_s = simulate(
            factor=use, opens=opens, closes=closes, picks=picks,
            bt_start=bt_start, hold_days=int(b["hold_days"]), top_k=int(b["top_k"]),
            initial_cash=INITIAL_CASH, factor_label=f"best_{name}",
        )
        eq.to_csv(OUT / f"equity_best_{name}.csv", index=False, encoding="utf-8-sig")
        b["summary_ret"] = float(sum_s.get("total_return_pct", np.nan))
        b["summary_dd"] = float(sum_s.get("max_drawdown_pct", np.nan))
        b["summary_sharpe"] = float(sum_s.get("sharpe", np.nan))
        side[name] = b

    best = res.sort_values("sharpe", ascending=False).iloc[0].to_dict()
    (OUT / "best_config.json").write_text(
        json.dumps(
            {
                "best": best,
                "by_slice": side,
                "compare_mean": res.groupby("slice")[["sharpe", "ret_pct", "dd_pct"]]
                .mean()
                .round(4)
                .to_dict(),
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    print("\nBEST overall", best)
    print(f"输出 {OUT}")


if __name__ == "__main__":
    main()
