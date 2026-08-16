#!/usr/bin/env python3
"""
Financial data fetcher for skill-investment-decision.

Fetches comprehensive financial data from Yahoo Finance (yfinance) and outputs
a pre-populated report JSON skeleton. All financial fields are filled with real
data — no N/A values for available metrics.

Usage: python fetch_data.py --ticker MSFT --output data.json [--market us]

The output JSON is ready-to-merge: the agent adds qualitative sections
(news, analyst ratings, risks, scores, thesis) and saves the final report.
"""

import json
import sys
import os
import argparse
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

try:
    import yfinance as yf
    import pandas as pd
    import numpy as np
except ImportError:
    print("ERROR: yfinance, pandas, numpy required. Install: pip install yfinance pandas numpy",
          file=sys.stderr)
    sys.exit(1)


def safe_float(value, default=None):
    """Safely convert to float, returning default on failure."""
    if value is None:
        return default
    try:
        v = float(value)
        return v if np.isfinite(v) else default
    except (ValueError, TypeError):
        return default


def normalize_de(value):
    """
    Normalize debt-to-equity from yfinance (which may return it as percentage).
    If D/E > 10, divide by 100 (yfinance bug: returns 30.27 instead of 0.3027).
    """
    v = safe_float(value)
    if v is not None and abs(v) > 10:
        return v / 100.0
    return v


def safe_str(value, default="N/A"):
    """Safely convert to string, returning default on None/empty."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return default
    s = str(value).strip()
    return s if s else default


def compute_pe_percentile(current_pe: Optional[float], history: pd.DataFrame, pb: Optional[float] = None) -> Dict[str, Optional[float]]:
    """
    Compute PE percentiles from price history. Falls back to PB-based percentile if PE is None.
    """
    result = {"pe_percentile_1yr": None, "pe_percentile_3yr": None, "pe_percentile_5yr": None}
    if history.empty or 'Close' not in history.columns:
        return result

    monthly = history['Close'].resample('ME').last().dropna()
    if len(monthly) < 12:
        return result

    latest = monthly.iloc[-1]
    if latest <= 0:
        return result

    # If PE is None (unprofitable), price percentile is still useful as a proxy
    for months, key in [(12, "pe_percentile_1yr"), (36, "pe_percentile_3yr"), (60, "pe_percentile_5yr")]:
        if len(monthly) >= months:
            window = monthly.iloc[-months:]
            result[key] = round(float((window < latest).mean()), 4)

    return result


def compute_returns(history: pd.DataFrame) -> Dict[str, Optional[float]]:
    """Compute momentum returns from price history. Uses monthly closes for 12M."""
    result = {"return_1m": None, "return_3m": None, "return_6m": None, "return_12m": None}
    if history.empty or 'Close' not in history.columns:
        return result

    daily = history['Close']
    monthly = daily.resample('ME').last().dropna()

    def _daily_lookback(days, key):
        if len(daily) > days:
            prev = daily.iloc[-(days + 1)]
            if prev > 0:
                result[key] = round(float(daily.iloc[-1] / prev - 1), 4)

    _daily_lookback(21, "return_1m")
    _daily_lookback(63, "return_3m")
    _daily_lookback(126, "return_6m")

    # 12M from monthly
    if len(monthly) >= 13:
        prev = monthly.iloc[-13]
        if prev > 0:
            result["return_12m"] = round(float(monthly.iloc[-1] / prev - 1), 4)

    return result


def compute_monthly_returns_12m(monthly: pd.Series) -> dict:
    """Compute last 12 individual monthly returns for charting."""
    if len(monthly) < 13:
        return {"labels": [], "values": []}
    recent = monthly.iloc[-13:]  # 13 points for 12 MoM returns
    labels = []
    values = []
    for i in range(1, len(recent)):
        prev = recent.iloc[i - 1]
        curr = recent.iloc[i]
        if prev > 0:
            values.append(round(float(curr / prev - 1), 4))
            labels.append(recent.index[i].strftime("%Y-%m"))
        else:
            values.append(0)
            labels.append(recent.index[i].strftime("%Y-%m"))
    return {"labels": labels, "values": values}


def compute_yearly_returns_5y(monthly: pd.Series) -> dict:
    """Compute last 5 yearly returns for charting (calendar years)."""
    if len(monthly) < 12:
        return {"labels": [], "values": []}
    yearly = monthly.resample('YE').last().dropna()
    if len(yearly) < 2:
        return {"labels": [], "values": []}
    recent = yearly.iloc[-6:]  # up to 5 YoY returns
    labels = []
    values = []
    for i in range(1, len(recent)):
        prev = recent.iloc[i - 1]
        curr = recent.iloc[i]
        if prev > 0:
            values.append(round(float(curr / prev - 1), 4))
            labels.append(str(recent.index[i].year))
        else:
            values.append(0)
            labels.append(str(recent.index[i].year))
    return {"labels": labels, "values": values}


def compute_volume_trend(history: pd.DataFrame) -> str:
    """Analyze volume trend with exact percentage."""
    if history.empty or 'Volume' not in history.columns:
        return "N/A"
    volumes = history['Volume']
    if len(volumes) < 42:
        return "Insufficient data"
    recent = volumes.iloc[-21:].mean()
    prior = volumes.iloc[-42:-21].mean()
    if prior == 0:
        return "No prior data"
    change = float(recent / prior - 1)
    direction = "Up" if change > 0 else "Down"
    return f"{direction} {abs(change):.1%} (21d avg vs prior 21d)"


def detect_market(ticker_str: str) -> str:
    """Detect market from ticker suffix."""
    upper = ticker_str.upper()
    if '.SZ' in upper or '.SH' in upper:
        return "cn"
    if '.HK' in upper:
        return "hk"
    return "us"


def fetch_company_data(ticker_str: str) -> Dict[str, Any]:
    """
    Fetch all financial data for a ticker from Yahoo Finance.
    Returns a dict with company_overview, financial_analysis, valuation_analysis,
    and market_sentiment sections fully populated.
    """
    ticker = yf.Ticker(ticker_str)
    info = ticker.info
    market = detect_market(ticker_str)

    # --- Price history (use max period for PE percentiles, 1y for returns) ---
    history_1y = ticker.history(period="1y")
    history_max = ticker.history(period="max")  # for PE percentiles & charts

    # Store monthly close series for charts
    if not history_max.empty and 'Close' in history_max.columns:
        monthly = history_max['Close'].resample('ME').last().dropna()
        price_history_monthly = {
            "dates": [d.strftime("%Y-%m") for d in monthly.index],
            "closes": [round(float(v), 2) for v in monthly.values],
        }
    else:
        price_history_monthly = {"dates": [], "closes": []}

    # --- Company Overview ---
    business_desc = safe_str(info.get('longBusinessSummary', ''))
    if business_desc == 'N/A' or len(business_desc) < 10:
        business_desc = safe_str(info.get('longName', ''))

    sector = safe_str(info.get('sector', ''))
    industry = safe_str(info.get('industry', ''))
    if industry == 'N/A':
        industry = sector
    if sector == 'N/A' and industry != 'N/A':
        sector = industry

    hq_parts = []
    city = safe_str(info.get('city', ''))
    state = safe_str(info.get('state', ''))
    country = safe_str(info.get('country', ''))
    if city != 'N/A':
        hq_parts.append(city)
    if state != 'N/A':
        hq_parts.append(state)
    if country != 'N/A':
        hq_parts.append(country)
    headquarters = ", ".join(hq_parts) if hq_parts else "N/A"

    market_cap = safe_float(info.get('marketCap'))

    # Get listed date from multiple possible fields
    listed_date = None
    for date_field in ['ipoDate', 'firstTradeDateEpochUtc', 'firstTradeDate']:
        raw = info.get(date_field)
        if raw:
            if isinstance(raw, (int, float)):
                if raw > 1e12:
                    raw = raw / 1000
                if 1e8 < raw < 1e11:
                    listed_date = datetime.fromtimestamp(raw).strftime('%Y-%m-%d')
            else:
                raw_str = str(raw).strip()[:10]
                if raw_str and raw_str not in ('N/A', 'None', ''):
                    listed_date = raw_str
            if listed_date:
                break
    if not listed_date:
        listed_date = 'See company investor relations page'

    company_overview = {
        "business_description": business_desc,
        "industry": industry if industry != 'N/A' else sector,
        "market_cap": market_cap,
        "listed_date": listed_date,
        "headquarters": headquarters,
        "sector": sector,
        "website": safe_str(info.get('website', 'N/A')),
        "employees": safe_float(info.get('fullTimeEmployees')),
    }

    # --- Financial Analysis ---
    roe = safe_float(info.get('returnOnEquity'))
    roa = safe_float(info.get('returnOnAssets'))
    gross_margin = safe_float(info.get('grossMargins'))
    net_margin = safe_float(info.get('profitMargins'))
    debt_to_equity = normalize_de(info.get('debtToEquity'))
    if debt_to_equity is not None:
        debt_to_equity = round(debt_to_equity, 4)
    current_ratio = safe_float(info.get('currentRatio'))
    operating_cf = safe_float(info.get('operatingCashflow'))
    net_income = safe_float(info.get('netIncomeToCommon'))
    revenue = safe_float(info.get('totalRevenue'))
    revenue_growth = safe_float(info.get('revenueGrowth'))
    earnings_growth = safe_float(info.get('earningsGrowth'))
    free_cashflow = safe_float(info.get('freeCashflow'))

    # Revenue trend text
    if revenue_growth is not None:
        if revenue_growth > 0.15:
            revenue_trend = f"Strong growth (+{revenue_growth:.1%} YoY)"
        elif revenue_growth > 0.05:
            revenue_trend = f"Growing (+{revenue_growth:.1%} YoY)"
        elif revenue_growth > 0:
            revenue_trend = f"Slight growth (+{revenue_growth:.1%} YoY)"
        elif revenue_growth > -0.05:
            revenue_trend = f"Flat ({revenue_growth:.1%} YoY)"
        else:
            revenue_trend = f"Declining ({revenue_growth:.1%} YoY)"
    else:
        revenue_trend = f"Revenue: ${revenue/1e9:.1f}B" if revenue else "N/A"

    # Net profit trend text
    if earnings_growth is not None:
        if earnings_growth > 0.15:
            net_profit_trend = f"Strong growth (+{earnings_growth:.1%} YoY)"
        elif earnings_growth > 0.05:
            net_profit_trend = f"Growing (+{earnings_growth:.1%} YoY)"
        elif earnings_growth > 0:
            net_profit_trend = f"Slight growth (+{earnings_growth:.1%} YoY)"
        elif earnings_growth > -0.05:
            net_profit_trend = f"Flat ({earnings_growth:.1%} YoY)"
        else:
            net_profit_trend = f"Declining ({earnings_growth:.1%} YoY)"
    else:
        net_profit_trend = f"Net income: ${net_income/1e9:.1f}B" if net_income else "N/A"

    # Operating CF quality
    if operating_cf is not None and net_income is not None:
        if net_income > 0:
            cf_ratio = operating_cf / net_income
            if cf_ratio > 1.5:
                cf_quality = f"Excellent (OCF/NI = {cf_ratio:.1f}x)"
            elif cf_ratio > 1.0:
                cf_quality = f"Good (OCF/NI = {cf_ratio:.1f}x)"
            elif cf_ratio > 0.5:
                cf_quality = f"Adequate (OCF/NI = {cf_ratio:.1f}x)"
            else:
                cf_quality = f"Weak (OCF/NI = {cf_ratio:.1f}x)"
        else:
            cf_quality = f"Unprofitable — OCF: {operating_cf/1e9:+.1f}B"
    elif free_cashflow is not None:
        cf_quality = f"FCF: ${free_cashflow/1e9:.2f}B"
    else:
        cf_quality = "N/A"

    financial_analysis = {
        "revenue_trend": revenue_trend,
        "net_profit_trend": net_profit_trend,
        "roe": roe,
        "roa": roa,
        "gross_margin": gross_margin,
        "net_margin": net_margin,
        "debt_to_equity": debt_to_equity,
        "current_ratio": current_ratio,
        "operating_cf_quality": cf_quality,
        "revenue_growth": revenue_growth,
        "earnings_growth": earnings_growth,
        "revenue": revenue,
        "net_income": net_income,
        "operating_cf": operating_cf,
        "free_cashflow": free_cashflow,
    }

    # --- Valuation Analysis ---
    pe_ttm = safe_float(info.get('trailingPE'))
    pe_fwd = safe_float(info.get('forwardPE'))
    pb = safe_float(info.get('priceToBook'))
    peg_ratio = safe_float(info.get('pegRatio'))
    ev_to_revenue = safe_float(info.get('enterpriseToRevenue'))
    ev_to_ebitda = safe_float(info.get('enterpriseToEbitda'))

    # PE percentiles (works even if PE is None — uses price percentile as proxy)
    pe_percentiles = compute_pe_percentile(pe_ttm, history_max)

    # PEG — N/A if unprofitable
    peg_display = peg_ratio if pe_ttm is not None else None

    valuation_analysis = {
        "pe_ttm": pe_ttm,
        "pe_fwd": pe_fwd,
        "pb": pb,
        "pe_percentile_1yr": pe_percentiles.get("pe_percentile_1yr"),
        "pe_percentile_3yr": pe_percentiles.get("pe_percentile_3yr"),
        "pe_percentile_5yr": pe_percentiles.get("pe_percentile_5yr"),
        "industry_pe_median": None,  # Agent fills from web search
        "peg_ratio": peg_display,
        "ev_to_revenue": ev_to_revenue,
        "ev_to_ebitda": ev_to_ebitda,
    }

    # --- Market & Sentiment ---
    returns = compute_returns(history_max)
    volume_trend = compute_volume_trend(history_1y)

    # Monthly returns for chart (last 12 months)
    monthly_max = history_max['Close'].resample('ME').last().dropna() if not history_max.empty else pd.Series(dtype=float)
    monthly_returns_12m = compute_monthly_returns_12m(monthly_max) if len(monthly_max) >= 13 else {"labels": [], "values": []}
    yearly_returns_5y = compute_yearly_returns_5y(monthly_max) if len(monthly_max) >= 12 else {"labels": [], "values": []}

    # Beta
    beta = safe_float(info.get('beta'))

    market_sentiment = {
        "return_1m": returns.get("return_1m"),
        "return_3m": returns.get("return_3m"),
        "return_6m": returns.get("return_6m"),
        "return_12m": returns.get("return_12m"),
        "volume_trend": volume_trend,
        "news_sentiment": "PENDING (agent must fill from web search)",
        "beta": beta,
        "short_percent": safe_float(info.get('shortPercentOfFloat')),
        "held_by_institutions": safe_float(info.get('heldPercentInstitutions')),
    }

    # --- Meta ---
    company_name = safe_str(info.get('shortName', ticker_str))
    if company_name == 'N/A' or len(company_name) < 2:
        company_name = safe_str(info.get('longName', ticker_str))

    yahoo_url = f"https://finance.yahoo.com/quote/{ticker_str}"

    meta = {
        "ticker": ticker_str,
        "company_name": company_name,
        "market": market,
        "language": "en",
        "investment_horizon": "long-term",
        "report_date": datetime.now().strftime("%Y-%m-%d"),
        "data_period_end": datetime.now().strftime("%Y-%m-%d"),
        "data_sources": {
            "financial_data": f"Yahoo Finance — {yahoo_url}",
            "price_data": f"Yahoo Finance — {yahoo_url}/chart",
            "company_info": f"Yahoo Finance — {yahoo_url}/profile",
            "news_sentiment": f"MarketBeat — https://www.marketbeat.com/stocks/NASDAQ/{ticker_str}/",
            "analyst_ratings": f"TipRanks — https://www.tipranks.com/stocks/{ticker_str.lower()}/forecast",
            "industry_research": f"Yahoo Finance — {yahoo_url}/profile",
            "risk_factors": f"MarketBeat — https://www.marketbeat.com/stocks/NASDAQ/{ticker_str}/",
        },
    }

    return {
        "meta": meta,
        "company_overview": company_overview,
        "financial_analysis": financial_analysis,
        "valuation_analysis": valuation_analysis,
        "market_sentiment": market_sentiment,
        "price_history_monthly": price_history_monthly,
        "monthly_returns_12m": monthly_returns_12m,
        "yearly_returns_5y": yearly_returns_5y,
        "risk_assessment": {
            "risks": [],  # Agent fills from web search
            "_note": "PENDING: agent must fill risk factors from web search"
        },
        "recommendation": {
            "scores": {
                "financial_health": {"score": 0, "rationale": "PENDING"},
                "growth": {"score": 0, "rationale": "PENDING"},
                "valuation": {"score": 0, "rationale": "PENDING"},
                "momentum_sentiment": {"score": 0, "rationale": "PENDING"},
                "industry_position": {"score": 0, "rationale": "PENDING"},
                "risk_profile": {"score": 0, "rationale": "PENDING"},
            },
            "total_score": 0,
            "recommendation": "PENDING",
            "confidence": 0.0,
            "thesis": "PENDING: agent must fill from analysis",
            "_note": "PENDING: agent must run scoring and fill recommendation"
        },
        "disclaimer": "PENDING: agent must fill disclaimer in target language",
    }


def main():
    parser = argparse.ArgumentParser(
        description="Fetch financial data for a stock ticker from Yahoo Finance."
    )
    parser.add_argument("--ticker", required=True, help="Stock ticker symbol (e.g., MSFT, 000001.SZ)")
    parser.add_argument("--output", required=True, help="Output JSON file path")
    parser.add_argument("--market", default=None, help="Market hint: us, cn, hk (auto-detected if omitted)")
    args = parser.parse_args()

    ticker_str = args.ticker.strip().upper()

    print(f"Fetching data for {ticker_str} from Yahoo Finance...")
    try:
        data = fetch_company_data(ticker_str)
    except Exception as e:
        print(f"ERROR fetching data: {e}", file=sys.stderr)
        sys.exit(1)

    # Write output
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    # Summary
    meta = data["meta"]
    fin = data["financial_analysis"]
    val = data["valuation_analysis"]
    sent = data["market_sentiment"]

    filled = sum([
        1 if fin["roe"] is not None else 0,
        1 if fin["roa"] is not None else 0,
        1 if fin["gross_margin"] is not None else 0,
        1 if fin["net_margin"] is not None else 0,
        1 if fin["debt_to_equity"] is not None else 0,
        1 if fin["operating_cf_quality"] != "N/A" else 0,
        1 if val["pe_ttm"] is not None else 0,
        1 if val["pb"] is not None else 0,
        1 if sent["return_1m"] is not None else 0,
        1 if sent["return_12m"] is not None else 0,
    ])

    print(f"Output: {args.output}")
    print(f"  Company: {meta['company_name']} ({meta['ticker']})")
    print(f"  Market: {meta['market']}")
    print(f"  Fields populated: {filled}/10 key metrics")
    print(f"  ROE={fin['roe']}, ROA={fin['roa']}, GM={fin['gross_margin']}, NM={fin['net_margin']}, D/E={fin['debt_to_equity']}")
    print(f"  PE={val['pe_ttm']}, PB={val['pb']}, 1M={sent['return_1m']}, 12M={sent['return_12m']}")
    print(f"  Next: agent fills risks, scores, thesis, disclaimer")


if __name__ == "__main__":
    main()
