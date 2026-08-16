"""Market price & volume data — 行情与价量指标."""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def get_price_data(client: Any, symbol: str, months: int = 12) -> dict[str, Any]:
    """Fetch daily price data and price-volume indicators.

    Returns a dict with:
      - daily: DataFrame of recent daily prices
      - pv_indicators: dict of price-volume metrics
      - summary: computed stats (latest price, ytd return, etc.)
    """
    result: dict[str, Any] = {}

    # --- Daily price data (last ~12 months) ---
    try:
        import datetime

        today = datetime.date.today()
        start = today - datetime.timedelta(days=months * 31)
        df = client.call(
            "get_hk_daily",
            symbol=[symbol],
            start_date=start.strftime("%Y%m%d"),
            end_date=today.strftime("%Y%m%d"),
            fields=[],
        )
        if df is not None and not df.empty:
            df = df.sort_values("date", ascending=False).reset_index(drop=True)
            result["daily"] = df
            # Summary stats
            latest = df.iloc[0]
            oldest = df.iloc[-1]
            result["summary"] = {
                "latest_close": float(latest.get("close", 0) or 0),
                "latest_date": str(latest.get("date", "")),
                "open": float(latest.get("open", 0) or 0),
                "high": float(latest.get("high", 0) or 0),
                "low": float(latest.get("low", 0) or 0),
                "pre_close": float(latest.get("pre_close", 0) or 0),
                "volume": int(latest.get("volume", 0) or 0),
                "vwap": float(latest.get("vwap", 0) or 0),
                "avg_volume_10d": _calc_avg_volume(df, 10),
                "avg_volume_90d": _calc_avg_volume(df, 90),
                "period_return": _calc_return(
                    float(latest.get("close", 0) or 0),
                    float(oldest.get("close", 0) or 0),
                ),
            }
        else:
            result["daily"] = None
            result["summary"] = {}
    except Exception as e:
        logger.warning("Failed to fetch daily data for %s: %s", symbol, e)
        result["daily"] = None
        result["summary"] = {}

    # --- Price-volume indicators ---
    try:
        pv_df = client.call(
            "get_stock_pv_indicator", symbol=[symbol], fields=[]
        )
        if pv_df is not None and not pv_df.empty:
            row = pv_df.iloc[0]
            result["pv_indicators"] = {
                "beta_5y": row.get("pv_beta_5y"),
                "return_mtd": row.get("pv_return_mtd"),
                "return_ytd": row.get("pv_return_ytd"),
                "return_1d": row.get("pv_return_1d"),
                "return_5d": row.get("pv_return_5d"),
                "return_13w": row.get("pv_return_13w"),
                "return_26w": row.get("pv_return_26w"),
                "return_52w": row.get("pv_return_52w"),
                "rel_return_ytd": row.get("pv_rel_return_ytd"),
                "rel_return_13w": row.get("pv_rel_return_13w"),
                "rel_return_26w": row.get("pv_rel_return_26w"),
                "rel_return_52w": row.get("pv_rel_return_52w"),
                "market_cap": row.get("pv_market_cap"),
                "market_cap_currency": row.get("pv_market_cap_currency"),
                "market_cap_date": row.get("pv_market_cap_date"),
                "high_52w": row.get("pv_high_52w"),
                "high_52w_date": row.get("pv_high_52w_date"),
                "low_52w": row.get("pv_low_52w"),
                "low_52w_date": row.get("pv_low_52w_date"),
                "close": row.get("pv_close"),
                "close_date": row.get("pv_close_date"),
                "close_currency": row.get("pv_close_currency"),
                "avg_vol_10d": row.get("pv_avg_vol_10d"),
                "avg_vol_90d": row.get("pv_avg_vol_90d"),
                "avg_val_3m": row.get("pv_avg_val_3m"),
            }
        else:
            result["pv_indicators"] = {}
    except Exception as e:
        logger.warning("Failed to fetch PV indicators for %s: %s", symbol, e)
        result["pv_indicators"] = {}

    return result


def _calc_avg_volume(df: Any, days: int) -> float | None:
    """Calculate average volume over the last N trading days."""
    try:
        vols = df.head(days)["volume"].dropna()
        if vols.empty:
            return None
        return float(vols.mean())
    except (KeyError, IndexError, TypeError, AttributeError):
        return None


def _calc_return(latest: float, oldest: float) -> float | None:
    """Calculate simple period return."""
    if oldest and oldest != 0:
        return (latest - oldest) / oldest * 100
    return None
