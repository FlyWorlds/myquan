"""Universe resolution — determine the stock pool for audit opinion scanning.

Default: CSI300 constituents. Supports arbitrary index symbols.
"""

from __future__ import annotations

import pandas as pd
import sys

from . import data as data_mod


def resolve_universe(
    index_symbol: str = "000300.SH",
    date: str | None = None,
) -> pd.DataFrame:
    """Return the CSI300 (or other index) stock list for a given date.

    Args:
        index_symbol: Index code, e.g. "000300.SH", "000905.SH".
        date: Reference date in YYYYMMDD. Defaults to last trade date.

    Returns:
        DataFrame with columns: index_symbol, date, stock_symbol, weight.

    Raises:
        RuntimeError: if no weights are available.
    """
    if date is None:
        date = data_mod.get_last_trade_date()

    weights = data_mod.load_index_weights(index_symbol, date)

    # Fallback: try the 5 preceding trading days
    fallback = 0
    while weights.empty and fallback < 5:
        fallback += 1
        prev = data_mod.get_prev_trade_date(date, n=fallback)
        if prev is None:
            break
        weights = data_mod.load_index_weights(index_symbol, prev)

    if weights.empty:
        raise RuntimeError(
            f"No index weights found for {index_symbol} on {date} or nearby dates."
        )

    print(
        f"[info] universe: {weights['stock_symbol'].nunique()} stocks in {index_symbol}",
        file=sys.stderr,
    )
    return weights


def filter_universe(
    weights_df: pd.DataFrame,
    exclude_st: bool = True,
    reference_date: str | None = None,
) -> list[str]:
    """Extract and filter stock symbols from index weights.

    Args:
        weights_df: Output of resolve_universe().
        exclude_st: If True, mark (but don't fully exclude) all symbols — ST
            filtering is optionally done via get_stock_status_change in v2.
        reference_date: Date used for ST checks (currently unused in v1,
            reserved for v2).

    Returns:
        Sorted list of stock symbols.
    """
    symbols = sorted(weights_df["stock_symbol"].unique().tolist())
    if not symbols:
        raise RuntimeError("Universe is empty — no stocks found in index weights.")
    return symbols
