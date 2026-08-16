"""Financial data — 财务三表、关键比率与行业中位数.

注意：
  1. HK 的 get_stock_mktfin_indicator 仅有 curr_sales_per_emp / curr_net_inc_per_emp，
     无 PE/PB/EV 字段（与 A 股不同）。
  2. HK 的 get_fina_statement 使用 HK 特有字段名（不带 _accruals 后缀），且币种为 CNY。
  3. 估值指标（PE/PB/股息率）从报表数据 + 行情数据计算得出。
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# HK fina_statement 字段映射（区别于 A 股 schema）
_HK_STMT_FIELDS = {
    "total_assets": "bs_asset_accruals",
    "total_liabilities": "bs_total_liabilities",
    "total_equity": "bs_shareholders_equity_parent",
    "revenue": "is_sales_goods_services_net",
    "gross_profit": "is_gross_profit",
    "ebit": "is_ebit",
    "net_income": "is_income_available_common",
    "operating_cf": "cfs_net_cf_operating",
    "basic_eps": "is_eps_basic_inc_exord",
    "diluted_eps": "is_eps_diluted_inc_exord",
    "total_shares": "bs_common_shares_outstanding",
    "fy_period": "fy_period",
    "currency": "currency",
}


def _extract_stmt_fields(row: Any) -> dict[str, Any]:
    """Extract and rename fields from a fina_statement row using HK field mapping."""
    result = {}
    for our_name, api_name in _HK_STMT_FIELDS.items():
        try:
            val = row.get(api_name)
            # Filter out NaN
            if val is not None and (isinstance(val, float) and val == val):
                result[our_name] = val
            elif val is not None and not (isinstance(val, float) and val != val):
                result[our_name] = val
        except Exception:
            pass
    return result


def _compute_ratios(
    stmt: dict, market: dict, close_price: float | None
) -> dict[str, Any]:
    """Compute valuation ratios from statement data + market data.

    Returns dict with keys like pe_ttm, pb, dividend_yield etc.
    """
    ratios: dict[str, Any] = {}

    if not close_price:
        return ratios

    try:
        price = float(close_price)

        # PE = price / EPS
        eps = stmt.get("basic_eps")
        if eps is not None and float(eps) != 0:
            ratios["pe_ttm"] = price / abs(float(eps)) * (-1 if float(eps) < 0 else 1)
            ratios["pe_positive"] = float(eps) > 0

        # PB = price / (book_value_per_share)
        total_equity = stmt.get("total_equity")
        total_shares = stmt.get("total_shares")
        if total_equity is not None and total_shares is not None and float(total_shares) > 0:
            bvps = float(total_equity) / float(total_shares)
            ratios["pb"] = price / bvps
            ratios["bvps"] = bvps

        # Gross margin
        revenue = stmt.get("revenue")
        gross_profit = stmt.get("gross_profit")
        if revenue is not None and gross_profit is not None and float(revenue) > 0:
            ratios["gross_margin"] = float(gross_profit) / float(revenue) * 100

        # Net margin
        net_income = stmt.get("net_income")
        if net_income is not None and revenue is not None and float(revenue) > 0:
            ratios["net_margin"] = float(net_income) / float(revenue) * 100

        # ROE
        if net_income is not None and total_equity is not None and float(total_equity) > 0:
            ratios["roe"] = float(net_income) / float(total_equity) * 100

        # Dividend yield from latest dividend event
        divs = market.get("dividend_events", [])
        if divs and close_price:
            try:
                latest_div = divs[0].get("number")
                if latest_div is not None and float(close_price) > 0:
                    ratios["dividend_yield"] = float(latest_div) / float(close_price) * 100
            except (ValueError, TypeError):
                pass

        # Market cap from price * shares
        if total_shares is not None:
            ratios["market_cap_calculated"] = price * float(total_shares)
            ratios["market_cap_currency"] = "HKD"

    except (ValueError, TypeError, ZeroDivisionError) as e:
        logger.debug("Failed to compute ratios: %s", e)

    return ratios


def get_financials(client: Any, symbol: str) -> dict[str, Any]:
    """Fetch financial statements and compute valuation ratios.

    Returns dict with:
      - statement: dict of extracted financial statement fields
      - mktfin: market financial indicator ratios (HK naming: curr_sales_per_emp_ttm, etc.)
      - industry_median: industry median ratios for comparison
      - computed_ratios: PE/PB/etc computed from statement + market data
    """
    result: dict[str, Any] = {}

    # --- Financial statements ---
    try:
        df = client.call(
            "get_fina_statement",
            symbol=symbol,
            start_quarter="2024q3",
            end_quarter="2026q2",
            is_latest=True,
            fields=[],
        )
        if df is not None and not df.empty:
            row = df.iloc[0]
            result["statement"] = _extract_stmt_fields(row)
        else:
            result["statement"] = {}
    except Exception as e:
        logger.warning(
            "Failed to fetch financial statement for %s: %s", symbol, e
        )
        # Retry with shorter range
        try:
            df = client.call(
                "get_fina_statement",
                symbol=symbol,
                start_quarter="2025q4",
                end_quarter="2026q2",
                is_latest=True,
                fields=[],
            )
            if df is not None and not df.empty:
                row = df.iloc[0]
                result["statement"] = _extract_stmt_fields(row)
            else:
                result["statement"] = {}
        except Exception as e2:
            logger.warning("Retry also failed: %s", e2)
            result["statement"] = {}

    # --- Market financial indicators (only per-employee data for HK) ---
    try:
        mkt_df = client.call(
            "get_stock_mktfin_indicator", symbol=[symbol], fields=[]
        )
        if mkt_df is not None and not mkt_df.empty:
            row = mkt_df.iloc[0]
            result["mktfin"] = {
                "sales_per_emp": row.get("curr_sales_per_emp_ttm"),
                "sales_per_emp_currency": row.get("curr_sales_per_emp_currency_ttm"),
                "net_inc_per_emp": row.get("curr_net_inc_per_emp_ttm"),
                "net_inc_per_emp_currency": row.get("curr_net_inc_per_emp_currency_ttm"),
            }
        else:
            result["mktfin"] = {}
    except Exception as e:
        logger.warning("Failed to fetch mktfin indicators for %s: %s", symbol, e)
        result["mktfin"] = {}

    # --- Industry median ---
    try:
        ind_df = client.call(
            "get_stock_industry_median", symbol=[symbol], fields=[]
        )
        if ind_df is not None and not ind_df.empty:
            row = ind_df.iloc[0]
            result["industry_median"] = {
                "industry_name": row.get("industry_name"),
                "imed_pe_ttm": row.get("imed_pe_ttm"),
                "imed_pb_ttm": row.get("imed_pb_ttm"),
                "imed_ps_ttm": row.get("imed_ps_ttm"),
                "imed_roe_avg_common_ttm": row.get("imed_roe_avg_common_ttm"),
                "imed_pretax_roa_ratio_ttm": row.get("imed_pretax_roa_ratio_ttm"),
                "imed_gross_div_yield_ttm": row.get("imed_gross_div_yield_ttm"),
                "imed_gross_margin_ratio_fye_mid": row.get("imed_gross_margin_ratio_fye_mid"),
                "imed_net_margin_ratio_fye_mid": row.get("imed_net_margin_ratio_fye_mid"),
                "imed_ebitda_margin_ratio_fye_mid": row.get("imed_ebitda_margin_ratio_fye_mid"),
                "imed_debt_to_equity_ratio_fye_mid": row.get("imed_debt_to_equity_ratio_fye_mid"),
                "imed_curr_ratio_fye_mid": row.get("imed_curr_ratio_fye_mid"),
                "imed_asset_turnover_ttm": row.get("imed_asset_turnover_ttm"),
            }
        else:
            result["industry_median"] = {}
    except Exception as e:
        logger.warning("Failed to fetch industry median for %s: %s", symbol, e)
        result["industry_median"] = {}

    return result


def compute_ratios_from_market(
    financials: dict, market_data: dict
) -> dict[str, Any]:
    """Post-process: compute valuation ratios using market data.

    Call this from core.py after both financials and market data are available.
    """
    stmt = financials.get("statement", {}) or {}

    # Get close price from market data
    pv = market_data.get("pv_indicators", {}) or {}
    summary = market_data.get("summary", {}) or {}
    close = summary.get("latest_close") or pv.get("close")

    # Pass dividend events for yield computation
    ratios = _compute_ratios(stmt, market_data, close)

    financials["computed_ratios"] = ratios
    return financials
