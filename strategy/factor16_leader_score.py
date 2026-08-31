"""因子16：概念龙头评分（因子13质量带 + 因子1 OOS + 缠论笔对照）。

口径与 ``backtest/ai_concept_f1_f13_report.py`` / ``sectors/leader_score.py`` 一致：
  · FIT 2020–2023：因子13 ``score_quality`` + 质量带硬过滤（``f13_pass``）
  · OOS（默认 2025→今）：因子1 开盘±2.5% 盈亏比/胜率/超额/回撤
  · 缠论笔：OOS 窗 ``analyze_bi_pl_ratio`` 作对照列

研究用途，不构成投资建议。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from backtest.ai_concept_f1_f13_report import (  # noqa: E402
    FIT_END,
    FIT_START,
    MIN_BARS,
    OOS_START,
    THR,
    _slice_daily,
    _to_symbol,
    eval_window,
)
from strategy.factor13_fit import enrich_cross_section_scores, load_best_rule

FACTOR_ID = "factor16"
FACTOR_NAME = "因子16·概念龙头评分"

DEFAULT_PARAMS: dict[str, Any] = {
    "fit_start": FIT_START,
    "fit_end": FIT_END,
    "oos_start": OOS_START,
    "thr": THR,
    "min_bars": MIN_BARS,
    "min_oos_trades": 3,
    "top_k": 5,
    "mainboard_only": False,
    "rank_by": [
        "f13_pass",
        "oos_pl_ratio",
        "oos_profit_factor",
        "score_quality",
    ],
}

_FIT_RENAME = {
    "fit_ret": "ret",
    "fit_mdd": "mdd",
    "fit_sharpe": "sharpe",
    "fit_bh_ret": "bh_ret",
    "fit_bh_dd": "bh_dd",
    "fit_excess": "excess",
    "fit_dd_improve": "dd_improve",
}


def factor16_rules_text(params: dict[str, Any] | None = None) -> str:
    p = {**DEFAULT_PARAMS, **load_best_rule(), **(params or {})}
    return f"""
================================================================================
  因子16 · 概念龙头评分（F13质量带 + 因子1 OOS + 缠论笔）
================================================================================
定参 FIT : {p.get('fit_start')} → {p.get('fit_end')}
  · 因子13 截面 score_quality + 质量带硬过滤（f13_pass）
样本外 OOS: {p.get('oos_start')} → 今（可覆盖 oos_start/oos_end）
  · 策略一因子1 开盘 ±{float(p.get('thr', THR))*100:.1f}%：盈亏比、胜率、超额、回撤
  · 策略七缠论笔盈亏比（OOS 对照列，不参与主排序）
排序：F13通过优先 → OOS盈亏比 → 利润因子 → score_quality
门槛：FIT bars≥{p.get('min_bars')}；OOS 闭环≥{p.get('min_oos_trades')}
研究用途，不构成投资建议。
================================================================================
""".strip()


def f13_quality_pass_mask(scored: pd.DataFrame, rule: dict[str, Any]) -> pd.Series:
    """与 ai_concept_f1_f13_report 一致的质量带硬过滤。"""
    bands = rule.get("fill_bands") or [
        {
            "min_sharpe": rule.get("min_sharpe"),
            "max_sharpe": rule.get("max_sharpe"),
            "mdd_lo": rule.get("mdd_lo"),
            "mdd_hi": rule.get("mdd_hi"),
            "dd_ratio_max": rule.get("dd_ratio_max"),
        }
    ]
    pass_mask = pd.Series(False, index=scored.index)
    for band in bands:
        m = pd.Series(True, index=scored.index)
        if band.get("min_sharpe") is not None:
            m &= scored["sharpe"] >= float(band["min_sharpe"])
        if band.get("max_sharpe") is not None:
            m &= scored["sharpe"] <= float(band["max_sharpe"])
        if band.get("mdd_lo") is not None:
            m &= scored["mdd"] >= float(band["mdd_lo"])
        if band.get("mdd_hi") is not None:
            m &= scored["mdd"] <= float(band["mdd_hi"])
        if band.get("dd_ratio_max") is not None:
            m &= (scored["dd_ratio"] <= float(band["dd_ratio_max"])) & (scored["bh_dd"] > 5)
        if int(m.sum()) >= int(rule.get("top_k", 10)):
            pass_mask = m
            break
        pass_mask = pass_mask | m
    return pass_mask


def chan_oos_metrics(
    daily: pd.DataFrame,
    *,
    code: str,
    name: str,
    oos_start: str,
    oos_end: str,
    entry_pct: float = THR,
) -> dict[str, Any]:
    try:
        from strategy.bi_pl_ratio import analyze_bi_pl_ratio

        sub = _slice_daily(daily, oos_start, oos_end)
        if sub is None or len(sub) < 30:
            return {}
        sym = _to_symbol(code)
        if not sym:
            return {}
        res = analyze_bi_pl_ratio(
            sub,
            symbol=sym,
            symbol_name=name,
            entry_pct=entry_pct,
            max_bi_num=300,
            out_dir=None,
        )
        s = res.summary or {}
        return {
            "chan_pl_ratio": s.get("pl_ratio"),
            "chan_win_rate": s.get("win_rate_net"),
            "chan_trades": s.get("n_trades"),
            "chan_compound_pct": s.get("factor1_compound_net_pct"),
        }
    except Exception:
        return {}


def eval_stock_metrics_from_daily(
    code: str,
    daily: pd.DataFrame,
    *,
    name: str = "",
    oos_start: str = OOS_START,
    oos_end: str,
    fit_start: str = FIT_START,
    fit_end: str = FIT_END,
    with_chan: bool = True,
    entry_pct: float = THR,
) -> dict[str, Any] | None:
    """单票：FIT + OOS 因子1 指标，可选缠论 OOS 对照。"""
    symbol = _to_symbol(code)
    if not symbol:
        return None
    fit = eval_window(daily, fit_start, fit_end)
    oos = eval_window(daily, oos_start, oos_end)
    if int(fit.get("n_bars") or 0) < MIN_BARS:
        return None
    chan: dict[str, Any] = {}
    if with_chan:
        chan = chan_oos_metrics(
            daily,
            code=code,
            name=name,
            oos_start=oos_start,
            oos_end=oos_end,
            entry_pct=entry_pct,
        )
    dd_ratio = (
        fit["mdd"] / fit["bh_dd"]
        if fit.get("bh_dd") and fit["bh_dd"] > 0
        else np.nan
    )
    return {
        "code": str(code).zfill(6),
        "name": name or code,
        "symbol": symbol,
        "dd_ratio": dd_ratio,
        "fit_ret": fit["ret"],
        "fit_mdd": fit["mdd"],
        "fit_sharpe": fit["sharpe"],
        "fit_bh_ret": fit["bh_ret"],
        "fit_bh_dd": fit["bh_dd"],
        "fit_excess": fit["excess"],
        "fit_dd_improve": fit["dd_improve"],
        "fit_pl_ratio": fit["pl_ratio"],
        "fit_win_rate": fit["win_rate"],
        "fit_n_bars": fit["n_bars"],
        "oos_ret": oos["ret"],
        "oos_mdd": oos["mdd"],
        "oos_sharpe": oos["sharpe"],
        "oos_excess": oos["excess"],
        "oos_pl_ratio": oos["pl_ratio"],
        "oos_win_rate": oos["win_rate"],
        "oos_profit_factor": oos["profit_factor"],
        "oos_n_trades": oos["n_trades"],
        "oos_n_bars": oos["n_bars"],
        **chan,
    }


def attach_factor13_scores(
    metrics: pd.DataFrame,
    *,
    params: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """在指标表上附加因子13 score_quality / f13_pass。"""
    if metrics.empty:
        return metrics.copy()
    p = {**load_best_rule(), **DEFAULT_PARAMS, **(params or {})}
    if bool(p.get("mainboard_only", False)) and "mainboard" in metrics.columns:
        base = metrics[metrics["mainboard"].astype(int) == 1].copy()
    else:
        base = metrics.copy()
    scored = base.rename(columns=_FIT_RENAME)
    if "dd_ratio" not in scored.columns:
        scored["dd_ratio"] = scored["mdd"] / scored["bh_dd"].replace(0, np.nan)
    scored = enrich_cross_section_scores(scored)
    scored["f13_pass"] = f13_quality_pass_mask(scored, p).astype(int)
    merge_cols = ["code", "score_quality", "score_fit", "score_esd", "f13_pass"]
    if "code" not in base.columns and "symbol" in base.columns:
        merge_cols[0] = "symbol"
        scored = scored.rename(columns={"code": "symbol"})
    out = base.merge(scored[merge_cols], on=merge_cols[0], how="left")
    return out


def rank_leader_pool(
    scored: pd.DataFrame,
    *,
    top_k: int = 5,
    params: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """因子16 主排序：F13通过 → OOS盈亏比 → 利润因子 → score_quality。"""
    p = {**DEFAULT_PARAMS, **(params or {})}
    min_trades = int(p.get("min_oos_trades", 3))
    min_bars = int(p.get("min_bars", MIN_BARS))
    ranked = scored.copy()
    ranked["oos_pl_ratio"] = pd.to_numeric(ranked["oos_pl_ratio"], errors="coerce")
    ranked["score_quality"] = pd.to_numeric(ranked["score_quality"], errors="coerce")
    ranked = ranked[ranked["oos_n_trades"].fillna(0) >= min_trades]
    ranked = ranked[ranked["fit_n_bars"].fillna(0) >= min_bars]
    pool = ranked[ranked["f13_pass"] == 1].copy()
    if len(pool) < top_k:
        extra = ranked[ranked["f13_pass"] != 1].sort_values(
            "score_quality", ascending=False, na_position="last"
        )
        need = max(top_k * 4, 20) - len(pool)
        pool = pd.concat([pool, extra.head(max(0, need))], ignore_index=True)
    rank_cols = list(p.get("rank_by") or DEFAULT_PARAMS["rank_by"])
    asc = [False] * len(rank_cols)
    return pool.sort_values(
        by=rank_cols,
        ascending=asc,
        na_position="last",
    ).head(int(top_k))


def score_metrics_frame(
    metrics: pd.DataFrame,
    *,
    top_k: int | None = None,
    params: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """截面打分并排序（返回带 score_quality / f13_pass 的完整表，含 rank 列）。"""
    p = {**DEFAULT_PARAMS, **(params or {})}
    k = int(top_k if top_k is not None else p.get("top_k", 5))
    scored = attach_factor13_scores(metrics, params=p)
    top = rank_leader_pool(scored, top_k=k, params=p)
    top = top.copy()
    top["rank"] = range(1, len(top) + 1)
    return top


def factor16_signal(
    *,
    metrics: pd.DataFrame | None = None,
    top_k: int | None = None,
    params: dict[str, Any] | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    """因子16 信号：输入成分股指标表，输出排序后的 picks。"""
    p = {**DEFAULT_PARAMS, **load_best_rule(), **(params or {})}
    if metrics is None or metrics.empty:
        raise ValueError("factor16 需要非空 metrics 表（含 fit_* / oos_* 列）")
    k = int(top_k if top_k is not None else p.get("top_k", 5))
    picks = score_metrics_frame(metrics, top_k=k, params=p)
    return {
        "factor_id": FACTOR_ID,
        "params": p,
        "picks": picks,
        "universe": picks["code"].tolist() if "code" in picks.columns else [],
        "rules_text": factor16_rules_text(p),
        "scoring": {
            "quality": "因子13质量带（FIT 截面 score_quality + f13_pass）",
            "factor1": f"策略一因子1 OOS 盈亏比/胜率（±{float(p.get('thr', THR))*100:.1f}%）",
            "chan": "策略七缠论笔 OOS 对照",
            "rank": " → ".join(str(x) for x in p.get("rank_by", [])),
        },
    }


def format_leader_row(row: pd.Series | dict[str, Any], *, rank: int) -> dict[str, Any]:
    """API/Web 展示用单行格式化。"""

    def _get(key: str, default: Any = None) -> Any:
        if isinstance(row, pd.Series):
            return row.get(key, default)
        return row.get(key, default)

    def _f(v: Any, nd: int = 2) -> float | None:
        try:
            x = float(v)
        except (TypeError, ValueError):
            return None
        if not np.isfinite(x):
            return None
        return round(x, nd)

    chan_wr = _get("chan_win_rate")
    return {
        "rank": rank,
        "code": str(_get("code")),
        "name": str(_get("name") or _get("code")),
        "score_quality": _f(_get("score_quality"), 4),
        "f13_pass": bool(int(_get("f13_pass") or 0) == 1),
        "pl_ratio": _f(_get("oos_pl_ratio"), 3),
        "win_rate": _f(_get("oos_win_rate"), 2),
        "profit_factor": _f(_get("oos_profit_factor"), 3),
        "excess_pct": _f(_get("oos_excess"), 2),
        "mdd_pct": _f(_get("oos_mdd"), 2),
        "ret_pct": _f(_get("oos_ret"), 2),
        "sharpe_fit": _f(_get("fit_sharpe"), 3),
        "n_trades": int(_get("oos_n_trades") or 0),
        "chan_pl_ratio": _f(_get("chan_pl_ratio"), 3),
        "chan_win_rate": _f(float(chan_wr) * 100, 2)
        if chan_wr is not None and chan_wr == chan_wr
        else None,
        "chan_trades": int(_get("chan_trades") or 0),
    }
