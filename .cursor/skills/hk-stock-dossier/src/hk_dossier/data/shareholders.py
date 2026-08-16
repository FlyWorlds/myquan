"""Shareholder structure — 股东集中度与持股报告."""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def get_shareholders(client: Any, symbol: str) -> dict[str, Any]:
    """Fetch shareholder concentration and shareholder holding reports.

    Returns:
      - concentration: overall investor concentration
      - top20_concentration: top 20 investor concentration
      - holdings: shareholder holding reports
    """
    result: dict[str, Any] = {}

    # --- Overall investor concentration ---
    try:
        conc_df = client.call(
            "get_stock_investor_concentration", symbol=[symbol], fields=[]
        )
        if conc_df is not None and not conc_df.empty:
            row = conc_df.iloc[0]
            result["concentration"] = {
                "total_investors": int(row.get("total_investors", 0) or 0),
                "investor_outstanding_ratio": row.get("investor_outstanding_ratio"),
                "total_sharehold": row.get("total_sharehold"),
                "total_holdings_value": row.get("total_holdings_value"),
                "currency": row.get("currency"),
            }
        else:
            result["concentration"] = {}
    except Exception as e:
        logger.warning("Failed to fetch concentration for %s: %s", symbol, e)
        result["concentration"] = {}

    # --- Top 20 concentration ---
    try:
        top_df = client.call(
            "get_stock_top20_concentration", symbol=[symbol], fields=[]
        )
        if top_df is not None and not top_df.empty:
            row = top_df.iloc[0]
            result["top20"] = {
                "top_investors_num": int(row.get("top_investors_num", 0) or 0),
                "investor_outstanding_ratio": row.get("investor_outstanding_ratio"),
                "sharehold": row.get("sharehold"),
                "holdings_value": row.get("holdings_value"),
                "currency": row.get("currency"),
            }
        else:
            result["top20"] = {}
    except Exception as e:
        logger.warning("Failed to fetch top20 for %s: %s", symbol, e)
        result["top20"] = {}

    # --- Shareholder holding reports ---
    try:
        hold_df = client.call(
            "get_stock_shareholder_holding",
            symbol=symbol,
            fields=[],
            start_date="20230101",
            end_date="20271231",
        )
        if hold_df is not None and not hold_df.empty:
            hold_df = hold_df.sort_values("holding_date", ascending=False).reset_index(drop=True)
            result["holdings"] = hold_df.to_dict("records")
        else:
            result["holdings"] = []
    except Exception as e:
        logger.warning("Failed to fetch holdings for %s: %s", symbol, e)
        result["holdings"] = []

    return result
