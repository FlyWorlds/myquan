"""因子13 · 策略一因子1 契合选股（质量带 Walk-Forward）。

推荐规则（quality_v3）：
  · 阈值固定 ±2.5%
  · 上年夏普 ∈ [1.0, 2.2]（偏高但排除极端）
  · 上年策略回撤 ∈ [18%, 32%]（目标带 20–30 的可交易放宽）
  · 策略回撤 / 持有回撤 ≤ 0.55（目标 ≤0.5）
  · 按 score_quality 排序取 Top8
  · 下一年等权跑因子1
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_MYQUAN = Path(__file__).resolve().parents[1]
_RULE_PATHS = [
    _MYQUAN / "backtest" / "factor13_quality_opt" / "best_rule.json",
    _MYQUAN / "backtest" / "factor13_walkforward" / "best_rule.json",
]

DEFAULT_PARAMS: dict[str, Any] = {
    "signal": "score_quality",
    "top_k": 10,
    "min_sharpe": 1.0,
    "max_sharpe": 2.2,
    "mdd_lo": 18.0,
    "mdd_hi": 32.0,
    "dd_ratio_max": 0.55,
    "thr_mode": "0.025",
    "threshold_pct": 0.025,
    "mainboard_only": True,
}


def load_best_rule() -> dict[str, Any]:
    for path in _RULE_PATHS:
        if path.exists():
            return {**DEFAULT_PARAMS, **json.loads(path.read_text(encoding="utf-8"))}
    return dict(DEFAULT_PARAMS)


def factor13_rules_text(params: dict[str, Any] | None = None) -> str:
    p = {**load_best_rule(), **(params or {})}
    return f"""
================================================================================
  因子13 · 策略1契合选股（质量带）
================================================================================
选股年 T → 持有交易年 T+1（不看下一年行情）
阈值模式：{p.get('thr_mode')}（默认开盘突破 ±{float(p.get('threshold_pct', 0.025))*100:.1f}%）
硬过滤：
  · 夏普 ∈ [{p.get('min_sharpe')}, {p.get('max_sharpe')}]  （大点但不要极端）
  · 策略最大回撤 ∈ [{p.get('mdd_lo')}%, {p.get('mdd_hi')}%]
  · 策略回撤/持有回撤 ≤ {p.get('dd_ratio_max')}
排序：{p.get('signal')} ；名额 Top{p.get('top_k')}
score_quality ≈ 超额分位 + 夏普分位 + 回撤甜区(≈25%) + 低回撤比
================================================================================
"""


def _pct_rank(s: pd.Series) -> pd.Series:
    return s.rank(method="average", pct=True)


def enrich_cross_section_scores(year_df: pd.DataFrame) -> pd.DataFrame:
    g = year_df.copy()
    if g.empty:
        return g
    if "dd_ratio" not in g.columns:
        g["dd_ratio"] = g["mdd"] / g["bh_dd"].replace(0, np.nan)
    g["rk_excess"] = _pct_rank(g["excess"])
    g["rk_sharpe"] = _pct_rank(g["sharpe"])
    g["rk_dd_imp"] = _pct_rank(g["dd_improve"])
    g["rk_ret"] = _pct_rank(g["ret"])
    g["mdd_sweet"] = np.exp(-0.5 * ((g["mdd"] - 25.0) / 6.0) ** 2)
    g["rk_mdd_sweet"] = _pct_rank(g["mdd_sweet"])
    g["rk_dd_ratio_inv"] = _pct_rank(-g["dd_ratio"])
    g["score_esd"] = 5 * g["rk_excess"] + 3 * g["rk_sharpe"] + 2 * g["rk_dd_imp"]
    g["score_fit"] = 4 * g["rk_excess"] + 3 * g["rk_sharpe"] + 2 * g["rk_dd_imp"] + g["rk_ret"]
    g["score_quality"] = (
        3 * g["rk_excess"]
        + 2 * g["rk_sharpe"]
        + 2 * g["rk_mdd_sweet"]
        + 2 * g["rk_dd_ratio_inv"]
        + 1 * g["rk_dd_imp"]
    )
    return g


def apply_quality_filters(g: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    out = g.copy()
    lo = params.get("min_sharpe")
    hi = params.get("max_sharpe")
    if lo is not None and lo != "":
        out = out[out["sharpe"] >= float(lo)]
    if hi is not None and hi != "":
        out = out[out["sharpe"] <= float(hi)]
    if params.get("mdd_lo") is not None:
        out = out[out["mdd"] >= float(params["mdd_lo"])]
    if params.get("mdd_hi") is not None:
        out = out[out["mdd"] <= float(params["mdd_hi"])]
    if params.get("dd_ratio_max") is not None:
        if "dd_ratio" not in out.columns:
            out["dd_ratio"] = out["mdd"] / out["bh_dd"].replace(0, np.nan)
        out = out[out["dd_ratio"] <= float(params["dd_ratio_max"])]
        out = out[out["bh_dd"] > 5]
    return out


def select_for_next_year(
    scored_year: pd.DataFrame,
    *,
    params: dict[str, Any] | None = None,
) -> pd.DataFrame:
    p = {**load_best_rule(), **(params or {})}
    g = enrich_cross_section_scores(scored_year)
    if bool(p.get("mainboard_only", True)) and "mainboard" in g.columns:
        g = g[g["mainboard"].astype(int) == 1]
    g = apply_quality_filters(g, p)
    sig = str(p.get("signal", "score_quality"))
    if sig not in g.columns:
        raise KeyError(f"选股列不存在: {sig}")
    g = g.dropna(subset=[sig]).sort_values(sig, ascending=False)
    return g.head(int(p.get("top_k", 8))).reset_index(drop=True)


def factor13_signal(
    *,
    year_panel: pd.DataFrame | None = None,
    fit_year: int | None = None,
    scored_year: pd.DataFrame | None = None,
    params: dict[str, Any] | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    p = {**load_best_rule(), **(params or {})}
    if scored_year is None:
        cache = _MYQUAN / "backtest" / "factor13_quality_opt" / "year_thr_panel.parquet"
        if year_panel is None:
            if not cache.exists():
                raise ValueError("缺少年面板，请先跑 strategy/run_factor13_quality_opt.py")
            year_panel = pd.read_parquet(cache)
        if fit_year is None:
            fit_year = int(year_panel["year"].max())
        thr_mode = str(p.get("thr_mode", "0.025"))
        scored_year = year_panel[
            (year_panel["year"] == int(fit_year)) & (year_panel["thr_mode"] == thr_mode)
        ].copy()
    picks = select_for_next_year(scored_year, params=p)
    return {
        "factor_id": "factor13",
        "params": p,
        "fit_year": fit_year,
        "hold_year": (int(fit_year) + 1) if fit_year is not None else None,
        "picks": picks,
        "universe": picks["symbol"].tolist() if len(picks) else [],
        "rules_text": factor13_rules_text(p),
    }
