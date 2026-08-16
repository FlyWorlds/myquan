"""Chinese crude oil futures data fetcher (SC — Shanghai INE).

API reference:
  get_future_dominant(underlying_symbol=['SC']) -> dominant contract per date
  get_future_daily(symbol='SC2608.INE', start_date, end_date) -> daily OHLCV
  get_future_term_structure(symbol=[...], start_date, end_date) -> term structure
  get_future_warehouse_receipt(underlying_symbol=['SC']) -> warehouse receipt
  get_future_ls_ratio(symbol='SC2608.INE', start_date, end_date) -> long/short ratio
  get_future_variety_posi(symbol='SC2608.INE', start_date, end_date) -> position
  get_future_free_spread(contract_symbol_1, contract_symbol_2, date) -> calendar spread
  get_future_contract_indicators(symbol='SC2608.INE', start_date, end_date) -> indicators
"""

import logging
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

SC_UNDERLYING = "SC"


def get_dominant_symbol(client: Any, trade_date: str | None = None) -> str | None:
    """Get the current dominant SC contract symbol.

    Args:
        client: PandadataClient instance.
        trade_date: Date string YYYYMMDD, defaults to today.

    Returns:
        Dominant contract symbol (e.g., 'SC2608.INE') or None.
    """
    try:
        if trade_date is None:
            trade_date = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=10)).strftime("%Y%m%d")

        df = client.call("get_future_dominant", underlying_symbol=[SC_UNDERLYING], start_date=start, end_date=trade_date)
        if df is not None and not df.empty and "symbol" in df.columns:
            # Get the most recent dominant symbol
            symbol = df["symbol"].iloc[-1]
            logger.info("Current SC dominant contract: %s", symbol)
            return symbol
        logger.warning("No dominant contract found for SC")
        return None
    except Exception as e:
        logger.error("Failed to get dominant symbol: %s", e)
        return None


def get_dominant_daily(client: Any, days: int = 120) -> pd.DataFrame:
    """Fetch SC dominant continuous contract daily data.

    First finds the dominant contract via get_future_dominant, then
    fetches daily data for that contract.

    Args:
        client: PandadataClient instance.
        days: Number of days of historical data to fetch.

    Returns:
        DataFrame with columns: trade_date, open, high, low, close, volume, oi
    """
    try:
        end = datetime.now()
        start = end - timedelta(days=days)
        start_str = start.strftime("%Y%m%d")
        end_str = end.strftime("%Y%m%d")

        # Get dominant contract symbol
        dom_symbol = get_dominant_symbol(client, end_str)
        if not dom_symbol:
            logger.warning("Could not determine dominant contract, trying SC2608.INE")
            dom_symbol = "SC2608.INE"

        df = client.call("get_future_daily", symbol=dom_symbol, start_date=start_str, end_date=end_str)
        if df is None or df.empty:
            logger.warning("No daily data returned for %s", dom_symbol)
            return pd.DataFrame()

        # Normalize columns
        df = df.rename(columns={
            "date": "trade_date",
            "open_interest": "oi",
        })
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df = df.sort_values("trade_date").reset_index(drop=True)
        logger.info("Fetched %d rows of %s daily data", len(df), dom_symbol)
        return df
    except Exception as e:
        logger.error("Failed to fetch SC dominant daily data: %s", e)
        return pd.DataFrame()


def get_term_structure(client: Any, symbol: str | None = None) -> pd.DataFrame:
    """Fetch SC futures term structure.

    Gets prices across all active contract months.

    Args:
        client: PandadataClient instance.
        symbol: Optional specific contract to focus on.

    Returns:
        DataFrame with term structure data.
    """
    try:
        today = datetime.now().strftime("%Y%m%d")
        # Use a set of common contract months
        months = []
        base_year = datetime.now().year
        for y in range(base_year, base_year + 3):
            for m in range(1, 13):
                code = f"SC{y % 100:02d}{m:02d}.INE"
                months.append(code)

        df = client.call("get_future_term_structure", symbol=months, start_date=today, end_date=today)
        if df is not None and not df.empty:
            logger.info("Fetched SC term structure, %d rows", len(df))
        return df if df is not None else pd.DataFrame()
    except Exception as e:
        logger.error("Failed to fetch term structure: %s", e)
        return pd.DataFrame()


def get_warehouse_receipts(client: Any) -> pd.DataFrame:
    """Fetch SC warehouse receipt (仓单) inventory data.

    Args:
        client: PandadataClient instance.

    Returns:
        DataFrame with warehouse receipt data.
    """
    try:
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
        df = client.call("get_future_warehouse_receipt", underlying_symbol=[SC_UNDERLYING], start_date=start, end_date=end)
        if df is not None and not df.empty:
            logger.info("Fetched SC warehouse receipts, %d rows", len(df))
        return df if df is not None else pd.DataFrame()
    except Exception as e:
        logger.error("Failed to fetch warehouse receipts: %s", e)
        return pd.DataFrame()


def get_long_short_ratio(client: Any, symbol: str | None = None) -> pd.DataFrame:
    """Fetch SC long/short ratio data.

    Args:
        client: PandadataClient instance.
        symbol: Contract symbol (e.g., 'SC2608.INE'). If None, tries dominant.

    Returns:
        DataFrame with long/short ratio data.
    """
    try:
        if symbol is None:
            symbol = get_dominant_symbol(client) or "SC2608.INE"
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=10)).strftime("%Y%m%d")
        df = client.call("get_future_ls_ratio", symbol=symbol, start_date=start, end_date=end)
        if df is not None and not df.empty:
            logger.info("Fetched SC long/short ratio, %d rows", len(df))
        return df if df is not None else pd.DataFrame()
    except Exception as e:
        logger.error("Failed to fetch long/short ratio: %s", e)
        return pd.DataFrame()


def get_variety_position(client: Any, symbol: str | None = None) -> pd.DataFrame:
    """Fetch SC variety position data.

    Args:
        client: PandadataClient instance.
        symbol: Contract symbol. If None, tries dominant.

    Returns:
        DataFrame with position data.
    """
    try:
        if symbol is None:
            symbol = get_dominant_symbol(client) or "SC2608.INE"
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=10)).strftime("%Y%m%d")
        df = client.call("get_future_variety_posi", symbol=symbol, start_date=start, end_date=end)
        if df is not None and not df.empty:
            logger.info("Fetched SC variety position, %d rows", len(df))
        return df if df is not None else pd.DataFrame()
    except Exception as e:
        logger.error("Failed to fetch variety position: %s", e)
        return pd.DataFrame()


def get_contract_indicators(client: Any, symbol: str | None = None) -> pd.DataFrame:
    """Fetch SC contract indicator data.

    Args:
        client: PandadataClient instance.
        symbol: Contract symbol. If None, tries dominant.

    Returns:
        DataFrame with contract indicator data.
    """
    try:
        if symbol is None:
            symbol = get_dominant_symbol(client) or "SC2608.INE"
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=10)).strftime("%Y%m%d")
        df = client.call("get_future_contract_indicators", symbol=symbol, start_date=start, end_date=end)
        if df is not None and not df.empty:
            logger.info("Fetched SC contract indicators, %d rows", len(df))
        return df if df is not None else pd.DataFrame()
    except Exception as e:
        logger.error("Failed to fetch contract indicators: %s", e)
        return pd.DataFrame()


def fetch_all(client: Any, days: int = 120) -> dict[str, Any]:
    """Fetch all SC-related data modules.

    Args:
        client: PandadataClient instance.
        days: Days of historical daily data.

    Returns:
        Dict with keys: daily, term_structure, warehouse, ls_ratio, position, indicators
    """
    results = {}

    # First get the dominant symbol for targeted queries
    dom_symbol = get_dominant_symbol(client)

    results["daily"] = get_dominant_daily(client, days=days)
    results["term_structure"] = get_term_structure(client, symbol=dom_symbol)
    results["warehouse"] = get_warehouse_receipts(client)
    results["ls_ratio"] = get_long_short_ratio(client, symbol=dom_symbol)
    results["position"] = get_variety_position(client, symbol=dom_symbol)
    results["indicators"] = get_contract_indicators(client, symbol=dom_symbol)

    # Count and log
    for key, df in results.items():
        if isinstance(df, pd.DataFrame):
            logger.info("%s: %d rows", key, len(df))

    return results
