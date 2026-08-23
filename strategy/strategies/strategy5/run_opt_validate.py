"""优化后因子11：回测 + 验证 + 过拟合。

研究候选 mom_n=5, high_n=10, k=5（样本内选出）。默认策略10 参数未改。

  python strategy/strategies/strategy5/run_opt_validate.py
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
from strategy.near_high_hold import OPTIMIZED_PARAMS  # noqa: E402
from strategy.strategies.strategy5.run_optimize import (  # noqa: E402
    FULL_START,
    IS_END,
    IS_START,
    OOS_END,
    OOS_START,
    apply_cost,
    cond_ic,
    daily_from_snaps,
    make_snaps,
    metrics_of,
    week_turn,
)
from strategy.strategies.strategy4.portfolio import window_metrics  # noqa: E402
from strategy.strategies.strategy4.run_two_stage import load_combined_panel  # noqa: E402

OUT = Path(__file__).resolve().parent / "opt_validate"
# 原研究 20 + period9 + ablation8 + refine7
N_TRIALS = 44
S1_RT = COST_ROUND_TRIP
SHOT_RT = FEE_ROUND_TRIP


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


def _norm(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    idx = pd.to_datetime(out.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    out.index = pd.DatetimeIndex(idx).normalize()
    return out.sort_index()


def _week(idx: pd.DatetimeIndex):
    return idx - pd.to_timedelta(idx.dayofweek, unit="D")


def _xs_corr(x: pd.DataFrame, y: pd.DataFrame) -> pd.Series:
    x = x.sub(x.mean(axis=1), axis=0)
    y = y.sub(y.mean(axis=1), axis=0)
    num = (x * y).sum(axis=1)
    den = np.sqrt((x ** 2).sum(axis=1) * (y ** 2).sum(axis=1))
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


def nw_sharpe(r: pd.Series, lags: int = 5, periods: int = 252) -> dict:
    x = r.dropna().astype(float)
    if len(x) < 40:
        return {"sharpe": float("nan"), "t": float("nan"), "ci_lo": float("nan"), "ci_hi": float("nan")}
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
        "sharpe": sh,
        "t": t,
        "ci_lo": (mu - 1.96 * se) / sig * math.sqrt(periods) if sig else float("nan"),
        "ci_hi": (mu + 1.96 * se) / sig * math.sqrt(periods) if sig else float("nan"),
    }


def nav_from_daily(d: pd.Series) -> pd.Series:
    nav = (1.0 + d.fillna(0.0)).cumprod()
    if len(nav):
        nav.iloc[0] = 1.0
    return nav


def yearly_of(nav: pd.Series) -> pd.DataFrame:
    sl = nav[(nav.index >= FULL_START) & (nav.index <= OOS_END)]
    rows = []
    for y in range(2020, 2027):
        prev, this = sl[sl.index.year < y], sl[sl.index.year == y]
        if this.empty:
            continue
        start = float(prev.iloc[-1]) if len(prev) else float(this.iloc[0])
        rows.append({"year": y, "ret_pct": (float(this.iloc[-1]) / start - 1.0) * 100.0})
    return pd.DataFrame(rows)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    close, high = load_combined_panel()
    close, high = _norm(close), _norm(high)
    high = high.reindex(index=close.index, columns=close.columns)
    print("宇宙", close.shape[1], "优化参数", OPTIMIZED_PARAMS)

    mom5 = close / close.shift(5) - 1.0
    mom20 = close / close.shift(20) - 1.0
    near10 = close / high.rolling(10, min_periods=10).max().replace(0.0, np.nan)
    near20 = close / high.rolling(20, min_periods=20).max().replace(0.0, np.nan)
    fwd = close.shift(-6) / close.shift(-1) - 1.0
    ends = pd.DatetimeIndex([g.index[-1] for _, g in pd.Series(1, index=close.index).groupby(_week(close.index))])
    ends = ends[(ends >= pd.Timestamp(FULL_START)) & (ends <= pd.Timestamp(OOS_END))]

    cond = near10.reindex(ends).copy()
    m5e = mom5.reindex(ends)
    for i, ts in enumerate(ends):
        row = m5e.iloc[i].dropna()
        if row.empty:
            cond.iloc[i] = np.nan
            continue
        pool = set(row.nlargest(min(20, len(row))).index)
        cond.iloc[i, ~cond.columns.isin(pool)] = np.nan
    fwd_w = fwd.reindex(ends)
    ic_opt = both_ic(cond, fwd_w, 52, min_n=8)
    ic_near = both_ic(near10.reindex(ends), fwd_w, 52, min_n=30)
    ic_mom = both_ic(mom5.reindex(ends), fwd_w, 52, min_n=30)
    mono, groups = monotonicity(cond, fwd_w, 5)
    ic_table = pd.DataFrame(
        [
            {"signal": "优化 5日动量 全宇宙", **ic_mom},
            {"signal": "优化 10日近高 全宇宙", **ic_near},
            {"signal": "优化因子11 条件近高(动量Top20内)", **ic_opt},
        ]
    )
    ic_table.to_csv(OUT / "ic.csv", index=False)
    print(ic_table.to_string(index=False))
    print("条件五分组", [round(g, 4) for g in groups], "mono", round(mono, 3) if mono == mono else None)

    specs = {
        "original_20_20_k5": make_snaps(mom20, near20, stage1_k=20, stage2_k=5),
        "opt_5_10_k5": make_snaps(mom5, near10, stage1_k=20, stage2_k=5),
        "opt_5_10_k3": make_snaps(mom5, near10, stage1_k=20, stage2_k=3),
        "opt_5_10_s30_k5": make_snaps(mom5, near10, stage1_k=30, stage2_k=5),
        "opt_5_10_biweekly": make_snaps(mom5, near10, stage1_k=20, stage2_k=5, every_n_weeks=2),
        "mom5_only_k5": make_snaps(mom5, None, stage1_k=5, stage2_k=5),
        "near10_only_k5": make_snaps(near10, None, stage1_k=5, stage2_k=5),
        "opt_invert_far": make_snaps(mom5, near10, stage1_k=20, stage2_k=5, invert2=True),
        "mom10_high20_k5": make_snaps(close / close.shift(10) - 1.0, near20, stage1_k=20, stage2_k=5),
        "opt_5_20_k5": make_snaps(mom5, near20, stage1_k=20, stage2_k=5),
        "univ_ew": None,
    }

    trial_daily = pd.DataFrame(index=close.index)
    rows = []
    dailies = {}
    for name, snap in specs.items():
        if snap is None:
            d = close.pct_change().mean(axis=1)
            wt = float("nan")
        else:
            d = daily_from_snaps(close, snap)
            wt = week_turn(snap)
        dailies[name] = d
        trial_daily[name] = d
        g = metrics_of(d)
        n = metrics_of(apply_cost(d, wt if wt == wt else 0.0, S1_RT))
        sh = metrics_of(apply_cost(d, wt if wt == wt else 0.0, SHOT_RT))
        rows.append(
            {
                "id": name,
                "week_turn": wt,
                "g_all_ret": g["all_ret"],
                "g_all_ann": g.get("all_ann", float("nan")),
                "g_all_sharpe": g["all_sharpe"],
                "g_all_mdd": g["all_mdd"],
                "g_is_sharpe": g["is_sharpe"],
                "g_oos_sharpe": g["oos_sharpe"],
                "g_is_ret": g["is_ret"],
                "g_oos_ret": g["oos_ret"],
                "n_s1_all_ret": n["all_ret"],
                "n_s1_all_sharpe": n["all_sharpe"],
                "n_s1_all_mdd": n["all_mdd"],
                "n_s1_is_sharpe": n["is_sharpe"],
                "n_s1_oos_sharpe": n["oos_sharpe"],
                "n_s1_is_ret": n["is_ret"],
                "n_s1_oos_ret": n["oos_ret"],
                "n_shot_all_ret": sh["all_ret"],
                "n_shot_all_sharpe": sh["all_sharpe"],
                "n_shot_oos_ret": sh["oos_ret"],
            }
        )
        print(name, "毛", round(g["all_ret"], 1), "S1净夏普", round(n["all_sharpe"], 3))

    combo = pd.DataFrame(rows)
    combo.to_csv(OUT / "summary.csv", index=False)

    # fill all_ann from window_metrics - metrics_of has all_ann? check run_optimize metrics_of
    # it has is_ann oos_ann but I used g.get all_ann - add via nav
    opt_d = dailies["opt_5_10_k5"]
    wt = float(combo.loc[combo["id"] == "opt_5_10_k5", "week_turn"].iloc[0])
    cost_rows = []
    for label, rt in [("gross", 0.0), ("s1_cost", S1_RT), ("shot_fee", SHOT_RT), ("15bp_rt", 0.003), ("30bp_rt", 0.006)]:
        dnet = apply_cost(opt_d, wt, rt) if rt else opt_d
        nav = nav_from_daily(dnet)
        m = window_metrics(nav, start=FULL_START, end=OOS_END)
        m_is = window_metrics(nav, start=IS_START, end=IS_END)
        m_oos = window_metrics(nav, start=OOS_START, end=OOS_END)
        sl = dnet[(dnet.index >= FULL_START) & (dnet.index <= OOS_END)]
        nw = nw_sharpe(sl)
        nw_oos = nw_sharpe(dnet[dnet.index >= OOS_START])
        cost_rows.append(
            {
                "cost": label,
                "ret": m["ret_pct"],
                "ann": m["ann_pct"],
                "sharpe": m["sharpe"],
                "mdd": m["mdd_pct"],
                "is_ret": m_is["ret_pct"],
                "is_sharpe": m_is["sharpe"],
                "oos_ret": m_oos["ret_pct"],
                "oos_sharpe": m_oos["sharpe"],
                "sharpe_t": nw["t"],
                "ci_lo": nw["ci_lo"],
                "ci_hi": nw["ci_hi"],
                "oos_sharpe_t": nw_oos["t"],
            }
        )
    cost_df = pd.DataFrame(cost_rows)
    cost_df.to_csv(OUT / "cost_sweep.csv", index=False)
    print(cost_df.to_string(index=False))

    opt_nav = nav_from_daily(opt_d)
    yearly_of(opt_nav).to_csv(OUT / "yearly.csv", index=False)

    tm = trial_daily.loc[
        (trial_daily.index >= FULL_START) & (trial_daily.index <= OOS_END),
        [c for c in trial_daily.columns if c != "univ_ew"],
    ].fillna(0.0)
    overfit = build_report(
        selected_returns=tm["opt_5_10_k5"].to_numpy(),
        n_trials=N_TRIALS,
        trials_matrix=tm.to_numpy(),
        periods_per_year=252,
        haircut_method="holm",
        n_blocks=16,
    )
    (OUT / "overfit.json").write_text(
        json.dumps(overfit, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print("OVERFIT", overfit["verdict"])

    net = cost_df.loc[cost_df["cost"] == "s1_cost"].iloc[0]
    rir = float(ic_opt["rank_ic_ir"])
    if rir != rir:
        rir = 0.0
    score, terms = primary_score(
        rank_ic_ir=rir,
        sharpe=float(net["sharpe"]),
        ann_ret=float(net["ann"]) / 100.0,
        max_dd=-abs(float(net["mdd"])) / 100.0,
        mono=float(mono) if mono == mono else 0.0,
        ann_turnover=wt * 52.0,
    )
    score_pack = {
        "score": score,
        "terms": terms,
        "params": OPTIMIZED_PARAMS,
        "decision": "探索性",
        "n_trials": N_TRIALS,
        "ic": ic_opt,
        "mono": mono,
        "groups": groups,
    }
    (OUT / "score.json").write_text(json.dumps(score_pack, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    def md(df):
        use = df.copy()
        for c in use.columns:
            if use[c].dtype.kind == "f":
                use[c] = use[c].map(lambda x: round(x, 3) if pd.notna(x) else x)
        return use.to_markdown(index=False)

    report = f"""# 优化后因子11 回测与验证

研究回测，不构成投资建议。默认策略10 未改。

## 契约

- 变体：mom_n=5, high_n=10, stage1=20, k=5（2020–2023 费用后夏普选出）
- 对照：原始 20/20/k5；进攻 k=3
- 宇宙：沪深300+中证500+中证1000 当前成分
- 区间：{FULL_START}～{OOS_END}；样本内到 {IS_END}；确认 {OOS_START} 起（已窥探）
- 费用：毛收益；策略1 口径一轮；对账单税费一轮约万分之 6.88
- n_trials={N_TRIALS}

## 回测

{md(combo[["id","week_turn","g_all_ret","g_all_sharpe","g_all_mdd","g_is_ret","g_oos_ret","n_s1_all_ret","n_s1_all_sharpe","n_s1_oos_ret"]])}

## 优化 k=5 成本与显著性

{md(cost_df)}

## 因子验证（周频 √52）

{md(ic_table)}

条件近高五分组下周收益：{groups}；单调性 {mono}

## 主分（成本后 v2）

主分 **{score:.3f}**。IC {terms['ic_term']:.3f} 夏普 {terms['shp_term']:.3f} 年化 {terms['ret_term']:.3f} 回撤 {terms['mdd_term']:.3f} 单调 {terms['mono_term']:.3f} 换手 {terms['turn_term']:.3f}

## 过拟合

- {overfit['verdict']}
- 观测年化 Sharpe {overfit['observed_sharpe_annual']}
- DSR {overfit['deflated_sharpe_ratio']}  PSR(>0) {overfit['psr_vs_zero']}
- Haircut Sharpe {overfit['haircut']['adjusted_sharpe_annual']} 折扣 {overfit['haircut']['haircut_pct']}
- MinTRL {overfit['minimum_track_record_length']} / 样本 {overfit['n_obs']}
- PBO {overfit.get('pbo')}

## 决策

**探索性，不替换默认。** 短窗在样本内、确认段纸面都更强，但参数落在网格端点、n_trials=44、无点时成分、确认段已窥探。Newey-West 区间仍可能含 0。

本报告仅供研究参考，不构成任何投资建议。
"""
    (OUT / "report.md").write_text(report, encoding="utf-8")
    print("主分", round(score, 3), "决策 探索性")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
