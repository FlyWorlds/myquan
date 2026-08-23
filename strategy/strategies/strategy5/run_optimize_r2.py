"""因子11 第 2 轮优化：短窗端点以下 + skip1 动量。

上一轮成交约束下 best 落在 mom3/high5（网格最短端点）。本轮只向更短窗扩，
并试「跳过当日」动量。选参仍只看 2020–2023 费用后夏普。不改 DEFAULT_PARAMS。

  python strategy/strategies/strategy5/run_optimize_r2.py
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

from strategy.costs import fee_rules_text  # noqa: E402
from strategy.near_high_hold import limit_fill_masks  # noqa: E402
from strategy.strategies.strategy5.run_optimize import (  # noqa: E402
    IS_END,
    IS_START,
    OOS_END,
    OOS_START,
    VAL_END,
    VAL_START,
    _norm,
    cond_ic,
    eval_snap,
    make_snaps,
    md_table,
    pick_is,
)
from strategy.strategies.strategy4.run_two_stage import load_combined_ohlc  # noqa: E402

OUT = Path(__file__).resolve().parent / "optimize_tests" / "round2"
COLS = [
    "id",
    "logic",
    "cond_ic_is",
    "week_turn",
    "skipped_buy",
    "n_is_ret",
    "n_is_sharpe",
    "n_is_mdd",
    "n_oos_ret",
    "n_oos_sharpe",
    "n_val_ret",
    "n_val_sharpe",
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "period_sweep").mkdir(exist_ok=True)
    (OUT / "ablation").mkdir(exist_ok=True)
    (OUT / "refinement").mkdir(exist_ok=True)

    ohlc = load_combined_ohlc()
    close = _norm(ohlc["close"])
    high = _norm(ohlc["high"]).reindex(index=close.index, columns=close.columns)
    open_px = _norm(ohlc["open"]).reindex(index=close.index, columns=close.columns)
    low = _norm(ohlc["low"]).reindex(index=close.index, columns=close.columns)
    print(f"宇宙 {close.shape[1]} 止 {close.index.max().date()} {fee_rules_text()}")
    print("第2轮：短于 mom3/high5；一字涨停买不进、封跌停卖不出")
    block_buy, block_sell, close_lu = limit_fill_masks(close, open_px, high, low)

    persist = (close.diff() > 0).astype(float).rolling(20, min_periods=20).mean()
    roc5 = close / close.shift(5) - 1.0
    fwd = close.shift(-6) / close.shift(-1) - 1.0
    mom_ns = (1, 2, 3, 4, 5)
    high_ns = (1, 2, 3, 4, 5, 6, 8)
    cache_mom = {n: close / close.shift(n) - 1.0 for n in mom_ns}
    cache_skip = {n: close.shift(1) / close.shift(n + 1) - 1.0 for n in mom_ns}
    cache_near = {
        n: close / high.rolling(n, min_periods=n).max().replace(0.0, np.nan) for n in high_ns
    }

    def ev(snap, name, extra):
        return eval_snap(close, snap, name, extra, block_buy=block_buy, block_sell=block_sell)

    seen: set[str] = set()
    sweep_rows: list[dict] = []

    def add_period(vid: str, mom_df, near_df, mom_n: int, high_n: int, logic: str, skip: bool):
        if vid in seen:
            return
        snap = make_snaps(mom_df, near_df, stage1_k=20, stage2_k=5)
        ic = cond_ic(mom_df, near_df, fwd, 20, IS_START, IS_END)
        row = ev(
            snap,
            vid,
            {
                "phase": "period",
                "mom_n": mom_n,
                "high_n": high_n,
                "skip1": skip,
                "logic": logic,
                "cond_ic_is": ic,
            },
        )
        sweep_rows.append(row)
        seen.add(vid)
        print(vid, "IS净夏普", round(row["n_is_sharpe"], 3), "买不进", row["skipped_buy"])

    for mom_n in mom_ns:
        add_period(
            f"mom{mom_n}_high5_k5",
            cache_mom[mom_n],
            cache_near[5],
            mom_n,
            5,
            f"动量{mom_n}日 Top20→近高5日 Top5",
            False,
        )
    for mom_n in (1, 2, 3, 4):
        add_period(
            f"mom{mom_n}_skip1_high5_k5",
            cache_skip[mom_n],
            cache_near[5],
            mom_n,
            5,
            f"跳过当日的{mom_n}日动量 Top20→近高5",
            True,
        )

    mom_plain = pd.DataFrame([r for r in sweep_rows if not r.get("skip1")])
    best_mom_n = int(mom_plain.loc[mom_plain["id"] == pick_is(mom_plain), "mom_n"].iloc[0])
    print("best mom_n (IS, high=5, 无skip)", best_mom_n)

    for high_n in high_ns:
        add_period(
            f"mom{best_mom_n}_high{high_n}_k5",
            cache_mom[best_mom_n],
            cache_near[high_n],
            best_mom_n,
            high_n,
            f"动量{best_mom_n} Top20→近高{high_n} Top5",
            False,
        )

    sweep_so_far = pd.DataFrame(sweep_rows)
    best0 = sweep_so_far.loc[sweep_so_far["id"] == pick_is(sweep_so_far)].iloc[0]
    bm, bh = int(best0["mom_n"]), int(best0["high_n"])
    use_skip = bool(best0.get("skip1"))
    mom_grid = [n for n in mom_ns if abs(n - bm) <= 1]
    high_grid = [n for n in high_ns if abs(n - bh) <= 1]
    for mom_n in mom_grid:
        for high_n in high_grid:
            add_period(
                f"mom{mom_n}_high{high_n}_k5",
                cache_mom[mom_n],
                cache_near[high_n],
                mom_n,
                high_n,
                f"邻域 动量{mom_n}→近高{high_n}",
                False,
            )

    sweep = pd.DataFrame(sweep_rows).drop_duplicates("id")
    best_period_id = pick_is(sweep)
    best_period = sweep.loc[sweep["id"] == best_period_id].iloc[0]
    best_mom_n = int(best_period["mom_n"])
    best_high_n = int(best_period["high_n"])
    use_skip = bool(best_period.get("skip1"))
    sweep.to_csv(OUT / "period_sweep" / "period_sweep_metrics.csv", index=False)
    (OUT / "period_sweep" / "period_sweep_summary.md").write_text(
        f"第2轮选参只看 2020–2023 费用后夏普。best={best_period_id} "
        f"(mom_n={best_mom_n}, high_n={best_high_n}, skip1={use_skip})。\n"
        f"对照现行默认 mom3_high5_k5。\n",
        encoding="utf-8",
    )
    print("BEST PERIOD", best_period_id)

    mom = cache_skip[best_mom_n] if use_skip else cache_mom[best_mom_n]
    near = cache_near[best_high_n]

    ablations = [
        ("orig_two_stage", make_snaps(mom, near, stage1_k=20, stage2_k=5), "保留两段", "core"),
        (
            "drop_stage1_near_only",
            make_snaps(near, None, stage1_k=5, stage2_k=5, use_s1=True),
            "去掉动量门，全宇宙近高Top5",
            "harmful_test",
        ),
        (
            "invert_stage2_far",
            make_snaps(mom, near, stage1_k=20, stage2_k=5, invert2=True),
            "动量Top20→远离前高",
            "harmful_test",
        ),
        (
            "invert_stage1_lowmom",
            make_snaps(mom, near, stage1_k=20, stage2_k=5, invert1=True),
            "动量最弱20→近高Top5",
            "harmful_test",
        ),
        ("mom_only_top5", make_snaps(mom, None, stage1_k=5, stage2_k=5), "只有动量Top5", "harmful_test"),
        (
            "mom_top20_ew",
            make_snaps(mom, None, stage1_k=20, stage2_k=20),
            "动量Top20等权",
            "harmful_test",
        ),
        (
            "stage2_persist",
            make_snaps(mom, persist, stage1_k=20, stage2_k=5),
            "二段改上涨日占比",
            "helpful_test",
        ),
        (
            "stage2_not_climax",
            make_snaps(mom, -roc5, stage1_k=20, stage2_k=5),
            "二段改未拉直",
            "helpful_test",
        ),
    ]
    abl_rows = []
    for name, snap, logic, tag in ablations:
        row = ev(
            snap,
            name,
            {
                "phase": "ablation",
                "mom_n": best_mom_n,
                "high_n": best_high_n,
                "logic": logic,
                "tag": tag,
            },
        )
        abl_rows.append(row)
        print(name, "IS净夏普", round(row["n_is_sharpe"], 3), "OOS净", round(row["n_oos_sharpe"], 3))
    abl = pd.DataFrame(abl_rows)
    abl.to_csv(OUT / "ablation" / "ablation_metrics.csv", index=False)
    core_id = pick_is(abl)
    (OUT / "ablation" / "ablation_summary.md").write_text(
        f"固定 {best_period_id}。IS core={core_id}。\n", encoding="utf-8"
    )

    core_s1, core_s2 = mom, near
    core_invert2 = False
    if core_id == "invert_stage2_far":
        core_invert2 = True
    elif core_id == "stage2_persist":
        core_s2 = persist
    elif core_id == "stage2_not_climax":
        core_s2 = -roc5
    elif core_id == "drop_stage1_near_only":
        core_s1, core_s2 = near, None
    elif core_id == "mom_only_top5":
        core_s2 = None

    refinements: list[tuple[str, dict, str]] = []

    def add(name, snap, logic):
        refinements.append((name, snap, logic))

    add("core_k5_s20", make_snaps(core_s1, core_s2, stage1_k=20, stage2_k=5, invert2=core_invert2), "core k=5")
    for k in (2, 3, 4, 6, 7, 8):
        add(f"k{k}", make_snaps(core_s1, core_s2, stage1_k=20, stage2_k=k, invert2=core_invert2), f"收到 {k} 只")
    for s1 in (10, 15, 30):
        add(
            f"s1_{s1}",
            make_snaps(core_s1, core_s2, stage1_k=s1, stage2_k=5, invert2=core_invert2),
            f"一段 Top{s1}",
        )
    if not use_skip:
        add(
            "skip1_on_core",
            make_snaps(cache_skip[best_mom_n], core_s2, stage1_k=20, stage2_k=5),
            "core 上改跳过当日动量",
        )
    add(
        "exclude_lu_close",
        make_snaps(
            core_s1, core_s2, stage1_k=20, stage2_k=5, invert2=core_invert2, drop_lu=close_lu
        ),
        "排名日收盘涨停顺延",
    )
    add(
        "biweekly",
        make_snaps(
            core_s1, core_s2, stage1_k=20, stage2_k=5, invert2=core_invert2, every_n_weeks=2
        ),
        "两周调一次",
    )
    hyst_base = make_snaps(core_s1, core_s2, stage1_k=20, stage2_k=5, invert2=core_invert2)
    hyst: dict = {}
    prev_pick: set[str] = set()
    for w in sorted(hyst_base):
        fresh = hyst_base[w]
        keep = prev_pick & fresh
        extra = [x for x in fresh if x not in keep][: max(5 - len(keep), 0)]
        hyst[w] = set(list(keep) + extra) if extra or keep else fresh
        prev_pick = hyst[w]
    add("hysteresis", hyst, "仍进第二段则续持")

    ref_rows = []
    for name, snap, logic in refinements:
        row = ev(
            snap,
            name,
            {
                "phase": "refine",
                "mom_n": best_mom_n,
                "high_n": best_high_n,
                "logic": logic,
                "core": core_id,
            },
        )
        ref_rows.append(row)
        print(name, "IS净夏普", round(row["n_is_sharpe"], 3), "OOS净", round(row["n_oos_sharpe"], 3))
    ref = pd.DataFrame(ref_rows)
    ref.to_csv(OUT / "refinement" / "refinement_metrics.csv", index=False)
    best_final_id = pick_is(ref)
    best_final = ref.loc[ref["id"] == best_final_id].iloc[0]
    default_row = sweep.loc[sweep["id"] == "mom3_high5_k5"]
    def_is = float(default_row.iloc[0]["n_is_sharpe"]) if len(default_row) else float("nan")
    (OUT / "refinement" / "refinement_summary.md").write_text(
        f"core={core_id}。机械 IS best_final={best_final_id} "
        f"IS净夏普 {float(best_final['n_is_sharpe']):.3f}。现行默认 IS {def_is:.3f}。\n",
        encoding="utf-8",
    )

    manifest = {
        "round": 2,
        "factor": "factor11",
        "select_on": f"{IS_START}..{IS_END}",
        "confirm_on": f"{OOS_START}..{OOS_END}",
        "validate_on": f"{VAL_START}..{VAL_END}",
        "fill": "block_limit_up_buy + block_limit_down_sell",
        "do_not_replace_default": True,
        "baseline": "mom3_high5_k5",
        "best_period": best_period_id,
        "core": core_id,
        "best_final": best_final_id,
        "n_period": int(len(sweep)),
        "n_ablation": int(len(abl)),
        "n_refine": int(len(ref)),
    }
    (OUT / "00_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    report = f"""# 因子11 第2轮优化（短窗端点以下）

研究回测，不构成投资建议。`DEFAULT_PARAMS` 未改。

## 本轮目的

第1轮成交约束下 best 落在 **mom3/high5**（当时网格最短端点）。本轮只向更短窗扩：动量 1–5 日、近高 1–8 日，并试跳过当日动量。选参仍只看 {IS_START}～{IS_END} 费用后夏普。

成交：一字涨停开盘买不进、一字跌停封单卖不出。费率：{fee_rules_text()}。

## Period Sweep

{md_table(sweep, COLS + ["skip1"])}

- Best period：**{best_period_id}**
- 现行默认 mom3_high5_k5 IS净夏普 {def_is:.3f}

## Ablation（固定 best period）

{md_table(abl, COLS + ["tag"])}

- core：**{core_id}**

## Refinement

{md_table(ref, COLS)}

- 机械 best final：**{best_final_id}**（IS净夏普 {float(best_final['n_is_sharpe']):.3f}；2024–2025 {float(best_final['n_oos_sharpe']):.3f}；2026 {float(best_final['n_val_sharpe']):.3f}）

## 稳健性

- 若 best 仍在最短端点，说明 1 日动量/1 日近高未形成稳健更好区间。
- 跳过当日动量若不如含当日，则连板路径即使买不进，排名仍依赖当日涨幅。
- 时间：2024–2025 / 2026 不参与选择；确认段已窥探。
- 搜索：本轮 period {len(sweep)} + ablation {len(abl)} + refine {len(ref)}，叠加第1轮 29 次。
- 未验证：点时成分、开盘成交、行业中性。

## 最终决策

报告正文在对话里给出保留/候选结论。默认参数未改。

本报告仅供研究参考，不构成任何投资建议。
"""
    (OUT / "optimize_report.md").write_text(report, encoding="utf-8")
    print("CORE", core_id)
    print("BEST FINAL", best_final_id)


if __name__ == "__main__":
    main()
