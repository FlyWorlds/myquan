"""Market confidence, liquidity and animal-spirits proxies."""
from __future__ import annotations
from typing import Any
import numpy as np
import pandas as pd


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(frame[column], errors="coerce") if column in frame.columns else pd.Series(dtype=float)


def calculate_breadth(stock_daily: pd.DataFrame, as_of: str) -> dict[str, Any]:
    if stock_daily.empty or "symbol" not in stock_daily.columns or "close" not in stock_daily.columns:
        return {"status": "empty", "evidence_level": "N/A", "up_ratio": None, "sample_size": 0}
    frame = stock_daily.copy()
    date_col = "date" if "date" in frame.columns else None
    if date_col:
        dates = frame[date_col].astype(str).str.replace("-", "", regex=False)
        frame = frame.loc[dates <= as_of]
    rows = []
    for symbol, group in frame.groupby("symbol"):
        group = group.sort_values(date_col) if date_col else group
        if len(group) >= 2:
            close = pd.to_numeric(group["close"], errors="coerce")
            rows.append(float(close.iloc[-1] / close.iloc[-2] - 1) if close.iloc[-2] else np.nan)
    values = pd.Series(rows).replace([np.inf, -np.inf], np.nan).dropna()
    if values.empty:
        return {"status": "empty", "evidence_level": "N/A", "up_ratio": None, "sample_size": 0}
    return {"status": "derived", "evidence_level": "DERIVED", "up_ratio": float((values > 0).mean()), "median_return": float(values.median()), "down_ratio": float((values < 0).mean()), "sample_size": int(len(values)), "caveat": "上涨广度是市场信心代理，不是企业价值事实"}


def liquidity_proxy(stock_daily: pd.DataFrame, margin: pd.DataFrame | None = None, etf_flow: pd.DataFrame | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"status": "empty", "evidence_level": "PROXY", "amount_trend": None, "margin_available": not (margin is None or margin.empty), "margin_change": None, "etf_flow_available": not (etf_flow is None or etf_flow.empty), "etf_flow_change": None, "caveat": "成交额、融资和 ETF 申赎只是流动性/风险偏好代理，不是主力资金真实流向"}
    if stock_daily is not None and not stock_daily.empty and "amount" in stock_daily.columns:
        frame = stock_daily.sort_values("date") if "date" in stock_daily.columns else stock_daily
        amounts = _num(frame, "amount").dropna()
        if len(amounts) >= 10 and amounts.iloc[-10] != 0:
            result["amount_trend"] = float(amounts.iloc[-1] / amounts.iloc[-10] - 1)
            result["status"] = "derived"
    if margin is not None and not margin.empty:
        balance_col = next((c for c in ("margin_balance", "total_balance", "financing_balance") if c in margin.columns), None)
        if balance_col:
            values = _num(margin.sort_values("date") if "date" in margin.columns else margin, balance_col).dropna()
            if len(values) >= 2 and values.iloc[-2] != 0:
                result["margin_change"] = float(values.iloc[-1] / values.iloc[-2] - 1)
                result["status"] = "derived"
    if etf_flow is not None and not etf_flow.empty:
        flow_col = next((c for c in ("net_inflow", "net_redemption", "size_change", "shares_change") if c in etf_flow.columns), None)
        if flow_col:
            values = _num(etf_flow.sort_values("date") if "date" in etf_flow.columns else etf_flow, flow_col).dropna()
            if not values.empty:
                result["etf_flow_change"] = float(values.sum())
                result["status"] = "derived"
    return result


def build_market_context(stock_daily: pd.DataFrame, index_daily: pd.DataFrame, margin: pd.DataFrame | None, northbound: pd.DataFrame | None, lhb: pd.DataFrame | None, etf_flow: pd.DataFrame | None, as_of: str) -> dict[str, Any]:
    breadth = calculate_breadth(stock_daily, as_of)
    liquidity = liquidity_proxy(stock_daily, margin, etf_flow)
    flags: list[str] = []
    if breadth.get("up_ratio") is not None and breadth["up_ratio"] < 0.3:
        flags.append("市场广度偏弱")
    if liquidity.get("amount_trend") is not None and liquidity["amount_trend"] < -0.2:
        flags.append("成交活跃度下降")
    return {"status": "derived" if breadth["status"] != "empty" or liquidity["status"] != "empty" else "empty", "confidence_proxy": breadth, "liquidity_proxy": liquidity, "animal_spirits_proxy": {"evidence_level": "PROXY", "signals": flags, "caveat": "价格和交易行为不能证明长期企业价值改变"}, "reflexivity_flags": flags, "northbound_rows": 0 if northbound is None else len(northbound), "lhb_rows": 0 if lhb is None else len(lhb), "as_of": as_of}
