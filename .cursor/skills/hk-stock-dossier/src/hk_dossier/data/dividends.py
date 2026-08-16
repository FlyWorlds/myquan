"""Dividends & capital market events — 分红与市场活动."""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def get_dividends(client: Any, symbol: str) -> dict[str, Any]:
    """Fetch dividend events and market activity events.

    Returns:
      - dividend_events: list of dividend-related events
      - market_events: list of market activity events (placements, etc.)
    """
    result: dict[str, Any] = {}

    # --- Dividend events ---
    try:
        df = client.call(
            "get_stock_dividend_event",
            symbol=symbol,
            fields=[],
            start_date="20230101",
            end_date="20271231",
        )
        if df is not None and not df.empty:
            df = df.sort_values("publish_date", ascending=False).reset_index(drop=True)
            result["dividend_events"] = df.to_dict("records")
        else:
            result["dividend_events"] = []
    except Exception as e:
        logger.warning("Failed to fetch dividends for %s: %s", symbol, e)
        result["dividend_events"] = []

    # --- Market events (placements, lockups, etc.) ---
    try:
        mkt_df = client.call(
            "get_stock_market_event",
            symbol=symbol,
            fields=[],
            start_date="20230101",
            end_date="20271231",
        )
        if mkt_df is not None and not mkt_df.empty:
            mkt_df = mkt_df.sort_values("info_date", ascending=False).reset_index(drop=True)
            result["market_events"] = mkt_df.to_dict("records")
        else:
            result["market_events"] = []
    except Exception as e:
        logger.warning("Failed to fetch market events for %s: %s", symbol, e)
        result["market_events"] = []

    return result
