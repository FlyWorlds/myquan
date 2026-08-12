"""Top100 尾部10（rank 91-100）× 池内动量/反转，对照尖端1-10。"""

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

from backtest.top20_momentum_dig import build_panel, blend_factor  # noqa: E402
from backtest.top3_momentum_dig import equal_pool_picks, mask_factor_to_pool_fast  # noqa: E402
from backtest.top50_tail_momentum_dig import build_ranked_pool, slice_pool  # noqa: E402
from backtest.zz1000_momentum_select import (  # noqa: E402
    INITIAL_CASH,
    compute_factor,
    load_zz1000_mainboard,
    simulate,
)

OUT = Path(__file__).resolve().parent / "top100_tail10_momentum"
SCORE_MODE = "roll12"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    univ = load_zz1000_mainboard()
    opens, highs, lows, closes = build_panel(univ["symbol"].tolist(), refresh=False)
    have = set(closes.columns)
    ranked = build_ranked_pool(SCORE_MODE, 100)

    slices = {
        "tip_1_10": (1, 10),
        "tail_91_100": (91, 100),
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
        avg_n = float(np.mean([len(v) for v in tp.values()])) if tp else 0.0
        print(f"  slice {name} ranks {lo}-{hi} avg_size={avg_n:.2f} months={len(tp)}")

    bt_start = (
        pd.Timestamp("2020-02-01", tz=closes.index.tz)
        if closes.index.tz is not None
        else pd.Timestamp("2020-02-01")
    )

    kinds_ns = [
        ("rev", 20), ("rev", 40), ("rev", 60),
        ("roc", 60), ("roc", 120),
        ("ma_gap", 20), ("ma_gap", 60),
    ]
    top_ks = [2, 3, 5, 8]
    holds = [5, 10]
    combos = []
    for slice_name in slices:
        for kind, n in kinds_ns:
            for top_k in top_ks:
                for hold in holds:
                    for mode, w1, w2 in [("pool", 0.0, 1.0), ("blend", 0.4, 0.6)]:
                        combos.append((slice_name, mode, kind, n, top_k, hold, w1, w2))
        for top_k in [3, 5, 8, 10]:
            for hold in holds:
                combos.append((slice_name, "equal", "score", 0, top_k, hold, 1.0, 0.0))

    print(f"网格 {len(combos)}")
    fac_cache: dict = {}
    pool_cache: dict = {}
    results = []
    t0 = time.time()

    for i, (slice_name, mode, kind, n, top_k, hold, w1, w2) in enumerate(combos, 1):
        trade_pool, score_by_trade = pools[slice_name]
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
                pkey = (slice_name, kind, n)
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
            _, _, summary = simulate(
                factor=use, opens=opens, closes=closes, picks=picks,
                bt_start=bt_start, hold_days=hold, top_k=top_k,
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
                "w_f1": w1,
                "w_mom": w2,
                "sharpe": float(summary.get("sharpe", np.nan)),
                "ret_pct": float(summary.get("total_return_pct", np.nan)),
                "dd_pct": float(summary.get("max_drawdown_pct", np.nan)),
                "n_buys": int(summary.get("n_buys", 0)),
            }
        )
        if i % 30 == 0 or i == len(combos):
            best = max(results, key=lambda x: x["sharpe"]) if results else None
            msg = ""
            if best:
                msg = (
                    f" best={best['slice']} {best['mode']} {best['kind']}{best['n']} "
                    f"k={best['top_k']} h={best['hold_days']} "
                    f"sh={best['sharpe']:.2f} ret={best['ret_pct']:.0f}%"
                )
            print(f"  {i}/{len(combos)} ({time.time()-t0:.0f}s){msg}")

    res = pd.DataFrame(results)
    res.to_csv(OUT / "grid_results.csv", index=False, encoding="utf-8-sig")
    if res.empty:
        print("无结果")
        return

    print("\n===== 切片均值 =====")
    print(res.groupby("slice")[["sharpe", "ret_pct", "dd_pct"]].mean().round(3).to_string())

    side = {}
    for name in slices:
        sub = res[res["slice"] == name].sort_values("sharpe", ascending=False)
        print(f"\n--- {name} top5 ---")
        print(sub.head(5).to_string(index=False))
        print(f"--- {name} dd<45 top5 ---")
        c = sub[sub["dd_pct"] < 45]
        print((c.head(5).to_string(index=False)) if len(c) else "  none")
        if sub.empty:
            continue
        # 存绝对最优 + dd<45 最优
        for tag, pick_df in [("best", sub), ("best_dd45", c if len(c) else sub)]:
            b = pick_df.iloc[0].to_dict()
            trade_pool, score_by_trade = pools[name]
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
                    use = blend_factor(
                        fac, score_by_trade, trade_pool, float(b["w_f1"]), float(b["w_mom"])
                    )
                picks = {}
                for dt_idx, row in use.iterrows():
                    s = row.dropna()
                    if len(s) >= int(b["top_k"]):
                        picks[pd.Timestamp(dt_idx)] = s.nlargest(int(b["top_k"])).index.tolist()
            eq, _, sum_s = simulate(
                factor=use, opens=opens, closes=closes, picks=picks,
                bt_start=bt_start, hold_days=int(b["hold_days"]), top_k=int(b["top_k"]),
                initial_cash=INITIAL_CASH, factor_label=f"{tag}_{name}",
            )
            eq.to_csv(OUT / f"equity_{tag}_{name}.csv", index=False, encoding="utf-8-sig")
            b["summary_ret"] = float(sum_s.get("total_return_pct", np.nan))
            b["summary_dd"] = float(sum_s.get("max_drawdown_pct", np.nan))
            b["summary_sharpe"] = float(sum_s.get("sharpe", np.nan))
            side[f"{name}:{tag}"] = b

    (OUT / "best_config.json").write_text(
        json.dumps(
            {
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
    print(f"\n输出 {OUT}")


if __name__ == "__main__":
    main()
