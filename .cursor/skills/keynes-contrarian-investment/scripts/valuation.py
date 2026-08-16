"""Valuation and price-implied expectation helpers."""
from __future__ import annotations
from typing import Any
import numpy as np
import pandas as pd


def _find(frame: pd.DataFrame, names: tuple[str, ...]) -> str | None:
    for name in names:
        for column in frame.columns:
            if name.lower() == str(column).lower() or name.lower() in str(column).lower():
                return str(column)
    return None


def percentile_rank(values: pd.Series, value: float | None) -> float | None:
    if value is None:
        return None
    numeric = pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    numeric = numeric[numeric > 0]
    if numeric.empty:
        return None
    return float((numeric <= value).mean() * 100)


def _as_of_frame(frame: pd.DataFrame, as_of: str, date_columns: tuple[str, ...] = ("date", "info_date", "ann_date")) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    result = frame.copy()
    for column in date_columns:
        if column in result.columns:
            values = result[column].astype(str).str.replace("-", "", regex=False).str[:8]
            return result.loc[values.isin(("", "nan", "None", "NaT")) | (values <= as_of)].copy()
    return result


def _latest_price(price: pd.DataFrame, as_of: str) -> float | None:
    frame = _as_of_frame(price, as_of)
    if frame.empty or "close" not in frame.columns:
        return None
    if "date" in frame.columns:
        frame = frame.sort_values("date")
    value = pd.to_numeric(frame.iloc[-1]["close"], errors="coerce")
    return float(value) if pd.notna(value) else None


def _quarter_number(value: str) -> tuple[int, int] | None:
    text = str(value).lower().replace(" ", "")
    if "q" not in text:
        return None
    year, quarter = text.split("q", 1)
    try:
        return int(year), int(quarter)
    except ValueError:
        return None


def _latest_report_rows(reports: pd.DataFrame, as_of: str) -> pd.DataFrame:
    frame = _as_of_frame(reports, as_of)
    if frame.empty or "quarter" not in frame.columns:
        return frame
    # Keep the latest disclosed version for each reporting quarter.
    frame = frame.copy()
    frame["_qkey"] = frame["quarter"].map(_quarter_number)
    frame = frame.loc[frame["_qkey"].notna()].sort_values(["_qkey", "date" if "date" in frame.columns else "quarter"])
    return frame.drop_duplicates("_qkey", keep="last").drop(columns=["_qkey"])


def _cumulative_ttm(frame: pd.DataFrame, value_column: str) -> tuple[float | None, str | None]:
    if frame.empty or value_column not in frame.columns or "quarter" not in frame.columns:
        return None, None
    rows = {key: row for _, row in frame.iterrows() if (key := _quarter_number(row["quarter"]))}
    if not rows:
        return None, None
    latest_key = max(rows)
    latest_year, latest_q = latest_key
    def value(key: tuple[int, int]) -> float | None:
        if key not in rows:
            return None
        number = pd.to_numeric(rows[key][value_column], errors="coerce")
        return float(number) if pd.notna(number) else None
    current = value(latest_key)
    if current is None:
        return None, f"{latest_year}q{latest_q}"
    if latest_q == 4:
        return current, f"{latest_year}FY"
    prior_fy = value((latest_year - 1, 4))
    prior_cumulative = value((latest_year - 1, latest_q))
    if prior_fy is None or prior_cumulative is None:
        return None, f"{latest_year}q{latest_q}"
    return prior_fy + current - prior_cumulative, f"TTM through {latest_year}q{latest_q}"


def calculate_a_share_valuation(price: pd.DataFrame, reports: pd.DataFrame, shares: pd.DataFrame, as_of: str, benchmark: pd.DataFrame | None = None) -> dict[str, Any]:
    latest_price = _latest_price(price, as_of)
    report = _latest_report_rows(reports, as_of)
    revenue_col = _find(report, ("is_revenue", "operating_revenue", "revenue"))
    profit_col = _find(report, ("is_n_income_attr_p", "net_profit_parent", "net_profit"))
    equity_col = _find(report, ("bs_total_hldr_eqy_exc_min_int", "equity_parent", "total_equity"))
    ttm_profit, profit_period = _cumulative_ttm(report, profit_col) if profit_col else (None, None)
    ttm_revenue, revenue_period = _cumulative_ttm(report, revenue_col) if revenue_col else (None, None)
    latest_key = max((_quarter_number(value) for value in report.get("quarter", [])), default=None) if not report.empty else None
    latest_row = report.loc[report["quarter"].map(_quarter_number) == latest_key].iloc[-1] if latest_key and "quarter" in report.columns else None
    equity = float(pd.to_numeric(latest_row[equity_col], errors="coerce")) if latest_row is not None and equity_col and pd.notna(pd.to_numeric(latest_row[equity_col], errors="coerce")) else None
    share_frame = _as_of_frame(shares, as_of)
    total_col = _find(share_frame, ("total_a", "total"))
    total_shares = None
    if not share_frame.empty and total_col:
        if "date" in share_frame.columns:
            share_frame = share_frame.sort_values("date")
        number = pd.to_numeric(share_frame.iloc[-1][total_col], errors="coerce")
        total_shares = float(number) if pd.notna(number) else None
    market_cap = latest_price * total_shares if latest_price is not None and total_shares is not None else None
    pe = market_cap / ttm_profit if market_cap and ttm_profit and ttm_profit > 0 else None
    pb = market_cap / equity if market_cap and equity and equity > 0 else None
    ps = market_cap / ttm_revenue if market_cap and ttm_revenue and ttm_revenue > 0 else None
    benchmark_row = None
    if benchmark is not None and not benchmark.empty:
        benchmark = _as_of_frame(benchmark, as_of)
        if not benchmark.empty:
            benchmark_row = benchmark.sort_values("date").iloc[-1] if "date" in benchmark.columns else benchmark.iloc[-1]
    benchmark_pe = float(pd.to_numeric(benchmark_row["pe_ttm"], errors="coerce")) if benchmark_row is not None and "pe_ttm" in benchmark_row.index and pd.notna(pd.to_numeric(benchmark_row["pe_ttm"], errors="coerce")) else None
    benchmark_pb = float(pd.to_numeric(benchmark_row["pb_ttm"], errors="coerce")) if benchmark_row is not None and "pb_ttm" in benchmark_row.index and pd.notna(pd.to_numeric(benchmark_row["pb_ttm"], errors="coerce")) else None
    return {"status": "derived" if pe is not None or pb is not None else "empty", "latest_price": latest_price, "market_cap": market_cap, "total_shares": total_shares, "ttm_profit": ttm_profit, "ttm_revenue": ttm_revenue, "equity": equity, "pe_ttm": pe, "pb": pb, "ps": ps, "pe_percentile": None, "pb_percentile": None, "benchmark_symbol": str(benchmark_row.get("symbol")) if benchmark_row is not None and "symbol" in benchmark_row.index else None, "benchmark_pe_ttm": benchmark_pe, "benchmark_pb_ttm": benchmark_pb, "relative_pe": pe / benchmark_pe if pe is not None and benchmark_pe else None, "relative_pb": pb / benchmark_pb if pb is not None and benchmark_pb else None, "profit_period": profit_period, "revenue_period": revenue_period, "source_methods": ["get_stock_daily", "get_share_float", "get_fina_reports", "get_index_indicator"], "as_of": as_of, "caveat": "A股估值由截至分析日可得的股价、总股本、财务报表和指数估值重建；TTM采用上一完整年度+本年度累计-上年同期累计。不是 PandaData 单一估值接口返回值。"}


def calculate_factor_valuation(factor: pd.DataFrame, as_of: str, benchmark: pd.DataFrame | None = None) -> dict[str, Any]:
    """Read A-share valuation factors from get_factor.

    The factor endpoint is the canonical A-share source for PE/PB/market cap;
    the HK mktfin reader must not be used for .SH/.SZ symbols.
    """
    frame = _as_of_frame(factor, as_of, ("date",))
    if frame.empty:
        return {"status": "empty", "source_methods": ["get_factor"], "as_of": as_of, "caveat": "get_factor 未返回 A 股估值因子"}
    if "symbol" in frame.columns and "date" in frame.columns:
        frame = frame.sort_values(["symbol", "date"])
    pe_col = _find(frame, ("pe_ratio_ttm",))
    pe_lyr_col = _find(frame, ("pe_ratio_lyr",))
    pb_lf_col = _find(frame, ("pb_ratio_lf",))
    pb_ttm_col = _find(frame, ("pb_ratio_ttm",))
    pb_lyr_col = _find(frame, ("pb_ratio_lyr",))
    ps_col = _find(frame, ("ps_ratio_ttm", "ps_ratio_lyr"))
    cap_col = _find(frame, ("market_cap",))
    latest = frame.iloc[-1]

    def positive(column: str | None) -> float | None:
        if not column:
            return None
        value = pd.to_numeric(latest[column], errors="coerce")
        return float(value) if pd.notna(value) and float(value) > 0 else None

    pe, pe_lyr = positive(pe_col), positive(pe_lyr_col)
    pb_lf, pb_ttm, pb_lyr = positive(pb_lf_col), positive(pb_ttm_col), positive(pb_lyr_col)
    ps = positive(ps_col)
    pe_history = pd.to_numeric(frame[pe_col], errors="coerce") if pe_col else pd.Series(dtype=float)
    pb_history = pd.to_numeric(frame[pb_lf_col or pb_ttm_col or pb_lyr_col], errors="coerce") if (pb_lf_col or pb_ttm_col or pb_lyr_col) else pd.Series(dtype=float)
    benchmark_row = None
    if benchmark is not None and not benchmark.empty:
        benchmark = _as_of_frame(benchmark, as_of)
        if not benchmark.empty:
            benchmark_row = benchmark.sort_values("date").iloc[-1] if "date" in benchmark.columns else benchmark.iloc[-1]
    benchmark_pe = float(pd.to_numeric(benchmark_row["pe_ttm"], errors="coerce")) if benchmark_row is not None and "pe_ttm" in benchmark_row.index and pd.notna(pd.to_numeric(benchmark_row["pe_ttm"], errors="coerce")) else None
    benchmark_pb = float(pd.to_numeric(benchmark_row["pb_ttm"], errors="coerce")) if benchmark_row is not None and "pb_ttm" in benchmark_row.index and pd.notna(pd.to_numeric(benchmark_row["pb_ttm"], errors="coerce")) else None
    return {"status": "derived", "latest_price": None, "market_cap": float(pd.to_numeric(latest[cap_col], errors="coerce")) if cap_col and pd.notna(pd.to_numeric(latest[cap_col], errors="coerce")) else None, "pe_ttm": pe, "pe_lyr": pe_lyr, "pb_lf": pb_lf, "pb_ttm": pb_ttm, "pb_lyr": pb_lyr, "pb": pb_lf or pb_ttm or pb_lyr, "ps": ps, "pe_percentile": percentile_rank(pe_history, pe), "pb_percentile": percentile_rank(pb_history, pb_lf or pb_ttm or pb_lyr), "factor_date": str(latest.get("date")), "factor_fields": [column for column in (pe_col, pe_lyr_col, pb_lf_col, pb_ttm_col, pb_lyr_col, ps_col, cap_col) if column], "benchmark_symbol": str(benchmark_row.get("symbol")) if benchmark_row is not None and "symbol" in benchmark_row.index else None, "benchmark_pe_ttm": benchmark_pe, "benchmark_pb_ttm": benchmark_pb, "relative_pe": pe / benchmark_pe if pe is not None and benchmark_pe else None, "relative_pb": (pb_ttm or pb_lf or pb_lyr) / benchmark_pb if (pb_ttm or pb_lf or pb_lyr) is not None and benchmark_pb else None, "source_methods": ["get_factor", "get_index_indicator"], "as_of": as_of, "caveat": "A股 PE/PB/PS 来自 get_factor；历史分位是因子样本内的历史定价代理，不是正式分析师一致预期"}


def calculate_valuation_metrics(indicator: pd.DataFrame, price: pd.DataFrame, as_of: str, annual_eps: float | None = None, reports: pd.DataFrame | None = None, shares: pd.DataFrame | None = None, benchmark: pd.DataFrame | None = None, factor: pd.DataFrame | None = None) -> dict[str, Any]:
    if factor is not None and not factor.empty:
        return calculate_factor_valuation(factor, as_of, benchmark)
    if reports is not None and shares is not None and not reports.empty and not shares.empty:
        return calculate_a_share_valuation(price, reports, shares, as_of, benchmark)
    if indicator.empty:
        latest_price = _latest_price(price, as_of)
        pe_proxy = latest_price / annual_eps if latest_price is not None and annual_eps not in (None, 0) and annual_eps > 0 else None
        return {"status": "derived" if pe_proxy is not None else "empty", "pe_ttm": None, "pb": None, "pe_percentile": None, "pb_percentile": None, "price_annual_eps_pe_proxy": pe_proxy, "latest_price": latest_price, "source_methods": ["get_stock_daily", "get_fina_reports"], "as_of": as_of, "caveat": "估值接口无数据，当前只提供静态PE代理"}
    frame = indicator.copy()
    date_col = _find(frame, ("date", "trade_date", "ann_date"))
    if date_col:
        dates = frame[date_col].astype(str).str.replace("-", "", regex=False)
        frame = frame.loc[dates <= as_of]
    pe_col = _find(frame, ("pe_ttm", "pe", "pettm"))
    pb_col = _find(frame, ("pb", "pb_mrq"))
    latest = frame.iloc[-1] if not frame.empty else None
    pe = float(pd.to_numeric(latest[pe_col], errors="coerce")) if latest is not None and pe_col and pd.notna(pd.to_numeric(latest[pe_col], errors="coerce")) else None
    pb = float(pd.to_numeric(latest[pb_col], errors="coerce")) if latest is not None and pb_col and pd.notna(pd.to_numeric(latest[pb_col], errors="coerce")) else None
    return {"status": "ok" if latest is not None else "empty", "pe_ttm": pe if pe and pe > 0 else None, "pb": pb if pb and pb > 0 else None, "pe_percentile": percentile_rank(frame[pe_col], pe) if pe_col else None, "pb_percentile": percentile_rank(frame[pb_col], pb) if pb_col else None, "price_rows": len(price), "source_methods": ["get_stock_mktfin_indicator", "get_stock_daily"], "as_of": as_of, "caveat": "历史分位描述过去定价，不等同于真实市场一致预期"}


def infer_price_implied_expectation(price: float | None, earnings_base: float | None, horizon_years: int = 5, target_multiple: float = 15.0) -> dict[str, Any]:
    if price is None or earnings_base is None or price <= 0 or earnings_base <= 0 or horizon_years <= 0 or target_multiple <= 0:
        return {"status": "empty", "implied_growth": None, "formula": "(price / target_multiple / earnings_base) ** (1 / horizon_years) - 1", "caveat": "价格、盈利基数、目标倍数和期限必须有效"}
    implied_terminal_earnings = price / target_multiple
    growth = (implied_terminal_earnings / earnings_base) ** (1 / horizon_years) - 1
    return {"status": "derived", "implied_growth": float(growth), "target_multiple": target_multiple, "horizon_years": horizon_years, "formula": "(price / target_multiple / earnings_base) ** (1 / horizon_years) - 1", "caveat": "这是模型隐含增长要求，不是观测到的市场共识；目标倍数为假设"}


def margin_of_safety(intrinsic_value: float | None, market_price: float | None) -> float | None:
    if intrinsic_value is None or market_price in (None, 0):
        return None
    return float(intrinsic_value / market_price - 1)
