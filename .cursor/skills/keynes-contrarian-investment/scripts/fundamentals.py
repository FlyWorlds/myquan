"""Pure functions for reported reality and fundamental durability."""
from __future__ import annotations

from typing import Any
import numpy as np
import pandas as pd


def _column(frame: pd.DataFrame, names: tuple[str, ...]) -> str | None:
    lower = {str(c).lower(): c for c in frame.columns}
    for name in names:
        if name.lower() in lower:
            return str(lower[name.lower()])
    for name in names:
        for key, original in lower.items():
            if name.lower() in key:
                return str(original)
    return None


def _number(value: Any) -> float | None:
    try:
        number = float(value)
        return number if np.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _available_as_of(frame: pd.DataFrame, as_of: str) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    result = frame.copy()
    disclosure = _column(result, ("info_date", "ann_date", "publish_date", "date"))
    if disclosure:
        values = result[disclosure].astype(str).str.replace("-", "", regex=False).str[:8]
        result = result.loc[values.isin(("", "nan", "None", "NaT")) | (values <= as_of)].copy()
    return result


def _annual_rows(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    quarter = _column(frame, ("quarter",))
    if quarter:
        annual = frame[frame[quarter].astype(str).str.lower().str.endswith("q4")]
        if not annual.empty:
            return annual.sort_values(quarter)
    period = _column(frame, ("end_date", "report_date"))
    if period:
        annual = frame[frame[period].astype(str).str.replace("-", "", regex=False).str.endswith("1231")]
        if not annual.empty:
            return annual.sort_values(period)
    return frame


def metric(value: float | None, *, unit: str, formula: str | None = None, fields: list[str] | None = None, period: str | None = None, methods: list[str] | None = None, status: str = "derived", caveat: str | None = None) -> dict[str, Any]:
    return {"value": value, "unit": unit, "status": status if value is not None else "empty", "formula": formula, "fields": fields or [], "period": period, "source_methods": methods or [], "caveat": caveat}


def _growth_metric(frame: pd.DataFrame, column: str | None, label: str) -> dict[str, Any]:
    if not column or len(frame) < 2:
        return metric(None, unit="ratio", methods=["get_fina_reports", "get_fina_performance"])
    current, prior = _number(frame.iloc[-1][column]), _number(frame.iloc[-2][column])
    value = current / abs(prior) - 1 if current is not None and prior not in (None, 0) else None
    return metric(value, unit="ratio", formula=f"current_{label} / abs(prior_{label}) - 1", fields=[column], methods=["get_fina_reports", "get_fina_performance"])


def calculate_metrics(performance: pd.DataFrame, reports: pd.DataFrame, as_of: str) -> dict[str, Any]:
    performance = _available_as_of(performance, as_of)
    reports = _available_as_of(reports, as_of)
    # Keep the latest disclosed version of each quarter. PandaData's default
    # is_latest=True can still return revised quarters with different dates.
    if "quarter" in reports.columns:
        reports = reports.copy()
        reports["_qkey"] = reports["quarter"].astype(str).str.lower()
        reports = reports.sort_values(["_qkey", "date"] if "date" in reports.columns else ["_qkey"]).drop_duplicates("_qkey", keep="last").drop(columns=["_qkey"])
    # Prefer full annual statements. Performance is an announcement/flash table
    # and can contain only one latest row for the current account.
    annual = _annual_rows(reports)
    frame = annual if len(annual) >= 2 else _annual_rows(performance)
    revenue_col = _column(frame, ("is_revenue", "operating_revenue", "total_revenue", "revenue"))
    profit_col = _column(frame, ("is_n_income_attr_p", "net_profit_parent", "net_profit", "n_income", "net_income"))
    result: dict[str, Any] = {
        "revenue_yoy": _growth_metric(frame, revenue_col, "revenue"),
        "net_profit_yoy": _growth_metric(frame, profit_col, "net_profit"),
    }

    latest_annual = annual.iloc[-1] if not annual.empty else None
    ocf_col = _column(annual, ("cfs_net_cash_operating", "net_cash_flow_operating", "operating_cash_flow", "net_cash_operate", "cfo"))
    annual_profit_col = _column(annual, ("is_n_income_attr_p", "is_n_income", "net_profit_parent", "net_profit"))
    if latest_annual is not None and ocf_col and annual_profit_col:
        cash, profit = _number(latest_annual[ocf_col]), _number(latest_annual[annual_profit_col])
        value = cash / profit if cash is not None and profit not in (None, 0) else None
        result["cash_conversion"] = metric(value, unit="ratio", formula="operating_cash_flow / net_profit", fields=[ocf_col, annual_profit_col], methods=["get_fina_reports"])
    else:
        result["cash_conversion"] = metric(None, unit="ratio", methods=["get_fina_reports"])

    eps_col = _column(annual, ("is_basic_eps", "basic_eps", "eps"))
    eps = _number(latest_annual[eps_col]) if latest_annual is not None and eps_col else None
    period_col = _column(annual, ("quarter", "end_date", "report_date"))
    period = str(latest_annual[period_col]) if latest_annual is not None and period_col else None
    result["annual_eps"] = metric(eps, unit="currency_per_share", fields=[eps_col] if eps_col else [], period=period, methods=["get_fina_reports"], status="ok", caveat="使用最新完整年度口径，不使用未完成季度累计EPS")

    assets_col = _column(annual, ("bs_total_assets", "total_assets"))
    liabilities_col = _column(annual, ("bs_total_liab", "total_liabilities"))
    if latest_annual is not None and assets_col and liabilities_col:
        assets, liabilities = _number(latest_annual[assets_col]), _number(latest_annual[liabilities_col])
        debt_ratio = liabilities / assets if liabilities is not None and assets not in (None, 0) else None
        result["liability_ratio"] = metric(debt_ratio, unit="ratio", formula="total_liabilities / total_assets", fields=[liabilities_col, assets_col], methods=["get_fina_reports"])
    else:
        result["liability_ratio"] = metric(None, unit="ratio", methods=["get_fina_reports"])
    return result


def build_fundamental_snapshot(symbol: str, performance: pd.DataFrame, reports: pd.DataFrame, forecast: pd.DataFrame, audit: pd.DataFrame, as_of: str) -> dict[str, Any]:
    metrics = calculate_metrics(performance, reports, as_of)
    flags: list[str] = []
    yoy = metrics.get("net_profit_yoy", {}).get("value")
    cash = metrics.get("cash_conversion", {}).get("value")
    liability = metrics.get("liability_ratio", {}).get("value")
    if yoy is not None and yoy < -0.2:
        flags.append("净利润同比显著下降")
    if cash is not None and cash < 0.7:
        flags.append("经营现金流/净利润偏低")
    if liability is not None and liability > 0.75:
        flags.append("资产负债率偏高")
    audit_available = _available_as_of(audit, as_of)
    opinion_col = _column(audit_available, ("opinion",))
    opinions = audit_available[opinion_col].dropna().astype(str).str.lower().tolist() if opinion_col else []
    adverse_codes = {"qualified_opinion", "adverse_opinion", "disclaimer_of_opinion"}
    chinese_adverse = ("无法表示意见", "保留意见", "否定意见")
    if any(opinion in adverse_codes or any(term in opinion for term in chinese_adverse) for opinion in opinions):
        flags.append("审计意见存在非标准风险")
    coverage = sum(value.get("status") != "empty" for value in metrics.values()) / max(1, len(metrics))
    return {"symbol": symbol, "reported_reality": {"metrics": metrics}, "deterioration_flags": flags, "quality_flags": [], "fundamental_confidence": round(min(1.0, coverage), 2), "source_methods": ["get_fina_reports", "get_fina_performance", "get_fina_forecast", "get_audit_opinion"], "as_of": as_of}
