"""Point-in-time Buffett-style quality, capital-allocation, and valuation scoring."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd

from .core import AUTO_PATTERN, BANK_PATTERN, CYCLICAL_PATTERN, DEFAULT_THRESHOLDS, FINANCIAL_PATTERN


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _linear(value: float | None, low: float, high: float, points: float) -> float:
    if value is None:
        return 0.0
    if high == low:
        return points if value >= high else 0.0
    return float(np.clip((value - low) / (high - low), 0.0, 1.0) * points)


def _declining(value: float | None, best: float, worst: float, points: float) -> float:
    if value is None:
        return 0.0
    return float(np.clip((worst - value) / (worst - best), 0.0, 1.0) * points)


def _cagr(first: Any, last: Any, years: int) -> float | None:
    left, right = _finite(first), _finite(last)
    if left is None or right is None or left <= 0 or right <= 0 or years <= 0:
        return None
    return (right / left) ** (1.0 / years) - 1.0


def _audit_state(
    audit_history: Sequence[Mapping[str, Any]], as_of_year: int
) -> tuple[str, str]:
    available = []
    for row in audit_history:
        year = row.get("year")
        status = str(row.get("status") or "missing").lower()
        try:
            fiscal_year = int(year)
        except (TypeError, ValueError):
            continue
        if fiscal_year <= as_of_year and status != "missing":
            available.append((fiscal_year, status))
    if not available:
        return "missing", "missing"
    latest_year, latest_status = sorted(available)[-1]
    if latest_status in {"adverse", "qualified", "disclaimer"}:
        return latest_status, "fresh" if latest_year == as_of_year else "audit_lagged"
    lag = as_of_year - latest_year
    if lag == 0:
        return latest_status, "fresh"
    if lag <= 2:
        return latest_status, "audit_lagged"
    return latest_status, "missing"


def _series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce")


def _average_positive(left: Any, right: Any) -> float | None:
    first, second = _finite(left), _finite(right)
    if first is None or second is None or first <= 0 or second <= 0:
        return None
    return (first + second) / 2.0


def _ordinary_scores(metrics: Mapping[str, Any], audit_freshness: str) -> tuple[dict[str, float], float]:
    missing = 0.0
    roic_median = metrics.get("roic_proxy_median_pct")
    roic_floor = metrics.get("roic_proxy_floor_pct")
    if roic_median is None:
        missing += 12.0
    if roic_floor is None:
        missing += 8.0
    if metrics.get("roic_proxy_latest_pct") is None:
        missing += 5.0
    gross_level = metrics.get("gross_margin_latest_pct")
    gross_std = metrics.get("gross_margin_std_pct_points")
    gross_trend = metrics.get("gross_margin_trend_5y_pct_points")
    if gross_level is None:
        missing += 6.0
    if gross_std is None:
        missing += 8.0
    if gross_trend is None:
        missing += 3.0
    revenue_positive = metrics.get("revenue_positive_year_ratio")
    if revenue_positive is None:
        missing += 3.0
    moat = (
        _linear(roic_median, 8.0, 20.0, 10.0)
        + _linear(roic_floor, 5.0, 12.0, 7.0)
        + _linear(metrics.get("roic_proxy_latest_pct"), 8.0, 20.0, 5.0)
        + _linear(gross_level, 15.0, 50.0, 6.0)
        + _declining(gross_std, 3.0, 15.0, 8.0)
        + _linear(gross_trend, -2.0, 1.0, 2.0)
        + _linear(revenue_positive, 0.5, 1.0, 2.0)
    )

    eps_cagr = metrics.get("eps_cagr_5y")
    incremental_roic = metrics.get("incremental_roic_proxy_pct")
    cash_conversion = metrics.get("cash_conversion_5y")
    dilution = metrics.get("implied_share_dilution_5y")
    capex = metrics.get("capex_to_profit_5y")
    for value, weight in ((eps_cagr, 5), (incremental_roic, 5), (cash_conversion, 10), (dilution, 5), (capex, 5)):
        if value is None:
            missing += float(weight)
    capital = (
        _linear(eps_cagr, 0.0, 0.15, 5.0)
        + _linear(incremental_roic, 8.0, 20.0, 5.0)
        + _linear(cash_conversion, 0.4, 1.0, 10.0)
        + _declining(dilution, 0.0, 0.10, 5.0)
        + _declining(capex, 0.20, 0.50, 5.0)
    )

    debt = metrics.get("long_term_debt_to_profit")
    positive_owner_earnings = metrics.get("owner_earnings_positive_year_ratio")
    positive_profit = metrics.get("positive_profit_year_ratio")
    for value, weight in ((debt, 10), (positive_owner_earnings, 5), (positive_profit, 5)):
        if value is None:
            missing += float(weight)
    financial = (
        _declining(debt, 1.0, 4.0, 10.0)
        + _linear(positive_owner_earnings, 0.6, 1.0, 5.0)
        + _linear(positive_profit, 0.8, 1.0, 5.0)
    )
    audit_score = (
        7.0 if audit_freshness == "fresh"
        else 4.0 if audit_freshness == "audit_lagged"
        else 5.0 if audit_freshness == "not_backtested"
        else 0.0
    )
    if audit_freshness == "missing":
        missing += 7.0
    data_score = _linear(metrics.get("valid_return_year_ratio"), 0.8, 1.0, 3.0)
    if metrics.get("valid_return_year_ratio") is None:
        missing += 3.0
    return {
        "moat_score": moat,
        "capital_allocation_score": capital,
        "financial_strength_score": financial,
        "audit_data_score": audit_score + data_score,
    }, missing


def _bank_scores(metrics: Mapping[str, Any], audit_freshness: str) -> tuple[dict[str, float], float]:
    missing = 0.0
    roa_median = metrics.get("roa_median_pct")
    roa_floor = metrics.get("roa_floor_pct")
    positive_profit = metrics.get("positive_profit_year_ratio")
    eps_cagr = metrics.get("eps_cagr_5y")
    equity_cagr = metrics.get("equity_cagr_5y")
    dilution = metrics.get("implied_share_dilution_5y")
    for value, weight in (
        (roa_median, 20), (roa_floor, 15), (positive_profit, 20),
        (eps_cagr, 15), (equity_cagr, 10), (dilution, 10),
    ):
        if value is None:
            missing += float(weight)
    moat = _linear(roa_median, 0.6, 1.2, 20.0) + _linear(roa_floor, 0.4, 1.0, 15.0)
    capital = (
        _linear(positive_profit, 0.8, 1.0, 20.0)
        + _linear(eps_cagr, 0.0, 0.12, 15.0)
        + _linear(equity_cagr, 0.0, 0.10, 10.0)
    )
    financial = _declining(dilution, 0.0, 0.10, 10.0)
    audit = (
        10.0 if audit_freshness == "fresh"
        else 6.0 if audit_freshness == "audit_lagged"
        else 5.0 if audit_freshness == "not_backtested"
        else 0.0
    )
    if audit_freshness == "missing":
        missing += 10.0
    return {
        "moat_score": moat,
        "capital_allocation_score": capital,
        "financial_strength_score": financial,
        "audit_data_score": audit,
    }, missing


def evaluate_buffett_company(
    symbol: str,
    annual_history: pd.DataFrame,
    *,
    industry: str,
    audit_history: Sequence[Mapping[str, Any]],
    as_of_year: int,
    thresholds: Mapping[str, float] | None = None,
    audit_gate: bool = True,
) -> dict[str, Any]:
    limits = {**DEFAULT_THRESHOLDS, **dict(thresholds or {})}
    history = annual_history[annual_history["symbol"] == symbol].copy()
    history = history.sort_values("year").drop_duplicates("year", keep="last").tail(11)
    years = history.get("year", pd.Series(dtype=float)).dropna().astype(int).tolist()
    recent_three_complete = len(years) >= 3 and years[-3:] == list(range(years[-1] - 2, years[-1] + 1))

    profits = _series(history, "parent_net_profit")
    equities = _series(history, "parent_equity")
    assets = _series(history, "total_assets")
    debt = _series(history, "long_term_interest_bearing_debt")
    cash = _series(history, "cash_equivalents")
    operating_profit = _series(history, "operating_profit")
    total_profit = _series(history, "total_profit")
    income_tax = _series(history, "income_tax")
    eps = _series(history, "basic_eps")
    revenue = _series(history, "revenue")
    gross_profit = _series(history, "gross_profit")
    cfo = _series(history, "operating_cash_flow")
    capex = _series(history, "gross_capex").abs()

    roe_values: list[float] = []
    roa_values: list[float] = []
    roic_values: list[float] = []
    for index in range(1, len(history)):
        profit = _finite(profits.iloc[index])
        avg_equity = _average_positive(equities.iloc[index - 1], equities.iloc[index])
        avg_assets = _average_positive(assets.iloc[index - 1], assets.iloc[index])
        roe_values.append(np.nan if profit is None or avg_equity is None else profit / avg_equity * 100.0)
        roa_values.append(np.nan if profit is None or avg_assets is None else profit / avg_assets * 100.0)

        op = _finite(operating_profit.iloc[index])
        pre_tax = _finite(total_profit.iloc[index])
        tax = _finite(income_tax.iloc[index])
        current_capital = None
        previous_capital = None
        if all(pd.notna(value) for value in (equities.iloc[index], debt.iloc[index], cash.iloc[index])):
            current_capital = float(equities.iloc[index] + debt.iloc[index] - max(cash.iloc[index], 0.0))
        if all(pd.notna(value) for value in (equities.iloc[index - 1], debt.iloc[index - 1], cash.iloc[index - 1])):
            previous_capital = float(equities.iloc[index - 1] + debt.iloc[index - 1] - max(cash.iloc[index - 1], 0.0))
        avg_capital = _average_positive(previous_capital, current_capital)
        effective_tax = None if pre_tax is None or pre_tax <= 0 or tax is None else float(np.clip(tax / pre_tax, 0.0, 0.35))
        roic_values.append(
            np.nan if op is None or avg_capital is None or effective_tax is None else op * (1.0 - effective_tax) / avg_capital * 100.0
        )

    operating = history.tail(10)
    gross_margins = gross_profit.tail(10) / revenue.tail(10) * 100.0
    last_five = history.tail(5)
    profit5 = _series(last_five, "parent_net_profit")
    cfo5 = _series(last_five, "operating_cash_flow")
    capex5 = _series(last_five, "gross_capex").abs()
    eps5 = _series(last_five, "basic_eps")
    equity5 = _series(last_five, "parent_equity")
    cash_conversion = None
    capex_ratio = None
    owner_earnings = cfo5 - capex5
    owner_earnings_positive_ratio = None
    owner_earnings_total = None
    if len(last_five) == 5 and owner_earnings.notna().all():
        owner_earnings_total = float(owner_earnings.sum())
        owner_earnings_positive_ratio = float((owner_earnings > 0).mean())
    if len(last_five) == 5 and profit5.notna().all() and profit5.sum() > 0:
        if cfo5.notna().all() and capex5.notna().all():
            cash_conversion = float((cfo5.sum() - capex5.sum()) / profit5.sum())
        if capex5.notna().all():
            capex_ratio = float(capex5.sum() / profit5.sum())
    last_three = history.tail(3)
    profit3 = _series(last_three, "parent_net_profit")
    cfo3 = _series(last_three, "operating_cash_flow")
    capex3 = _series(last_three, "gross_capex").abs()
    cash_conversion3 = (
        float((cfo3.sum() - capex3.sum()) / profit3.sum())
        if len(last_three) == 3 and profit3.notna().all() and profit3.sum() > 0 and cfo3.notna().all() and capex3.notna().all()
        else None
    )
    owner_earnings3 = cfo3 - capex3
    owner_earnings_positive_ratio3 = (
        float((owner_earnings3 > 0).mean())
        if len(last_three) == 3 and owner_earnings3.notna().all()
        else None
    )

    latest = history.iloc[-1] if not history.empty else None
    latest_profit = None if latest is None else _finite(latest.get("parent_net_profit"))
    latest_eps = None if latest is None else _finite(latest.get("basic_eps"))
    latest_close = None if latest is None else _finite(latest.get("close"))
    latest_debt = None if latest is None else _finite(latest.get("long_term_interest_bearing_debt"))
    latest_equity = None if latest is None else _finite(latest.get("parent_equity"))
    normalized_eps = None
    eps_window_years = max(3, int(limits.get("normalized_eps_years", 3)))
    eps_window = eps.tail(eps_window_years).dropna()
    if latest_eps is not None and latest_eps > 0 and len(eps_window) == eps_window_years:
        normalized_eps = min(latest_eps, float(eps_window.median()))
    normalized_pe = None if normalized_eps is None or latest_close is None or latest_close <= 0 else latest_close / normalized_eps
    clipped_conversion = None if cash_conversion is None else float(np.clip(cash_conversion, 0.0, 1.2))
    cash_yield = (
        None if normalized_eps is None or latest_close is None or clipped_conversion is None or latest_close <= 0
        else normalized_eps * clipped_conversion / latest_close
    )
    debt_ratio = None if latest_debt is None or latest_profit is None or latest_profit <= 0 else abs(latest_debt) / latest_profit
    implied_shares = profits / eps.replace(0, np.nan)
    dilution = _cagr(implied_shares.iloc[-5] if len(implied_shares) >= 5 else None, implied_shares.iloc[-1] if len(implied_shares) else None, 4)
    eps_cagr = _cagr(eps5.iloc[0] if len(eps5) else None, eps5.iloc[-1] if len(eps5) else None, 4)
    equity_cagr = _cagr(equity5.iloc[0] if len(equity5) else None, equity5.iloc[-1] if len(equity5) else None, 4)
    incremental_roic = None
    if len(last_five) == 5:
        def _nopat(index: int) -> float | None:
            op = _finite(operating_profit.iloc[index])
            pre_tax = _finite(total_profit.iloc[index])
            tax = _finite(income_tax.iloc[index])
            if op is None or pre_tax is None or pre_tax <= 0 or tax is None:
                return None
            rate = float(np.clip(tax / pre_tax, 0.0, 0.35))
            return op * (1.0 - rate)

        def _invested_capital(index: int) -> float | None:
            values = (equity5.iloc[index], debt.iloc[-5 + index], cash.iloc[-5 + index])
            if any(pd.isna(value) for value in values):
                return None
            capital = float(values[0] + values[1] - max(values[2], 0.0))
            return capital if capital > 0 else None

        first_nopat, last_nopat = _nopat(len(history) - 5), _nopat(len(history) - 1)
        first_capital, last_capital = _invested_capital(0), _invested_capital(4)
        delta_capital = None if first_capital is None or last_capital is None else last_capital - first_capital
        if first_nopat is not None and last_nopat is not None and delta_capital is not None and delta_capital > 0:
            incremental_roic = (last_nopat - first_nopat) / delta_capital * 100.0
    valid_roes = pd.Series(roe_values, dtype=float).dropna()
    valid_roas = pd.Series(roa_values, dtype=float).dropna()
    valid_roics = pd.Series(roic_values, dtype=float).dropna()
    revenue_growth = revenue.tail(10).pct_change().dropna()
    recent_margins = gross_margins.dropna().tail(5)
    recent_operating_margins = (
        operating_profit.tail(5) / revenue.tail(5).replace(0, np.nan) * 100.0
    ).dropna()
    gross_margin_trend = (
        None
        if len(recent_margins) < 5
        else float((recent_margins.iloc[-1] - recent_margins.iloc[0]) / 4.0)
    )

    metrics = {
        "valid_return_years": int(len(valid_roes)),
        "valid_return_year_ratio": float(len(valid_roes) / 10.0),
        "roe_latest_pct": None if not roe_values or pd.isna(roe_values[-1]) else float(roe_values[-1]),
        "roe_mean_pct": None if valid_roes.empty else float(valid_roes.mean()),
        "roe_median_pct": None if valid_roes.empty else float(valid_roes.median()),
        "roe_floor_pct": None if valid_roes.empty else float(valid_roes.min()),
        "roa_latest_pct": None if not roa_values or pd.isna(roa_values[-1]) else float(roa_values[-1]),
        "roa_median_pct": None if valid_roas.empty else float(valid_roas.median()),
        "roa_floor_pct": None if valid_roas.empty else float(valid_roas.min()),
        "roic_proxy_median_pct": None if len(valid_roics) < 5 else float(valid_roics.median()),
        "roic_proxy_floor_pct": None if len(valid_roics) < 5 else float(valid_roics.min()),
        "roic_proxy_latest_pct": None if valid_roics.empty else float(valid_roics.iloc[-1]),
        "gross_margin_latest_pct": None if gross_margins.dropna().empty else float(gross_margins.dropna().iloc[-1]),
        "gross_margin_std_pct_points": None if gross_margins.count() < 8 else float(gross_margins.std(ddof=0)),
        "gross_margin_mean_5y_pct": None if len(recent_margins) < 3 else float(recent_margins.mean()),
        "gross_margin_std_5y_pct_points": None if len(recent_margins) < 3 else float(recent_margins.std(ddof=0)),
        "gross_margin_trend_5y_pct_points": gross_margin_trend,
        "operating_margin_mean_5y_pct": None if len(recent_operating_margins) < 3 else float(recent_operating_margins.mean()),
        "revenue_positive_year_ratio": None if revenue_growth.empty else float((revenue_growth > 0).mean()),
        "cash_conversion_5y": cash_conversion,
        "cash_conversion_3y": cash_conversion3,
        "owner_earnings_5y": owner_earnings_total,
        "owner_earnings_positive_year_ratio": owner_earnings_positive_ratio,
        "owner_earnings_positive_year_ratio_3y": owner_earnings_positive_ratio3,
        "capex_to_profit_5y": capex_ratio,
        "long_term_debt_to_profit": debt_ratio,
        "eps_cagr_5y": eps_cagr,
        "incremental_roic_proxy_pct": incremental_roic,
        "equity_cagr_5y": equity_cagr,
        "implied_share_dilution_5y": dilution,
        "positive_cfo_year_ratio": None if cfo.tail(10).dropna().empty else float((cfo.tail(10).dropna() > 0).mean()),
        "positive_profit_year_ratio": None if profits.tail(10).dropna().empty else float((profits.tail(10).dropna() > 0).mean()),
        "normalized_eps": normalized_eps,
        "current_pe": None if latest_eps is None or latest_eps <= 0 or latest_close is None or latest_close <= 0 else latest_close / latest_eps,
        "latest_profit": latest_profit,
    }

    audit_status, audit_freshness = _audit_state(audit_history, as_of_year)
    if not audit_gate:
        # Historical quantitative replay cannot backfill a complete audit
        # corpus for every historical A share. Keep the status explicit while
        # preventing an unavailable audit endpoint from forcing all cash.
        audit_status = "not_backtested"
        audit_freshness = "not_backtested"
    is_bank = bool(BANK_PATTERN.search(industry or ""))
    observed_auto_cyclicality = bool(
        AUTO_PATTERN.search(industry or "")
        and (
            (metrics.get("revenue_positive_year_ratio") is not None and metrics["revenue_positive_year_ratio"] < 0.80)
            or (metrics.get("eps_cagr_5y") is not None and metrics["eps_cagr_5y"] < 0)
            or (metrics.get("gross_margin_std_pct_points") is not None and metrics["gross_margin_std_pct_points"] >= 10.0)
        )
    )
    special_case = None if is_bank else "financial" if FINANCIAL_PATTERN.search(industry or "") else (
        "cyclical" if CYCLICAL_PATTERN.search(industry or "") or observed_auto_cyclicality else None
    )
    if is_bank:
        components, missing_weight = _bank_scores(metrics, audit_freshness)
    else:
        components, missing_weight = _ordinary_scores(metrics, audit_freshness)
    quality_score = float(sum(components.values()))

    book_value_per_share = None
    pb = None
    if latest_profit is not None and latest_eps is not None and latest_eps > 0 and latest_equity is not None:
        shares = latest_profit / latest_eps
        if shares > 0:
            book_value_per_share = latest_equity / shares
            if latest_close is not None and book_value_per_share > 0:
                pb = latest_close / book_value_per_share
    if is_bank:
        entry_eligible = bool(
            quality_score >= limits["bank_quality_score_min"]
            and normalized_pe is not None and 0 < normalized_pe <= limits["bank_normalized_pe_max"]
            and pb is not None and 0 < pb <= limits["bank_pb_max"]
        )
    else:
        entry_eligible = bool(
            quality_score >= limits["quality_score_min"]
            and normalized_pe is not None and 0 < normalized_pe <= limits["normalized_pe_max"]
            and cash_yield is not None and cash_yield >= limits["cash_earnings_yield_min"]
        )
    dilution_limit = limits.get("share_dilution_5y_max")
    if dilution_limit is not None:
        dilution_value = metrics.get("implied_share_dilution_5y")
        entry_eligible = bool(
            entry_eligible
            and dilution_value is not None
            and float(dilution_value) <= float(dilution_limit)
        )
    cash_conversion_3y_limit = limits.get("cash_conversion_3y_min")
    if cash_conversion_3y_limit is not None:
        recent_conversion = metrics.get("cash_conversion_3y")
        entry_eligible = bool(
            entry_eligible
            and recent_conversion is not None
            and float(recent_conversion) >= float(cash_conversion_3y_limit)
        )
    equity_growth_limit = limits.get("equity_cagr_5y_min")
    if equity_growth_limit is not None:
        equity_growth = metrics.get("equity_cagr_5y")
        entry_eligible = bool(
            entry_eligible
            and equity_growth is not None
            and float(equity_growth) >= float(equity_growth_limit)
        )
    owner_ratio_limit = limits.get("owner_earnings_positive_ratio_min")
    if owner_ratio_limit is not None:
        owner_ratio = metrics.get("owner_earnings_positive_year_ratio")
        entry_eligible = bool(
            entry_eligible
            and owner_ratio is not None
            and float(owner_ratio) >= float(owner_ratio_limit)
        )

    if limits.get("strict_buffett_gate") and not is_bank:
        # 原始巴菲特门槛：ROE ≥ 15%、10 年 ROE 下限 ≥ 12%、毛利率 ≥ 40%、
        # 毛利率标准差 < 10 个百分点、资本开支 / 净利润 < 30%、正常化 PE < 25。
        # 周期股与非银金融已由 special_case 走人工复核路径，此处只作用于普通企业。
        roe_latest = metrics.get("roe_latest_pct")
        roe_floor_limit = limits.get("roe_floor_min")
        roe_floor_value = metrics.get("roe_floor_pct")
        gross_min = limits.get("gross_margin_min_pct")
        gross_level = metrics.get("gross_margin_latest_pct")
        gross_std_limit = limits.get("gross_margin_std_max_pct")
        gross_std_value = metrics.get("gross_margin_std_pct_points")
        capex_limit = limits.get("capex_to_profit_max")
        capex_value = metrics.get("capex_to_profit_5y")
        conditions = (
            (limits.get("roe_current_min") is None)
            or (roe_latest is not None and roe_latest >= float(limits["roe_current_min"])),
            (roe_floor_limit is None)
            or (roe_floor_value is not None and roe_floor_value >= float(roe_floor_limit)),
            (gross_min is None)
            or (gross_level is not None and gross_level >= float(gross_min)),
            (gross_std_limit is None)
            or (gross_std_value is not None and gross_std_value < float(gross_std_limit)),
            (capex_limit is None)
            or (capex_value is not None and capex_value < float(capex_limit)),
        )
        entry_eligible = bool(entry_eligible and all(conditions))

    sell_triggers: list[str] = []
    if audit_gate and audit_status in {"adverse", "qualified", "disclaimer"}:
        sell_triggers.append("audit_opinion")
    if latest_profit is None or latest_profit <= 0 or normalized_eps is None or normalized_eps <= 0:
        sell_triggers.append("normalized_profit_nonpositive")
    if debt_ratio is not None and debt_ratio >= 6.0:
        sell_triggers.append("debt_to_profit_at_least_6")
    if quality_score < 50.0:
        sell_triggers.append("quality_score_below_50")
    if special_case in {"financial", "cyclical"}:
        sell_triggers.append("industry_manual_review")
    # A Buffett-style holding is not sold because a composite score drifted
    # lower.  Keep that drift visible, but only count dated operating damage
    # toward the two-warning exit state machine.
    warning_reasons: list[str] = []
    if cash_conversion3 is not None and cash_conversion3 < 0.40:
        warning_reasons.append("cash_conversion_3y_below_40pct")
    if owner_earnings_positive_ratio3 is not None and owner_earnings_positive_ratio3 < 2.0 / 3.0:
        warning_reasons.append("owner_earnings_negative_years")
    if debt_ratio is not None and 4.0 <= debt_ratio < 6.0:
        warning_reasons.append("debt_to_profit_between_4_and_6")
    if missing_weight > 10.0:
        warning_reasons.append("data_confidence_decline")
    if 50.0 <= quality_score < 70.0:
        warning_reasons.append("quality_score_soft_warning")
    warning = bool(warning_reasons)
    hold_status = "exit" if sell_triggers else "warning" if warning else "healthy"

    critical_coverage = (
        len(valid_roas if is_bank else valid_roes) >= limits["valid_years_min"]
        and (metrics["roa_latest_pct"] if is_bank else metrics["roe_latest_pct"]) is not None
        and recent_three_complete
        and latest_profit is not None and latest_profit > 0
        and normalized_eps is not None and normalized_eps > 0
        and (is_bank or (cfo5.notna().all() and cfo5.sum() > 0))
    )
    if special_case:
        decision = "manual_review"
    elif audit_gate and audit_status in {"adverse", "qualified", "disclaimer"}:
        decision = "reject"
    elif not critical_coverage or missing_weight > limits["missing_score_weight_max"] or (audit_gate and audit_freshness == "missing"):
        decision = "insufficient_data"
    else:
        if is_bank:
            minimum_quality = (
                metrics["roa_latest_pct"] is not None and metrics["roa_latest_pct"] >= limits["bank_roa_current_min"]
                and metrics["roa_floor_pct"] is not None and metrics["roa_floor_pct"] >= limits["bank_roa_floor_min"]
                and quality_score >= limits["bank_quality_score_min"]
            )
        else:
            minimum_quality = (
                metrics["roe_latest_pct"] is not None and metrics["roe_latest_pct"] >= limits["roe_current_min"]
                and metrics["roe_median_pct"] is not None and metrics["roe_median_pct"] >= limits["roe_median_min"]
                and cash_conversion is not None and cash_conversion >= limits["cash_conversion_5y_min"]
                and debt_ratio is not None and debt_ratio < limits["debt_to_profit_max"]
                and quality_score >= limits["quality_score_min"]
            )
        decision = "research_candidate" if minimum_quality and entry_eligible else "watchlist" if minimum_quality else "reject"

    metrics.update(
        {
            "normalized_pe": normalized_pe,
            "cash_earnings_yield_proxy": cash_yield,
            "pb": pb,
        }
    )
    return {
        "target_id": symbol,
        "decision": decision,
        "priority_rank": None,
        "quality_score": quality_score,
        **components,
        "missing_score_weight": missing_weight,
        "audit_status": audit_status,
        "audit_freshness": audit_freshness,
        "normalized_pe": normalized_pe,
        "cash_earnings_yield_proxy": cash_yield,
        "qualitative_score": None,
        "qualitative_verdict": "qualitative_pending",
        "qualitative_confidence": 0.0,
        "valuation_score": None,
        "conviction_score": None,
        "policy_ceiling": 0.0,
        "liquidity_capacity": "not_observed",
        "entry_eligible": entry_eligible and decision == "research_candidate",
        "hold_status": hold_status,
        "warning_reasons": warning_reasons,
        "sell_triggers": sell_triggers,
        "metrics": metrics,
        "coverage": {
            "annual_reports": int(len(history)),
            "valid_return_years": int(len(valid_roes)),
            "recent_three_complete": recent_three_complete,
        },
        "industry": industry,
        "special_case": "bank_roa" if is_bank else special_case,
        "actual_source_date": None if history.empty else str(history.iloc[-1].get("published_at") or "") or None,
        "research_gaps": [
            "ROIC and cash earnings are engineering proxies; owner earnings means operating cash flow less gross capex and is not a full maintenance-capex measure.",
            "Management integrity and durable competitive advantage require manual research.",
        ],
    }


def rank_buffett_candidates(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def key(row: Mapping[str, Any]) -> tuple[Any, ...]:
        conviction = _finite(row.get("conviction_score"))
        quality = _finite(row.get("quality_score"))
        valuation = _finite(row.get("valuation_score"))
        cash_yield = _finite(row.get("cash_earnings_yield_proxy"))
        return (
            -(conviction if conviction is not None else -math.inf),
            -(quality if quality is not None else -math.inf),
            -(valuation if valuation is not None else -math.inf),
            -(cash_yield if cash_yield is not None else -math.inf),
            str(row.get("target_id", "")),
        )

    candidates = sorted((row for row in records if row.get("decision") == "research_candidate"), key=key)
    for rank, row in enumerate(candidates, start=1):
        row["priority_rank"] = rank
    remainder = sorted((row for row in records if row.get("decision") != "research_candidate"), key=key)
    return candidates + remainder
