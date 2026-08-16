"""Crude oil price and inventory data client.

Data sources:
  1. Yahoo Finance API (free, no key required) — WTI & Brent futures prices
  2. EIA Open API v2 (requires API key) — US inventory/production data
"""

import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent.parent.parent / ".env")

logger = logging.getLogger(__name__)

EIA_BASE_URL = "https://api.eia.gov/v2"

SERIES = {
    "wti_spot": "PET.EER_EPD2F_PBC_S1Y_D",
    "brent_spot": "PET.EER_EPD1_PBC_S1Y_D",
    "crude_stocks": "PET.WCRSTUS1.W",
    "crude_production": "PET.WCRFPUS2.W",
    "refinery_inputs": "PET.WCRRIUS2.W",
    "crude_imports": "PET.WCRIMUS2.W",
    "crude_exports": "PET.WCREXUS2.W",
}

# EIA v2 API route mapping for petroleum series
# Format: (route_path, facet_overrides)
# See: https://www.eia.gov/opendata/browser
EIA_ROUTES = {
    "PET.WCRSTUS1.W": ("/petroleum/stoc/wstk/data/", {"product": "EPC0", "process": "SAE"}),
    "PET.WCRFPUS2.W": ("/petroleum/stoc/wstk/data/", {"product": "EPC0", "process": "SPR"}),
    "PET.WCRRIUS2.W": ("/petroleum/stoc/wstk/data/", {"product": "EPC0", "process": "SIR"}),
    "PET.WCRIMUS2.W": ("/petroleum/stoc/wstk/data/", {"product": "EPC0", "process": "SIM"}),
    "PET.WCREXUS2.W": ("/petroleum/stoc/wstk/data/", {"product": "EPC0", "process": "SEX"}),
}

YAHOO_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


# ── Yahoo Finance helpers (no API key needed) ──────────────────────────

def _fetch_yahoo_chart(ticker: str, days: int = 60) -> pd.DataFrame:
    """Fetch daily close prices from Yahoo Finance chart API.

    Uses query1.finance.yahoo.com directly.

    Args:
        ticker: Yahoo Finance ticker (e.g. 'CL=F' for WTI, 'BZ=F' for Brent).
        days: Number of days of history to fetch.

    Returns:
        DataFrame with columns: date, value (close price).
    """
    df = _fetch_yahoo_ohlcv(ticker, days=days)
    if df.empty:
        return df
    return df[["date", "value"]]


def _fetch_yahoo_ohlcv(ticker: str, days: int = 120) -> pd.DataFrame:
    """Fetch daily OHLCV data from Yahoo Finance chart API.

    Args:
        ticker: Yahoo Finance ticker (e.g. 'CL=F' for WTI, 'BZ=F' for Brent).
        days: Number of days of history to fetch.

    Returns:
        DataFrame with columns: date, value (close), open, high, low, volume.
    """
    try:
        range_str = f"{min(days + 5, 365)}d"
        url = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
            f"?range={range_str}&interval=1d"
        )
        resp = requests.get(url, headers=YAHOO_HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        result = data.get("chart", {}).get("result", [])
        if not result:
            logger.warning("Yahoo chart API returned no result for %s", ticker)
            return pd.DataFrame()

        result = result[0]
        timestamps = result.get("timestamp", [])
        quote = result.get("indicators", {}).get("quote", [{}])[0]

        records = []
        for i, ts in enumerate(timestamps):
            close = quote.get("close", [None])[i]
            if close is None:
                continue
            records.append({
                "date": datetime.fromtimestamp(ts),
                "value": float(close),
                "open": float(quote.get("open", [0])[i] or 0),
                "high": float(quote.get("high", [0])[i] or 0),
                "low": float(quote.get("low", [0])[i] or 0),
                "volume": float(quote.get("volume", [0])[i] or 0),
            })

        df = pd.DataFrame(records)
        if df.empty:
            return df
        df = df.sort_values("date").reset_index(drop=True)
        logger.info("Fetched %s OHLCV from Yahoo: %d rows, latest=%.2f",
                     ticker, len(df), df["value"].iloc[-1])
        return df

    except requests.RequestException as e:
        logger.warning("Yahoo Finance request failed for %s: %s", ticker, e)
        return pd.DataFrame()
    except (ValueError, KeyError, IndexError) as e:
        logger.warning("Yahoo Finance parse failed for %s: %s", ticker, e)
        return pd.DataFrame()


def get_wti_yahoo(days: int = 60) -> pd.DataFrame:
    """Fetch WTI Crude Oil futures (CL=F) close prices from Yahoo Finance."""
    return _fetch_yahoo_chart("CL=F", days=days)


def get_brent_yahoo(days: int = 60) -> pd.DataFrame:
    """Fetch Brent Crude Oil futures (BZ=F) close prices from Yahoo Finance."""
    return _fetch_yahoo_chart("BZ=F", days=days)


def get_brent_daily(days: int = 120) -> pd.DataFrame:
    """Fetch Brent daily OHLCV data for technical analysis."""
    return _fetch_yahoo_ohlcv_to_daily("BZ=F", days=days)


def get_wti_daily(days: int = 120) -> pd.DataFrame:
    """Fetch WTI daily OHLCV data for technical analysis."""
    return _fetch_yahoo_ohlcv_to_daily("CL=F", days=days)


def get_energy_daily(ticker: str, days: int = 120) -> pd.DataFrame:
    """Fetch daily OHLCV for any energy commodity ticker.

    Args:
        ticker: Yahoo Finance ticker (e.g. 'NG=F', 'RB=F', 'HO=F').
        days: Number of days of history.

    Returns:
        DataFrame with columns: trade_date, open, high, low, close, volume.
    """
    return _fetch_yahoo_ohlcv_to_daily(ticker, days=days)


def _fetch_yahoo_ohlcv_to_daily(ticker: str, days: int = 120) -> pd.DataFrame:
    """Fetch Yahoo OHLCV and rename to standard daily format."""
    df = _fetch_yahoo_ohlcv(ticker, days=days)
    if df.empty:
        return df
    df = df.rename(columns={"date": "trade_date", "value": "close"})
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


# ── EIA API client ────────────────────────────────────────────────────

class EIAClient:
    """Client for crude oil price and inventory data.

    WTI/Brent prices come from Yahoo Finance (free, always available).
    US inventory/production data comes from EIA API (requires API key).
    """

    def __init__(self, api_key: str | None = None):
        self._api_key = api_key or os.environ.get("EIA_API_KEY") or ""
        self._has_key = bool(self._api_key) and self._api_key not in ("", "your_eia_api_key")

    @property
    def available(self) -> bool:
        """EIA-specific endpoints available (inventory/production)."""
        return self._has_key

    # ── Yahoo Finance based price fetch (always available) ──

    def get_wti_spot(self, days: int = 60) -> pd.DataFrame:
        """Fetch WTI crude oil futures price from Yahoo Finance."""
        return get_wti_yahoo(days=days)

    def get_brent_spot(self, days: int = 60) -> pd.DataFrame:
        """Fetch Brent crude oil futures price from Yahoo Finance."""
        return get_brent_yahoo(days=days)

    def get_brent_daily(self, days: int = 120) -> pd.DataFrame:
        """Fetch Brent daily OHLCV for technical analysis."""
        return get_brent_daily(days=days)

    def get_wti_daily(self, days: int = 120) -> pd.DataFrame:
        """Fetch WTI daily OHLCV for technical analysis."""
        return get_wti_daily(days=days)

    def get_energy_daily(self, ticker: str, days: int = 120) -> pd.DataFrame:
        """Fetch daily OHLCV for any energy commodity ticker."""
        return get_energy_daily(ticker, days=days)

    # ── EIA API based data (requires API key) ──

    def _fetch_eia_series(self, series_id: str, start: str | None = None,
                          end: str | None = None, length: int | None = 365) -> pd.DataFrame:
        """Fetch a data series from EIA API v2.

        Uses the proper v2 route + facet approach rather than the deprecated
        series endpoint.
        """
        if not self._has_key:
            return pd.DataFrame()

        route_info = EIA_ROUTES.get(series_id)
        if not route_info:
            logger.warning("No EIA route mapping for series %s", series_id)
            return pd.DataFrame()

        route_path, facets = route_info
        url = f"{EIA_BASE_URL}{route_path}"
        params = {
            "api_key": self._api_key,
            "frequency": "weekly",
            "data[0]": "value",
        }
        # Add facet filters
        for facet_name, facet_val in facets.items():
            params[f"facets[{facet_name}][]"] = facet_val
        if length:
            params["length"] = length
        params["sort[0][column]"] = "period"
        params["sort[0][direction]"] = "desc"

        try:
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            series_data = data.get("response", {}).get("data", [])
            if not series_data:
                logger.debug("EIA v2 returned empty data for %s", series_id)
                return pd.DataFrame()

            records = []
            for item in series_data:
                records.append({
                    "date": item.get("period", ""),
                    "value": item.get("value"),
                })
            df = pd.DataFrame(records)
            if df.empty:
                return df
            df["date"] = pd.to_datetime(df["date"])
            df["value"] = pd.to_numeric(df["value"], errors="coerce")
            return df.sort_values("date").reset_index(drop=True)
        except Exception as e:
            logger.debug("EIA API fetch failed for %s: %s", series_id, e)
            return pd.DataFrame()

    def get_us_crude_stocks(self, weeks: int = 52) -> pd.DataFrame:
        """Fetch US crude oil stocks (weekly) from EIA."""
        end_d = datetime.now().strftime("%Y-%m-%d")
        start_d = (datetime.now() - timedelta(weeks=weeks)).strftime("%Y-%m-%d")
        return self._fetch_eia_series(SERIES["crude_stocks"], start=start_d, end=end_d)

    def get_us_crude_production(self, weeks: int = 52) -> pd.DataFrame:
        """Fetch US crude oil production (weekly) from EIA."""
        end_d = datetime.now().strftime("%Y-%m-%d")
        start_d = (datetime.now() - timedelta(weeks=weeks)).strftime("%Y-%m-%d")
        return self._fetch_eia_series(SERIES["crude_production"], start=start_d, end=end_d)

    # ── Batch fetchers ──

    def fetch_oil_prices(self) -> dict[str, pd.DataFrame]:
        """Fetch WTI and Brent prices from Yahoo Finance.

        Returns:
            Dict with 'wti_spot' and 'brent_spot' DataFrames (columns: date, value).
        """
        results = {}
        results["wti_spot"] = self.get_wti_spot(days=60)
        results["brent_spot"] = self.get_brent_spot(days=60)
        return results

    def fetch_all(self) -> dict[str, pd.DataFrame]:
        """Fetch all available crude oil data.

        Returns dict with keys: wti_spot, brent_spot, crude_stocks,
        crude_production, refinery_inputs, crude_imports, crude_exports.

        Note: Inventory/production data requires EIA API key.
        """
        results = self.fetch_oil_prices()

        # Inventory/production data requires EIA key
        for key in ["crude_stocks", "crude_production", "refinery_inputs",
                    "crude_imports", "crude_exports"]:
            try:
                df = self._fetch_eia_series(SERIES[key], length=365)
                results[key] = df
                if not df.empty:
                    logger.info("Fetched EIA %s: %d rows", key, len(df))
            except Exception as e:
                logger.warning("Failed EIA %s: %s", key, e)
                results[key] = pd.DataFrame()

        return results
