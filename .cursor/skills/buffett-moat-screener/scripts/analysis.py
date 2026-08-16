"""Evaluate A-share companies as research candidates, never as buy signals."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd

from .core import BANK_PATTERN, CYCLICAL_PATTERN, DEFAULT_THRESHOLDS, FINANCIAL_PATTERN


RESEARCH_CHECKLIST = [
    "能力圈：能否用简洁语言解释商业模式、客户需求和主要风险？",
    "护城河：品牌、成本、网络效应或转换成本是否有可验证证据？",
    "资本配置：留存收益、分红、回购和并购是否提升每股内在价值？",
    "所有者收益：维持性资本开支和营运资本需求需要人工估计。",
    "估值纪律：与保守内在价值区间相比是否存在足够安全边际？",
    "机会成本：它是否显著优于当前最佳研究对象；现金和不行动均可接受。",
]


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _ratio(numerator: Any, denominator: Any) -> float | None:
    n, d = _finite(numerator), _finite(denominator)
    if n is None or d is None or d <= 0:
        return None
    return abs(n) / d


def _average_positive(left: Any, right: Any) -> float | None:
    first, second = _finite(left), _finite(right)
    if first is None or second is None or first <= 0 or second <= 0:
        return None
    return (first + second) / 2.0


def evaluate_company(
    symbol: str,
    annual_history: pd.DataFrame,
    *,
    industry: str,
    audit_status: str,
    thresholds: Mapping[str, float] | None = None,
    revision_conflicts: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    limits = {**DEFAULT_THRESHOLDS, **dict(thresholds or {})}
    history = annual_history[annual_history["symbol"] == symbol].copy()
    history = history.sort_values("year").drop_duplicates("year", keep="last")
    latest_source_date = (
        None if history.empty else str(history.iloc[-1].get("published_at") or "") or None
    )
    years = history["year"].dropna().astype(int).tolist() if "year" in history else []
    consecutive = len(years) >= 11 and years[-11:] == list(range(years[-1] - 10, years[-1] + 1))
    selected = history.tail(11) if consecutive else history.iloc[0:0]

    roe_values: list[float] = []
    roa_values: list[float] = []
    if len(selected) == 11:
        for index in range(1, 11):
            previous = selected.iloc[index - 1]
            current = selected.iloc[index]
            avg_equity = _average_positive(previous.get("parent_equity"), current.get("parent_equity"))
            avg_assets = _average_positive(previous.get("total_assets"), current.get("total_assets"))
            profit = _finite(current.get("parent_net_profit"))
            roe_values.append(np.nan if profit is None or avg_equity is None else profit / avg_equity * 100.0)
            roa_values.append(np.nan if profit is None or avg_assets is None else profit / avg_assets * 100.0)

    operating = selected.tail(10) if len(selected) == 11 else selected.iloc[0:0]
    margins = pd.to_numeric(operating.get("gross_profit"), errors="coerce") / pd.to_numeric(
        operating.get("revenue"), errors="coerce"
    ) * 100.0 if not operating.empty else pd.Series(dtype=float)
    latest = selected.iloc[-1] if len(selected) == 11 else None
    last_five = selected.tail(5) if len(selected) == 11 else selected.iloc[0:0]

    latest_profit = None if latest is None else _finite(latest.get("parent_net_profit"))
    latest_debt = None if latest is None else _finite(latest.get("long_term_interest_bearing_debt"))
    latest_eps = None if latest is None else _finite(latest.get("basic_eps"))
    latest_close = None if latest is None else _finite(latest.get("close"))
    debt_ratio = _ratio(latest_debt, latest_profit)
    pe_lyr = None if latest_eps is None or latest_eps <= 0 or latest_close is None else latest_close / latest_eps

    capex = pd.to_numeric(last_five.get("gross_capex"), errors="coerce") if not last_five.empty else pd.Series(dtype=float)
    profits = pd.to_numeric(last_five.get("parent_net_profit"), errors="coerce") if not last_five.empty else pd.Series(dtype=float)
    capex_ratio = None
    if len(capex) == 5 and capex.notna().all() and profits.notna().all() and profits.sum() > 0:
        capex_ratio = float(capex.abs().sum() / profits.sum())

    cash_proxy = None
    cash_conversion_5y = None
    if latest is not None:
        cfo = _finite(latest.get("operating_cash_flow"))
        latest_capex = _finite(latest.get("gross_capex"))
        if cfo is not None and latest_capex is not None:
            cash_proxy = cfo - abs(latest_capex)
    if not last_five.empty:
        cfo5 = pd.to_numeric(last_five.get("operating_cash_flow"), errors="coerce")
        if cfo5.notna().all() and capex.notna().all() and profits.notna().all() and profits.sum() > 0:
            cash_conversion_5y = float((cfo5.sum() - capex.abs().sum()) / profits.sum())

    roe_latest = None if not roe_values or pd.isna(roe_values[-1]) else float(roe_values[-1])
    roe_floor = None if not roe_values or pd.isna(roe_values).any() else float(min(roe_values))
    roa_latest = None if not roa_values or pd.isna(roa_values[-1]) else float(roa_values[-1])
    roa_floor = None if not roa_values or pd.isna(roa_values).any() else float(min(roa_values))
    gross_latest = None if len(margins) != 10 or margins.isna().any() else float(margins.iloc[-1])
    gross_std = None if len(margins) != 10 or margins.isna().any() else float(margins.std(ddof=0))

    is_bank = bool(BANK_PATTERN.search(industry or ""))
    if is_bank:
        criteria: dict[str, bool | None] = {
            "roa_current": None if roa_latest is None else roa_latest >= limits["bank_roa_current_min"],
            "roa_history": None if roa_floor is None else roa_floor >= limits["bank_roa_floor"],
        }
    else:
        criteria = {
            "roe_current": None if roe_latest is None else roe_latest >= limits["roe_current_min"],
            "roe_history": None if roe_floor is None else roe_floor >= limits["roe_floor"],
            "gross_margin": None if gross_latest is None or gross_std is None else gross_latest >= limits["gross_margin_min"] and gross_std < limits["gross_margin_std_max"],
            "capital_intensity": None if capex_ratio is None else capex_ratio < limits["capex_to_profit_5y_max"],
            "debt_safety": None if debt_ratio is None else debt_ratio < limits["debt_to_profit_max"],
        }
    valuation_status = "insufficient" if pe_lyr is None else (
        "within_limit" if 0 < pe_lyr < limits["pe_lyr_max"] else "above_limit"
    )
    special_case = None if is_bank else "financial" if FINANCIAL_PATTERN.search(industry or "") else (
        "cyclical" if CYCLICAL_PATTERN.search(industry or "") else None
    )

    if not consecutive or any(value is None for value in criteria.values()) or audit_status == "missing":
        quality_status = "insufficient"
        decision = "insufficient_data"
    elif audit_status == "adverse":
        quality_status = "rejected"
        decision = "reject"
    elif special_case or audit_status == "qualified" or revision_conflicts:
        quality_status = "manual_review"
        decision = "manual_review"
    elif not all(criteria.values()):
        quality_status = "not_qualified"
        decision = "reject"
    else:
        quality_status = "qualified"
        decision = "research_candidate" if valuation_status == "within_limit" else (
            "watchlist" if valuation_status == "above_limit" else "insufficient_data"
        )

    research_gaps = []
    if special_case:
        research_gaps.append("行业经济特征不适用普通企业自动筛选，必须使用专项分析。")
    if revision_conflicts:
        research_gaps.append("同一披露日存在冲突财报版本，必须人工核对。")
    if cash_proxy is None:
        research_gaps.append("经营现金流或资本开支缺失，现金收益代理不可用。")
    research_gaps.append("量化初筛不能证明能力圈、真实护城河或管理层资本配置质量。")

    return {
        "target_id": symbol,
        "decision": decision,
        "priority_rank": None,
        "quality_status": quality_status,
        "valuation_status": valuation_status,
        "criteria": criteria,
        "metrics": {
            "roe_latest_pct": roe_latest,
            "roe_ten_year_floor_pct": roe_floor,
            "roa_latest_pct": roa_latest,
            "roa_ten_year_floor_pct": roa_floor,
            "gross_margin_latest_pct": gross_latest,
            "gross_margin_std_pct_points": gross_std,
            "capex_to_profit_5y": capex_ratio,
            "long_term_debt_to_profit": debt_ratio,
            "pe_lyr": pe_lyr,
            "cash_earnings_proxy": cash_proxy,
            "cash_earnings_conversion_5y": cash_conversion_5y,
        },
        "coverage": {
            "annual_reports": len(selected),
            "roe_years": len(roe_values),
            "consecutive": consecutive,
        },
        "industry": industry,
        "special_case": "bank_roa" if is_bank else special_case,
        "audit_status": audit_status,
        "revision_conflicts": list(revision_conflicts),
        "actual_source_date": latest_source_date,
        "research_gaps": research_gaps,
    }


def rank_research_queue(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def finite_or(value: Any, fallback: float) -> float:
        number = _finite(value)
        return fallback if number is None else number

    candidates = [row for row in records if row["decision"] == "research_candidate"]
    candidates.sort(
        key=lambda row: (
            finite_or(row["metrics"].get("pe_lyr"), float("inf")),
            -finite_or(row["metrics"].get("roe_ten_year_floor_pct"), float("-inf")),
            finite_or(row["metrics"].get("capex_to_profit_5y"), float("inf")),
            finite_or(row["metrics"].get("gross_margin_std_pct_points"), float("inf")),
            row["target_id"],
        )
    )
    for rank, row in enumerate(candidates, start=1):
        row["priority_rank"] = rank

    watchlist = [row for row in records if row["decision"] == "watchlist"]
    watchlist.sort(
        key=lambda row: (
            finite_or(row["metrics"].get("pe_lyr"), float("inf")) - DEFAULT_THRESHOLDS["pe_lyr_max"],
            -finite_or(row["metrics"].get("roe_ten_year_floor_pct"), float("-inf")),
            row["target_id"],
        )
    )
    for rank, row in enumerate(watchlist, start=1):
        row["priority_rank"] = rank
    remainder = [row for row in records if row["decision"] not in {"research_candidate", "watchlist"}]
    remainder.sort(key=lambda row: row["target_id"])
    return candidates + watchlist + remainder
