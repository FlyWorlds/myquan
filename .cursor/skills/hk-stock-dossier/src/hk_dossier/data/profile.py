"""Company profile data — 公司基本信息."""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def get_profile(client: Any, symbol: str) -> dict[str, Any]:
    """Fetch company basic information via get_hk_detail.

    Returns a dict with keys: name, cn_name, symbol, listed_date, industry,
    website, office, board_type, status, etc.
    """
    try:
        df = client.call("get_hk_detail", symbol=[symbol], fields=[], status=None)
    except Exception as e:
        logger.warning("Failed to fetch profile for %s: %s", symbol, e)
        return {"error": str(e), "symbol": symbol}

    if df is None or df.empty:
        logger.warning("No profile data for %s", symbol)
        return {"symbol": symbol}

    row = df.iloc[0]
    return {
        "symbol": row.get("symbol", symbol),
        "name": row.get("name", ""),
        "cn_name": row.get("cn_name", ""),
        "local_name": row.get("local_name", ""),
        "status": row.get("status"),
        "isin_code": row.get("isin_code", ""),
        "abbrev_symbol": row.get("abbrev_symbol", ""),
        "min_order_amount": row.get("min_order_amount", ""),
        "trading_code": row.get("trading_code", ""),
        "asset_state": row.get("asset_state", ""),
        "business_sector": row.get("business_sector", ""),
        "economic_sector": row.get("economic_sector", ""),
        "industry_group": row.get("industry_group", ""),
        "incorp_date": str(row.get("incorp_date", "") or ""),
        "office_address": row.get("office_address", ""),
        "office_city": row.get("office_city", ""),
        "office_country": row.get("office_country", ""),
        "website": row.get("website", ""),
        "listed_date": str(row.get("listed_date", "") or ""),
        "board_type": row.get("board_type", ""),
    }
