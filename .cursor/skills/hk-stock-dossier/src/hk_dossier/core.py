"""Core orchestrator — 协调各数据模块，并行抓取，生成完整研报."""

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from hk_dossier.client import PandadataClient
from hk_dossier.data import (
    profile as mod_profile,
    market as mod_market,
    financials as mod_financials,
    dividends as mod_dividends,
    shareholders as mod_shareholders,
    insider as mod_insider,
    consensus as mod_consensus,
    events as mod_events,
)
from hk_dossier.renderer import render_dossier

logger = logging.getLogger(__name__)


# Optional broker research module
try:
    from hk_dossier.data import research as mod_research

    _HAS_RESEARCH = True
except ImportError:
    _HAS_RESEARCH = False
    logger.debug("Research module not available")


def _fetch_all(client: PandadataClient, symbol: str) -> dict[str, Any]:
    """Fetch all data modules in parallel using a thread pool."""
    tasks = [
        ("profile", mod_profile.get_profile, client, symbol),
        ("market", mod_market.get_price_data, client, symbol),
        ("financials", mod_financials.get_financials, client, symbol),
        ("dividends", mod_dividends.get_dividends, client, symbol),
        ("shareholders", mod_shareholders.get_shareholders, client, symbol),
        ("insider", mod_insider.get_insider_trades, client, symbol),
        ("consensus", mod_consensus.get_consensus, client, symbol),
        ("events", mod_events.get_events, client, symbol),
    ]

    results: dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        future_map = {}
        for name, func, c, sym in tasks:
            logger.info("Dispatching %s...", name)
            future = pool.submit(func, c, sym)
            future_map[future] = name

        for future in as_completed(future_map):
            name = future_map[future]
            try:
                results[name] = future.result()
                logger.info("Fetched %s", name)
            except Exception as e:
                logger.error("Failed to fetch %s: %s", name, e)
                results[name] = {}

    return results


def _generate_charts(
    market: dict, symbol: str, output_dir: str | None
) -> dict[str, str]:
    """Generate charts if output directory is provided and daily data available."""
    chart_paths: dict[str, str] = {}
    if output_dir and market.get("daily") is not None:
        try:
            from hk_dossier.charts import generate_charts

            prefix = symbol.replace(".", "_").lower()
            chart_paths = generate_charts(
                market["daily"], output_dir=output_dir, prefix=prefix
            )
        except ImportError:
            logger.warning("Charts module not available, skipping chart generation")
        except Exception as e:
            logger.warning("Chart generation failed: %s", e)
    return chart_paths


def generate_dossier(
    symbol: str,
    client: PandadataClient | None = None,
    output_dir: str | None = None,
    **kwargs,
) -> str:
    """Generate a complete HK stock dossier for the given symbol.

    Args:
        symbol: HK stock symbol (e.g., "0700.HK")
        client: Optional PandadataClient instance.
        output_dir: If provided, also generate chart images in this directory.
        **kwargs: Additional arguments.

    Returns:
        Markdown-formatted dossier string.
    """
    if client is None:
        client = PandadataClient()

    logger.info("Generating dossier for %s...", symbol)

    # Normalize symbol
    symbol = symbol.upper().strip()
    if not symbol.endswith(".HK"):
        symbol = symbol + ".HK"
        logger.info("Normalized symbol to %s", symbol)

    # Fetch all data in parallel
    data = _fetch_all(client, symbol)

    profile = data.get("profile", {})
    market = data.get("market", {})
    financials = data.get("financials", {})
    dividends = data.get("dividends", {})
    shareholders = data.get("shareholders", {})
    insider = data.get("insider", {})
    consensus = data.get("consensus", {})
    events = data.get("events", {})

    # Post-process: compute valuation ratios from financials + market data
    financials = mod_financials.compute_ratios_from_market(financials, market)

    # Fetch broker research views and business analysis (optional, curated)
    research: dict = {}
    if _HAS_RESEARCH:
        try:
            logger.info("Fetching broker research views...")
            research = mod_research.get_broker_views(symbol)
        except Exception as e:
            logger.warning("Failed to fetch broker research: %s", e)
        try:
            biz = mod_research.get_business_analysis(symbol)
            if biz:
                research["business"] = biz
        except Exception as e:
            logger.warning("Failed to fetch business analysis: %s", e)

    # Generate charts (optional)
    chart_paths = _generate_charts(market, symbol, output_dir)

    # Render
    logger.info("Rendering dossier...")
    report = render_dossier(
        symbol=symbol,
        profile=profile,
        market=market,
        financials=financials,
        dividends=dividends,
        shareholders=shareholders,
        insider=insider,
        consensus=consensus,
        events=events,
        chart_paths=chart_paths,
        research=research,
    )

    logger.info("Dossier generation complete for %s", symbol)
    return report
