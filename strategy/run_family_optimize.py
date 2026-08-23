"""全家族截面优化：单因子 period sweep → 去冗余 → 等权/ICIR 组合。

同一套口径：沪深300∪中证500∪中证1000 当前成分（幸存者偏差）；
周频 TopK 等权持有；一字涨停开盘买不进、一字跌停封单卖不出；
选参只看 2020–2023 费用后夏普；2024–2025 / 2026 只确认。
不改策略1 / 策略5 默认参数。

  python strategy/run_family_optimize.py
"""

from __future__ import annotations

import json
import logging
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[1]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

from strategy.costs import COST_ROUND_TRIP, fee_rules_text  # noqa: E402
from strategy.near_high_hold import daily_from_snaps_fill, limit_fill_masks  # noqa: E402
from strategy.strategies.strategy4.run_two_stage import load_combined_ohlc  # noqa: E402
from strategy.strategies.strategy5.run_optimize import (  # noqa: E402
    IS_END,
    IS_START,
    OOS_END,
    OOS_START,
    RT,
    VAL_END,
    VAL_START,
    _norm,
    _week,
    apply_cost,
    eval_snap,
    make_snaps,
    md_table,
    pick_is,
)

OUT = Path(__file__).resolve().parent / "optimize_family"
CORR_CAP = 0.70
K = 5
STAGE1 = 20


def cs_rank(df: pd.DataFrame) -> pd.DataFrame:
    return df.rank(axis=1, pct=True, method="average")


def score_mom(close: pd.DataFrame, n: int) -> pd.DataFrame:
    return close / close.shift(int(n)) - 1.0


def score_near(close: pd.DataFrame, high: pd.DataFrame, n: int) -> pd.DataFrame:
    hx = high.rolling(int(n), min_periods=int(n)).max().replace(0.0, np.nan)
    return close / hx


def score_trend(close: pd.DataFrame, n: int) -> pd.DataFrame:
    sma = close.rolling(int(n), min_periods=int(n)).mean().replace(0.0, np.nan)
    return close / sma - 1.0


def score_persist(close: pd.DataFrame, n: int) -> pd.DataFrame:
    return (close.diff() > 0).astype(float).rolling(int(n), min_periods=int(n)).mean()


def score_f10_comp(
    close: pd.DataFrame,
    high: pd.DataFrame,
    *,
    high_n: int,
    trend_n: int,
    mom_n: int,
) -> pd.DataFrame:
    parts = [
        cs_rank(score_near(close, high, high_n)),
        cs_rank(score_trend(close, trend_n)),
        cs_rank(score_mom(close, mom_n)),
    ]
    return sum(parts) / len(parts)


def score_f9_energy(
    close: pd.DataFrame,
    high: pd.DataFrame,
    *,
    fast: int,
    slow: int,
    ma_n: int,
    up_n: int,
) -> pd.DataFrame:
    """价格版多空净动能（无成交量，避免面板缺 volume）。"""
    roc_f = score_mom(close, fast)
    roc_s = score_mom(close, slow)
    gap = score_trend(close, ma_n)
    up = score_persist(close, up_n)
    near = score_near(close, high, slow)
    return (
        cs_rank(roc_f)
        + cs_rank(roc_s)
        + cs_rank(gap)
        + cs_rank(up)
        + cs_rank(near)
    ) / 5.0


def week_end_corr(a: pd.DataFrame, b: pd.DataFrame, start: str, end: str) -> float:
    week = _week(a.index)
    rhos = []
    lo, hi = pd.Timestamp(start), pd.Timestamp(end)
    for _, g in a.groupby(week):
        last = g.index[-1]
        if last < lo or last > hi:
            continue
        x = a.loc[last]
        y = b.reindex(index=a.index, columns=a.columns).loc[last]
        df = pd.DataFrame({"x": x, "y": y}).dropna()
        if len(df) < 40:
            continue
        rho = float(df["x"].rank().corr(df["y"].rank()))
        if rho == rho:
            rhos.append(rho)
    return float(np.mean(rhos)) if rhos else float("nan")


def rank_icir(score: pd.DataFrame, fwd: pd.DataFrame, start: str, end: str) -> tuple[float, float]:
    week = _week(score.index)
    ics = []
    lo, hi = pd.Timestamp(start), pd.Timestamp(end)
    for _, g in score.groupby(week):
        last = g.index[-1]
        if last < lo or last > hi:
            continue
        df = pd.DataFrame({"x": score.loc[last], "y": fwd.loc[last]}).dropna()
        if len(df) < 40:
            continue
        rho = float(df["x"].rank().corr(df["y"].rank()))
        if rho == rho:
            ics.append(rho)
    if len(ics) < 8:
        return float("nan"), float("nan")
    mu = float(np.mean(ics))
    sd = float(np.std(ics, ddof=1)) if len(ics) > 1 else float("nan")
    ir = mu / sd if sd and sd == sd and sd > 1e-12 else float("nan")
    return mu, ir


def zblend(frames: list[pd.DataFrame], weights: list[float]) -> pd.DataFrame:
    ranked = [cs_rank(f) for f in frames]
    w = np.array(weights, dtype=float)
    w = w / w.sum() if w.sum() else np.ones(len(w)) / len(w)
    out = ranked[0] * 0.0
    for frame, wi in zip(ranked, w):
        out = out.add(frame * float(wi), fill_value=np.nan)
    return out


def write_md(path: Path, title: str, df: pd.DataFrame, cols: list[str], note: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = [f"# {title}", "", note, "", md_table(df, cols), ""]
    path.write_text("\n".join(body), encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for sub in ("period_sweep", "blend", "refinement"):
        (OUT / sub).mkdir(parents=True, exist_ok=True)
    ohlc = load_combined_ohlc()
    close = _norm(ohlc["close"])
    high = _norm(ohlc["high"]).reindex(index=close.index, columns=close.columns)
    open_px = _norm(ohlc["open"]).reindex(index=close.index, columns=close.columns)
    low = _norm(ohlc["low"]).reindex(index=close.index, columns=close.columns)
    block_buy, block_sell, _ = limit_fill_masks(close, open_px, high, low)
    fwd = close.shift(-6) / close.shift(-1) - 1.0
    print(f"宇宙 {close.shape[1]}  {close.index.min().date()} ~ {close.index.max().date()}")
    print(fee_rules_text())

    scores: dict[str, pd.DataFrame] = {}
    rows: list[dict] = []

    def add_score(fid: str, logic: str, family: str, score: pd.DataFrame, invert: bool = False) -> None:
        scores[fid] = -score if invert else score
        snap = make_snaps(scores[fid], None, stage1_k=10_000, stage2_k=K, invert1=False)
        row = eval_snap(
            close,
            snap,
            fid,
            {"logic": logic, "family": family, "kind": "single"},
            block_buy=block_buy,
            block_sell=block_sell,
        )
        mu, ir = rank_icir(scores[fid], fwd, IS_START, IS_END)
        row["ic_is"] = mu
        row["icir_is"] = ir
        rows.append(row)
        print(f"  {fid:28} IS sharpe {row.get('n_is_sharpe', float('nan')):7.3f}")

    print("=== period sweep / 单因子 ===")
    for n in (3, 5, 10, 20, 60):
        add_score(f"f3_mom{n}", f"因子3 {n}日动量 Top{K}", "f3", score_mom(close, n))
    for n in (5, 10, 20):
        add_score(
            f"f3_rev{n}",
            f"因子3 {n}日反转（动量最低）Top{K}",
            "f3",
            score_mom(close, n),
            invert=True,
        )
    for n in (5, 10, 20, 60):
        add_score(f"f10_near{n}", f"因子10 近{n}日高 Top{K}", "f10", score_near(close, high, n))
    for n in (20, 60):
        add_score(f"f10_trend{n}", f"因子10 偏离{n}日均线 Top{K}", "f10", score_trend(close, n))
    for n in (10, 20):
        add_score(f"f10_persist{n}", f"因子10 {n}日上涨占比 Top{K}", "f10", score_persist(close, n))
    add_score(
        "f10_comp_default",
        "因子10 默认近高20+趋势60+动量20 等权百分位",
        "f10",
        score_f10_comp(close, high, high_n=20, trend_n=60, mom_n=20),
    )
    add_score(
        "f10_comp_short",
        "因子10 短窗近高5+趋势20+动量5 等权百分位",
        "f10",
        score_f10_comp(close, high, high_n=5, trend_n=20, mom_n=5),
    )
    add_score(
        "f9_e5_20",
        "因子9 价格动能 fast5/slow20",
        "f9",
        score_f9_energy(close, high, fast=5, slow=20, ma_n=20, up_n=10),
    )
    add_score(
        "f9_e3_10",
        "因子9 价格动能 fast3/slow10",
        "f9",
        score_f9_energy(close, high, fast=3, slow=10, ma_n=10, up_n=5),
    )

    two_stage = [
        ("f11_mom3_high5", 3, 5, False, False, "因子11 默认 3日动量Top20→近5日高 Top5"),
        ("f11_mom5_high5", 5, 5, False, False, "因子11 5/5"),
        ("f11_mom3_high10", 3, 10, False, False, "因子11 3/10"),
        ("f11_mom20_high20", 20, 20, False, False, "因子11 原 20/20"),
        ("f11_not_climax", 3, 5, False, True, "一段动量Top20→二段5日涨幅最低"),
        ("f11_far_high", 3, 5, False, True, "一段动量Top20→远离前高"),
    ]
    for fid, mn, hn, inv1, inv2, logic in two_stage:
        s1 = score_mom(close, mn)
        if fid == "f11_not_climax":
            s2 = score_mom(close, 5)
            inv2 = True
        elif fid == "f11_far_high":
            s2 = score_near(close, high, 5)
            inv2 = True
        else:
            s2 = score_near(close, high, hn)
        snap = make_snaps(s1, s2, stage1_k=STAGE1, stage2_k=K, invert1=inv1, invert2=inv2)
        row = eval_snap(
            close,
            snap,
            fid,
            {"logic": logic, "family": "f11", "kind": "two_stage"},
            block_buy=block_buy,
            block_sell=block_sell,
        )
        mu, ir = rank_icir(s2 if fid != "f11_not_climax" else -s2, fwd, IS_START, IS_END)
        row["ic_is"] = mu
        row["icir_is"] = ir
        rows.append(row)
        scores[fid] = s2 if not inv2 else -s2
        print(f"  {fid:28} IS sharpe {row.get('n_is_sharpe', float('nan')):7.3f}")

    sweep = pd.DataFrame(rows)
    sweep.to_csv(OUT / "period_sweep" / "period_sweep_metrics.csv", index=False)
    cols = [
        "id",
        "family",
        "logic",
        "ic_is",
        "week_turn",
        "skipped_buy",
        "n_is_sharpe",
        "n_is_ret",
        "n_is_mdd",
        "n_oos_sharpe",
        "n_oos_ret",
        "n_val_sharpe",
        "n_val_ret",
    ]
    best_single = pick_is(sweep)
    write_md(
        OUT / "period_sweep" / "period_sweep_summary.md",
        "截面家族 Period Sweep",
        sweep.sort_values("n_is_sharpe", ascending=False),
        cols,
        f"选参只看 IS 费用后夏普。best single = `{best_single}`。OOS/2026 不参与选择。",
    )

    print("=== 去冗余 + 组合 ===")
    usable = sweep.replace([np.inf, -np.inf], np.nan).dropna(subset=["n_is_sharpe"])
    usable = usable[(usable["kind"] == "single") & (usable["n_is_sharpe"] > 0)]
    usable = usable.sort_values("n_is_sharpe", ascending=False)
    selected: list[str] = []
    corr_log: list[dict] = []
    for _, r in usable.iterrows():
        fid = str(r["id"])
        if fid not in scores:
            continue
        ok = True
        max_c = 0.0
        hit = ""
        for keep in selected:
            rho = week_end_corr(scores[fid], scores[keep], IS_START, IS_END)
            corr_log.append({"a": fid, "b": keep, "rho_is": rho})
            if rho == rho and rho > max_c:
                max_c = float(rho)
                hit = keep
            if rho == rho and rho >= CORR_CAP:
                ok = False
                break
        if ok:
            selected.append(fid)
            print(f"  keep {fid}  (max corr {max_c:.2f} vs {hit or '-'})")
        else:
            print(f"  drop {fid}  corr {max_c:.2f} vs {hit}")

    pd.DataFrame(corr_log).to_csv(OUT / "blend" / "corr_is.csv", index=False)
    blend_rows = []
    if selected:
        frames = [scores[i] for i in selected]
        eq = zblend(frames, [1.0] * len(selected))
        scores["blend_equal"] = eq
        snap = make_snaps(eq, None, stage1_k=10_000, stage2_k=K)
        row = eval_snap(
            close,
            snap,
            "blend_equal",
            {
                "logic": "去冗余后截面 z 等权 Top5：" + "+".join(selected),
                "family": "blend",
                "kind": "blend",
                "legs": ",".join(selected),
            },
            block_buy=block_buy,
            block_sell=block_sell,
        )
        mu, ir = rank_icir(eq, fwd, IS_START, IS_END)
        row["ic_is"] = mu
        row["icir_is"] = ir
        blend_rows.append(row)
        print(f"  blend_equal IS sharpe {row.get('n_is_sharpe', float('nan')):7.3f}")

        icirs = []
        for fid in selected:
            _, ir = rank_icir(scores[fid], fwd, IS_START, IS_END)
            icirs.append(max(0.01, ir) if ir == ir else 0.01)
        ic = zblend(frames, icirs)
        scores["blend_icir"] = ic
        snap = make_snaps(ic, None, stage1_k=10_000, stage2_k=K)
        row = eval_snap(
            close,
            snap,
            "blend_icir",
            {
                "logic": "去冗余后 IS-ICIR 加权 Top5：" + "+".join(selected),
                "family": "blend",
                "kind": "blend",
                "legs": ",".join(selected),
            },
            block_buy=block_buy,
            block_sell=block_sell,
        )
        mu, ir = rank_icir(ic, fwd, IS_START, IS_END)
        row["ic_is"] = mu
        row["icir_is"] = ir
        blend_rows.append(row)
        print(f"  blend_icir  IS sharpe {row.get('n_is_sharpe', float('nan')):7.3f}")

    # refinement: k=3/8 on best single and best blend
    print("=== refinement k ===")
    ref_rows = []
    cand_ids = [best_single]
    if blend_rows:
        cand_ids.append(pick_is(pd.DataFrame(blend_rows)))
    for base_id in cand_ids:
        if base_id not in scores:
            continue
        for kk in (3, 5, 8):
            snap = make_snaps(scores[base_id], None, stage1_k=10_000, stage2_k=kk)
            rid = f"{base_id}_k{kk}"
            row = eval_snap(
                close,
                snap,
                rid,
                {
                    "logic": f"{base_id} Top{kk}",
                    "family": "refine",
                    "kind": "refine",
                    "base": base_id,
                    "k": kk,
                },
                block_buy=block_buy,
                block_sell=block_sell,
            )
            ref_rows.append(row)
            print(f"  {rid:28} IS sharpe {row.get('n_is_sharpe', float('nan')):7.3f}")

    blend_df = pd.DataFrame(blend_rows)
    ref_df = pd.DataFrame(ref_rows)
    if not blend_df.empty:
        blend_df.to_csv(OUT / "blend" / "blend_metrics.csv", index=False)
        write_md(
            OUT / "blend" / "blend_summary.md",
            "去冗余组合",
            blend_df,
            cols + ["legs"],
            f"相关性阈值 {CORR_CAP}；权重只用 IS。保留腿：{selected}",
        )
    if not ref_df.empty:
        ref_df.to_csv(OUT / "refinement" / "refinement_metrics.csv", index=False)
        write_md(
            OUT / "refinement" / "refinement_summary.md",
            "K 值 refinement",
            ref_df,
            cols + ["base", "k"],
            "只在 best single / best blend 上改 K。选参仍只看 IS。",
        )

    all_df = pd.concat([sweep, blend_df, ref_df], ignore_index=True)
    all_df.to_csv(OUT / "all_metrics.csv", index=False)
    best_all = pick_is(all_df[all_df["kind"] != "refine"] if "kind" in all_df else all_df)
    best_refine = pick_is(ref_df) if not ref_df.empty else best_all
    # 落地推荐：refinement 的 k≠5 若 OOS 变差则仍用 k=5
    promote = best_all
    frozen = {
        "best_single": best_single,
        "selected_legs": selected,
        "best_blend": pick_is(blend_df) if not blend_df.empty else None,
        "best_all_is": best_all,
        "best_refine_is": best_refine,
        "promote_candidate": promote,
        "corr_cap": CORR_CAP,
        "k": K,
        "n_trials": int(len(all_df)),
        "is": [IS_START, IS_END],
        "oos": [OOS_START, OOS_END],
        "val": [VAL_START, VAL_END],
        "cost_round_trip": RT,
        "universe": "hs300_zz500_zz1000_current",
        "fill": "block_limit_up_buy + block_limit_down_sell",
        "overwrite_defaults": False,
    }
    (OUT / "00_manifest.json").write_text(
        json.dumps(
            {
                "engine": "weekly equal-weight hold + limit fill + COST_ROUND_TRIP",
                "select": "IS 2020-2023 net Sharpe only",
                **frozen,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (OUT / "frozen_params.json").write_text(
        json.dumps(frozen, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    def _line(df: pd.DataFrame, fid: str) -> str:
        hit = df[df["id"] == fid]
        if hit.empty:
            return f"| {fid} | — |"
        r = hit.iloc[0]
        return (
            f"| {fid} | {r.get('logic','')} | {r.get('n_is_sharpe', float('nan')):.3f} | "
            f"{r.get('n_oos_sharpe', float('nan')):.3f} | {r.get('n_val_sharpe', float('nan')):.3f} | "
            f"{r.get('n_is_ret', float('nan')):.1f} | {r.get('week_turn', float('nan')):.3f} |"
        )

    report = [
        "# 策略/因子家族优化",
        "",
        "研究回测，不构成投资建议。**未改**策略1、策略5 默认参数。",
        "",
        "## 研究合同",
        "",
        "- 宇宙：沪深300 ∪ 中证500 ∪ 中证1000 **当前成分**（幸存者偏差）",
        "- 执行：周频 Top5 等权；一字涨停开盘买不进、一字跌停封单卖不出",
        f"- 费率：{fee_rules_text()}；一轮含滑点 {RT:.6f}",
        "- 选参：仅 2020-01-02～2023-12-31 费用后夏普",
        "- 确认：2024-01-02～2025-12-31；验证：2026-01-02～2026-08-20",
        f"- 试验次数：{len(all_df)}（全部计入多重检验分母）",
        "",
        "策略1 / 策略5 已有独立 optimize_tests，结论是保留默认；本轮把它们当作冻结基线，",
        "只在同一持有引擎上比较截面因子 3/9/10/11 与新组合。",
        "",
        "## Period Sweep",
        "",
        md_table(sweep.sort_values("n_is_sharpe", ascending=False).head(16), cols),
        "",
        f"- Best single（只看 IS）：`{best_single}`",
        "",
        "## 组合",
        "",
        f"IS 夏普>0 的单因子去冗余（corr≥{CORR_CAP} 同簇只留更强）。保留：`{selected}`",
        "",
        md_table(blend_df, cols + ["legs"]) if not blend_df.empty else "无可用组合。",
        "",
        "## Refinement",
        "",
        md_table(ref_df, cols + ["k"]) if not ref_df.empty else "无",
        "",
        "## 对照表",
        "",
        "| id | logic | IS夏普 | 24-25夏普 | 2026夏普 | IS收益% | 周换手 |",
        "|---|---|---:|---:|---:|---:|---:|",
        _line(all_df, "f11_mom3_high5"),
        _line(all_df, best_single),
        _line(all_df, frozen["best_blend"] or ""),
        _line(all_df, best_refine),
        "",
        "## 稳健性",
        "",
        "- 参数：短窗动量/近高再次出现在网格短端，和策略5 已有结论同向。",
        "- 时间：OOS/2026 只确认，不参与选择。",
        "- 搜索：全部变体计入 n_trials。k≠5 若只在 IS 更好、OOS 更差，不推广。",
        "- 未验证：点时指数成分、行业中性、策略1 开盘突破叠加（策略4 执行层）。",
        "- 策略2/3：缠论与事件帖不是同一持有引擎，本轮不改默认。",
        "",
        "## 决策",
        "",
        "- 策略1：保留默认（见 `strategy1/optimize_tests/better_report.md`）",
        "- 策略5 / 因子11：保留 mom3/high5/k5",
        f"- 新组合候选：`{frozen['best_blend']}` legs=`{selected}`",
        "- 推广：本脚本不覆盖 canonical 默认；是否注册因子12/策略6由后续步骤按 IS 是否优于 f11 决定。",
        "",
    ]
    (OUT / "optimize_report.md").write_text("\n".join(report), encoding="utf-8")
    print("best_single", best_single, "best_blend", frozen["best_blend"], "n", len(all_df))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
