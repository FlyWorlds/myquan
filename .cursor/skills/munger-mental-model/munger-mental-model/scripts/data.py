"""
Data IO layer for Munger mental model analysis.

Provides network functions to fetch financial data, holdings, peer information,
and corporate event data from panda_data SDK. Includes retry logic with
exponential backoff and relogin on token expiration.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

import config

# Error codes from panda_data SDK
_TOKEN_EXPIRED_CODE = "200004"
_RATE_LIMIT_CODE = "500010"


def _date_to_yyyymmdd(value: str) -> str:
    """
    Convert date string to YYYYMMDD format.

    Args:
        value: Date string in YYYY-MM-DD or YYYYMMDD format

    Returns:
        Date string in YYYYMMDD format

    Raises:
        ValueError: If date cannot be parsed or is invalid
    """
    text = str(value).replace("-", "")
    if len(text) != 8 or not text.isdigit():
        raise ValueError(f"Date must be YYYY-MM-DD or YYYYMMDD: {value}")
    return text


def _date_to_iso(value: str) -> str:
    """
    Convert YYYYMMDD date to ISO format (YYYY-MM-DD).

    Args:
        value: Date string in YYYYMMDD format

    Returns:
        Date string in YYYY-MM-DD format
    """
    return pd.to_datetime(str(value), format="%Y%m%d").strftime("%Y-%m-%d")


def _get_end_date(end_date: str | None) -> str:
    """
    Get end date in YYYYMMDD format, defaulting to today if None.

    Args:
        end_date: Optional end date in YYYY-MM-DD or YYYYMMDD format

    Returns:
        End date in YYYYMMDD format
    """
    if end_date is None:
        return datetime.now().strftime("%Y%m%d")
    return _date_to_yyyymmdd(end_date)


def _call_with_retry(
    fn: callable,
    *args,
    max_retries: int = 6,
    base_wait: float = 10.0,
    **kwargs
) -> Any:
    """
    Call a panda_data function with retry logic and relogin on token expiration.

    Implements exponential backoff for rate limiting and network errors.
    Automatically relogins on error code 200004 (token expired).

    Args:
        fn: Callable function from panda_data SDK
        *args: Positional arguments to pass to fn
        max_retries: Maximum number of retry attempts (default 6)
        base_wait: Base wait time in seconds for exponential backoff (default 10.0)
        **kwargs: Keyword arguments to pass to fn

    Returns:
        Result from fn

    Raises:
        Exception: If all retries exhausted or unrecoverable error
    """
    import panda_data
    from panda_data.exceptions import ServiceError

    for attempt in range(max_retries):
        try:
            return fn(*args, **kwargs)
        except ServiceError as e:
            err = str(e)
            if _TOKEN_EXPIRED_CODE in err and attempt < max_retries - 1:
                print(
                    f"  [Token expired] Relogging in and retrying "
                    f"(attempt {attempt + 1}/{max_retries})..."
                )
                try:
                    username, password = config.get_credentials()
                    panda_data.init_token(username=username, password=password)
                except Exception as login_err:
                    print(f"  [Token expired] Relogin failed: {login_err}")
                continue
            elif attempt < max_retries - 1:
                wait = base_wait * (2 ** attempt)
                reason = "Rate limit" if _RATE_LIMIT_CODE in err else "Network error"
                print(
                    f"  [{reason}] {err[:80]} → waiting {wait:.0f}s before retry "
                    f"(attempt {attempt + 1}/{max_retries})..."
                )
                time.sleep(wait)
            else:
                raise
        except (TimeoutError, OSError, ConnectionError) as e:
            if attempt < max_retries - 1:
                wait = base_wait * (2 ** attempt)
                print(
                    f"  [Network timeout] {str(e)[:80]} → waiting {wait:.0f}s before retry "
                    f"(attempt {attempt + 1}/{max_retries})..."
                )
                time.sleep(wait)
            else:
                raise


def init() -> None:
    """
    Initialize panda_data session by logging in with credentials from environment.

    Credentials are read from PANDA_DATA_USERNAME and PANDA_DATA_PASSWORD env vars
    via config.get_credentials().

    Raises:
        RuntimeError: If credentials are not set in environment
    """
    import panda_data

    username, password = config.get_credentials()
    panda_data.init_token(username=username, password=password)


def _latest_annual_quarter(end_date_str: str) -> str:
    """
    Return the most-recently-completed annual report quarter for end_date.

    Annual reports (Q4) are typically published by April of the following year.
    We conservatively require the report publication date to be <= end_date.

    Examples:
        20260710 -> '2024q4'  (2024 annual, published ~Apr 2025)
        20250301 -> '2023q4'  (2024 annual not yet published)
    """
    dt = datetime.strptime(end_date_str, "%Y%m%d")
    # Annual report for year Y is published around April of Y+1.
    # If we are past April 30 of year Y+1, the Y annual report is available.
    candidate_year = dt.year - 1
    if dt.month <= 4:
        candidate_year -= 1
    return f"{candidate_year}q4"


def fetch_fina(
    symbols: list[str],
    end_date: str | None = None,
) -> pd.DataFrame:
    """
    Fetch latest annual financial data for given symbols using get_fina_reports.

    Uses the most-recently-completed annual report (Q4) as of end_date.
    Computes ROE from net profit / average equity (period-begin + period-end).
    Gross profit rate is computed as is_gross_profit / is_revenue * 100.

    Args:
        symbols: List of stock symbols (e.g., ['000001.SZ', '600000.SH'])
        end_date: Optional analysis date in YYYY-MM-DD or YYYYMMDD format.
                 If None, uses current date.

    Returns:
        DataFrame with columns: roe, gross_profit, operating_revenue, ocf, symbol.

    Raises:
        ValueError: If no data returned or symbols list is empty
    """
    import panda_data

    if not symbols:
        raise ValueError("symbols list cannot be empty")

    end = _get_end_date(end_date)
    annual_q = _latest_annual_quarter(end)

    # For ROE computation we also need the prior year's equity (period-begin)
    prior_year = int(annual_q[:4]) - 1
    prior_q = f"{prior_year}q4"

    rows = []
    for symbol in symbols:
        try:
            cur = _call_with_retry(
                panda_data.get_fina_reports,
                symbol=symbol,
                start_quarter=annual_q,
                end_quarter=annual_q,
            )
            if cur is None or cur.empty:
                continue
            r = cur.iloc[0]

            # Fetch prior-year equity for ROE denominator (best-effort)
            eq_begin = None
            try:
                prev = _call_with_retry(
                    panda_data.get_fina_reports,
                    symbol=symbol,
                    start_quarter=prior_q,
                    end_quarter=prior_q,
                )
                if prev is not None and not prev.empty:
                    eq_begin = prev.iloc[0].get("bs_total_hldr_eqy_exc_min_int")
            except Exception:
                pass

            eq_end = r.get("bs_total_hldr_eqy_exc_min_int")
            net_profit = r.get("is_n_income_attr_p")

            # Weighted-average ROE
            if net_profit and eq_end and eq_end != 0:
                if eq_begin and eq_begin != 0:
                    avg_eq = (eq_begin + eq_end) / 2.0
                else:
                    avg_eq = eq_end
                roe = net_profit / avg_eq * 100.0
            else:
                roe = None

            # Gross profit rate (%)
            rev = r.get("is_revenue")
            gp_raw = r.get("is_gross_profit")
            if gp_raw and rev and rev > 0:
                gross_profit = gp_raw / rev * 100.0
            else:
                gross_profit = None

            rows.append({
                "symbol": symbol,
                "roe": roe,
                "gross_profit": gross_profit,
                "operating_revenue": rev,
                "ocf": r.get("cfs_net_cash_operating"),
            })
        except Exception as e:
            print(f"  Warning: Failed to fetch fina for {symbol}: {e}")
            continue

    if not rows:
        raise ValueError(
            f"panda_data returned no financial data for symbols: {symbols}"
        )

    return pd.DataFrame(rows, columns=["roe", "gross_profit", "operating_revenue", "ocf", "symbol"])


def fetch_industry_peers(
    symbol: str,
    end_date: str | None = None,
) -> list[str]:
    """
    Fetch list of industry peer symbols for a given stock.

    Gets the L2 industry classification for the stock, then fetches all constituents
    in that industry. Returns the peer symbol list including the target symbol.

    Args:
        symbol: Stock symbol (e.g., '000001.SZ')
        end_date: Optional date in YYYY-MM-DD or YYYYMMDD format (not used for
                 peer lookup but kept for API consistency)

    Returns:
        List of peer symbols (sorted, includes target symbol)

    Raises:
        ValueError: If industry lookup or constituent fetch fails
    """
    import panda_data

    # Get industry for the target symbol
    industry_raw = _call_with_retry(
        panda_data.get_stock_industry,
        stock_symbol=symbol,
        level="L2",
    )

    if industry_raw is None or industry_raw.empty:
        raise ValueError(f"Could not determine industry for {symbol}")

    # Extract industry code (assuming first row)
    industry_code = industry_raw.iloc[0].get("industry_code")
    if not industry_code:
        raise ValueError(f"No industry_code found for {symbol}")

    # Get all constituents in that industry
    constituents_raw = _call_with_retry(
        panda_data.get_industry_constituents,
        industry_code=industry_code,
        level="L2",
    )

    if constituents_raw is None or constituents_raw.empty:
        raise ValueError(f"No constituents found for industry {industry_code}")

    # Extract symbol column
    peers = sorted(constituents_raw["stock_symbol"].unique().tolist())
    return peers


def fetch_top_holders(
    symbol: str,
    end_date: str | None = None,
) -> pd.DataFrame:
    """
    Fetch top shareholders for a given stock.

    Uses get_top_holders with market="cn" to retrieve top-10 holdings.
    Returns DataFrame with shareholder details as-is from SDK.

    Args:
        symbol: Stock symbol (e.g., '000001.SZ')
        end_date: Optional date in YYYY-MM-DD or YYYYMMDD format

    Returns:
        DataFrame with columns from SDK (e.g., hold_percent_total, pledge, freeze).
        Returns empty DataFrame if no data available.
    """
    import panda_data

    end = _get_end_date(end_date)

    # Calculate start_date: 1 year back from end_date
    end_dt = datetime.strptime(end, "%Y%m%d")
    start_dt = end_dt - timedelta(days=365)
    start = start_dt.strftime("%Y%m%d")

    try:
        df = _call_with_retry(
            panda_data.get_top_holders,
            symbol=symbol,
            start_date=start,
            end_date=end,
            market="cn",
        )

        if df is None or df.empty:
            return pd.DataFrame()

        return df.copy()
    except Exception as e:
        print(f"  Warning: Could not fetch top holders for {symbol}: {e}")
        return pd.DataFrame()


def fetch_holder_count(
    symbol: str,
    end_date: str | None = None,
) -> pd.DataFrame:
    """
    Fetch shareholder count statistics for a given stock.

    Uses get_holder_count to retrieve time series of shareholder counts.

    Args:
        symbol: Stock symbol (e.g., '000001.SZ')
        end_date: Optional date in YYYY-MM-DD or YYYYMMDD format

    Returns:
        DataFrame with holder count data from SDK.

    Raises:
        ValueError: If no data returned
    """
    import panda_data

    end = _get_end_date(end_date)

    df = _call_with_retry(
        panda_data.get_holder_count,
        symbol=symbol,
        end_date=end,
    )

    if df is None or df.empty:
        raise ValueError(f"No holder count data for {symbol} as of {end}")

    return df.copy()


def fetch_shareholder_change(
    symbol: str,
    end_date: str | None = None,
) -> pd.DataFrame:
    """
    Fetch shareholder buy/sell activity (增减持) for a given stock.

    Uses get_stock_shareholder_change to retrieve management and major shareholder
    trading activity (増持 buys and 減持 sells).

    Args:
        symbol: Stock symbol (e.g., '000001.SZ')
        end_date: Optional date in YYYY-MM-DD or YYYYMMDD format

    Returns:
        DataFrame with columns: shareholder_type, direction, ratio_up_limit, etc.
        Returns empty DataFrame if no data available.
    """
    import panda_data

    end = _get_end_date(end_date)

    # Calculate start_date: use same window as investor activity (ir_months)
    ir_months = config.ir_months()
    end_dt = datetime.strptime(end, "%Y%m%d")
    start_dt = end_dt - timedelta(days=30 * ir_months)
    start = start_dt.strftime("%Y%m%d")

    try:
        df = _call_with_retry(
            panda_data.get_stock_shareholder_change,
            symbol=symbol,
            start_date=start,
            end_date=end,
        )

        if df is None or df.empty:
            return pd.DataFrame()

        # Diagnostic: log actual API column names to aid field-mapping debugging.
        # Expected columns for dimensions.py: nature (增减持人性质), net_change (净变动),
        # holder_type (股东类型), ratio_up_limit (减持比例上限).
        result = df.copy()
        print(f"  [DEBUG] get_stock_shareholder_change columns: {list(result.columns)}")
        print(f"  [DEBUG] Sample nature values: {result['nature'].unique()[:5].tolist() if 'nature' in result.columns else 'N/A'}")
        print(f"  [DEBUG] Sample holder_type values: {result['holder_type'].unique()[:5].tolist() if 'holder_type' in result.columns else 'N/A'}")
        return result
    except Exception as e:
        print(f"  Warning: Could not fetch shareholder change for {symbol}: {e}")
        return pd.DataFrame()


def fetch_investor_activity(
    symbol: str,
    end_date: str | None = None,
) -> pd.DataFrame:
    """
    Fetch investor relations activity (roadshow, investor meetings) for a given stock.

    Uses get_investor_activity to retrieve activity over the last config.ir_months()
    months. Expects columns like 'date', 'institute' (or similar institution field).

    Args:
        symbol: Stock symbol (e.g., '000001.SZ')
        end_date: Optional date in YYYY-MM-DD or YYYYMMDD format.
                 Query window: end_date back to (end_date - ir_months)

    Returns:
        DataFrame with activity records (columns: date, institute, etc.)

    Raises:
        ValueError: If no data returned
    """
    import panda_data

    end = _get_end_date(end_date)

    # Calculate start date based on ir_months config
    ir_months = config.ir_months()
    end_dt = datetime.strptime(end, "%Y%m%d")
    start_dt = end_dt - timedelta(days=30 * ir_months)
    start = start_dt.strftime("%Y%m%d")

    df = _call_with_retry(
        panda_data.get_investor_activity,
        symbol=symbol,
        start_date=start,
        end_date=end,
    )

    if df is None or df.empty:
        raise ValueError(
            f"No investor activity data for {symbol} "
            f"in period {start}–{end}"
        )

    return df.copy()


def fetch_audit(
    symbol: str,
    end_date: str | None = None,
) -> pd.DataFrame:
    """
    Fetch audit opinions for a given stock.

    Uses get_audit_opinion with market="cn" to retrieve latest audit opinion
    and auditor information.

    Args:
        symbol: Stock symbol (e.g., '000001.SZ')
        end_date: Optional date in YYYY-MM-DD or YYYYMMDD format (converted to quarter)

    Returns:
        DataFrame with columns: opinion, agency, quarter, etc.

    Raises:
        ValueError: If no data returned
    """
    import panda_data

    # Convert date to quarter (e.g., 20260630 -> 2026Q2)
    if end_date:
        end = _date_to_yyyymmdd(end_date)
        month = int(end[4:6])
        year = end[0:4]
        quarter = (month - 1) // 3 + 1
        end_quarter = f"{year}Q{quarter}"
    else:
        end_dt = datetime.now()
        month = end_dt.month
        year = end_dt.year
        quarter = (month - 1) // 3 + 1
        end_quarter = f"{year}Q{quarter}"

    df = _call_with_retry(
        panda_data.get_audit_opinion,
        symbol=symbol,
        end_quarter=end_quarter,
        market="cn",
    )

    if df is None or df.empty:
        raise ValueError(f"No audit opinion data for {symbol} as of {end_quarter}")

    return df.copy()


def fetch_status_change(
    symbol: str,
    end_date: str | None = None,
) -> pd.DataFrame:
    """
    Fetch status changes (ST, delisting, etc.) for a given stock.

    Uses get_stock_status_change to retrieve corporate status events
    (suspension, ST designation, delisting, etc.).

    Args:
        symbol: Stock symbol (e.g., '000001.SZ')
        end_date: Optional date in YYYY-MM-DD or YYYYMMDD format

    Returns:
        DataFrame with columns: type, date, reason, etc.
        Empty DataFrame if no status changes.

    Raises:
        Exception: Only if network/API error; empty result is valid
    """
    import panda_data

    end = _get_end_date(end_date)

    df = _call_with_retry(
        panda_data.get_stock_status_change,
        symbol=symbol,
        end_date=end,
    )

    # Return empty DataFrame if no status changes (valid state)
    return df.copy() if df is not None else pd.DataFrame()


def fetch_pledge(
    symbol: str,
    end_date: str | None = None,
) -> pd.DataFrame:
    """
    Fetch stock pledge (collateralization) data for a given stock.

    Uses get_stock_pledge to retrieve pledge details including pledge ratio
    and amount pledged.

    Args:
        symbol: Stock symbol (e.g., '000001.SZ')
        end_date: Optional date in YYYY-MM-DD or YYYYMMDD format

    Returns:
        DataFrame with columns: pledge_ratio, pledge_amount, etc.
        Empty DataFrame if no pledges.

    Raises:
        Exception: Only if network/API error; empty result is valid
    """
    import panda_data

    end = _get_end_date(end_date)

    # Calculate start_date: 1 year back from end_date
    end_dt = datetime.strptime(end, "%Y%m%d")
    start_dt = end_dt - timedelta(days=365)
    start = start_dt.strftime("%Y%m%d")

    try:
        df = _call_with_retry(
            panda_data.get_stock_pledge,
            symbol=symbol,
            start_date=start,
            end_date=end,
        )

        # Return empty DataFrame if no pledge data (valid state)
        return df.copy() if df is not None else pd.DataFrame()
    except Exception as e:
        print(f"  Warning: Could not fetch pledge for {symbol}: {e}")
        return pd.DataFrame()


def fetch_industry_peers_by_code(
    industry_code: str,
) -> list[str]:
    """
    Fetch list of all symbols in a given industry (by L2 industry code).

    Used by analyze.main in --industry path to get peer list without
    specifying a target symbol.

    Args:
        industry_code: L2 industry code (e.g., 'L2004001' for banks)

    Returns:
        List of stock symbols in the industry (sorted)

    Raises:
        ValueError: If industry lookup fails or no constituents found
    """
    import panda_data

    constituents_raw = _call_with_retry(
        panda_data.get_industry_constituents,
        industry_code=industry_code,
        level="L2",
    )

    if constituents_raw is None or constituents_raw.empty:
        raise ValueError(f"No constituents found for industry {industry_code}")

    peers = sorted(constituents_raw["stock_symbol"].unique().tolist())
    return peers
