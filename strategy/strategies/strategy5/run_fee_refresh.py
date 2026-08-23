"""新费率下重跑策略10（因子11）与因子10 等权持有对照。

不调参、不改默认。策略10 绑因子11；因子10 是价格综合分周频 Top5。

  python strategy/strategies/strategy5/run_fee_refresh.py
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
from strategy.near_high_hold import DEFAULT_PARAMS, OPTIMIZED_PARAMS  # noqa: E402
from strategy.strategies.strategy5.run_optimize import (  # noqa: E402
    apply_cost,
    daily_from_snaps,
    make_snaps,
    week_turn,
)
from strategy.strategies.strategy5.run_walk_forward import (  # noqa: E402
    IS_END,
    IS_START,
    OOS_END,
    OOS_START,
    VAL_END,
    VAL_START,
    _norm,
    metrics_of,
    nav_from_daily,
    nw_sharpe,
    slice_daily,
    yearly_of,
)
from strategy.strategies.strategy4.run_two_stage import load_combined_panel  # noqa: E402

OUT = Path(__file__).resolve().parent / "fee_refresh"


def _md(df: pd.DataFrame, cols: list[str]) -> str:
    use = df[[c for c in cols if c in df.columns]].copy()
    for c in use.columns:
        if use[c].dtype.kind == "f":
            use[c] = use[c].map(lambda x: f"{x:.3f}" if pd.notna(x) else "")
    header = "| " + " | ".join(use.columns) + " |"
    sep = "| " + " | ".join("---" for _ in use.columns) + " |"
    body = "\n".join("| " + " | ".join(map(str, row)) + " |" for row in use.values)
    return "\n".join([header, sep, body])


def pack(name: str, logic: str, d: pd.Series, wt: float) -> dict:
    g = metrics_of(d)
    n = metrics_of(apply_cost(d, wt if wt == wt else 0.0, COST_ROUND_TRIP))
    f = metrics_of(apply_cost(d, wt if wt == wt else 0.0, FEE_ROUND_TRIP))
    dnet = apply_cost(d, wt if wt == wt else 0.0, COST_ROUND_TRIP)
    nw_all = nw_sharpe(slice_daily(dnet, IS_START, VAL_END))
    nw_oos = nw_sharpe(slice_daily(dnet, OOS_START, OOS_END))
    nw_val = nw_sharpe(slice_daily(dnet, VAL_START, VAL_END))
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
        "nw_all_t": nw_all["t"],
        "nw_oos_t": nw_oos["t"],
        "nw_val_t": nw_val["t"],
        "nw_oos_lo": nw_oos["ci_lo"],
        "nw_oos_hi": nw_oos["ci_hi"],
        "nw_val_lo": nw_val["ci_lo"],
        "nw_val_hi": nw_val["ci_hi"],
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    close, high = load_combined_panel()
    close, high = _norm(close), _norm(high)
    high = high.reindex(index=close.index, columns=close.columns)
    val_end = min(pd.Timestamp(VAL_END), close.index.max()).strftime("%Y-%m-%d")
    print(f"宇宙 {close.shape[1]} 止 {close.index.max().date()} 费率 {fee_rules_text()}")
    print(f"一轮含滑点 {COST_ROUND_TRIP:.6f} 仅税费 {FEE_ROUND_TRIP:.6f}")

    mom20 = close / close.shift(20) - 1.0
    mom5 = close / close.shift(5) - 1.0
    mom3 = close / close.shift(3) - 1.0
    near20 = close / high.rolling(20, min_periods=20).max().replace(0.0, np.nan)
    near10 = close / high.rolling(10, min_periods=10).max().replace(0.0, np.nan)
    near5 = close / high.rolling(5, min_periods=5).max().replace(0.0, np.nan)
    trend60 = close / close.rolling(60, min_periods=60).mean().replace(0.0, np.nan) - 1.0
    persist20 = (close.diff() > 0).astype(float).rolling(20, min_periods=20).mean()
    f10_comp = (
        near20.rank(axis=1, pct=True)
        + trend60.rank(axis=1, pct=True)
        + mom20.rank(axis=1, pct=True)
    ) / 3.0

    specs = [
        ("s10_default_20_20_k5", make_snaps(mom20, near20, stage1_k=20, stage2_k=5), "策略10默认 因子11 20日动量Top20→20日近高Top5"),
        ("s10_opt_5_10_k5", make_snaps(mom5, near10, stage1_k=20, stage2_k=5), "策略10上轮候选 5/10/k5"),
        ("s10_wf_3_5_k3", make_snaps(mom3, near5, stage1_k=20, stage2_k=3), "策略10 walk-forward冻结 3/5/k3"),
        ("f10_composite_k5", make_snaps(f10_comp, None, stage1_k=5, stage2_k=5), "因子10 综合分(近高+趋势+动量)周频Top5"),
        ("f10_near_high_k5", make_snaps(near20, None, stage1_k=5, stage2_k=5), "因子10 近20日高点周频Top5"),
        ("f10_mom_k5", make_snaps(mom20, None, stage1_k=5, stage2_k=5), "因子10 20日动量周频Top5"),
        ("f10_persist_k5", make_snaps(persist20, None, stage1_k=5, stage2_k=5), "因子10 上涨日占比周频Top5"),
        ("univ_ew", None, "宇宙等权"),
    ]

    rows = []
    dailies: dict[str, pd.Series] = {}
    for name, snap, logic in specs:
        if snap is None:
            d = close.pct_change().mean(axis=1)
            wt = float("nan")
        else:
            d = daily_from_snaps(close, snap)
            wt = week_turn(snap)
        dailies[name] = d
        row = pack(name, logic, d, wt)
        row["logic"] = logic
        rows.append(row)
        print(name, "费用后IS夏普", round(row["n_is_sharpe"], 3), "2024-25", round(row["n_oos_sharpe"], 3), "2026", round(row["n_val_sharpe"], 3))

    combo = pd.DataFrame(rows)
    combo.to_csv(OUT / "summary.csv", index=False)

    yearly_parts = []
    for name in ("s10_default_20_20_k5", "s10_opt_5_10_k5", "s10_wf_3_5_k3", "f10_composite_k5", "univ_ew"):
        y = yearly_of(nav_from_daily(dailies[name]), range(2020, 2027))
        y["id"] = name
        yearly_parts.append(y)
    yearly = pd.concat(yearly_parts, ignore_index=True)
    yearly.to_csv(OUT / "yearly.csv", index=False)

    cost_rows = []
    for name in ("s10_default_20_20_k5", "s10_opt_5_10_k5", "f10_composite_k5"):
        d = dailies[name]
        wt = float(combo.loc[combo["id"] == name, "week_turn"].iloc[0])
        for label, rt in [("gross", 0.0), ("new_fee_slip", COST_ROUND_TRIP), ("new_fee_only", FEE_ROUND_TRIP)]:
            dd = apply_cost(d, wt, rt) if rt else d
            m = metrics_of(dd)
            cost_rows.append({"id": name, "cost": label, **{k: m[k] for k in m if not k.endswith(("start", "end"))}})
    cost_df = pd.DataFrame(cost_rows)
    cost_df.to_csv(OUT / "cost_sweep.csv", index=False)

    manifest = {
        "fee": fee_rules_text(),
        "cost_round_trip": COST_ROUND_TRIP,
        "fee_round_trip": FEE_ROUND_TRIP,
        "universe": "HS300+ZZ500+ZZ1000 current constituents",
        "n_names": int(close.shape[1]),
        "start": IS_START,
        "end": val_end,
        "note": "策略10默认仍是20/20/k5；因子10做等权持有对照，不是策略1开盘突破",
        "do_not_replace_default": True,
        "s10_default": DEFAULT_PARAMS,
        "s10_optimized_candidate": OPTIMIZED_PARAMS,
    }
    (OUT / "00_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    cols = [
        "id",
        "logic",
        "week_turn",
        "n_is_ret",
        "n_is_sharpe",
        "n_oos_ret",
        "n_oos_sharpe",
        "nw_oos_t",
        "n_val_ret",
        "n_val_sharpe",
        "nw_val_t",
    ]
    report = f"""# 新费率重跑：策略10 与 因子10

研究回测，不构成投资建议。默认未改。

## 契约

- 费率：{fee_rules_text()}
- 一轮含滑点 {COST_ROUND_TRIP:.6f}；仅税费 {FEE_ROUND_TRIP:.6f}
- 宇宙：沪深300+中证500+中证1000 当前成分 {close.shape[1]} 只；收盘对收盘等权
- 区间：{IS_START}～{val_end}；IS 2020–2023；回测 2024–2025；验证 2026～{val_end}
- **策略10 绑定因子11**（两段近高），不是因子10
- **因子10** 本表是周频价格分数 Top5 等权持有，不是策略1 开盘突破

## 费用后对照

{_md(combo, cols)}

## 分年毛收益

{_md(yearly, ["id", "year", "ret_pct"])}

## 决策

费用更新后纸面数字会变，**不替换策略10 默认 20/20/k5，也不把因子10 写成策略10**。Newey-West t 仍是约束：2024–2025 / 2026 区间含 0 则未验证。

本报告仅供研究参考，不构成任何投资建议。
"""
    (OUT / "report.md").write_text(report, encoding="utf-8")
    print("wrote", OUT)
    print(combo[["id", "n_is_sharpe", "n_oos_sharpe", "n_val_sharpe", "nw_oos_t", "nw_val_t"]].to_string(index=False))


if __name__ == "__main__":
    main()
