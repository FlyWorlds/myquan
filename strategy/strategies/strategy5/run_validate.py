"""策略10 / 因子11：回测 + 因子验证 + 过拟合。

  python strategy/strategies/strategy5/run_validate.py
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

_OVERFIT = (
    Path("/Users/wangxiangyu/Documents/akquan回测/myquan")
    / ".cursor"
    / "skills"
    / "backtest-overfit"
    / "scripts"
)
if str(_OVERFIT) not in sys.path:
    sys.path.insert(0, str(_OVERFIT))

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

from strategy.costs import COST_ROUND_TRIP  # noqa: E402
from overfit_report import build_report  # noqa: E402
from strategy.near_high_hold import DEFAULT_PARAMS, equal_weight_hold_nav  # noqa: E402
from strategy.s1_price_select import weekly_mom_gate_from_close, weekly_two_stage_gate  # noqa: E402
from strategy.strategies.strategy4.portfolio import window_metrics  # noqa: E402
from strategy.strategies.strategy4.run_two_stage import load_combined_panel  # noqa: E402

OUT = Path(__file__).resolve().parent / "validate"
START = "2020-01-02"
END = "2026-08-20"
IS_END = "2023-12-31"
OOS_START = "2024-01-02"
# 本轮研究里与「近高等权持有」相关的已试配置（少报=自欺）
# 因子9 日频门控、因子10 五列、两段 4 组、两套宇宙、S1 vs 持有 ≈ 20
N_TRIALS_HONEST = 20
S1_RT = COST_ROUND_TRIP


def primary_score(rank_ic_ir, sharpe, ann_ret, max_dd, mono, ann_turnover):
    """与 evaluation.md / strategy.chan.mining.primary_score 同一套 v2 公式。"""
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
        {
            "ic_term": ic_term,
            "shp_term": shp_term,
            "ret_term": ret_term,
            "mdd_term": mdd_term,
            "mono_term": mono_term,
            "turn_term": turn_term,
        },
    )


def _norm_idx(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    idx = pd.to_datetime(out.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    out.index = pd.DatetimeIndex(idx).normalize()
    return out.sort_index()


def _week_key(idx: pd.DatetimeIndex) -> pd.Index:
    return idx - pd.to_timedelta(idx.dayofweek, unit="D")


def week_end_dates(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    w = _week_key(idx)
    s = pd.Series(1, index=idx)
    return pd.DatetimeIndex([g.index[-1] for _, g in s.groupby(w)])


def _xs_corr(x: pd.DataFrame, y: pd.DataFrame) -> pd.Series:
    x = x.sub(x.mean(axis=1), axis=0)
    y = y.sub(y.mean(axis=1), axis=0)
    num = (x * y).sum(axis=1)
    den = np.sqrt((x ** 2).sum(axis=1) * (y ** 2).sum(axis=1))
    return num / den.replace(0, np.nan)


def both_ic(
    signal: pd.DataFrame, fwd: pd.DataFrame, periods_per_year: float, min_n: int = 30
) -> dict:
    aligned = signal.reindex_like(fwd)
    nobs = aligned.notna().sum(axis=1)
    ok = nobs >= min_n
    rank_ic = _xs_corr(aligned.rank(axis=1), fwd.rank(axis=1)).where(ok)
    pearson_ic = _xs_corr(aligned, fwd).where(ok)
    rstd = float(rank_ic.std())
    pstd = float(pearson_ic.std())
    rmean = float(rank_ic.mean())
    pmean = float(pearson_ic.mean())
    return {
        "n_ic": int(rank_ic.dropna().shape[0]),
        "rank_ic_mean": rmean,
        "rank_ic_ir": (rmean / rstd * math.sqrt(periods_per_year)) if rstd else float("nan"),
        "pearson_ic_mean": pmean,
        "pearson_ic_ir": (pmean / pstd * math.sqrt(periods_per_year)) if pstd else float("nan"),
        "rank_ic_pos": float((rank_ic.dropna() > 0).mean()) if rank_ic.dropna().size else float("nan"),
        "rank_ic": rank_ic,
        "pearson_ic": pearson_ic,
    }


def monotonicity(signal: pd.DataFrame, fwd: pd.DataFrame, n_groups: int = 5) -> tuple[float, list[float]]:
    rank = signal.rank(axis=1, pct=True)
    group_rets = []
    for q in range(n_groups):
        lo, hi = q / n_groups, (q + 1) / n_groups
        mask = (rank > lo) & (rank <= hi)
        group_rets.append(float(fwd.where(mask).mean(axis=1).mean()))
    if np.any(np.isnan(group_rets)):
        return float("nan"), group_rets
    return float(np.corrcoef(np.arange(n_groups), group_rets)[0, 1]), group_rets


def weekly_turnover(gate: dict[str, dict[str, bool]], dates: pd.DatetimeIndex) -> tuple[float, float]:
    weeks = {}
    for d in dates:
        key = pd.Timestamp(d).strftime("%Y-%m-%d")
        names = {s for s, mp in gate.items() if (mp or {}).get(key)}
        w = d - pd.Timedelta(days=int(d.dayofweek))
        weeks[w] = names
    ws = sorted(weeks)
    turns = []
    for a, b in zip(ws, ws[1:]):
        if not weeks[a]:
            continue
        turns.append(1.0 - len(weeks[a] & weeks[b]) / max(len(weeks[a]), 1))
    avg = float(np.mean(turns)) if turns else float("nan")
    return avg, avg * 52.0


def apply_weekly_cost(daily: pd.Series, week_turn: float, round_trip: float) -> pd.Series:
    """把周换手费用摊到该周第一个交易日。"""
    out = daily.copy()
    seen = set()
    for ts in out.index:
        w = ts - pd.Timedelta(days=int(ts.dayofweek))
        if w in seen:
            continue
        seen.add(w)
        out.loc[ts] = float(out.loc[ts]) - week_turn * round_trip
    return out


def nw_sharpe(r: pd.Series, lags: int = 5, periods: int = 252) -> dict:
    x = r.dropna().astype(float)
    if len(x) < 40:
        return {"sharpe": float("nan"), "t": float("nan"), "ci_lo": float("nan"), "ci_hi": float("nan")}
    mu = float(x.mean())
    u = x - mu
    gamma0 = float((u * u).mean())
    nw = gamma0
    n = len(u)
    for lag in range(1, lags + 1):
        w = 1.0 - lag / (lags + 1.0)
        nw += 2.0 * w * float((u.iloc[lag:] * u.iloc[:-lag]).mean())
    se_mu = math.sqrt(max(nw, 1e-18) / n)
    sig = float(x.std(ddof=1))
    sharpe = mu / sig * math.sqrt(periods) if sig else float("nan")
    t = mu / se_mu if se_mu else float("nan")
    lo = (mu - 1.96 * se_mu) / sig * math.sqrt(periods) if sig else float("nan")
    hi = (mu + 1.96 * se_mu) / sig * math.sqrt(periods) if sig else float("nan")
    return {"sharpe": sharpe, "t": t, "ci_lo": lo, "ci_hi": hi, "n": n}


def daily_from_nav(nav: pd.Series, start: str, end: str) -> pd.Series:
    sl = nav[(nav.index >= pd.Timestamp(start)) & (nav.index <= pd.Timestamp(end))].dropna()
    return sl.pct_change().dropna()


def gate_from_spec(close, high, spec: dict) -> dict[str, dict[str, bool]]:
    kind = spec["kind"]
    if kind == "mom":
        return weekly_mom_gate_from_close(close, mom_n=spec.get("mom_n", 20), k=spec.get("k", 5))
    return weekly_two_stage_gate(
        close,
        high,
        mom_n=spec.get("mom_n", 20),
        stage1_k=spec.get("stage1_k", 20),
        stage2_k=spec.get("stage2_k", 5),
        stage2=spec.get("stage2", "near_high"),
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    close, high = load_combined_panel()
    close, high = _norm_idx(close), _norm_idx(high)
    high = high.reindex(index=close.index, columns=close.columns)
    print(f"宇宙 {close.shape[1]} 只  {close.index.min().date()}～{close.index.max().date()}")

    mom = close / close.shift(20) - 1.0
    near = close / high.rolling(20, min_periods=20).max().replace(0.0, np.nan)
    persist = (close.diff() > 0).astype(float).rolling(20, min_periods=20).mean()
    # 下周收益：周收盘信号，跳过次日（周一）开盘不可用，用 T+1 收到 T+1+5
    fwd5 = close.shift(-6) / close.shift(-1) - 1.0

    ends = week_end_dates(close.index)
    ends = ends[(ends >= pd.Timestamp(START)) & (ends <= pd.Timestamp(END))]
    mom_w = mom.reindex(ends)
    near_w = near.reindex(ends)
    persist_w = persist.reindex(ends)
    fwd_w = fwd5.reindex(ends)

    # 条件近高：仅动量 Top20 内有分数
    cond = near_w.copy()
    for i, ts in enumerate(ends):
        row = mom_w.iloc[i].dropna()
        if row.empty:
            cond.iloc[i] = np.nan
            continue
        pool = set(row.nlargest(min(20, len(row))).index)
        mask = ~cond.columns.isin(pool)
        cond.iloc[i, mask] = np.nan

    ic_near = both_ic(near_w, fwd_w, 52)
    ic_mom = both_ic(mom_w, fwd_w, 52)
    ic_cond = both_ic(cond, fwd_w, 52, min_n=8)
    ic_persist = both_ic(persist_w, fwd_w, 52)
    mono_cond, groups = monotonicity(cond, fwd_w, 5)
    mono_near, groups_near = monotonicity(near_w, fwd_w, 5)

    ic_table = pd.DataFrame(
        [
            {
                "signal": "near_high 全宇宙",
                "rank_ic": ic_near["rank_ic_mean"],
                "rank_ic_ir": ic_near["rank_ic_ir"],
                "pearson_ic": ic_near["pearson_ic_mean"],
                "ic_pos": ic_near["rank_ic_pos"],
                "n": ic_near["n_ic"],
            },
            {
                "signal": "mom20 全宇宙",
                "rank_ic": ic_mom["rank_ic_mean"],
                "rank_ic_ir": ic_mom["rank_ic_ir"],
                "pearson_ic": ic_mom["pearson_ic_mean"],
                "ic_pos": ic_mom["rank_ic_pos"],
                "n": ic_mom["n_ic"],
            },
            {
                "signal": "persist 全宇宙",
                "rank_ic": ic_persist["rank_ic_mean"],
                "rank_ic_ir": ic_persist["rank_ic_ir"],
                "pearson_ic": ic_persist["pearson_ic_mean"],
                "ic_pos": ic_persist["rank_ic_pos"],
                "n": ic_persist["n_ic"],
            },
            {
                "signal": "因子11 条件近高(动量Top20内)",
                "rank_ic": ic_cond["rank_ic_mean"],
                "rank_ic_ir": ic_cond["rank_ic_ir"],
                "pearson_ic": ic_cond["pearson_ic_mean"],
                "ic_pos": ic_cond["rank_ic_pos"],
                "n": ic_cond["n_ic"],
            },
        ]
    )
    ic_table.to_csv(OUT / "ic.csv", index=False)
    print(ic_table.to_string(index=False))
    print("条件近高 quintile 下周收益", [round(g, 4) for g in groups], "mono", round(mono_cond, 3))

    specs = {
        "selected_near5": {
            "kind": "two",
            "mom_n": 20,
            "stage1_k": 20,
            "stage2_k": 5,
            "stage2": "near_high",
        },
        "mom_top5": {"kind": "mom", "mom_n": 20, "k": 5},
        "mom_top10": {"kind": "mom", "mom_n": 20, "k": 10},
        "persist5": {
            "kind": "two",
            "mom_n": 20,
            "stage1_k": 20,
            "stage2_k": 5,
            "stage2": "persist",
        },
        "noclimax5": {
            "kind": "two",
            "mom_n": 20,
            "stage1_k": 20,
            "stage2_k": 5,
            "stage2": "not_climax",
        },
        "near_k3": {
            "kind": "two",
            "mom_n": 20,
            "stage1_k": 20,
            "stage2_k": 3,
            "stage2": "near_high",
        },
        "near_k8": {
            "kind": "two",
            "mom_n": 20,
            "stage1_k": 20,
            "stage2_k": 8,
            "stage2": "near_high",
        },
        "near_s1_10": {
            "kind": "two",
            "mom_n": 20,
            "stage1_k": 10,
            "stage2_k": 5,
            "stage2": "near_high",
        },
        "near_s1_30": {
            "kind": "two",
            "mom_n": 20,
            "stage1_k": 30,
            "stage2_k": 5,
            "stage2": "near_high",
        },
        "near_m10": {
            "kind": "two",
            "mom_n": 10,
            "stage1_k": 20,
            "stage2_k": 5,
            "stage2": "near_high",
        },
        "near_m40": {
            "kind": "two",
            "mom_n": 40,
            "stage1_k": 20,
            "stage2_k": 5,
            "stage2": "near_high",
        },
        "univ_ew": None,
    }

    rets = close.pct_change()
    trial_daily = pd.DataFrame(index=rets.index)
    navs = {}
    rows = []
    selected_gate = None
    for name, spec in specs.items():
        print(f"== {name} ==")
        if spec is None:
            d = rets.mean(axis=1)
            nav = (1.0 + d.fillna(0.0)).cumprod()
            nav.iloc[0] = 1.0
            gate = None
            wturn, annturn = float("nan"), float("nan")
        else:
            gate = gate_from_spec(close, high, spec)
            if name == "selected_near5":
                selected_gate = gate
            nav = equal_weight_hold_nav(close, gate)[0]
            d = nav.pct_change()
            wturn, annturn = weekly_turnover(
                gate, close.index[(close.index >= START) & (close.index <= END)]
            )
        navs[name] = nav
        trial_daily[name] = d.reindex(rets.index)
        m = window_metrics(nav, start=START, end=END)
        m_is = window_metrics(nav, start=START, end=IS_END)
        m_oos = window_metrics(nav, start=OOS_START, end=END)
        rows.append(
            {
                "id": name,
                "ret": m["ret_pct"],
                "ann": m["ann_pct"],
                "sharpe": m["sharpe"],
                "mdd": m["mdd_pct"],
                "is_2020_2023": m_is["ret_pct"],
                "oos_2024": m_oos["ret_pct"],
                "week_turn": wturn,
                "ann_turn_names": annturn,
            }
        )

    # 安慰剂：动量池内随机 5 只（固定种子，可复现，不进 PBO 选优）
    rng = np.random.default_rng(11)
    placebo_gate: dict[str, dict[str, bool]] = {c: {} for c in close.columns}
    snap = {}
    for w, g in mom.groupby(_week_key(mom.index)):
        last = g.iloc[-1].dropna()
        if last.empty:
            continue
        pool = list(last.nlargest(min(20, len(last))).index)
        k = min(5, len(pool))
        snap[w] = set(str(x) for x in rng.choice(pool, size=k, replace=False))
    weeks = sorted(snap)
    for d in close.index:
        w = d - pd.to_timedelta(int(d.dayofweek), unit="D")
        prev = None
        for cand in weeks:
            if cand < w:
                prev = cand
            else:
                break
        picked = snap.get(prev, set())
        key = pd.Timestamp(d).strftime("%Y-%m-%d")
        for sym in close.columns:
            placebo_gate[str(sym)][key] = str(sym) in picked
    pnav = equal_weight_hold_nav(close, placebo_gate)[0]
    navs["placebo_mom20_rand5"] = pnav
    pm = window_metrics(pnav, start=START, end=END)
    rows.append(
        {
            "id": "placebo_mom20_rand5",
            "ret": pm["ret_pct"],
            "ann": pm["ann_pct"],
            "sharpe": pm["sharpe"],
            "mdd": pm["mdd_pct"],
            "is_2020_2023": window_metrics(pnav, start=START, end=IS_END)["ret_pct"],
            "oos_2024": window_metrics(pnav, start=OOS_START, end=END)["ret_pct"],
            "week_turn": float("nan"),
            "ann_turn_names": float("nan"),
        }
    )

    combo = pd.DataFrame(rows)
    combo.to_csv(OUT / "combo.csv", index=False)
    print(combo.to_string(index=False))

    sel_nav = navs["selected_near5"]
    sel_d = daily_from_nav(sel_nav, START, END)
    wturn = float(combo.loc[combo["id"] == "selected_near5", "week_turn"].iloc[0])
    annturn = float(combo.loc[combo["id"] == "selected_near5", "ann_turn_names"].iloc[0])
    cost_rows = []
    net_daily = {}
    for label, rt in [("gross", 0.0), ("s1_cost", S1_RT), ("15bp_rt", 0.003), ("30bp_rt", 0.006)]:
        dnet = apply_weekly_cost(sel_d, wturn, rt) if rt else sel_d
        net_daily[label] = dnet
        navn = (1.0 + dnet).cumprod()
        m = window_metrics(pd.concat([pd.Series([1.0], index=navn.index[:1]), navn]))
        # window_metrics on nav starting at 1
        nav_full = (1.0 + dnet.reindex(sel_nav.index).fillna(0)).cumprod()
        m = window_metrics(nav_full, start=START, end=END)
        m_oos = window_metrics(nav_full, start=OOS_START, end=END)
        nw = nw_sharpe(dnet[(dnet.index >= START) & (dnet.index <= END)])
        nw_oos = nw_sharpe(dnet[dnet.index >= OOS_START])
        cost_rows.append(
            {
                "cost": label,
                "ret": m["ret_pct"],
                "ann": m["ann_pct"],
                "sharpe": m["sharpe"],
                "mdd": m["mdd_pct"],
                "oos_2024": m_oos["ret_pct"],
                "sharpe_t": nw["t"],
                "sharpe_ci_lo": nw["ci_lo"],
                "sharpe_ci_hi": nw["ci_hi"],
                "oos_sharpe": nw_oos["sharpe"],
                "oos_sharpe_t": nw_oos["t"],
            }
        )
    cost_df = pd.DataFrame(cost_rows)
    cost_df.to_csv(OUT / "cost_sweep.csv", index=False)
    print(cost_df.to_string(index=False))

    # 过拟合：选中策略日收益 + 试验矩阵（不含 univ_ew / placebo）
    trial_cols = [c for c in trial_daily.columns if c not in ("univ_ew",)]
    tm = trial_daily.loc[(trial_daily.index >= START) & (trial_daily.index <= END), trial_cols]
    tm = tm.dropna(how="all").fillna(0.0)
    sel = tm["selected_near5"].to_numpy()
    overfit = build_report(
        selected_returns=sel,
        n_trials=N_TRIALS_HONEST,
        trials_matrix=tm.to_numpy(),
        periods_per_year=252,
        haircut_method="holm",
        n_blocks=16,
    )
    (OUT / "overfit.json").write_text(json.dumps(overfit, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("OVERFIT", overfit["verdict"])

    # 主分：用成本后（策略1 同口径费用）+ 周频 IC_IR + 条件单调
    net = cost_df.loc[cost_df["cost"] == "s1_cost"].iloc[0]
    rir = float(ic_cond["rank_ic_ir"])
    if rir != rir:
        rir = 0.0
    score, terms = primary_score(
        rank_ic_ir=rir,
        sharpe=float(net["sharpe"]),
        ann_ret=float(net["ann"]) / 100.0,
        max_dd=-abs(float(net["mdd"])) / 100.0,
        mono=float(mono_cond) if mono_cond == mono_cond else 0.0,
        ann_turnover=float(annturn),
    )
    score_pack = {
        "score": score,
        "terms": terms,
        "rank_ic_ir": ic_cond["rank_ic_ir"],
        "sharpe_net": float(net["sharpe"]),
        "ann_net": float(net["ann"]),
        "mdd_net": float(net["mdd"]),
        "mono": mono_cond,
        "ann_turnover_names": annturn,
        "week_turn": wturn,
        "groups_cond": groups,
        "groups_near": groups_near,
        "mono_near": mono_near,
        "n_trials_honest": N_TRIALS_HONEST,
        "decision": "探索性",
        "decision_reason": (
            "无历史点时指数成分（幸存者偏差），"
            "2025 上看过四组两段才选定近高，再回看 2020；"
            "持有为收盘对收盘。evaluation.md：无法取得历史时点成分时结论上限为探索性。"
        ),
    }
    (OUT / "score.json").write_text(json.dumps(score_pack, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    yearly = []
    sl = sel_nav[(sel_nav.index >= START) & (sel_nav.index <= END)]
    for y in range(2020, 2027):
        prev = sl[sl.index.year < y]
        this = sl[sl.index.year == y]
        if this.empty:
            continue
        start_v = float(prev.iloc[-1]) if len(prev) else float(this.iloc[0])
        yearly.append({"year": y, "ret_pct": (float(this.iloc[-1]) / start_v - 1.0) * 100.0})
    pd.DataFrame(yearly).to_csv(OUT / "yearly.csv", index=False)

    lines = [
        "# 策略10 / 因子11 验证与过拟合",
        "",
        "研究回测，不构成投资建议。",
        "",
        "## 研究契约",
        "",
        "- 因子：因子11 两段近高；策略：策略10 等权持有",
        "- 宇宙：沪深300+中证500+中证1000 当前成分缓存（幸存者偏差）",
        "- 时点：周收盘算分，下一周持有；标签用 close[T+1+5]/close[T+1]-1（面板无开盘价）",
        f"- 区间：{START}～面板末日；样本内 2020–2023，样本外 2024 起",
        "- 选定过程：2025 样本上比较 mom Top5 / 近高 / persist / 未拉直，近高持有最好，再扩到 2020",
        f"- 诚实试验次数 n_trials={N_TRIALS_HONEST}（含因子9/10 变体、两段 4 组、两套宇宙、S1 vs 持有）",
        "- 费用：毛收益 + 策略1 同口径周换手费用 + 15bp/30bp 往返压力",
        "",
        "## 因子验证（周频，√52 年化 IR）",
        "",
        ic_table.to_markdown(index=False),
        "",
        f"因子11 条件近高五分组下周收益：{groups}；单调性 {mono_cond:.3f}",
        "",
        "## 策略回测（等权持有）",
        "",
        combo.to_markdown(index=False),
        "",
        "## 成本与夏普显著性（Newey-West lag=5）",
        "",
        cost_df.to_markdown(index=False),
        "",
        "## 主分（evaluation.md v2，成本后）",
        "",
        f"- 主分 **{score:.3f}**（<0 拒绝，0–0.5 探索，0.5–1 合格，>1.5 先查泄漏）",
        f"- IC term {terms['ic_term']:.3f}  Shp {terms['shp_term']:.3f}  Ret {terms['ret_term']:.3f}  MDD {terms['mdd_term']:.3f}  Mono {terms['mono_term']:.3f}  Turn {terms['turn_term']:.3f}",
        "",
        "## 过拟合",
        "",
        f"- 结论：{overfit['verdict']}",
        f"- 观测年化 Sharpe {overfit['observed_sharpe_annual']}",
        f"- DSR {overfit['deflated_sharpe_ratio']}  PSR(>0) {overfit['psr_vs_zero']}",
        f"- Haircut({overfit['haircut']['method']}) 调整后 Sharpe {overfit['haircut']['adjusted_sharpe_annual']}  折扣 {overfit['haircut']['haircut_pct']}",
        f"- MinTRL {overfit['minimum_track_record_length']} vs 样本 {overfit['n_obs']}",
        f"- PBO {overfit.get('pbo')}",
        "",
        "## 偏差清单",
        "",
        "- 前视：周频用上一周排名，单元测试覆盖；标签跳过 T 当日收盘",
        "- 幸存者：当前指数成分，无退市/调出历史",
        "- 数据窥探：在 2025 上看过结果再跑 2020，2020–2023 不是干净样本外",
        "- 成交：无涨停买不进、无开盘价；费用后仍可能高估",
        "- 多重检验：n_trials=20 仍是下限（未计入所有口头讨论的切分）",
        "",
        "## 决策标签",
        "",
        "**探索性**。纸面毛收益和邻域参数仍强，但不能当作可交易 alpha。无点时成分、选定窗口已偷看、换手极高。策略1 默认不改。",
        "",
        "本报告仅供研究参考，不构成任何投资建议。",
    ]
    (OUT / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"主分 {score:.3f} 决策 探索性")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
