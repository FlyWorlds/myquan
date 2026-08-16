"""Core orchestrator — coordinates data fetching, analysis, and report generation."""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any

import pandas as pd

from oil_brief.client import PandadataClient
from oil_brief.fetchers import china as china_fetcher
from oil_brief.fetchers import news as news_fetcher
from oil_brief.fetchers.eia import EIAClient
from oil_brief.analysis import (
    compute_all_indicators,
    find_support_resistance,
    analyze_trend,
    get_latest_indicators,
)
from oil_brief.renderer import render_report

logger = logging.getLogger(__name__)


VARIETY_CONFIG = {
    # Crude oil
    "BRENT": {
        "label": "Brent 原油",
        "unit": "美元/桶",
        "yahoo_ticker": "BZ=F",
        "category": "crude",
    },
    "WTI": {
        "label": "WTI 原油",
        "unit": "美元/桶",
        "yahoo_ticker": "CL=F",
        "category": "crude",
    },
    "SC": {
        "label": "上海原油期货",
        "unit": "元/桶",
        "yahoo_ticker": None,
        "category": "crude",
    },
    # Natural gas
    "NG": {
        "label": "天然气",
        "unit": "美元/百万英热",
        "yahoo_ticker": "NG=F",
        "category": "natgas",
    },
    # RBOB Gasoline
    "RB": {
        "label": "RBOB 汽油",
        "unit": "美元/加仑",
        "yahoo_ticker": "RB=F",
        "category": "gasoline",
    },
    # Heating Oil
    "HO": {
        "label": "取暖油",
        "unit": "美元/加仑",
        "yahoo_ticker": "HO=F",
        "category": "heating_oil",
    },
}


def _fetch_sc_data(client: PandadataClient, days: int = 120) -> dict[str, Any]:
    """Fetch SC crude oil futures data from Pandadata."""
    data = china_fetcher.fetch_all(client, days=days)
    logger.info("SC data: daily=%d rows", len(data.get("daily", [])))
    return data


def _fetch_eia_data() -> dict[str, Any]:
    """Fetch crude oil prices and daily OHLCV from Yahoo Finance."""
    eia_client = EIAClient()
    data = eia_client.fetch_all()
    # Also fetch Brent and WTI daily OHLCV for technical analysis fallback
    data["brent_daily"] = eia_client.get_brent_daily(days=120)
    data["wti_daily"] = eia_client.get_wti_daily(days=120)
    logger.info("Oil prices: WTI=%d rows, Brent=%d rows",
                len(data.get("wti_spot", [])), len(data.get("brent_spot", [])))
    return data


def _fetch_news_data() -> dict[str, Any]:
    """Fetch news and macro events."""
    news = news_fetcher.fetch_crude_news(days=3)
    events = news_fetcher.get_macro_events(days=7)
    logger.info("News: %d items, %d events", len(news), len(events))
    return {"news": news, "events": events}


def generate_report(
    variety: str = "BRENT",
    days: int = 120,
    output_path: str | None = None,
    client: PandadataClient | None = None,
    verbose: bool = False,
) -> str:
    """Generate a complete crude oil briefing report.

    Args:
        variety: Analysis target — "BRENT" (default), "WTI", or "SC".
        days: Days of historical data for analysis.
        output_path: If provided, save report to this path.
        client: Optional PandadataClient instance.
        verbose: Enable verbose logging.

    Returns:
        Markdown-formatted briefing report string.
    """
    variety = variety.upper()
    if client is None:
        client = PandadataClient()

    logger.info("Generating crude oil briefing for %s...", variety)
    report_date = datetime.now().strftime("%Y-%m-%d %H:%M")

    cfg = VARIETY_CONFIG.get(variety, VARIETY_CONFIG["BRENT"])
    logger.info("Primary analysis target: %s", cfg["label"])
    eia_client = EIAClient()

    # ── Parallel data fetching ──
    sc_data: dict[str, Any] = {}
    eia_data: dict[str, Any] = {}
    news_data: dict[str, Any] = {"news": [], "events": []}

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(_fetch_sc_data, client, days): "sc",
            pool.submit(_fetch_eia_data): "eia",
            pool.submit(_fetch_news_data): "news",
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                result = future.result()
                if name == "sc":
                    sc_data = result
                elif name == "eia":
                    eia_data = result
                elif name == "news":
                    news_data = result
                logger.info("Data module %s completed", name)
            except Exception as e:
                logger.error("Data module %s failed: %s", name, e)

    # ── Pick daily OHLCV for technical analysis based on variety ──
    daily_df = None
    yahoo_ticker = cfg.get("yahoo_ticker")

    if variety == "SC":
        daily_df = sc_data.get("daily", None)
    elif yahoo_ticker:
        # Fetch daily OHLCV from Yahoo for any commodity ticker
        try:
            daily_df = eia_client.get_energy_daily(yahoo_ticker, days=days)
            if daily_df is not None and not daily_df.empty:
                logger.info("Using %s (%s) daily data for TA: %d rows",
                            cfg["label"], yahoo_ticker, len(daily_df))
        except Exception as e:
            logger.warning("Failed to fetch %s daily data: %s", yahoo_ticker, e)

    # ── Technical analysis ──
    indicator_df = None
    indicators: dict[str, Any] = {}
    trend: dict[str, Any] = {"trend": "unknown", "strength": "unknown", "duration_days": 0}
    sr_levels: dict[str, Any] = {"support": [], "resistance": []}

    if daily_df is not None and not daily_df.empty:
        for col in ["open", "high", "low", "close", "volume"]:
            if col in daily_df.columns:
                daily_df[col] = pd.to_numeric(daily_df[col], errors="coerce")

        indicator_df = compute_all_indicators(daily_df)
        indicators = get_latest_indicators(indicator_df)
        trend = analyze_trend(indicator_df)
        sr_levels = find_support_resistance(indicator_df, lookback=min(60, len(indicator_df)))

        logger.info("Technical analysis: trend=%s, strength=%s, close=%.2f",
                     trend["trend"], trend["strength"], indicators.get("close", 0))
    else:
        logger.warning("No daily data for TA on %s", variety)

    # ── Gather latest prices for all three benchmarks ──
    def _latest_from(df, col="value"):
        if df is not None and isinstance(df, pd.DataFrame) and not df.empty and col in df.columns:
            return float(df[col].iloc[-1])
        return None

    def _compute_change(df, col="close"):
        """Compute daily % change from last 2 rows."""
        if df is not None and isinstance(df, pd.DataFrame) and len(df) >= 2:
            vals = pd.to_numeric(df[col], errors="coerce").dropna()
            if len(vals) >= 2:
                return float((vals.iloc[-1] / vals.iloc[-2] - 1) * 100)
        return None

    latest_wti = _latest_from(eia_data.get("wti_spot"))
    latest_brent = _latest_from(eia_data.get("brent_spot"))
    latest_sc = _latest_from(sc_data.get("daily"), col="close")

    wti_change_pct = _compute_change(eia_data.get("wti_daily"))
    brent_change_pct = _compute_change(eia_data.get("brent_daily"))
    sc_change_pct = _compute_change(sc_data.get("daily"), col="close")

    # Primary price from TA indicators (already has close from indicators)
    latest_primary = indicators.get("close", None)

    # If primary is from TA but we couldn't compute it, fall back to latest
    if latest_primary is None and variety == "BRENT":
        latest_primary = latest_brent
    elif latest_primary is None and variety == "WTI":
        latest_primary = latest_wti
    elif latest_primary is None and variety == "SC":
        latest_primary = latest_sc

    indicators["close"] = indicators.get("close", latest_primary or 0)

    # ── Render report ──
    logger.info("Rendering report...")

    def _to_dict(df):
        if df is None or df.empty:
            return {}
        try:
            return df.to_dict("records")
        except Exception:
            return {}

    report = render_report(
        report_date=report_date,
        variety=variety,
        primary_label=cfg["label"],
        primary_unit=cfg["unit"],
        sc_data=_to_dict(sc_data.get("daily")),
        indicators=indicators,
        trend=trend,
        sr_levels=sr_levels,
        eia_data={
            "wti_spot": _to_dict(eia_data.get("wti_spot")),
            "brent_spot": _to_dict(eia_data.get("brent_spot")),
            "crude_stocks": _to_dict(eia_data.get("crude_stocks")),
            "crude_production": _to_dict(eia_data.get("crude_production")),
        },
        term_structure=_to_dict(sc_data.get("term_structure")),
        warehouse=_to_dict(sc_data.get("warehouse")),
        ls_ratio=_to_dict(sc_data.get("ls_ratio")),
        position=_to_dict(sc_data.get("position")),
        spread=_to_dict(sc_data.get("spread")),
        news=news_data.get("news", []),
        events=news_data.get("events", []),
        latest_primary_price=latest_primary,
        latest_sc_price=latest_sc,
        latest_wti=latest_wti,
        latest_brent=latest_brent,
        wti_change_pct=wti_change_pct,
        brent_change_pct=brent_change_pct,
        sc_change_pct=sc_change_pct,
        energy_category=cfg.get("category", "crude"),
    )

    # ── Save if output path provided ──
    if output_path:
        from pathlib import Path
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report)
        logger.info("Report saved to %s", output_path)

    logger.info("Report generation complete")
    return report
