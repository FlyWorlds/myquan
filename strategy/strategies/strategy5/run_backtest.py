"""策略10 挂因子11 默认回测（mom3 / high5 / k5）。

因子11 现行定义：3 日动量 Top20 → 贴近 5 日高点 Top5；下一周等权持有。
原 20/20/k5 只作对照。新费率叠加。不混因子10。

  python strategy/strategies/strategy5/run_backtest.py
"""

from __future__ import annotations

import json
import logging
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[3]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

from strategy.costs import COST_ROUND_TRIP, FEE_ROUND_TRIP, fee_rules_text  # noqa: E402
from strategy.near_high_hold import (  # noqa: E402
    DEFAULT_PARAMS,
    ORIGINAL_PARAMS,
    near_high_rules_text,
)
from strategy.strategies.strategy5 import run_strategy10  # noqa: E402
from strategy.strategies.strategy5.run_optimize import apply_cost, cond_ic, week_turn  # noqa: E402
from strategy.strategies.strategy5.run_walk_forward import (  # noqa: E402
    IS_END,
    IS_START,
    OOS_END,
    OOS_START,
    VAL_END,
    VAL_START,
    _week,
    both_ic,
    cond_signal,
    metrics_of,
    monotonicity,
    nav_from_daily,
    nw_sharpe,
    slice_daily,
    yearly_of,
)
from strategy.strategies.strategy4.portfolio import window_metrics  # noqa: E402
from strategy.strategies.strategy4.run_two_stage import load_combined_ohlc  # noqa: E402

OUT = Path(__file__).resolve().parent / "backtest_mom3_high5_k5"

BEST_PERIOD = dict(DEFAULT_PARAMS)


def _md(df: pd.DataFrame, cols: list[str]) -> str:
    use = df[[c for c in cols if c in df.columns]].copy()
    for c in use.columns:
        if use[c].dtype.kind == "f":
            use[c] = use[c].map(lambda x: f"{x:.3f}" if pd.notna(x) else "")
    header = "| " + " | ".join(use.columns) + " |"
    sep = "| " + " | ".join("---" for _ in use.columns) + " |"
    body = "\n".join("| " + " | ".join(map(str, row)) + " |" for row in use.values)
    return "\n".join([header, sep, body])


def snap_from_gate(gate: dict[str, dict[str, bool]], dates: pd.DatetimeIndex) -> dict:
    snap: dict = {}
    for ts in dates:
        w = ts - pd.Timedelta(days=int(ts.dayofweek))
        if w in snap:
            continue
        key = pd.Timestamp(ts).strftime("%Y-%m-%d")
        snap[w] = {sym for sym, mp in gate.items() if bool((mp or {}).get(key))}
    return snap


def weekly_picks_table(snap: dict) -> pd.DataFrame:
    rows = []
    for w in sorted(snap):
        names = sorted(snap[w])
        rows.append(
            {
                "week": pd.Timestamp(w).strftime("%Y-%m-%d"),
                "n": len(names),
                "picks": ",".join(names),
            }
        )
    return pd.DataFrame(rows)


def pack(name: str, logic: str, d: pd.Series, wt: float) -> dict:
    g = metrics_of(d)
    n = metrics_of(apply_cost(d, wt if wt == wt else 0.0, COST_ROUND_TRIP))
    f = metrics_of(apply_cost(d, wt if wt == wt else 0.0, FEE_ROUND_TRIP))
    dnet = apply_cost(d, wt if wt == wt else 0.0, COST_ROUND_TRIP)
    nw_all = nw_sharpe(slice_daily(dnet, IS_START, VAL_END))
    nw_oos = nw_sharpe(slice_daily(dnet, OOS_START, OOS_END))
    nw_val = nw_sharpe(slice_daily(dnet, VAL_START, VAL_END))
    full = window_metrics(nav_from_daily(dnet), start=IS_START, end=VAL_END)
    return {
        "id": name,
        "logic": logic,
        "week_turn": wt,
        "g_is_ret": g["is_ret"],
        "g_is_sharpe": g["is_sharpe"],
        "g_oos_ret": g["oos_ret"],
        "g_oos_sharpe": g["oos_sharpe"],
        "g_val_ret": g["val_ret"],
        "g_val_sharpe": g["val_sharpe"],
        "n_is_ret": n["is_ret"],
        "n_is_sharpe": n["is_sharpe"],
        "n_is_mdd": n["is_mdd"],
        "n_oos_ret": n["oos_ret"],
        "n_oos_sharpe": n["oos_sharpe"],
        "n_oos_mdd": n["oos_mdd"],
        "n_val_ret": n["val_ret"],
        "n_val_sharpe": n["val_sharpe"],
        "n_val_mdd": n["val_mdd"],
        "fee_oos_ret": f["oos_ret"],
        "fee_val_ret": f["val_ret"],
        "full_net_ret": full["ret_pct"],
        "full_net_ann": full["ann_pct"],
        "full_net_sharpe": full["sharpe"],
        "full_net_mdd": full["mdd_pct"],
        "nw_all_t": nw_all["t"],
        "nw_oos_t": nw_oos["t"],
        "nw_val_t": nw_val["t"],
        "nw_oos_lo": nw_oos["ci_lo"],
        "nw_oos_hi": nw_oos["ci_hi"],
        "nw_val_lo": nw_val["ci_lo"],
        "nw_val_hi": nw_val["ci_hi"],
    }


def _one(close, high, params, verbose: bool, *, open_px=None, low=None):
    res = run_strategy10(
        close=close, high=high, open_px=open_px, low=low, verbose=verbose, **params
    )
    daily = res.nav.pct_change().fillna(0.0)
    daily.iloc[0] = 0.0
    snap = snap_from_gate(res.gate, close.index)
    return res, daily, snap, week_turn(snap)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    ohlc = load_combined_ohlc()
    close, high, open_px, low = ohlc["close"], ohlc["high"], ohlc["open"], ohlc["low"]
    idx = pd.to_datetime(close.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    close.index = pd.DatetimeIndex(idx).normalize()
    close = close.sort_index()
    high = high.reindex(index=close.index, columns=close.columns)
    open_px = open_px.reindex(index=close.index, columns=close.columns)
    low = low.reindex(index=close.index, columns=close.columns)
    val_end = min(pd.Timestamp(VAL_END), close.index.max()).strftime("%Y-%m-%d")
    print(f"宇宙 {close.shape[1]} 止 {close.index.max().date()} 费率 {fee_rules_text()}")
    print("主规格因子11 现行 mom3/high5/k5；一字涨停开盘买不进")

    res, daily, snap, wt = _one(
        close, high, BEST_PERIOD, True, open_px=open_px, low=low
    )
    p = dict(res.config)
    print("fill", res.fill_stats)
    _, d_orig, _, wt_orig = _one(
        close, high, dict(ORIGINAL_PARAMS), False, open_px=open_px, low=low
    )
    univ = close.pct_change().mean(axis=1)

    combo = pd.DataFrame(
        [
            pack("s10_factor11", "因子11 现行 3日动量Top20→5日近高Top5", daily, wt),
            pack("s10_original_20_20_k5", "原 20/20/k5 对照", d_orig, wt_orig),
            pack("univ_ew", "宇宙等权", univ, float("nan")),
        ]
    )
    combo.to_csv(OUT / "summary.csv", index=False)

    dnet = apply_cost(daily, wt, COST_ROUND_TRIP)
    nav_net = nav_from_daily(dnet)
    nav_gross = nav_from_daily(daily)
    nav_ew = nav_from_daily(univ)
    nav_orig = nav_from_daily(d_orig)
    pd.DataFrame(
        {
            "date": nav_gross.index.strftime("%Y-%m-%d"),
            "nav_gross": nav_gross.to_numpy(),
            "nav_net": nav_net.reindex(nav_gross.index).to_numpy(),
            "nav_original_gross": nav_orig.reindex(nav_gross.index).to_numpy(),
            "nav_univ_ew": nav_ew.reindex(nav_gross.index).to_numpy(),
        }
    ).to_csv(OUT / "nav_daily.csv", index=False)

    yearly_parts = []
    for name, nav in (
        ("s10_factor11_gross", nav_gross),
        ("s10_factor11_net", nav_net),
        ("s10_original_20_20_k5_gross", nav_orig),
        ("univ_ew", nav_ew),
    ):
        y = yearly_of(nav, range(2020, 2027))
        y["id"] = name
        yearly_parts.append(y)
    yearly_all = pd.concat(yearly_parts, ignore_index=True)
    yearly_all.to_csv(OUT / "yearly.csv", index=False)

    picks = weekly_picks_table(snap)
    picks.to_csv(OUT / "weekly_picks.csv", index=False)

    mom = close / close.shift(int(p["mom_n"])) - 1.0
    near = close / high.rolling(int(p["high_n"]), min_periods=int(p["high_n"])).max().replace(0.0, np.nan)
    fwd = close.shift(-6) / close.shift(-1) - 1.0
    ends = pd.DatetimeIndex([g.index[-1] for _, g in pd.Series(1, index=close.index).groupby(_week(close.index))])
    cond = cond_signal(mom, near, ends, int(p["stage1_k"]))
    fwd_w = fwd.reindex(ends)
    ic_rows = []
    for label, a, b in [
        ("IS 2020-2023", IS_START, IS_END),
        ("OOS 2024-2025", OOS_START, OOS_END),
        ("VAL 2026", VAL_START, val_end),
    ]:
        mask = (ends >= pd.Timestamp(a)) & (ends <= pd.Timestamp(b))
        ic = both_ic(cond.loc[mask], fwd_w.loc[mask], 52, min_n=8)
        mono, groups = monotonicity(cond.loc[mask], fwd_w.loc[mask], 5)
        ic_rows.append(
            {
                "window": label,
                "signal": "条件近高(动量Top20内)",
                **ic,
                "mono": mono,
                "g1": groups[0] if groups else float("nan"),
                "g2": groups[1] if groups else float("nan"),
                "g3": groups[2] if groups else float("nan"),
                "g4": groups[3] if groups else float("nan"),
                "g5": groups[4] if groups else float("nan"),
                "cond_rank_ic_alt": cond_ic(mom, near, fwd, int(p["stage1_k"]), a, b),
            }
        )
    ic_df = pd.DataFrame(ic_rows)
    ic_df.to_csv(OUT / "ic.csv", index=False)

    cost_rows = []
    for label, rt in [("gross", 0.0), ("fee_slip", COST_ROUND_TRIP), ("fee_only", FEE_ROUND_TRIP)]:
        dd = apply_cost(daily, wt, rt) if rt else daily
        m = metrics_of(dd)
        full = window_metrics(nav_from_daily(dd), start=IS_START, end=val_end)
        nw_oos = nw_sharpe(slice_daily(dd, OOS_START, OOS_END))
        nw_val = nw_sharpe(slice_daily(dd, VAL_START, VAL_END))
        cost_rows.append(
            {
                "cost": label,
                "full_ret": full["ret_pct"],
                "full_sharpe": full["sharpe"],
                "full_mdd": full["mdd_pct"],
                "nw_oos_t": nw_oos["t"],
                "nw_oos_lo": nw_oos["ci_lo"],
                "nw_oos_hi": nw_oos["ci_hi"],
                "nw_val_t": nw_val["t"],
                "nw_val_lo": nw_val["ci_lo"],
                "nw_val_hi": nw_val["ci_hi"],
                **{k: m[k] for k in m if not k.endswith(("start", "end"))},
            }
        )
    cost_df = pd.DataFrame(cost_rows)
    cost_df.to_csv(OUT / "cost_sweep.csv", index=False)

    month = {
        str(k.date())[:7]: float(v)
        for k, v in nav_net.resample("ME").last().dropna().items()
    }
    (OUT / "nav_monthly.json").write_text(
        json.dumps({"nav_net": month}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    row = combo.iloc[0]
    val_ic = ic_df.loc[ic_df["window"] == "VAL 2026"].iloc[0]
    oos_ic = ic_df.loc[ic_df["window"] == "OOS 2024-2025"].iloc[0]
    is_ic = ic_df.loc[ic_df["window"] == "IS 2020-2023"].iloc[0]
    manifest = {
        "strategy": "strategy5",
        "factor": "factor11",
        "spec": "mom3_high5_k5_best_period",
        "params": p,
        "fee": fee_rules_text(),
        "cost_round_trip": COST_ROUND_TRIP,
        "fee_round_trip": FEE_ROUND_TRIP,
        "universe": "HS300+ZZ500+ZZ1000 current constituents",
        "n_names": int(close.shape[1]),
        "start": IS_START,
        "end": val_end,
        "execution": "week-end close rank, hold next week; 一字涨停开盘买不进, 一字跌停封单卖不出",
        "fill_stats": res.fill_stats,
        "week_turn": wt,
        "n_weeks": int(len(picks)),
        "do_not_replace_default": False,
        "not_factor10": True,
        "not_k3": True,
        "note": "factor11 default is mom3/high5/k5; ORIGINAL_PARAMS remains 20/20/k5",
    }
    (OUT / "00_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    groups_txt = ", ".join(f"{100.0 * float(val_ic[g]):.2f}%" for g in ("g1", "g2", "g3", "g4", "g5"))
    report = f"""# 策略10 挂因子11 · mom3 high5 k5

研究回测，不构成投资建议。因子11 现行定义已是 3/5/k5。原 20/20/k5 仅对照。

不是 refinement 冻结的 k=3。

## 契约

{near_high_rules_text(p)}

- 费率：{fee_rules_text()}
- 一轮含滑点 {COST_ROUND_TRIP:.6f}；仅税费 {FEE_ROUND_TRIP:.6f}
- 周均换手 {wt:.3f}
- 宇宙：沪深300+中证500+中证1000 当前成分 {close.shape[1]} 只（幸存者偏差）
- Train {IS_START}～{IS_END}；Test {OOS_START}～{OOS_END}；Validate 2026-01-05～{val_end}

## 费用后对照

{_md(combo, ["id", "logic", "week_turn", "n_is_ret", "n_is_sharpe", "n_is_mdd", "n_oos_ret", "n_oos_sharpe", "nw_oos_t", "n_val_ret", "n_val_sharpe", "nw_val_t"])}

主规格 Newey-West：2024–2025 t={row["nw_oos_t"]:.2f}，CI {row["nw_oos_lo"]:.2f}～{row["nw_oos_hi"]:.2f}；2026 t={row["nw_val_t"]:.2f}，CI {row["nw_val_lo"]:.2f}～{row["nw_val_hi"]:.2f}。

## 分年毛收益

{_md(yearly_all, ["id", "year", "ret_pct"])}

## 因子11 条件 Rank IC（动量池内近高 vs 下周收益）

{_md(ic_df, ["window", "n", "rank_ic", "rank_ic_ir", "mono", "g1", "g2", "g3", "g4", "g5"])}

2026 五分组下周收益：{groups_txt}。单调性 {float(val_ic["mono"]):.2f}。

## 费率敏感（仅 mom3/high5/k5）

{_md(cost_df, ["cost", "full_ret", "full_sharpe", "full_mdd", "is_sharpe", "oos_ret", "oos_sharpe", "val_ret", "val_sharpe", "nw_oos_t", "nw_val_t"])}

## 决策

探索性。已写入因子11/策略10 默认：一字涨停开盘不可买入、一字跌停封单不可卖。纸面 2024–2025 / 2026 Newey-West 区间含 0 则未验证。2026 截面分组仍可能与净值路径矛盾。

条件 IC IR：IS {float(is_ic["rank_ic_ir"]):.2f}；2024–2025 {float(oos_ic["rank_ic_ir"]):.2f}；2026 {float(val_ic["rank_ic_ir"]):.2f}。

本报告仅供研究参考，不构成任何投资建议。
"""
    (OUT / "report.md").write_text(report, encoding="utf-8")
    print("wrote", OUT)
    print(combo[["id", "n_is_sharpe", "n_oos_ret", "n_oos_sharpe", "nw_oos_t", "n_val_ret", "n_val_sharpe", "nw_val_t"]].to_string(index=False))
    print(ic_df[["window", "rank_ic", "rank_ic_ir", "mono"]].to_string(index=False))


if __name__ == "__main__":
    main()
