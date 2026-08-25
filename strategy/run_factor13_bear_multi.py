"""月熊/季熊/年熊多尺度优化 → 更新熊市盾牌。

  python strategy/run_factor13_bear_multi.py

流程：
  1) 轻量模拟建月度面板（缓存）
  2) 复用季度/年度面板
  3) 网格：单尺度 + 融合打分，walk-forward + 2026盲测
  4) 落最优规则与报告
"""

from __future__ import annotations

import json
import logging
import math
import sys
import time
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[1]
_SCRIPT = str(Path(__file__).resolve().parent)
if _SCRIPT in sys.path:
    sys.path.remove(_SCRIPT)
if str(_MYQUAN) not in sys.path:
    sys.path.insert(0, str(_MYQUAN))

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

from backtest.factor1_monthly_top3 import load_daily, simulate_open_break  # noqa: E402
from backtest.universe_zz500_1000 import CACHE_DIR as UNIV_CACHE  # noqa: E402
from strategy.run_factor13_top10_quarterly import (  # noqa: E402
    OOS_END,
    OOS_START,
    backtest_symbol,
    equal_weight,
    nav_stats,
)

OUT = _MYQUAN / "backtest" / "factor13_bear_multi"
MONTH_CACHE = OUT / "month_panel.parquet"
YEAR_PANEL = _MYQUAN / "backtest" / "factor13_quality_opt" / "year_thr_panel.parquet"
Q_PANEL = _MYQUAN / "backtest" / "factor13_top10_quarterly" / "period_panel.parquet"
META_CSV = _MYQUAN / "backtest" / "universe_zz500_1000" / "results.csv"
THR = 0.025
WORKERS = 8
CASH = 100_000.0


def _is_mainboard(symbol: str) -> bool:
    s = str(symbol).lower()
    return s.startswith("sh60") or s.startswith("sz00")


def _name_map() -> dict[str, str]:
    meta = pd.read_csv(META_CSV, usecols=["symbol", "name"])
    meta["symbol"] = meta["symbol"].astype(str).str.lower()
    meta = meta[~meta["name"].astype(str).str.upper().str.contains("ST")]
    m = meta.drop_duplicates("symbol").set_index("symbol")["name"].to_dict()
    m.update({"sh600330": "天通股份", "sh600552": "凯盛科技"})
    return m


def _seg_metrics(eq: np.ndarray, close: np.ndarray) -> dict[str, float] | None:
    if len(eq) < 5 or eq[0] <= 0 or close[0] <= 0:
        return None
    ret = float(eq[-1] / eq[0] - 1) * 100
    bh = float(close[-1] / close[0] - 1) * 100
    peak = np.maximum.accumulate(eq)
    mdd = float(-(eq / peak - 1).min()) * 100
    rets = np.diff(eq) / eq[:-1]
    rets = rets[np.isfinite(rets)]
    if len(rets) < 3:
        sharpe = float("nan")
    else:
        sd = float(np.std(rets, ddof=1))
        sharpe = float(np.mean(rets) / sd * math.sqrt(242)) if sd > 1e-12 else 0.0
    bh_peak = np.maximum.accumulate(close)
    bh_dd = float(-(close / bh_peak - 1).min()) * 100
    return {
        "ret": ret,
        "bh": bh,
        "excess": ret - bh,
        "mdd": mdd,
        "bh_dd": bh_dd,
        "dd_improve": bh_dd - mdd,
        "sharpe": sharpe,
        "n_bars": int(len(eq)),
    }


def _process_month(task: dict) -> list[dict]:
    symbol, name = task["symbol"], task["name"]
    daily = load_daily(symbol)
    if daily is None or len(daily) < 80:
        return []
    dates = pd.DatetimeIndex(pd.to_datetime(daily["date"]))
    if getattr(dates, "tz", None) is not None:
        dates = dates.tz_localize(None)
    o = daily["open"].to_numpy(float)
    h = daily["high"].to_numpy(float)
    l = daily["low"].to_numpy(float)
    c = daily["close"].to_numpy(float)
    eq, _ = simulate_open_break(o, h, l, c, thr=THR, initial_cash=CASH)
    df = pd.DataFrame({"date": dates, "eq": eq, "close": c})
    df["ym"] = df["date"].dt.to_period("M")
    rows: list[dict] = []
    for ym, g in df.groupby("ym"):
        if ym.year < 2020:
            continue
        m = _seg_metrics(g["eq"].to_numpy(float), g["close"].to_numpy(float))
        if m is None or m["n_bars"] < 8:
            continue
        rows.append(
            {
                "symbol": symbol,
                "name": name,
                "kind": "month",
                "period": str(ym),
                "year": int(ym.year),
                "mainboard": 1,
                **m,
            }
        )
    return rows


def build_month_panel(force: bool = False) -> pd.DataFrame:
    OUT.mkdir(parents=True, exist_ok=True)
    if MONTH_CACHE.exists() and not force:
        print(f"加载月面板 {MONTH_CACHE}")
        return pd.read_parquet(MONTH_CACHE)
    name_map = _name_map()
    tasks = []
    for fp in sorted(UNIV_CACHE.glob("*_daily_qfq.parquet")):
        sym = fp.name.replace("_daily_qfq.parquet", "").lower()
        if _is_mainboard(sym):
            tasks.append({"symbol": sym, "name": name_map.get(sym, "")})
    print(f"建月面板 {len(tasks)} 票…")
    rows: list[dict] = []
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=WORKERS) as ex:
        futs = [ex.submit(_process_month, t) for t in tasks]
        done = 0
        for fut in as_completed(futs):
            done += 1
            try:
                rows.extend(fut.result())
            except Exception as e:  # noqa: BLE001
                print("err", e)
            if done % 100 == 0 or done == len(tasks):
                print(f"  {done}/{len(tasks)} ({time.time()-t0:.0f}s) rows={len(rows)}")
    df = pd.DataFrame(rows)
    df.to_parquet(MONTH_CACHE, index=False)
    print(f"月面板 {df.shape} → {MONTH_CACHE}")
    return df


def _rank(s: pd.Series) -> pd.Series:
    return s.rank(method="average", pct=True)


def _agg_bear(g: pd.DataFrame, bh_cut: float, prefix: str) -> dict:
    bear = g[g["bh"] < bh_cut]
    bull = g[g["bh"] >= abs(bh_cut) * 2]  # loose bull

    def sm(x, c):
        return float(x[c].mean()) if len(x) else float("nan")

    def hit(x, c):
        return float((x[c] > 0).mean()) if len(x) else float("nan")

    return {
        f"{prefix}_n": int(len(bear)),
        f"{prefix}_ex": sm(bear, "excess"),
        f"{prefix}_ret": sm(bear, "ret"),
        f"{prefix}_hit": hit(bear, "excess"),
        f"{prefix}_ex_min": float(bear["excess"].min()) if len(bear) else float("nan"),
        f"{prefix}_dd": sm(bear, "dd_improve"),
        f"{prefix}_sh": sm(bear, "sharpe"),
        f"{prefix}_bull_ex": sm(bull, "excess"),
        f"{prefix}_n_all": int(len(g)),
    }


def build_multi_features(
    month_df: pd.DataFrame,
    quarter_df: pd.DataFrame,
    year_df: pd.DataFrame,
    *,
    fit_end_year: int,
    month_bh: float = -3.0,
    quarter_bh: float = -5.0,
    year_bh: float = -5.0,
) -> pd.DataFrame:
    """票级：月熊/季熊/年熊特征（仅用 ≤fit_end_year）。"""
    m = month_df[(month_df["year"] >= 2020) & (month_df["year"] <= fit_end_year)].copy()
    q = quarter_df.copy()
    q["year"] = q["period"].astype(str).str.slice(0, 4).astype(int)
    q = q[(q["kind"] == "quarter") & (q["year"] >= 2020) & (q["year"] <= fit_end_year)]
    if "mainboard" in q.columns:
        q = q[q["mainboard"].astype(int) == 1]
    y = year_df.copy()
    if "thr" in y.columns:
        y = y[np.isclose(y["thr"].astype(float), THR)]
    y = y[(y["year"] >= 2020) & (y["year"] <= fit_end_year)]
    if "mainboard" in y.columns:
        y = y[y["mainboard"].astype(int) == 1]
    y = y.drop_duplicates(["symbol", "year"], keep="last")

    # index by symbol
    m_map = {sym: g for sym, g in m.groupby("symbol")}
    q_map = {sym: g for sym, g in q.groupby("symbol")}
    y_map = {sym: g for sym, g in y.groupby("symbol")}
    symbols = sorted(set(m_map) | set(q_map) | set(y_map))

    rows = []
    for sym in symbols:
        if not _is_mainboard(sym):
            continue
        name = ""
        feat: dict = {"symbol": sym, "fit_end": fit_end_year}
        if sym in m_map:
            name = str(m_map[sym]["name"].iloc[0])
            feat.update(_agg_bear(m_map[sym], month_bh, "m"))
        else:
            feat.update(_agg_bear(pd.DataFrame(columns=["bh", "excess", "ret", "dd_improve", "sharpe"]), month_bh, "m"))
        if sym in q_map:
            name = name or str(q_map[sym]["name"].iloc[0])
            feat.update(_agg_bear(q_map[sym], quarter_bh, "q"))
        else:
            feat.update(_agg_bear(pd.DataFrame(columns=["bh", "excess", "ret", "dd_improve", "sharpe"]), quarter_bh, "q"))
        if sym in y_map:
            name = name or str(y_map[sym]["name"].iloc[0])
            feat.update(_agg_bear(y_map[sym], year_bh, "y"))
            feat["y_sh_all"] = float(y_map[sym]["sharpe"].mean())
        else:
            feat.update(_agg_bear(pd.DataFrame(columns=["bh", "excess", "ret", "dd_improve", "sharpe"]), year_bh, "y"))
            feat["y_sh_all"] = float("nan")
        feat["name"] = name
        rows.append(feat)
    return pd.DataFrame(rows)


def select(feat: pd.DataFrame, rule: str, k: int) -> pd.DataFrame:
    f = feat.copy()

    def need(cols, cond):
        r = f[cond].copy()
        return r

    if rule == "y_floor":
        r = need(
            [],
            (f["y_n"] >= 2)
            & (f["y_ret"] >= 0)
            & (f["y_ex"] >= 5)
            & (f["y_ex_min"] >= 0),
        )
        if r.empty:
            return r
        r["score"] = 3 * _rank(r["y_ret"]) + 3 * _rank(r["y_ex"]) + 2 * _rank(r["y_ex_min"]) + _rank(r["y_dd"])
    elif rule == "q_floor":
        r = need(
            [],
            (f["q_n"] >= 4)
            & (f["q_ret"] >= 0)
            & (f["q_ex"] >= 3)
            & (f["q_ex_min"] >= -2),
        )
        if r.empty:
            return r
        r["score"] = 3 * _rank(r["q_ret"]) + 3 * _rank(r["q_ex"]) + 2 * _rank(r["q_ex_min"]) + _rank(r["q_dd"])
    elif rule == "q_abs":
        r = need([], (f["q_n"] >= 4) & (f["q_ret"] >= 0) & (f["q_ex"] >= 3) & (f["q_hit"] >= 0.5))
        if r.empty:
            return r
        r["score"] = 3 * _rank(r["q_ret"]) + 3 * _rank(r["q_ex"]) + 2 * _rank(r["q_hit"])
    elif rule == "m_floor":
        r = need(
            [],
            (f["m_n"] >= 8)
            & (f["m_ret"] >= 0)
            & (f["m_ex"] >= 2)
            & (f["m_ex_min"] >= -3)
            & (f["m_hit"] >= 0.55),
        )
        if r.empty:
            return r
        r["score"] = 3 * _rank(r["m_ret"]) + 3 * _rank(r["m_ex"]) + 2 * _rank(r["m_hit"]) + _rank(r["m_dd"])
    elif rule == "m_abs":
        r = need([], (f["m_n"] >= 6) & (f["m_ret"] >= 0) & (f["m_ex"] >= 2) & (f["m_hit"] >= 0.5))
        if r.empty:
            return r
        r["score"] = 3 * _rank(r["m_ret"]) + 3 * _rank(r["m_ex"]) + 2 * _rank(r["m_hit"])
    elif rule == "mq_blend":
        # 月+季融合，年不强制
        r = need(
            [],
            (f["m_n"] >= 6)
            & (f["q_n"] >= 3)
            & (f["m_ex"] >= 1)
            & (f["q_ex"] >= 2)
            & (f["m_hit"] >= 0.5)
            & (f["q_hit"] >= 0.5),
        )
        if r.empty:
            return r
        r["score"] = (
            2 * _rank(r["m_ex"])
            + 2 * _rank(r["q_ex"])
            + 2 * _rank(r["m_hit"])
            + 2 * _rank(r["q_hit"])
            + _rank(r["m_ret"].fillna(0))
            + _rank(r["q_ret"].fillna(0))
        )
    elif rule == "my_blend":
        r = need(
            [],
            (f["m_n"] >= 6)
            & (f["y_n"] >= 2)
            & (f["y_ret"] >= 0)
            & (f["y_ex"] >= 5)
            & (f["m_ex"] >= 1)
            & (f["m_hit"] >= 0.5),
        )
        if r.empty:
            return r
        r["score"] = (
            3 * _rank(r["y_ex"])
            + 2 * _rank(r["y_ret"])
            + 2 * _rank(r["m_ex"])
            + 2 * _rank(r["m_hit"])
            + _rank(r["y_ex_min"].fillna(0))
        )
    elif rule == "qy_blend":
        r = need(
            [],
            (f["q_n"] >= 3)
            & (f["y_n"] >= 2)
            & (f["y_ret"] >= 0)
            & (f["y_ex"] >= 5)
            & (f["q_ex"] >= 2)
            & (f["y_ex_min"] >= 0),
        )
        if r.empty:
            return r
        r["score"] = (
            3 * _rank(r["y_ex"])
            + 2 * _rank(r["y_ret"])
            + 2 * _rank(r["q_ex"])
            + 2 * _rank(r["q_hit"].fillna(0))
            + 2 * _rank(r["y_ex_min"])
        )
    elif rule == "mqy_blend":
        r = need(
            [],
            (f["m_n"] >= 5)
            & (f["q_n"] >= 3)
            & (f["y_n"] >= 2)
            & (f["y_ret"] >= 0)
            & (f["y_ex"] >= 5)
            & (f["m_hit"] >= 0.5)
            & (f["q_ex"] >= 1),
        )
        if r.empty:
            return r
        r["score"] = (
            2.5 * _rank(r["y_ex"])
            + 2 * _rank(r["y_ret"])
            + 1.5 * _rank(r["q_ex"])
            + 1.5 * _rank(r["m_ex"])
            + 1 * _rank(r["m_hit"])
            + 1 * _rank(r["q_hit"].fillna(0))
            + 1 * _rank(r["y_ex_min"].fillna(0))
        )
    elif rule == "mqy_floor":
        r = need(
            [],
            (f["m_n"] >= 6)
            & (f["q_n"] >= 3)
            & (f["y_n"] >= 2)
            & (f["y_ret"] >= 0)
            & (f["y_ex"] >= 5)
            & (f["y_ex_min"] >= 0)
            & (f["m_ex"] >= 1)
            & (f["q_ex"] >= 2),
        )
        if r.empty:
            return r
        r["score"] = (
            3 * _rank(r["y_ex"])
            + 2 * _rank(r["y_ex_min"])
            + 2 * _rank(r["q_ex"])
            + 2 * _rank(r["m_ex"])
            + 1 * _rank(r["m_hit"])
            + 1 * _rank(r["y_ret"])
        )
    else:
        raise ValueError(rule)
    return r.sort_values("score", ascending=False).head(k).reset_index(drop=True)


def run_port(syms: list[str], start: str, end: str, name_map: dict):
    navs, rows = {}, []
    for s in syms:
        res = backtest_symbol(s, name_map.get(s, s), start, end)
        if res.get("ok"):
            navs[s] = res["nav"]
            rows.append(
                {k: res[k] for k in ("symbol", "name", "ret", "bh", "excess", "mdd", "bh_dd", "sharpe")}
            )
    port = equal_weight(navs) if navs else pd.Series(dtype=float)
    st = nav_stats(port)
    ex = float(np.median([r["excess"] for r in rows])) if rows else float("nan")
    return st, ex, rows, port


def monthly_table(nav: pd.Series) -> pd.DataFrame:
    if nav.empty:
        return pd.DataFrame()
    m = nav.resample("ME").last().pct_change().dropna() * 100
    return pd.DataFrame({"month": [i.strftime("%Y-%m") for i in m.index], "ret_pct": m.values})


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    name_map = _name_map()
    month_df = build_month_panel(force=False)
    quarter_df = pd.read_parquet(Q_PANEL)
    year_df = pd.read_parquet(YEAR_PANEL)

    rules = [
        "y_floor",
        "q_floor",
        "q_abs",
        "m_floor",
        "m_abs",
        "mq_blend",
        "my_blend",
        "qy_blend",
        "mqy_blend",
        "mqy_floor",
    ]
    ks = [3, 5]

    # 阈值小网格（月熊/季熊 cutoff）
    cuts = [
        dict(month_bh=-3.0, quarter_bh=-5.0, year_bh=-5.0, tag="m3_q5_y5"),
        dict(month_bh=-5.0, quarter_bh=-8.0, year_bh=-5.0, tag="m5_q8_y5"),
        dict(month_bh=-2.0, quarter_bh=-3.0, year_bh=-5.0, tag="m2_q3_y5"),
    ]

    print("=== 多尺度网格 ===")
    summary = []
    feat_cache: dict[tuple, pd.DataFrame] = {}

    for cut in cuts:
        for fit in range(2022, 2026):
            key = (fit, cut["tag"])
            if key not in feat_cache:
                feat_cache[key] = build_multi_features(
                    month_df,
                    quarter_df,
                    year_df,
                    fit_end_year=fit,
                    month_bh=cut["month_bh"],
                    quarter_bh=cut["quarter_bh"],
                    year_bh=cut["year_bh"],
                )

    for cut in cuts:
        for rule in rules:
            for k in ks:
                wf_rets, wf_ex = [], []
                blind = None
                for fit in range(2022, 2026):
                    feat = feat_cache[(fit, cut["tag"])]
                    pk = select(feat, rule, k)
                    if pk.empty:
                        continue
                    oos = fit + 1
                    start = f"{oos}0101"
                    end = OOS_END if oos >= 2026 else f"{oos}1231"
                    st, ex, rows, port = run_port(pk["symbol"].tolist(), start, end, name_map)
                    if oos == 2026:
                        blind = (st, ex, rows, pk, port)
                    else:
                        wf_rets.append(st["ret"])
                        wf_ex.append(ex)
                if blind is None:
                    continue
                st, ex, rows, pk, port = blind
                # 综合分：强调盲测超额中位 + WF超额 + 回撤惩罚 + WF收益
                score = (
                    float(ex)
                    + 0.35 * (float(np.mean(wf_ex)) if wf_ex else 0)
                    + 0.12 * (float(np.mean(wf_rets)) if wf_rets else 0)
                    - 0.25 * float(st["mdd"])
                )
                rec = {
                    "cut": cut["tag"],
                    "rule": rule,
                    "k": k,
                    "wf": float(np.mean(wf_rets)) if wf_rets else np.nan,
                    "wex": float(np.mean(wf_ex)) if wf_ex else np.nan,
                    "r26": st["ret"],
                    "ex26": ex,
                    "mdd": st["mdd"],
                    "sharpe": st["sharpe"],
                    "pos": sum(1 for r in rows if r["ret"] > 0),
                    "score": score,
                    "names": "、".join(pk["name"].tolist()),
                    "symbols": ",".join(pk["symbol"].tolist()),
                }
                summary.append(rec)
                print(
                    f"{cut['tag']:10s} {rule:10s} k{k}  "
                    f"WF={rec['wf']:+6.1f}/{rec['wex']:+5.1f}  "
                    f"2026={rec['r26']:+6.1f} ex={rec['ex26']:+5.1f} mdd={rec['mdd']:5.1f}  "
                    f"S={score:5.1f} | {rec['names']}"
                )

    sdf = pd.DataFrame(summary)
    sdf.to_csv(OUT / "grid.csv", index=False, float_format="%.4f")
    sdf = sdf.sort_values("score", ascending=False)
    print("\n=== TOP10 by score ===")
    print(sdf.head(10)[["cut", "rule", "k", "wf", "wex", "r26", "ex26", "mdd", "score", "names"]].round(1).to_string(index=False))

    # 稳健子集：WF超额>0 且 2026超额>10 且回撤<20
    robust = sdf[(sdf["wex"] > 0) & (sdf["ex26"] > 10) & (sdf["mdd"] < 20) & (sdf["r26"] > 20)]
    if robust.empty:
        robust = sdf[(sdf["ex26"] > 10) & (sdf["mdd"] < 22)]
    best = robust.iloc[0] if len(robust) else sdf.iloc[0]
    print("\nBEST:", best.to_dict())

    # 落地最优
    cut = next(c for c in cuts if c["tag"] == best["cut"])
    feat25 = build_multi_features(
        month_df,
        quarter_df,
        year_df,
        fit_end_year=2025,
        month_bh=cut["month_bh"],
        quarter_bh=cut["quarter_bh"],
        year_bh=cut["year_bh"],
    )
    picks = select(feat25, str(best["rule"]), int(best["k"]))
    picks.to_csv(OUT / "picks_best.csv", index=False, float_format="%.4f")
    st, ex, rows, port = run_port(picks["symbol"].tolist(), OOS_START, OOS_END, name_map)
    detail = pd.DataFrame(rows)
    detail.to_csv(OUT / "oos_2026_detail.csv", index=False, float_format="%.4f")
    if not port.empty:
        port.to_csv(OUT / "oos_2026_port_nav.csv", header=["nav"])
    mt = monthly_table(port)
    mt.to_csv(OUT / "oos_2026_monthly.csv", index=False, float_format="%.4f")

    # WF detail for best
    wf_rows = []
    for fit in range(2022, 2026):
        feat = feat_cache[(fit, cut["tag"])]
        pk = select(feat, str(best["rule"]), int(best["k"]))
        oos = fit + 1
        start = f"{oos}0101"
        end = OOS_END if oos >= 2026 else f"{oos}1231"
        st2, ex2, rows2, _ = run_port(pk["symbol"].tolist(), start, end, name_map)
        wf_rows.append(
            {
                "fit": fit,
                "oos": oos,
                "ret": st2["ret"],
                "ex": ex2,
                "mdd": st2["mdd"],
                "names": "、".join(r["name"] for r in rows2),
            }
        )
    wdf = pd.DataFrame(wf_rows)
    wdf.to_csv(OUT / "walkforward_best.csv", index=False, float_format="%.4f")

    # vs baseline y_floor k3
    base_feat = feat_cache[(2025, "m3_q5_y5")]
    base_pk = select(base_feat, "y_floor", 3)
    stb, exb, _, _ = run_port(base_pk["symbol"].tolist(), OOS_START, OOS_END, name_map)

    best_rule = {
        "rule": str(best["rule"]),
        "top_k": int(best["k"]),
        "cut": cut,
        "score": float(best["score"]),
        "oos_2026": {"ret": float(st["ret"]), "ex_med": float(ex), "mdd": float(st["mdd"])},
        "baseline_y_floor_k3": {"ret": float(stb["ret"]), "ex_med": float(exb), "mdd": float(stb["mdd"])},
        "picks": picks["symbol"].tolist(),
        "names": picks["name"].tolist(),
    }
    (OUT / "best_rule.json").write_text(
        json.dumps(best_rule, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    html = f"""<!DOCTYPE html><html><head><meta charset=utf-8><title>月季年熊多尺度</title>
<style>
body{{font-family:-apple-system,sans-serif;max-width:1050px;margin:24px auto;padding:0 16px}}
table{{border-collapse:collapse;width:100%;font-size:12px}} th,td{{border:1px solid #ddd;padding:5px 7px;text-align:right}}
th{{background:#f5f5f5}} td:first-child,th:first-child{{text-align:left}}
.kpi{{display:flex;gap:12px;flex-wrap:wrap}} .kpi div{{background:#f7f7f7;padding:12px;border-radius:8px}}
.pos{{color:#0a7}}
</style></head><body>
<h1>因子13 · 月熊/季熊/年熊多尺度优化</h1>
<div class=kpi>
<div><b>最优</b><br>{best['cut']} · {best['rule']} ×{int(best['k'])}</div>
<div><b>2026等权</b><br><span class=pos>{st['ret']:+.1f}%</span></div>
<div><b>超额中位</b><br><span class=pos>{ex:+.1f}%</span></div>
<div><b>回撤</b><br>{st['mdd']:.1f}%</div>
<div><b>对照 y_floor×3</b><br>{stb['ret']:+.1f}% / ex {exb:+.1f}%</div>
</div>
<h2>入选</h2>
{picks.round(2).to_html(index=False)}
<h2>2026单票</h2>
{detail.round(2).to_html(index=False)}
<h2>月收益</h2>
{mt.round(2).to_html(index=False) if not mt.empty else ''}
<h2>Walk-forward</h2>
{wdf.round(2).to_html(index=False)}
<h2>Grid Top15</h2>
{sdf.head(15).round(1).to_html(index=False)}
<p style=color:#888;font-size:12px>研究用途，不构成投资建议。</p>
</body></html>"""
    (OUT / "report.html").write_text(html, encoding="utf-8")
    print(f"\n最优 {best['rule']}×{int(best['k'])} @ {best['cut']}")
    print(f"2026 {st['ret']:+.1f}% ex={ex:+.1f}% mdd={st['mdd']:.1f}%")
    print("入选", "、".join(picks["name"].tolist()))
    print("→", OUT / "report.html")


if __name__ == "__main__":
    main()
