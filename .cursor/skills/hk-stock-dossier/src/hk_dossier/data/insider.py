"""Insider trading — 内部人交易活动."""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def get_insider_trades(client: Any, symbol: str) -> dict[str, Any]:
    """Fetch insider trading activities.

    Returns:
      - trades: list of insider trade records
      - summary: aggregated stats (total transactions, net direction)
    """
    result: dict[str, Any] = {}

    try:
        df = client.call(
            "get_stock_insider_trade",
            symbol=symbol,
            fields=[],
            start_date="20230101",
            end_date="20271231",
        )
        if df is not None and not df.empty:
            df = df.sort_values("info_date", ascending=False).reset_index(drop=True)
            records = df.to_dict("records")
            result["trades"] = records

            # Summary
            total_volume = sum(
                float(r.get("adjusted_trade_shares", 0) or 0) for r in records
            )
            buy_count = sum(
                1
                for r in records
                if str(r.get("transaction_type", "")).lower() == "buy"
            )
            sell_count = sum(
                1
                for r in records
                if str(r.get("transaction_type", "")).lower() == "sale of shares"
                or str(r.get("transaction_type", "")).lower() == "sell"
            )
            result["summary"] = {
                "total_transactions": len(records),
                "buy_count": buy_count,
                "sell_count": sell_count,
                "net_volume": total_volume,
            }
        else:
            result["trades"] = []
            result["summary"] = {}
    except Exception as e:
        logger.warning("Failed to fetch insider trades for %s: %s", symbol, e)
        result["trades"] = []
        result["summary"] = {}

    return result
