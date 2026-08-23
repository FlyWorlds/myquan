"""因子11 walk-forward：2020–2023 选参 → 2024–2025 冻结回测 → 2026 验证。

选参只看样本内费用后夏普。2024–2025 与 2026 不参与选择。不改策略10 默认。

  python strategy/strategies/strategy5/run_walk_forward.py
"""

from __future__ import annotations

import json
import logging
import math
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[3]
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))
_OVERFIT = _MYQUAN / ".cursor" / "skills" / "backtest-overfit" / "scripts"
if str(_OVERFIT) not in sys.path:
    sys.path.insert(0, str(_OVERFIT))

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

from strategy.costs import COST_ROUND_TRIP, FEE_ROUND_TRIP  # noqa: E402
from overfit_report import build_report  # noqa: E402
from strategy.strategies.strategy5.run_optimize import (  # noqa: E402
    apply_cost,
    cond_ic,
    daily_from_snaps,
    make_snaps,
    pick_is,
    week_turn,
)
from strategy.strategies.strategy4.portfolio import window_metrics  # noqa: E402
from strategy.strategies.strategy4.run_two_stage import load_combined_panel  # noqa: E402

OUT = Path(__file__).resolve().parent / "walk_forward"
IS_START, IS_END = "2020-01-02", "2023-12-31"
OOS_START, OOS_END = "2024-01-02", "2025-12-31"
VAL_START, VAL_END = "2026-01-02", "2026-08-20"
S1_RT = COST_ROUND_TRIP
SHOT_RT = FEE_ROUND_TRIP


def _norm(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    idx = pd.to_datetime(out.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    out.index = pd.DatetimeIndex(idx).normalize()
    return out.sort_index()


def _week(idx: pd.DatetimeIndex) -> pd.Index:
    return idx - pd.to_timedelta(idx.dayofweek, unit="D")


def nav_from_daily(d: pd.Series) -> pd.Series:
    nav = (1.0 + d.fillna(0.0)).cumprod()
    if len(nav):
        nav.iloc[0] = 1.0
    return nav


def metrics_of(daily: pd.Series) -> dict:
    nav = nav_from_daily(daily)
    m_is = window_metrics(nav, start=IS_START, end=IS_END)
    m_oos = window_metrics(nav, start=OOS_START, end=OOS_END)
    m_val = window_metrics(nav, start=VAL_START, end=VAL_END)
    return {
        "is_ret": m_is["ret_pct"],
        "is_ann": m_is["ann_pct"],
        "is_sharpe": m_is["sharpe"],
        "is_mdd": m_is["mdd_pct"],
        "oos_ret": m_oos["ret_pct"],
        "oos_ann": m_oos["ann_pct"],
        "oos_sharpe": m_oos["sharpe"],
        "oos_mdd": m_oos["mdd_pct"],
        "val_ret": m_val["ret_pct"],
        "val_ann": m_val["ann_pct"],
        "val_sharpe": m_val["sharpe"],
        "val_mdd": m_val["mdd_pct"],
        "oos_start": m_oos.get("start"),
        "oos_end": m_oos.get("end"),
        "val_start": m_val.get("start"),
        "val_end": m_val.get("end"),
    }


def eval_snap(close: pd.DataFrame, snap: dict, name: str, extra: dict) -> dict:
    d = daily_from_snaps(close, snap)
    wt = week_turn(snap)
    dnet = apply_cost(d, wt, S1_RT)
    row = {"id": name, "week_turn": wt, **extra}
    g = metrics_of(d)
    n = metrics_of(dnet)
    for k, v in g.items():
        row[f"g_{k}"] = v
    for k, v in n.items():
        row[f"n_{k}"] = v
    return row, d


def slice_daily(d: pd.Series, start: str, end: str) -> pd.Series:
    return d[(d.index >= pd.Timestamp(start)) & (d.index <= pd.Timestamp(end))]


def nw_sharpe(r: pd.Series, lags: int = 5, periods: int = 252) -> dict:
    x = r.dropna().astype(float)
    if len(x) < 40:
        return {
            "n": int(len(x)),
            "sharpe": float("nan"),
            "t": float("nan"),
            "ci_lo": float("nan"),
            "ci_hi": float("nan"),
        }
    mu = float(x.mean())
    u = x - mu
    nw = float((u * u).mean())
    n = len(u)
    for lag in range(1, lags + 1):
        w = 1.0 - lag / (lags + 1.0)
        nw += 2.0 * w * float((u.iloc[lag:] * u.iloc[:-lag]).mean())
    se = math.sqrt(max(nw, 1e-18) / n)
    sig = float(x.std(ddof=1))
    sh = mu / sig * math.sqrt(periods) if sig else float("nan")
    t = mu / se if se else float("nan")
    return {
        "n": n,
        "sharpe": sh,
        "t": t,
        "ci_lo": (mu - 1.96 * se) / sig * math.sqrt(periods) if sig else float("nan"),
        "ci_hi": (mu + 1.96 * se) / sig * math.sqrt(periods) if sig else float("nan"),
    }


def _xs_corr(x: pd.DataFrame, y: pd.DataFrame) -> pd.Series:
    x = x.sub(x.mean(axis=1), axis=0)
    y = y.sub(y.mean(axis=1), axis=0)
    num = (x * y).sum(axis=1)
    den = np.sqrt((x**2).sum(axis=1) * (y**2).sum(axis=1))
    return num / den.replace(0, np.nan)


def both_ic(signal: pd.DataFrame, fwd: pd.DataFrame, ppy: float, min_n: int = 8) -> dict:
    nobs = signal.notna().sum(axis=1)
    ok = nobs >= min_n
    rank_ic = _xs_corr(signal.rank(axis=1), fwd.rank(axis=1)).where(ok)
    pear = _xs_corr(signal, fwd).where(ok)
    rstd, pstd = float(rank_ic.std()), float(pear.std())
    rmean, pmean = float(rank_ic.mean()), float(pear.mean())
    return {
        "n": int(rank_ic.dropna().shape[0]),
        "rank_ic": rmean,
        "rank_ic_ir": (rmean / rstd * math.sqrt(ppy)) if rstd else float("nan"),
        "pearson_ic": pmean,
        "ic_pos": float((rank_ic.dropna() > 0).mean()) if rank_ic.dropna().size else float("nan"),
    }


def monotonicity(signal: pd.DataFrame, fwd: pd.DataFrame, n_groups: int = 5):
    rank = signal.rank(axis=1, pct=True)
    grets = []
    for q in range(n_groups):
        lo, hi = q / n_groups, (q + 1) / n_groups
        grets.append(float(fwd.where((rank > lo) & (rank <= hi)).mean(axis=1).mean()))
    if np.any(np.isnan(grets)):
        return float("nan"), grets
    return float(np.corrcoef(np.arange(n_groups), grets)[0, 1]), grets


def cond_signal(mom: pd.DataFrame, near: pd.DataFrame, ends: pd.DatetimeIndex, stage1_k: int) -> pd.DataFrame:
    cond = near.reindex(ends).copy()
    me = mom.reindex(ends)
    for i, _ts in enumerate(ends):
        row = me.iloc[i].dropna()
        if row.empty:
            cond.iloc[i] = np.nan
            continue
        pool = set(row.nlargest(min(stage1_k, len(row))).index)
        cond.iloc[i, ~cond.columns.isin(pool)] = np.nan
    return cond


def yearly_of(nav: pd.Series, years: range) -> pd.DataFrame:
    rows = []
    for y in years:
        prev, this = nav[nav.index.year < y], nav[nav.index.year == y]
        if this.empty:
            continue
        start = float(prev.iloc[-1]) if len(prev) else float(this.iloc[0])
        rows.append(
            {
                "year": y,
                "ret_pct": (float(this.iloc[-1]) / start - 1.0) * 100.0,
                "start": str(this.index[0].date()),
                "end": str(this.index[-1].date()),
            }
        )
    return pd.DataFrame(rows)


def md_table(df: pd.DataFrame, cols: list[str]) -> str:
    use = df[[c for c in cols if c in df.columns]].copy()
    for c in use.columns:
        if use[c].dtype.kind == "f":
            use[c] = use[c].map(lambda x: f"{x:.3f}" if pd.notna(x) else "")
        else:
            use[c] = use[c].map(lambda x: "" if x is None or (isinstance(x, float) and pd.isna(x)) else str(x))
    header = "| " + " | ".join(use.columns) + " |"
    sep = "| " + " | ".join("---" for _ in use.columns) + " |"
    body = "\n".join("| " + " | ".join(row) + " |" for row in use.astype(str).values)
    return "\n".join([header, sep, body])


def primary_score(rank_ic_ir, sharpe, ann_ret, max_dd, mono, ann_turnover):
    clip = lambda x, lo, hi: max(lo, min(hi, float(x)))
    ic_term = clip(rank_ic_ir / 3.0, -2, 2)
    shp_term = clip((sharpe + 0.5) / 1.0, -2, 2)
    ret_term = clip(ann_ret / 0.10, -2, 2)
    mdd_term = clip(1 + max_dd / 0.30, -2, 1)
    mono_term = clip(mono, -1, 1)
    turn_term = -clip(ann_turnover / 30.0 - 1.0, 0, 3)
    return (
        0.20 * ic_term
        + 0.30 * shp_term
        + 0.30 * ret_term
        + 0.20 * mdd_term
        + 0.10 * mono_term
        + 0.10 * turn_term,
        dict(
            ic_term=ic_term,
            shp_term=shp_term,
            ret_term=ret_term,
            mdd_term=mdd_term,
            mono_term=mono_term,
            turn_term=turn_term,
        ),
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "period_sweep").mkdir(exist_ok=True)
    (OUT / "ablation").mkdir(exist_ok=True)
    (OUT / "refinement").mkdir(exist_ok=True)
    (OUT / "oos_2024_2025").mkdir(exist_ok=True)
    (OUT / "validate_2026").mkdir(exist_ok=True)

    close, high = load_combined_panel()
    close, high = _norm(close), _norm(high)
    high = high.reindex(index=close.index, columns=close.columns)
    data_end = str(close.index.max().date())
    val_end = min(pd.Timestamp(VAL_END), close.index.max()).strftime("%Y-%m-%d")
    print(f"宇宙 {close.shape[1]} 数据止 {data_end}")

    persist = (close.diff() > 0).astype(float).rolling(20, min_periods=20).mean()
    roc5 = close / close.shift(5) - 1.0
    fwd = close.shift(-6) / close.shift(-1) - 1.0
    cache_mom = {n: close / close.shift(n) - 1.0 for n in (3, 5, 10, 20, 40, 60)}
    cache_near = {
        n: close / high.rolling(n, min_periods=n).max().replace(0.0, np.nan) for n in (5, 10, 20, 40, 60)
    }

    manifest = {
        "factor": "factor11",
        "strategy": "strategy5",
        "engine": "weekly two-stage equal-weight close-to-close",
        "data": "HS300+ZZ500+ZZ1000 combined panel, current constituents",
        "select_on": f"{IS_START}..{IS_END}",
        "oos_backtest": f"{OOS_START}..{OOS_END}",
        "validate_on": f"{VAL_START}..{val_end}",
        "select_metric": "IS cost-adjusted Sharpe (strategy1 round-trip incl. stamp)",
        "do_not_replace_default": True,
        "prior_peek": "2024-2026 numbers were reported in earlier rounds; this split is protocol-clean for selection only",
    }
    (OUT / "00_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    trial_daily = pd.DataFrame(index=close.index)
    dailies: dict[str, pd.Series] = {}

    def record(row: dict, d: pd.Series) -> dict:
        dailies[row["id"]] = d
        trial_daily[row["id"]] = d
        return row

    # --- period sweep: mom then high; IS only for pick ---
    sweep_rows = []
    for mom_n in (3, 5, 10, 20, 40, 60):
        snap = make_snaps(cache_mom[mom_n], cache_near[20], stage1_k=20, stage2_k=5)
        ic = cond_ic(cache_mom[mom_n], cache_near[20], fwd, 20, IS_START, IS_END)
        row, d = eval_snap(
            close,
            snap,
            f"mom{mom_n}_high20_k5",
            {
                "phase": "period",
                "mom_n": mom_n,
                "high_n": 20,
                "stage1_k": 20,
                "stage2_k": 5,
                "logic": f"动量{mom_n}日 Top20→近高20日 Top5",
                "cond_ic_is": ic,
            },
        )
        sweep_rows.append(record(row, d))
        print(row["id"], "IS净夏普", round(row["n_is_sharpe"], 3), "IC", round(ic, 4))
    sweep_mom = pd.DataFrame(sweep_rows)
    best_mom_n = int(sweep_mom.loc[sweep_mom["id"] == pick_is(sweep_mom), "mom_n"].iloc[0])
    print("best mom_n (IS only)", best_mom_n)

    high_rows = []
    for high_n in (5, 10, 20, 40, 60):
        snap = make_snaps(cache_mom[best_mom_n], cache_near[high_n], stage1_k=20, stage2_k=5)
        ic = cond_ic(cache_mom[best_mom_n], cache_near[high_n], fwd, 20, IS_START, IS_END)
        row, d = eval_snap(
            close,
            snap,
            f"mom{best_mom_n}_high{high_n}_k5",
            {
                "phase": "period",
                "mom_n": best_mom_n,
                "high_n": high_n,
                "stage1_k": 20,
                "stage2_k": 5,
                "logic": f"动量{best_mom_n} Top20→近高{high_n} Top5",
                "cond_ic_is": ic,
            },
        )
        high_rows.append(record(row, d))
        print(row["id"], "IS净夏普", round(row["n_is_sharpe"], 3), "IC", round(ic, 4))
    sweep = pd.concat([sweep_mom, pd.DataFrame(high_rows)], ignore_index=True).drop_duplicates("id")
    best_period_id = pick_is(sweep)
    best_period = sweep.loc[sweep["id"] == best_period_id].iloc[0]
    best_mom_n = int(best_period["mom_n"])
    best_high_n = int(best_period["high_n"])
    sweep.to_csv(OUT / "period_sweep" / "period_sweep_metrics.csv", index=False)
    (OUT / "period_sweep" / "period_sweep_summary.md").write_text(
        f"选参只看 2020–2023 费用后夏普。best period = mom_n={best_mom_n}, high_n={best_high_n} ({best_period_id})。\n"
        f"2024–2025 / 2026 不参与选择。原始 period 为 mom_n=20, high_n=20。\n",
        encoding="utf-8",
    )

    mom = cache_mom[best_mom_n]
    near = cache_near[best_high_n]

    ablations = [
        ("orig_two_stage", make_snaps(mom, near, stage1_k=20, stage2_k=5), "保留两段", "core"),
        ("drop_stage1_near_only", make_snaps(near, None, stage1_k=5, stage2_k=5, use_s1=True), "去掉动量门，全宇宙近高Top5", "harmful_test"),
        ("invert_stage2_far", make_snaps(mom, near, stage1_k=20, stage2_k=5, invert2=True), "动量Top20→远离前高", "harmful_test"),
        ("invert_stage1_lowmom", make_snaps(mom, near, stage1_k=20, stage2_k=5, invert1=True), "动量最弱20→近高Top5", "harmful_test"),
        ("mom_only_top5", make_snaps(mom, None, stage1_k=5, stage2_k=5), "只有动量Top5", "harmful_test"),
        ("mom_top20_ew", make_snaps(mom, None, stage1_k=20, stage2_k=20), "动量Top20等权，无二段", "harmful_test"),
        ("stage2_persist", make_snaps(mom, persist, stage1_k=20, stage2_k=5), "二段改上涨日占比", "helpful_test"),
        ("stage2_not_climax", make_snaps(mom, -roc5, stage1_k=20, stage2_k=5), "二段改未拉直", "helpful_test"),
    ]
    abl_rows = []
    for name, snap, logic, tag in ablations:
        row, d = eval_snap(
            close,
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
        abl_rows.append(record(row, d))
        print(name, "IS净夏普", round(row["n_is_sharpe"], 3))
    abl = pd.DataFrame(abl_rows)
    abl.to_csv(OUT / "ablation" / "ablation_metrics.csv", index=False)
    core_id = pick_is(abl)
    (OUT / "ablation" / "ablation_summary.md").write_text(
        f"best period 固定 mom_n={best_mom_n}, high_n={best_high_n}。IS 选出 core={core_id}。\n",
        encoding="utf-8",
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

    refinements = []

    def add(name, snap, logic, stage1_k=20, stage2_k=5):
        refinements.append((name, snap, logic, stage1_k, stage2_k))

    add("core_k5_s20", make_snaps(core_s1, core_s2, stage1_k=20, stage2_k=5, invert2=core_invert2), "core 原 k=5 一段20")
    add("k3", make_snaps(core_s1, core_s2, stage1_k=20, stage2_k=3, invert2=core_invert2), "收到 3 只", stage2_k=3)
    add("k8", make_snaps(core_s1, core_s2, stage1_k=20, stage2_k=8, invert2=core_invert2), "收到 8 只", stage2_k=8)
    add("s1_10", make_snaps(core_s1, core_s2, stage1_k=10, stage2_k=5, invert2=core_invert2), "一段 Top10", stage1_k=10)
    add("s1_30", make_snaps(core_s1, core_s2, stage1_k=30, stage2_k=5, invert2=core_invert2), "一段 Top30", stage1_k=30)
    add("biweekly", make_snaps(core_s1, core_s2, stage1_k=20, stage2_k=5, invert2=core_invert2, every_n_weeks=2), "两周调一次")
    hyst_base = make_snaps(core_s1, core_s2, stage1_k=20, stage2_k=5, invert2=core_invert2)
    hyst, prev_pick = {}, set()
    for w in sorted(hyst_base):
        fresh = hyst_base[w]
        keep = prev_pick & fresh
        extra = [x for x in fresh if x not in keep][: max(5 - len(keep), 0)]
        hyst[w] = set(list(keep) + extra) if extra or keep else fresh
        prev_pick = hyst[w]
    add("hysteresis", hyst, "仍进第二段则续持")

    ref_rows = []
    for name, snap, logic, s1k, s2k in refinements:
        row, d = eval_snap(
            close,
            snap,
            name,
            {
                "phase": "refine",
                "mom_n": best_mom_n,
                "high_n": best_high_n,
                "stage1_k": s1k,
                "stage2_k": s2k,
                "logic": logic,
                "core": core_id,
            },
        )
        ref_rows.append(record(row, d))
        print(name, "IS净夏普", round(row["n_is_sharpe"], 3), "换手", round(row["week_turn"], 3))
    ref = pd.DataFrame(ref_rows)
    ref.to_csv(OUT / "refinement" / "refinement_metrics.csv", index=False)
    best_final_id = pick_is(ref)
    best_final = ref.loc[ref["id"] == best_final_id].iloc[0]
    orig = sweep.loc[sweep["id"] == "mom20_high20_k5"]
    orig_is = float(orig.iloc[0]["n_is_sharpe"]) if not orig.empty else float("nan")
    (OUT / "refinement" / "refinement_summary.md").write_text(
        f"core={core_id}。IS 选出 best_final={best_final_id}，IS净夏普 {best_final['n_is_sharpe']:.3f}。"
        f"原始 mom20_high20_k5 IS净夏普 {orig_is:.3f}。\n",
        encoding="utf-8",
    )

    frozen = {
        "id": best_final_id,
        "mom_n": best_mom_n,
        "high_n": best_high_n,
        "stage1_k": int(best_final.get("stage1_k", 20) or 20),
        "stage2_k": int(best_final.get("stage2_k", 5) or 5),
        "core": core_id,
        "logic": str(best_final["logic"]),
        "select_window": f"{IS_START}..{IS_END}",
        "select_metric": "n_is_sharpe",
    }
    neighbor_id = "core_k5_s20"
    (OUT / "frozen_params.json").write_text(json.dumps(frozen, ensure_ascii=False, indent=2), encoding="utf-8")
    print("FROZEN", frozen)

    # baselines that may already be in dailies
    if "univ_ew" not in dailies:
        dailies["univ_ew"] = close.pct_change().mean(axis=1)
        trial_daily["univ_ew"] = dailies["univ_ew"]

    focus_ids = []
    for x in ("mom20_high20_k5", best_period_id, neighbor_id, best_final_id, "univ_ew"):
        if x not in focus_ids:
            focus_ids.append(x)

    def pack_focus(name: str, d: pd.Series, wt: float) -> dict:
        g = metrics_of(d)
        n = metrics_of(apply_cost(d, wt if wt == wt else 0.0, S1_RT))
        sh = metrics_of(apply_cost(d, wt if wt == wt else 0.0, SHOT_RT))
        nw_oos = nw_sharpe(slice_daily(apply_cost(d, wt if wt == wt else 0.0, S1_RT), OOS_START, OOS_END))
        nw_val = nw_sharpe(slice_daily(apply_cost(d, wt if wt == wt else 0.0, S1_RT), VAL_START, val_end))
        return {
            "id": name,
            "week_turn": wt,
            **{f"g_{k}": v for k, v in g.items()},
            **{f"n_{k}": v for k, v in n.items()},
            "shot_oos_ret": sh["oos_ret"],
            "shot_oos_sharpe": sh["oos_sharpe"],
            "shot_val_ret": sh["val_ret"],
            "shot_val_sharpe": sh["val_sharpe"],
            "nw_oos_t": nw_oos["t"],
            "nw_oos_ci_lo": nw_oos["ci_lo"],
            "nw_oos_ci_hi": nw_oos["ci_hi"],
            "nw_val_t": nw_val["t"],
            "nw_val_ci_lo": nw_val["ci_lo"],
            "nw_val_ci_hi": nw_val["ci_hi"],
            "nw_oos_n": nw_oos["n"],
            "nw_val_n": nw_val["n"],
        }

    focus_rows = []
    for name in focus_ids:
        d = dailies[name]
        if name == "univ_ew":
            wt = float("nan")
        elif name in sweep["id"].values:
            wt = float(sweep.loc[sweep["id"] == name, "week_turn"].iloc[0])
        elif name in abl["id"].values:
            wt = float(abl.loc[abl["id"] == name, "week_turn"].iloc[0])
        elif name in ref["id"].values:
            wt = float(ref.loc[ref["id"] == name, "week_turn"].iloc[0])
        else:
            wt = float("nan")
        focus_rows.append(pack_focus(name, d, wt))
    focus = pd.DataFrame(focus_rows)
    focus.to_csv(OUT / "oos_2024_2025" / "frozen_backtest.csv", index=False)
    focus.to_csv(OUT / "validate_2026" / "frozen_validate.csv", index=False)

    sel_d = dailies[best_final_id]
    sel_wt = float(best_final["week_turn"])
    sel_nav = nav_from_daily(sel_d)
    yearly = yearly_of(sel_nav, range(2020, 2027))
    yearly.to_csv(OUT / "yearly.csv", index=False)
    yearly.to_csv(OUT / "oos_2024_2025" / "yearly.csv", index=False)

    cost_rows = []
    for label, rt in [("gross", 0.0), ("s1_cost", S1_RT), ("shot_fee", SHOT_RT), ("15bp_rt", 0.003), ("30bp_rt", 0.006)]:
        dnet = apply_cost(sel_d, sel_wt, rt) if rt else sel_d
        nav = nav_from_daily(dnet)
        m_oos = window_metrics(nav, start=OOS_START, end=OOS_END)
        m_val = window_metrics(nav, start=VAL_START, end=val_end)
        m_is = window_metrics(nav, start=IS_START, end=IS_END)
        nw_oos = nw_sharpe(slice_daily(dnet, OOS_START, OOS_END))
        nw_val = nw_sharpe(slice_daily(dnet, VAL_START, val_end))
        cost_rows.append(
            {
                "cost": label,
                "is_ret": m_is["ret_pct"],
                "is_sharpe": m_is["sharpe"],
                "oos_ret": m_oos["ret_pct"],
                "oos_ann": m_oos["ann_pct"],
                "oos_sharpe": m_oos["sharpe"],
                "oos_mdd": m_oos["mdd_pct"],
                "oos_t": nw_oos["t"],
                "oos_ci_lo": nw_oos["ci_lo"],
                "oos_ci_hi": nw_oos["ci_hi"],
                "val_ret": m_val["ret_pct"],
                "val_ann": m_val["ann_pct"],
                "val_sharpe": m_val["sharpe"],
                "val_mdd": m_val["mdd_pct"],
                "val_t": nw_val["t"],
                "val_ci_lo": nw_val["ci_lo"],
                "val_ci_hi": nw_val["ci_hi"],
            }
        )
    cost_df = pd.DataFrame(cost_rows)
    cost_df.to_csv(OUT / "oos_2024_2025" / "cost_sweep.csv", index=False)
    cost_df.to_csv(OUT / "validate_2026" / "cost_sweep.csv", index=False)

    ends = pd.DatetimeIndex([g.index[-1] for _, g in pd.Series(1, index=close.index).groupby(_week(close.index))])
    cond = cond_signal(mom, near, ends, 20)
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
        ic_rows.append({"window": label, "signal": "条件近高(动量Top20内)", **ic, "mono": mono, "groups": groups})
        ic_mom = both_ic(mom.reindex(ends).loc[mask], fwd_w.loc[mask], 52, min_n=30)
        ic_near = both_ic(near.reindex(ends).loc[mask], fwd_w.loc[mask], 52, min_n=30)
        ic_rows.append({"window": label, "signal": f"{best_mom_n}日动量 全宇宙", **ic_mom, "mono": float("nan"), "groups": None})
        ic_rows.append({"window": label, "signal": f"{best_high_n}日近高 全宇宙", **ic_near, "mono": float("nan"), "groups": None})
    ic_table = pd.DataFrame(ic_rows)
    ic_table.to_csv(OUT / "validate_2026" / "ic.csv", index=False)

    val_mask = (ends >= pd.Timestamp(VAL_START)) & (ends <= pd.Timestamp(val_end))
    val_mono, val_groups = monotonicity(cond.loc[val_mask], fwd_w.loc[val_mask], 5)
    oos_mask = (ends >= pd.Timestamp(OOS_START)) & (ends <= pd.Timestamp(OOS_END))
    oos_mono, oos_groups = monotonicity(cond.loc[oos_mask], fwd_w.loc[oos_mask], 5)

    # overfit: search on IS, n_trials = this round unique + prior 20 original research
    is_cols = [c for c in trial_daily.columns if c != "univ_ew"]
    tm_is = trial_daily.loc[
        (trial_daily.index >= IS_START) & (trial_daily.index <= IS_END), is_cols
    ].fillna(0.0)
    n_this = len(is_cols)
    n_trials = n_this + 20
    overfit_is = build_report(
        selected_returns=tm_is[best_final_id].to_numpy(),
        n_trials=n_trials,
        trials_matrix=tm_is.to_numpy(),
        periods_per_year=252,
        haircut_method="holm",
        n_blocks=8,
    )
    tm_oos = trial_daily.loc[
        (trial_daily.index >= OOS_START) & (trial_daily.index <= OOS_END), is_cols
    ].fillna(0.0)
    overfit_oos = build_report(
        selected_returns=tm_oos[best_final_id].to_numpy(),
        n_trials=1,
        trials_matrix=None,
        periods_per_year=252,
        haircut_method="holm",
    )
    tm_val = trial_daily.loc[
        (trial_daily.index >= VAL_START) & (trial_daily.index <= val_end), [best_final_id]
    ].fillna(0.0)
    overfit_val = build_report(
        selected_returns=tm_val[best_final_id].to_numpy(),
        n_trials=1,
        trials_matrix=None,
        periods_per_year=252,
        haircut_method="holm",
    )
    overfit_pack = {
        "n_trials_search": n_this,
        "n_trials_program": n_trials,
        "is": overfit_is,
        "oos_frozen_n1": overfit_oos,
        "val_frozen_n1": overfit_val,
    }
    (OUT / "validate_2026" / "overfit.json").write_text(
        json.dumps(overfit_pack, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

    val_ic = ic_table[(ic_table["window"] == "VAL 2026") & (ic_table["signal"].str.contains("条件近高"))].iloc[0]
    val_net = cost_df.loc[cost_df["cost"] == "s1_cost"].iloc[0]
    rir = float(val_ic["rank_ic_ir"])
    if rir != rir:
        rir = 0.0
    score, terms = primary_score(
        rank_ic_ir=rir,
        sharpe=float(val_net["val_sharpe"]),
        ann_ret=float(val_net["val_ann"]) / 100.0,
        max_dd=-abs(float(val_net["val_mdd"])) / 100.0,
        mono=float(val_mono) if val_mono == val_mono else 0.0,
        ann_turnover=sel_wt * 52.0,
    )
    ci_lo = float(val_net["val_ci_lo"])
    ci_hi = float(val_net["val_ci_hi"])
    oos_t = float(val_net["oos_t"]) if False else float(cost_df.loc[cost_df["cost"] == "s1_cost", "oos_t"].iloc[0])
    val_t = float(val_net["val_t"])
    oos_ci_lo = float(cost_df.loc[cost_df["cost"] == "s1_cost", "oos_ci_lo"].iloc[0])
    oos_ci_hi = float(cost_df.loc[cost_df["cost"] == "s1_cost", "oos_ci_hi"].iloc[0])
    decision = "探索性"
    if val_t == val_t and abs(val_t) >= 2 and (ci_lo > 0 or ci_hi < 0) and overfit_is.get("deflated_sharpe_ratio", 0) >= 0.95:
        decision = "有希望但未验证"
    score_pack = {
        "score": score,
        "terms": terms,
        "frozen": frozen,
        "decision": decision,
        "n_trials": n_trials,
        "val_ic": {k: (None if isinstance(v, float) and pd.isna(v) else v) for k, v in val_ic.to_dict().items() if k != "groups"},
        "val_mono": val_mono,
        "val_groups": val_groups,
        "oos_mono": oos_mono,
        "oos_groups": oos_groups,
    }
    (OUT / "validate_2026" / "score.json").write_text(
        json.dumps(score_pack, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

    cols_sel = [
        "id",
        "logic",
        "cond_ic_is",
        "week_turn",
        "n_is_ret",
        "n_is_sharpe",
        "n_is_mdd",
        "n_oos_ret",
        "n_oos_sharpe",
        "n_val_ret",
        "n_val_sharpe",
    ]
    cols_focus = [
        "id",
        "week_turn",
        "n_is_sharpe",
        "g_oos_ret",
        "n_oos_ret",
        "n_oos_sharpe",
        "n_oos_mdd",
        "nw_oos_t",
        "g_val_ret",
        "n_val_ret",
        "n_val_sharpe",
        "n_val_mdd",
        "nw_val_t",
    ]
    ytxt = yearly.to_string(index=False)
    report = f"""# 因子11 Walk-forward：2020–2023 选参 / 2024–2025 回测 / 2026 验证

研究回测，不构成投资建议。默认策略10 参数未改。

## 契约

- 原始因子：周频 20 日动量 Top20 → 贴近 20 日高点 Top5，下一周等权持有
- 数据：沪深300+中证500+中证1000 当前成分（幸存者偏差）；收盘对收盘
- 选参：仅 {IS_START}～{IS_END} **策略1 费用后夏普**（含印花）
- 冻结回测：{OOS_START}～{OOS_END}，不调参
- 验证：{VAL_START}～{val_end}，不调参
- 标签：close[T+1+5]/close[T+1]-1
- 本轮搜索配置数 {n_this}；程序累计 n_trials={n_trials}（含先前原始验证约 20）
- 上一轮已看过 2024–2026 汇总数字，本协议对**选参**干净，对研究史不是从未见过的样本

## Period Sweep（选参只看 IS）

{md_table(sweep, cols_sel)}

- Best period：**mom_n={best_mom_n}, high_n={best_high_n}**（{best_period_id}）
- 原始 mom_n=20, high_n=20。短端补测了 mom=3、high=5。

## Ablation（固定 best period）

{md_table(abl, ["id", "logic", "tag", "week_turn", "n_is_sharpe", "n_oos_sharpe", "n_val_sharpe"])}

- IS 选出的 core：**{core_id}**

## Refinement（best period + core）

{md_table(ref, cols_sel)}

- Best final（IS）：**{best_final_id}**
- 冻结参数：{frozen}

## 2024–2025 冻结回测

{md_table(focus, cols_focus)}

冻结规格费用扫描：

{md_table(cost_df, ["cost", "is_sharpe", "oos_ret", "oos_ann", "oos_sharpe", "oos_mdd", "oos_t", "oos_ci_lo", "oos_ci_hi"])}

策略1 费用后 2024–2025：累计 {float(val_net['oos_ret']):.1f}%，夏普 {float(val_net['oos_sharpe']):.2f}，回撤 {float(val_net['oos_mdd']):.1f}%，NW t={oos_t:.2f}，夏普 95% CI {oos_ci_lo:.2f}～{oos_ci_hi:.2f}。

## 2026 验证

{md_table(cost_df, ["cost", "val_ret", "val_ann", "val_sharpe", "val_mdd", "val_t", "val_ci_lo", "val_ci_hi"])}

策略1 费用后 2026：累计 {float(val_net['val_ret']):.1f}%，夏普 {float(val_net['val_sharpe']):.2f}，回撤 {float(val_net['val_mdd']):.1f}%，NW t={val_t:.2f}，夏普 95% CI {ci_lo:.2f}～{ci_hi:.2f}。

因子 IC（周频 √52）：

{md_table(ic_table.drop(columns=["groups"], errors="ignore"), ["window", "signal", "n", "rank_ic", "rank_ic_ir", "pearson_ic", "ic_pos", "mono"])}

2024–2025 条件五分组：{oos_groups}，单调性 {oos_mono}
2026 条件五分组：{val_groups}，单调性 {val_mono}

2026 主分 **{score:.3f}**（只根据验证段）。IC {terms['ic_term']:.3f} 夏普 {terms['shp_term']:.3f} 年化 {terms['ret_term']:.3f} 回撤 {terms['mdd_term']:.3f} 单调 {terms['mono_term']:.3f} 换手 {terms['turn_term']:.3f}

## 分年毛收益（冻结 best final）

```
{ytxt}
```

## 过拟合

样本内搜索（n_trials={n_trials}）：{overfit_is.get('verdict')}；DSR {overfit_is.get('deflated_sharpe_ratio')}；PBO {overfit_is.get('pbo')}
2024–2025 冻结规格按单次检验：{overfit_oos.get('verdict')}；观测年化 Sharpe {overfit_oos.get('observed_sharpe_annual')}
2026 冻结规格按单次检验：{overfit_val.get('verdict')}；观测年化 Sharpe {overfit_val.get('observed_sharpe_annual')}；样本短，检验力弱

## 稳健性

- 参数：best period 是否仍落在短窗端点见 sweep 表。
- 时间：本轮按 train / test / validate 切开；2026 不足一年。
- 成本：周换手仍高，主结论看费用后。
- 市场：当前成分幸存者偏差；未做点时指数、涨停买不进。
- 搜索：本轮 {n_this} 个配置；先前研究已扫过相近网格。
- 单侧：消融仍应显示远离前高 / 弱动量为负。

## 最终决策

**{decision}，不替换原因子。** 策略10 默认仍是 mom_n=20, high_n=20, k=5。

冻结规格是 2020–2023 费用后夏普选出的 `{best_final_id}`（mom={best_mom_n}, high={best_high_n}）。2024–2025 是该规格的样本外回测；2026 是验证段。若 2026 的 Newey-West 区间含 0 或样本过短，不得把纸面收益当成已验证。

本报告仅供研究参考，不构成任何投资建议。
"""
    (OUT / "optimize_report.md").write_text(report, encoding="utf-8")
    (OUT / "report.md").write_text(report, encoding="utf-8")
    print("BEST PERIOD", best_period_id)
    print("CORE", core_id)
    print("BEST FINAL", best_final_id)
    print("OOS net sharpe", round(float(val_net["oos_sharpe"]), 3), "VAL net sharpe", round(float(val_net["val_sharpe"]), 3))
    print("DECISION", decision)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
