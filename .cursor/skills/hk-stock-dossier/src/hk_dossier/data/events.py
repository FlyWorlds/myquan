"""Corporate events — 公司会议、财务披露与投资者关系活动."""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def get_events(client: Any, symbol: str) -> dict[str, Any]:
    """Fetch corporate events: meetings, financial disclosures, IR activities.

    Returns:
      - meeting_events: company meeting events
      - financial_events: financial disclosure events
      - ir_events: investor relations events
    """
    result: dict[str, Any] = {}

    # --- Meeting events (HK fields: info_date, start_date, end_date, event, event_type) ---
    try:
        m_df = client.call(
            "get_stock_meeting_event",
            symbol=symbol,
            fields=[],
            start_date="20230101",
            end_date="20271231",
        )
        if m_df is not None and not m_df.empty:
            m_df = m_df.sort_values("start_date", ascending=False).reset_index(
                drop=True
            )
            result["meeting_events"] = m_df.to_dict("records")
        else:
            result["meeting_events"] = []
    except Exception as e:
        logger.warning("Failed to fetch meeting events for %s: %s", symbol, e)
        result["meeting_events"] = []

    # --- Financial events (HK fields: info_date, event, event_type, fiscal_quarter) ---
    try:
        f_df = client.call(
            "get_stock_financial_event",
            symbol=symbol,
            fields=[],
            start_date="20230101",
            end_date="20271231",
        )
        if f_df is not None and not f_df.empty:
            f_df = f_df.sort_values("info_date", ascending=False).reset_index(
                drop=True
            )
            result["financial_events"] = f_df.to_dict("records")
        else:
            result["financial_events"] = []
    except Exception as e:
        logger.warning("Failed to fetch financial events for %s: %s", symbol, e)
        result["financial_events"] = []

    # --- IR events ---
    try:
        ir_df = client.call(
            "get_stock_ir_event",
            symbol=symbol,
            fields=[],
            start_date="20230101",
            end_date="20271231",
        )
        if ir_df is not None and not ir_df.empty:
            ir_df = ir_df.sort_values("info_date", ascending=False).reset_index(
                drop=True
            )
            result["ir_events"] = ir_df.to_dict("records")
        else:
            result["ir_events"] = []
    except Exception as e:
        logger.warning("Failed to fetch IR events for %s: %s", symbol, e)
        result["ir_events"] = []

    return result
