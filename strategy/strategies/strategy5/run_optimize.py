"""因子11 优化：period sweep → ablation → refinement。

成交约束与项目默认一致：一字涨停开盘买不进、一字跌停封单卖不出。
选参只看 2020–2023 费用后夏普；2024–2025 / 2026 只确认。不改 DEFAULT_PARAMS。

  python strategy/strategies/strategy5/run_optimize.py
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

from strategy.costs import COST_ROUND_TRIP, fee_rules_text  # noqa: E402
from strategy.near_high_hold import daily_from_snaps_fill, limit_fill_masks  # noqa: E402
from strategy.strategies.strategy4.portfolio import window_metrics  # noqa: E402
from strategy.strategies.strategy4.run_two_stage import load_combined_ohlc  # noqa: E402

OUT = Path(__file__).resolve().parent / "optimize_tests"
IS_START, IS_END = "2020-01-02", "2023-12-31"
OOS_START, OOS_END = "2024-01-02", "2025-12-31"
VAL_START, VAL_END = "2026-01-02", "2026-08-20"
FULL_START = "2020-01-02"
RT = COST_ROUND_TRIP


def _norm(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    idx = pd.to_datetime(out.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    out.index = pd.DatetimeIndex(idx).normalize()
    return out.sort_index()


def _week(idx: pd.DatetimeIndex) -> pd.Index:
    return idx - pd.to_timedelta(idx.dayofweek, unit="D")


def make_snaps(
    s1: pd.DataFrame,
    s2: pd.DataFrame | None,
    *,
    stage1_k: int,
    stage2_k: int,
    invert1: bool = False,
    invert2: bool = False,
    use_s1: bool = True,
    every_n_weeks: int = 1,
    drop_lu: pd.DataFrame | None = None,
) -> dict:
    week = _week(s1.index)
    snap: dict = {}
    for w, g in s1.groupby(week):
        last_d = g.index[-1]
        a = s1.loc[last_d].dropna()
        if a.empty:
            continue
        if use_s1:
            n1 = max(1, min(int(stage1_k), len(a)))
            pool = list((a.nsmallest(n1) if invert1 else a.nlargest(n1)).index)
        else:
            pool = list(a.index)
        if s2 is None:
            ranked = [str(x) for x in pool]
        else:
            sc = s2.loc[last_d, pool].dropna()
            ranked = [
                str(x)
                for x in (sc.nsmallest(len(sc)) if invert2 else sc.nlargest(len(sc))).index
            ]
        pick: list[str] = []
        for x in ranked:
            blocked = False
            if drop_lu is not None and x in drop_lu.columns and last_d in drop_lu.index:
                blocked = bool(drop_lu.at[last_d, x])
            if blocked:
                continue
            pick.append(x)
            if len(pick) >= int(stage2_k):
                break
        if not pick:
            pick = ranked[: max(1, min(int(stage2_k), len(ranked)))]
        snap[w] = set(pick)
    if every_n_weeks <= 1:
        return snap
    weeks = sorted(snap)
    keep = {weeks[i] for i in range(0, len(weeks), int(every_n_weeks))}
    out = {}
    last: set[str] = set()
    for w in weeks:
        if w in keep:
            last = snap[w]
        out[w] = set(last)
    return out


def daily_from_snaps(close: pd.DataFrame, snap: dict) -> pd.Series:
    """无成交约束对照，供 walk_forward 等旧脚本导入。正式优化不要用。"""
    rets = close.pct_change()
    weeks = sorted(snap)
    out = np.zeros(len(rets), dtype=float)
    wkey = _week(rets.index)
    prev = None
    wi = 0
    for i, (_ts, w) in enumerate(zip(rets.index, wkey)):
        while wi < len(weeks) and weeks[wi] < w:
            prev = weeks[wi]
            wi += 1
        names = snap.get(prev, set()) if prev is not None else set()
        if not names:
            continue
        row = rets.iloc[i]
        vals = [float(row[n]) for n in names if n in row.index and pd.notna(row[n])]
        if vals:
            out[i] = float(np.mean(vals))
    return pd.Series(out, index=rets.index)


def week_turn(snap: dict) -> float:
    ws = sorted(snap)
    if len(ws) < 2:
        return float("nan")
    turns = []
    for a, b in zip(ws, ws[1:]):
        if not snap[a]:
            continue
        turns.append(1.0 - len(snap[a] & snap[b]) / max(len(snap[a]), 1))
    return float(np.mean(turns)) if turns else float("nan")


def apply_cost(daily: pd.Series, wturn: float, rt: float) -> pd.Series:
    if not rt or wturn != wturn:
        return daily
    out = daily.copy()
    seen = set()
    for ts in out.index:
        w = ts - pd.Timedelta(days=int(ts.dayofweek))
        if w in seen:
            continue
        seen.add(w)
        out.loc[ts] = float(out.loc[ts]) - wturn * rt
    return out


def metrics_of(daily: pd.Series) -> dict:
    nav = (1.0 + daily.fillna(0.0)).cumprod()
    if len(nav):
        nav.iloc[0] = 1.0
    m_is = window_metrics(nav, start=IS_START, end=IS_END)
    m_oos = window_metrics(nav, start=OOS_START, end=OOS_END)
    m_val = window_metrics(nav, start=VAL_START, end=VAL_END)
    m_all = window_metrics(nav, start=FULL_START, end=VAL_END)
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
        "all_ret": m_all["ret_pct"],
        "all_sharpe": m_all["sharpe"],
        "all_mdd": m_all["mdd_pct"],
    }


def eval_snap(
    close: pd.DataFrame,
    snap: dict,
    name: str,
    extra: dict,
    *,
    block_buy: pd.DataFrame,
    block_sell: pd.DataFrame,
) -> dict:
    d, fill = daily_from_snaps_fill(close, snap, block_buy, block_sell)
    wt = float(fill.get("realized_week_turn", float("nan")))
    if wt != wt:
        wt = week_turn(snap)
    dnet = apply_cost(d, wt, RT)
    row = {
        "id": name,
        "week_turn": wt,
        "name_turn": week_turn(snap),
        "skipped_buy": fill.get("skipped_limit_up_buy", 0),
        "filled_buy": fill.get("filled_buy", 0),
        "blocked_sell": fill.get("blocked_limit_down_sell", 0),
        **extra,
    }
    g = metrics_of(d)
    n = metrics_of(dnet)
    for k, v in g.items():
        row[f"g_{k}"] = v
    for k, v in n.items():
        row[f"n_{k}"] = v
    return row


def cond_ic(mom: pd.DataFrame, near: pd.DataFrame, fwd: pd.DataFrame, stage1_k: int, start, end) -> float:
    week = _week(mom.index)
    ics = []
    for w, g in mom.groupby(week):
        last_d = g.index[-1]
        if last_d < pd.Timestamp(start) or last_d > pd.Timestamp(end):
            continue
        a = mom.loc[last_d].dropna()
        if len(a) < stage1_k:
            continue
        pool = list(a.nlargest(stage1_k).index)
        x = near.loc[last_d, pool].astype(float)
        y = fwd.loc[last_d, pool].astype(float)
        df = pd.DataFrame({"x": x, "y": y}).dropna()
        if len(df) < 8:
            continue
        ics.append(float(df["x"].rank().corr(df["y"].rank())))
    return float(np.nanmean(ics)) if ics else float("nan")


def pick_is(df: pd.DataFrame) -> str:
    """样本内费用后夏普；并列取换手更低。不看 OOS / 2026。"""
    sub = df.replace([np.inf, -np.inf], np.nan).dropna(subset=["n_is_sharpe"])
    pos = sub[sub["n_is_ret"] > 0]
    if not pos.empty:
        sub = pos
    sub = sub.sort_values(["n_is_sharpe", "week_turn"], ascending=[False, True])
    return str(sub.iloc[0]["id"])


def md_table(df: pd.DataFrame, cols: list[str]) -> str:
    use = df[[c for c in cols if c in df.columns]].copy()
    for c in use.columns:
        if use[c].dtype.kind == "f":
            use[c] = use[c].map(lambda x: round(float(x), 3) if pd.notna(x) else x)
    header = "| " + " | ".join(map(str, use.columns)) + " |"
    sep = "| " + " | ".join("---" for _ in use.columns) + " |"
    body = "\n".join("| " + " | ".join(map(str, row)) + " |" for row in use.values)
    return "\n".join([header, sep, body])


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
    print("成交：一字涨停开盘买不进、一字跌停封单卖不出")
    block_buy, block_sell, close_lu = limit_fill_masks(close, open_px, high, low)

    persist = (close.diff() > 0).astype(float).rolling(20, min_periods=20).mean()
    roc5 = close / close.shift(5) - 1.0
    fwd = close.shift(-6) / close.shift(-1) - 1.0
    mom_ns = (3, 5, 10, 20, 40, 60)
    high_ns = (5, 10, 20, 40, 60)
    cache_mom = {n: close / close.shift(n) - 1.0 for n in mom_ns}
    cache_near = {
        n: close / high.rolling(n, min_periods=n).max().replace(0.0, np.nan) for n in high_ns
    }

    def ev(snap, name, extra):
        return eval_snap(close, snap, name, extra, block_buy=block_buy, block_sell=block_sell)

    manifest = {
        "factor": "factor11",
        "strategy": "strategy5",
        "engine": "weekly two-stage equal-weight; 一字涨停开盘买不进 / 一字跌停封单卖不出; IS cost-adjusted Sharpe",
        "data": "HS300+ZZ500+ZZ1000 combined OHLC, current constituents",
        "select_on": f"{IS_START}..{IS_END}",
        "confirm_on": f"{OOS_START}..{OOS_END}",
        "validate_on": f"{VAL_START}..{VAL_END}",
        "cost": f"realized weekly turnover × ({fee_rules_text()})",
        "fill": "block_limit_up_buy + block_limit_down_sell",
        "do_not_replace_default": True,
        "original": "mom3_high5_k5",
    }
    (OUT / "00_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    sweep_rows = []
    for mom_n in mom_ns:
        snap = make_snaps(cache_mom[mom_n], cache_near[5], stage1_k=20, stage2_k=5)
        ic = cond_ic(cache_mom[mom_n], cache_near[5], fwd, 20, IS_START, IS_END)
        row = ev(
            snap,
            f"mom{mom_n}_high5_k5",
            {
                "phase": "period",
                "mom_n": mom_n,
                "high_n": 5,
                "logic": f"动量{mom_n}日 Top20→近高5日 Top5",
                "cond_ic_is": ic,
            },
        )
        sweep_rows.append(row)
        print(row["id"], "IS净夏普", round(row["n_is_sharpe"], 3), "买不进", row["skipped_buy"])
    sweep_mom = pd.DataFrame(sweep_rows)
    best_mom_n = int(sweep_mom.loc[sweep_mom["id"] == pick_is(sweep_mom), "mom_n"].iloc[0])
    print("best mom_n (IS, high=5)", best_mom_n)

    high_rows = []
    for high_n in high_ns:
        snap = make_snaps(cache_mom[best_mom_n], cache_near[high_n], stage1_k=20, stage2_k=5)
        ic = cond_ic(cache_mom[best_mom_n], cache_near[high_n], fwd, 20, IS_START, IS_END)
        row = ev(
            snap,
            f"mom{best_mom_n}_high{high_n}_k5",
            {
                "phase": "period",
                "mom_n": best_mom_n,
                "high_n": high_n,
                "logic": f"动量{best_mom_n} Top20→近高{high_n} Top5",
                "cond_ic_is": ic,
            },
        )
        high_rows.append(row)
        print(row["id"], "IS净夏普", round(row["n_is_sharpe"], 3), "买不进", row["skipped_buy"])
    extras = [
        (20, 20, "原 20/20 对照"),
        (5, 10, "无约束时的短窗候选"),
    ]
    extra_rows = []
    seen = {r["id"] for r in sweep_rows + high_rows}
    for mom_n, high_n, note in extras:
        vid = f"mom{mom_n}_high{high_n}_k5"
        if vid in seen:
            continue
        snap = make_snaps(cache_mom[mom_n], cache_near[high_n], stage1_k=20, stage2_k=5)
        ic = cond_ic(cache_mom[mom_n], cache_near[high_n], fwd, 20, IS_START, IS_END)
        extra_rows.append(
            ev(
                snap,
                vid,
                {
                    "phase": "period",
                    "mom_n": mom_n,
                    "high_n": high_n,
                    "logic": note,
                    "cond_ic_is": ic,
                },
            )
        )
        print(vid, "IS净夏普", round(extra_rows[-1]["n_is_sharpe"], 3))
    sweep = pd.concat(
        [sweep_mom, pd.DataFrame(high_rows), pd.DataFrame(extra_rows)],
        ignore_index=True,
    ).drop_duplicates("id")
    best_period_id = pick_is(sweep)
    best_period = sweep.loc[sweep["id"] == best_period_id].iloc[0]
    best_mom_n = int(best_period["mom_n"])
    best_high_n = int(best_period["high_n"])
    sweep.to_csv(OUT / "period_sweep" / "period_sweep_metrics.csv", index=False)
    (OUT / "period_sweep" / "period_sweep_summary.md").write_text(
        f"成交约束下选参只看 2020–2023 费用后夏普。best period = mom_n={best_mom_n}, "
        f"high_n={best_high_n} ({best_period_id})。现行默认 mom3/high5/k5。\n",
        encoding="utf-8",
    )

    mom = cache_mom[best_mom_n]
    near = cache_near[best_high_n]

    ablations = [
        (
            "orig_two_stage",
            make_snaps(mom, near, stage1_k=20, stage2_k=5),
            "保留两段",
            "core",
            "动量Top20→近高Top5",
        ),
        (
            "drop_stage1_near_only",
            make_snaps(near, None, stage1_k=5, stage2_k=5, use_s1=True),
            "去掉动量门，全宇宙近高Top5",
            "harmful_test",
            "验证：全宇宙近高",
        ),
        (
            "invert_stage2_far",
            make_snaps(mom, near, stage1_k=20, stage2_k=5, invert2=True),
            "动量Top20→远离前高",
            "harmful_test",
            "验证：应做多贴前高",
        ),
        (
            "invert_stage1_lowmom",
            make_snaps(mom, near, stage1_k=20, stage2_k=5, invert1=True),
            "动量最弱20→近高Top5",
            "harmful_test",
            "验证：一段动量门",
        ),
        (
            "mom_only_top5",
            make_snaps(mom, None, stage1_k=5, stage2_k=5),
            "只有动量Top5",
            "harmful_test",
            "去掉近高第二段",
        ),
        (
            "mom_top20_ew",
            make_snaps(mom, None, stage1_k=20, stage2_k=20),
            "动量Top20等权，无二段",
            "harmful_test",
            "去掉选5",
        ),
        (
            "stage2_persist",
            make_snaps(mom, persist, stage1_k=20, stage2_k=5),
            "二段改上涨日占比",
            "helpful_test",
            "替换近高",
        ),
        (
            "stage2_not_climax",
            make_snaps(mom, -roc5, stage1_k=20, stage2_k=5),
            "二段改未拉直（5日涨幅低）",
            "helpful_test",
            "替换近高",
        ),
    ]
    abl_rows = []
    for name, snap, logic, tag, note in ablations:
        row = ev(
            snap,
            name,
            {
                "phase": "ablation",
                "mom_n": best_mom_n,
                "high_n": best_high_n,
                "logic": logic,
                "tag": tag,
                "note": note,
            },
        )
        abl_rows.append(row)
        print(name, "IS净夏普", round(row["n_is_sharpe"], 3), "OOS净", round(row["n_oos_sharpe"], 3))
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

    def add(name, snap, logic):
        refinements.append((name, snap, logic))

    add(
        "core_k5_s20",
        make_snaps(core_s1, core_s2, stage1_k=20, stage2_k=5, invert2=core_invert2),
        "core 原 k=5 一段20",
    )
    add("k3", make_snaps(core_s1, core_s2, stage1_k=20, stage2_k=3, invert2=core_invert2), "收到 3 只")
    add("k8", make_snaps(core_s1, core_s2, stage1_k=20, stage2_k=8, invert2=core_invert2), "收到 8 只")
    add("k10", make_snaps(core_s1, core_s2, stage1_k=20, stage2_k=10, invert2=core_invert2), "收到 10 只")
    add("s1_10", make_snaps(core_s1, core_s2, stage1_k=10, stage2_k=5, invert2=core_invert2), "一段 Top10")
    add("s1_30", make_snaps(core_s1, core_s2, stage1_k=30, stage2_k=5, invert2=core_invert2), "一段 Top30")
    add(
        "biweekly",
        make_snaps(
            core_s1, core_s2, stage1_k=20, stage2_k=5, invert2=core_invert2, every_n_weeks=2
        ),
        "两周调一次降换手",
    )
    add(
        "exclude_lu_close",
        make_snaps(
            core_s1,
            core_s2,
            stage1_k=20,
            stage2_k=5,
            invert2=core_invert2,
            drop_lu=close_lu,
        ),
        "排名日收盘涨停的票顺延，避开周一买不进",
    )
    hyst_base = make_snaps(core_s1, core_s2, stage1_k=20, stage2_k=5, invert2=core_invert2)
    hyst = {}
    prev_pick: set[str] = set()
    for w in sorted(hyst_base):
        fresh = hyst_base[w]
        keep = prev_pick & fresh
        need = 5 - len(keep)
        extra = [x for x in fresh if x not in keep][: max(need, 0)]
        hyst[w] = set(list(keep) + extra) if extra or keep else fresh
        prev_pick = hyst[w]
    add("hysteresis", hyst, "仍进第二段则续持，降低换名")

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
        print(
            name,
            "IS净夏普",
            round(row["n_is_sharpe"], 3),
            "换手",
            round(row["week_turn"], 3),
            "OOS净",
            round(row["n_oos_sharpe"], 3),
            "买不进",
            row["skipped_buy"],
        )
    ref = pd.DataFrame(ref_rows)
    ref.to_csv(OUT / "refinement" / "refinement_metrics.csv", index=False)
    best_final_id = pick_is(ref)
    orig = sweep.loc[sweep["id"] == "mom3_high5_k5"]
    orig_is = float(orig.iloc[0]["n_is_sharpe"]) if len(orig) else float("nan")
    best_final = ref.loc[ref["id"] == best_final_id].iloc[0]
    (OUT / "refinement" / "refinement_summary.md").write_text(
        f"core={core_id}。IS 选出 best_final={best_final_id}，IS净夏普 {best_final['n_is_sharpe']:.3f}。"
        f"现行默认 mom3_high5_k5 IS净夏普 {orig_is:.3f}。\n",
        encoding="utf-8",
    )

    cols = [
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
    n_period = int(len(sweep))
    n_ablation = int(len(abl))
    n_refine = int(len(ref))
    manifest["n_period"] = n_period
    manifest["n_ablation"] = n_ablation
    manifest["n_refine"] = n_refine
    (OUT / "00_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    report = f"""# 因子11 优化报告（成交约束）

研究回测，不构成投资建议。默认策略10 参数未改。

## 原始因子

- 因子11 / 策略10 现行默认：周频 **3 日动量 Top20 → 贴近 5 日高点 Top5**，下一周等权持有
- 源码：`strategy/near_high_hold.py`
- 数据：沪深300+中证500+中证1000 当前成分 OHLC；幸存者偏差
- 成交：**一字涨停开盘买不进**（开盘已达涨停则放弃当日，周内未封可补买）；**一字跌停封单卖不出**
- 标签：close[T+1+5]/close[T+1]-1（条件 IC）
- 选参：仅 {IS_START}～{IS_END} **费用后夏普**（实现换手 × 一轮含滑点）
- 确认：{OOS_START}～{OOS_END}；验证：{VAL_START}～{VAL_END}。两者不参与选择
- 费率：{fee_rules_text()}

上一轮无约束网格把短窗抬到纸面夏普 9+，那是能买到连板的结果，本轮作废。

## Period Sweep

{md_table(sweep, cols)}

- Best period：**mom_n={best_mom_n}, high_n={best_high_n}**（{best_period_id}）
- 现行默认 mom3/high5；原注册 20/20 见对照行。选参未看 2024 起。

## Ablation（固定 best period）

{md_table(abl, cols + ["tag"])}

- IS 选出的 core：**{core_id}**

## Refinement（best period + core）

{md_table(ref, cols)}

- Best final：**{best_final_id}**
- 相对现行默认：IS 净夏普 {orig_is:.3f} → {float(best_final['n_is_sharpe']):.3f}；
  2024–2025 净夏普 {float(best_final['n_oos_sharpe']):.3f}；2026 净夏普 {float(best_final['n_val_sharpe']):.3f}（确认，不参与选择）

## 稳健性

- 参数：见 sweep。若 best 落在最短/最长端点，视为不够稳健。
- 时间：2024–2025 / 2026 只确认；2026 样本短。OOS 上一轮已看过，确认段不干净。
- 成交：买不进次数见 skipped_buy。短窗通常买不进更多。
- 成本：费用按**实现换手**扣，不是名单换手。
- 搜索：period {n_period} + ablation {n_ablation} + refine {n_refine}，计入多重检验。
- 未验证：点时指数成分、开盘价成交（仍是收盘对收盘，只拦一字开盘）、行业中性。

## 最终决策

**研究候选，不替换原因子。** 策略10 默认仍是 mom_n=3, high_n=5, k=5。若采用 best final，须用户明确同意后再改 `DEFAULT_PARAMS`。

结论上限：探索性。

本报告仅供研究参考，不构成任何投资建议。
"""
    (OUT / "optimize_report.md").write_text(report, encoding="utf-8")
    print("BEST PERIOD", best_period_id)
    print("CORE", core_id)
    print("BEST FINAL", best_final_id)


if __name__ == "__main__":
    main()
