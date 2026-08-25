"""因子13·夏普波动率契合选股。

用 2020–2025 策略一·因子1（开盘突破 ±2.5%）分年夏普序列：
  · sharpe_mean  —— 多年平均夏普（策略有效）
  · sharpe_vol   —— 年夏普标准差（夏普波动率；稳定可复现）
  · pos_yr / pos_ex —— 正收益年、正超额年占比（正反馈）
  · feedback     —— 上年正超额 → 下年仍正超额 的条件概率
  · ex_mean / dd_imp_mean —— 平均超额与回撤改善

契合带参考天通/凯盛：sharpe_mean≈0.7–1.1，sharpe_vol≈0.45–0.55。
股票池：中证500∪1000 主板（≈中证1500中小盘），剔创业板/科创板/ST。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

DEFAULT_PARAMS: dict[str, Any] = {
    "top_k": 8,
    "min_years": 5,
    "min_sharpe_mean": 0.45,
    "max_sharpe_mean": 2.0,
    "sharpe_vol_lo": 0.25,
    "sharpe_vol_hi": 0.95,
    "vol_sweet": 0.50,
    "vol_width": 0.35,
    "min_pos_yr": 0.50,
    "min_pos_ex": 0.40,
    "mainboard_only": True,
    "thr": 0.025,
    "fit_years": (2020, 2021, 2022, 2023, 2024, 2025),
}


def rules_text(params: dict[str, Any] | None = None) -> str:
    p = {**DEFAULT_PARAMS, **(params or {})}
    return f"""
================================================================================
  因子13 · 夏普波动率契合（策略1·因子1）
================================================================================
拟合窗：{p.get('fit_years')} 分年跑开盘突破 ±{float(p['thr'])*100:.1f}%
硬过滤：
  · 有效年数 ≥ {p['min_years']}
  · 年夏普均值 ∈ [{p['min_sharpe_mean']}, {p['max_sharpe_mean']}]
  · 夏普波动率(年std) ∈ [{p['sharpe_vol_lo']}, {p['sharpe_vol_hi']}]
  · 正收益年占比 ≥ {p['min_pos_yr']}；正超额年 ≥ {p['min_pos_ex']}
排序 score_sv（分位加权）：
  3·夏普均值 + 2·夏普波动率甜区(≈{p['vol_sweet']}) + 2·正超额占比
  + 2·平均超额 + 1·回撤改善 + 1·正反馈(上年正超额→下年仍正)
取 Top{p['top_k']} → 下一期等权跑因子1
池：中证500∪1000主板，无创业板/科创板/ST
================================================================================
"""


def _pct_rank(s: pd.Series) -> pd.Series:
    return s.rank(method="average", pct=True)


def _vol_sweet(vol: pd.Series, center: float, width: float) -> pd.Series:
    return np.exp(-0.5 * ((vol - center) / max(width, 1e-6)) ** 2)


def _feedback_rate(years: np.ndarray, excess: np.ndarray) -> float:
    """上年超额>0 时，下年超额仍>0 的条件概率。"""
    order = np.argsort(years)
    y = years[order]
    e = excess[order]
    hits = 0
    tot = 0
    for i in range(len(y) - 1):
        if y[i + 1] != y[i] + 1:
            continue
        if e[i] > 0:
            tot += 1
            if e[i + 1] > 0:
                hits += 1
    if tot < 2:
        return float("nan")
    return hits / tot


def build_stock_features(
    year_panel: pd.DataFrame,
    *,
    params: dict[str, Any] | None = None,
    fit_end_year: int | None = None,
) -> pd.DataFrame:
    """从分年面板聚合成票级夏普波动率特征。"""
    p = {**DEFAULT_PARAMS, **(params or {})}
    thr = float(p["thr"])
    y0, y1 = int(p["fit_years"][0]), int(p["fit_years"][-1])
    if fit_end_year is not None:
        y1 = int(fit_end_year)

    df = year_panel.copy()
    if "thr" in df.columns:
        df = df[np.isclose(df["thr"].astype(float), thr)]
    df = df[(df["year"] >= y0) & (df["year"] <= y1)]
    if bool(p.get("mainboard_only", True)) and "mainboard" in df.columns:
        df = df[df["mainboard"].astype(int) == 1]
    df = df.drop_duplicates(subset=["symbol", "year"], keep="last")

    rows: list[dict] = []
    for sym, g in df.groupby("symbol"):
        g = g.sort_values("year")
        if len(g) < int(p["min_years"]):
            continue
        sh = g["sharpe"].to_numpy(float)
        ex = g["excess"].to_numpy(float)
        ret = g["ret"].to_numpy(float)
        yrs = g["year"].to_numpy(int)
        name = str(g["name"].iloc[0]) if "name" in g.columns else ""
        sh_mean = float(np.nanmean(sh))
        sh_vol = float(np.nanstd(sh, ddof=1)) if len(sh) >= 2 else float("nan")
        rows.append(
            {
                "symbol": str(sym).lower(),
                "name": name,
                "n_years": int(len(g)),
                "sharpe_mean": sh_mean,
                "sharpe_vol": sh_vol,
                "sharpe_min": float(np.nanmin(sh)),
                "sharpe_max": float(np.nanmax(sh)),
                "sharpe_cv": sh_vol / abs(sh_mean) if abs(sh_mean) > 1e-9 else float("nan"),
                "ret_mean": float(np.nanmean(ret)),
                "ex_mean": float(np.nanmean(ex)),
                "pos_yr": float(np.mean(ret > 0)),
                "pos_ex": float(np.mean(ex > 0)),
                "dd_imp_mean": float(np.nanmean(g["dd_improve"].to_numpy(float))),
                "mdd_mean": float(np.nanmean(g["mdd"].to_numpy(float))),
                "feedback": _feedback_rate(yrs, ex),
                "fit_end": y1,
            }
        )
    return pd.DataFrame(rows)


def enrich_scores(feat: pd.DataFrame, params: dict[str, Any] | None = None) -> pd.DataFrame:
    p = {**DEFAULT_PARAMS, **(params or {})}
    g = feat.copy()
    if g.empty:
        return g
    g["vol_sweet"] = _vol_sweet(
        g["sharpe_vol"], float(p["vol_sweet"]), float(p["vol_width"])
    )
    for col in (
        "sharpe_mean",
        "vol_sweet",
        "pos_ex",
        "pos_yr",
        "ex_mean",
        "dd_imp_mean",
        "feedback",
    ):
        g[f"rk_{col}"] = _pct_rank(g[col].fillna(g[col].median() if g[col].notna().any() else 0))
    g["score_sv"] = (
        3.0 * g["rk_sharpe_mean"]
        + 2.0 * g["rk_vol_sweet"]
        + 2.0 * g["rk_pos_ex"]
        + 2.0 * g["rk_ex_mean"]
        + 1.0 * g["rk_dd_imp_mean"]
        + 1.0 * g["rk_feedback"]
    )
    return g


def apply_filters(feat: pd.DataFrame, params: dict[str, Any] | None = None) -> pd.DataFrame:
    p = {**DEFAULT_PARAMS, **(params or {})}
    if feat is None or feat.empty or "n_years" not in feat.columns:
        return pd.DataFrame()
    out = feat.copy()
    out = out[out["n_years"] >= int(p["min_years"])]
    out = out[
        (out["sharpe_mean"] >= float(p["min_sharpe_mean"]))
        & (out["sharpe_mean"] <= float(p["max_sharpe_mean"]))
    ]
    out = out[
        (out["sharpe_vol"] >= float(p["sharpe_vol_lo"]))
        & (out["sharpe_vol"] <= float(p["sharpe_vol_hi"]))
    ]
    out = out[out["pos_yr"] >= float(p["min_pos_yr"])]
    out = out[out["pos_ex"] >= float(p["min_pos_ex"])]
    return out


def select_top(
    year_panel: pd.DataFrame,
    *,
    params: dict[str, Any] | None = None,
    fit_end_year: int | None = None,
    k: int | None = None,
) -> pd.DataFrame:
    p = {**DEFAULT_PARAMS, **(params or {})}
    # 短窗时压低最少年数要求（walk-forward 早期）
    y0 = int(p["fit_years"][0])
    y1 = int(fit_end_year if fit_end_year is not None else p["fit_years"][-1])
    avail = max(y1 - y0 + 1, 1)
    p = {**p, "min_years": min(int(p["min_years"]), avail)}
    feat = build_stock_features(year_panel, params=p, fit_end_year=fit_end_year)
    if feat.empty:
        return feat
    feat = enrich_scores(feat, p)
    filt = apply_filters(feat, p)
    if filt.empty:
        soft = p.copy()
        soft["sharpe_vol_lo"] = 0.10
        soft["sharpe_vol_hi"] = 1.50
        soft["min_pos_ex"] = 0.30
        soft["min_pos_yr"] = 0.40
        soft["min_sharpe_mean"] = 0.30
        filt = apply_filters(feat, soft)
    if filt.empty:
        filt = feat.sort_values("score_sv", ascending=False)
    out = filt.sort_values("score_sv", ascending=False)
    return out.head(int(k if k is not None else p["top_k"])).reset_index(drop=True)


def factor13_sv_signal(
    *,
    year_panel: pd.DataFrame | None = None,
    fit_end_year: int = 2025,
    params: dict[str, Any] | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    if year_panel is None:
        cache = root / "backtest" / "factor13_quality_opt" / "year_thr_panel.parquet"
        if not cache.exists():
            raise ValueError("缺少年面板，请先跑质量带/walkforward 脚本生成 year_thr_panel")
        year_panel = pd.read_parquet(cache)
    picks = select_top(year_panel, params=params, fit_end_year=fit_end_year)
    return {
        "factor": "factor13_sharpe_vol",
        "fit_end_year": fit_end_year,
        "n": len(picks),
        "symbols": picks["symbol"].tolist(),
        "names": picks["name"].tolist(),
        "picks": picks,
        "rules": rules_text(params),
    }
