"""panda_data thin wrappers for skill-audit-opinion-scanner.

Four interfaces are used (see references/need_used_api.md):
  - get_audit_opinion                           (audit opinions per quarter)
  - get_index_weights                           (CSI300 constituents)
  - get_stock_detail                            (stock names for display)
  - get_last_trade_date, get_prev_trade_date    (calendar utilities)

panda_data is a private package imported lazily inside each function so that
this module can be imported (and its EXPECTED_COLUMNS inspected) without
panda_data installed — useful for unit-testing callers that mock the loaders.
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Optional

import pandas as pd

# Column supersets we DEPEND ON downstream. Upstream may return more columns;
# missing any of these breaks things.
EXPECTED_COLUMNS: dict[str, set[str]] = {
    "audit_opinion": {"symbol", "quarter", "date", "agency", "audit_type", "opinion"},
    "index_weights": {"index_symbol", "date", "stock_symbol"},
    "stock_detail":   {"symbol", "name"},
}


def init_panda_data() -> None:
    """Authenticate with panda_data using env vars. Raises RuntimeError if unset."""
    user = os.environ.get("PANDA_DATA_USERNAME")
    pwd = os.environ.get("PANDA_DATA_PASSWORD")
    if not user or not pwd:
        raise RuntimeError(
            "Missing env vars PANDA_DATA_USERNAME / PANDA_DATA_PASSWORD. "
            "Export them before running the scan."
        )
    import panda_data
    panda_data.init_token(username=user, password=pwd)


def _assert_columns(df: pd.DataFrame, kind: str) -> None:
    expected = EXPECTED_COLUMNS[kind]
    missing = expected - set(df.columns)
    if missing:
        raise ValueError(
            f"panda_data {kind} response missing columns: {sorted(missing)}. "
            f"Got: {sorted(df.columns)}."
        )


def _index_symbol_stripped(index_symbol: str) -> str:
    """Strip suffix for `indicator` / `index_component` args (e.g. 000300.SH → 000300)."""
    return index_symbol.split(".")[0]


def get_last_trade_date(exchange: str = "SH") -> str | None:
    """Wrap panda_data.get_last_trade_date; returns YYYYMMDD string or None.

    The live API may return a plain `str` even though the doc shows a one-row
    DataFrame. Handle both.
    """
    import panda_data
    result = panda_data.get_last_trade_date(exchange=exchange)
    if result is None:
        return None
    if isinstance(result, str):
        return result or None
    if hasattr(result, "empty") and result.empty:
        return None
    if hasattr(result, "iloc"):
        return str(result["date"].iloc[0])
    return str(result)


def get_prev_trade_date(date: str, n: int = 1, exchange: str = "SH") -> str | None:
    """Wrap panda_data.get_prev_trade_date; returns YYYYMMDD or None. See note above."""
    import panda_data
    result = panda_data.get_prev_trade_date(date=date, exchange=exchange, n=n)
    if result is None:
        return None
    if isinstance(result, str):
        return result or None
    if hasattr(result, "empty") and result.empty:
        return None
    if hasattr(result, "iloc"):
        return str(result["date"].iloc[0])
    return str(result)


def load_audit_opinion(
    start_quarter: str,
    end_quarter: str,
    symbol: str | list[str] | None = None,
    market: str = "cn",
) -> pd.DataFrame:
    """Fetch audit opinions. If symbol is None, queries ALL A-shares.

    Returns a DataFrame with columns [symbol, quarter, date, agency, audit_type, opinion];
    empty frame (with schema) if panda_data returned nothing.
    """
    import panda_data

    kwargs: dict = {
        "start_quarter": start_quarter,
        "end_quarter": end_quarter,
        "market": market,
        "fields": [],
    }
    if symbol is not None:
        kwargs["symbol"] = symbol

    df = panda_data.get_audit_opinion(**kwargs)
    if df is None or (hasattr(df, "empty") and df.empty):
        return pd.DataFrame(columns=sorted(EXPECTED_COLUMNS["audit_opinion"]))
    _assert_columns(df, "audit_opinion")
    df["symbol"] = df["symbol"].astype(str)
    df["quarter"] = df["quarter"].astype(str)
    df["date"] = df["date"].astype(str)
    return df


def load_index_weights(index_symbol: str, date: str) -> pd.DataFrame:
    """CSI300 (or other index) constituents on a single day.

    Returns a DataFrame with columns [index_symbol, date, stock_symbol]; empty
    frame (with schema) if panda_data returned nothing.
    """
    import panda_data
    df = panda_data.get_index_weights(
        index_symbol=index_symbol,
        start_date=date,
        end_date=date,
    )
    if df is None or (hasattr(df, "empty") and df.empty):
        return pd.DataFrame(columns=sorted(EXPECTED_COLUMNS["index_weights"]))
    _assert_columns(df, "index_weights")
    df["date"] = df["date"].astype(str)
    df["stock_symbol"] = df["stock_symbol"].astype(str)
    return df


def load_stock_names(symbols: list[str]) -> dict[str, str]:
    """Resolve a batch of symbols to display names via get_stock_detail.

    The API supports a list of symbols; we send all at once.
    Returns dict symbol → name. Stocks not found are omitted.
    """
    import panda_data

    if not symbols:
        return {}

    name_map: dict[str, str] = {}
    # Batch by chunks of 100 to avoid overly large requests
    chunk_size = 100
    for i in range(0, len(symbols), chunk_size):
        chunk = symbols[i:i + chunk_size]
        try:
            df = panda_data.get_stock_detail(symbol=chunk)
        except Exception:
            continue
        if df is None or (hasattr(df, "empty") and df.empty):
            continue
        if "symbol" in df.columns and "name" in df.columns:
            for _, row in df.iterrows():
                sym = str(row["symbol"])
                name = str(row["name"]) if pd.notna(row["name"]) else ""
                if name:
                    name_map[sym] = name
    return name_map


def self_check(quarter: str, index_symbol: str = "000300.SH") -> int:
    """Manually invoke each loader and print column diagnostics.

    Returns 0 on success, 4 on any column mismatch.
    """
    init_panda_data()
    import panda_data
    exit_code = 0

    ref_date = get_last_trade_date() or "20260731"

    checks = (
        ("audit_opinion", lambda: panda_data.get_audit_opinion(
            start_quarter=quarter, end_quarter=quarter, market="cn",
        )),
        ("index_weights", lambda: panda_data.get_index_weights(
            index_symbol=index_symbol, start_date=ref_date, end_date=ref_date,
        )),
        ("stock_detail", lambda: panda_data.get_stock_detail(
            symbol="000001.SZ",
        )),
    )
    for kind, loader in checks:
        print(f"--- {kind} ---")
        try:
            df = loader()
        except Exception as e:
            print(f"[ERROR] {kind} raised: {e}")
            exit_code = 4
            continue
        if df is None or (hasattr(df, "empty") and df.empty):
            print(f"[WARN] {kind} returned empty on {quarter}")
            continue
        got = set(df.columns)
        expected = EXPECTED_COLUMNS[kind]
        missing = expected - got
        extra = got - expected
        print(f"got columns:      {sorted(got)}")
        print(f"missing required: {sorted(missing)}")
        print(f"extra (ignored):  {sorted(extra)}")
        if missing:
            exit_code = 4
    return exit_code


def _main() -> int:
    p = argparse.ArgumentParser(
        description="panda_data field self-check for skill-audit-opinion-scanner",
    )
    p.add_argument("--self-check", action="store_true", required=True)
    p.add_argument("--quarter", required=True, help="e.g. 2024q4")
    p.add_argument("--index", default="000300.SH", help="Index symbol (default 000300.SH = CSI300)")
    args = p.parse_args()

    try:
        from panda_data.exceptions import ServiceError as _ServiceError
        service_error_cls: tuple = (_ServiceError,)
    except ImportError:
        service_error_cls = ()

    try:
        return self_check(args.quarter, index_symbol=args.index)
    except RuntimeError as e:
        print(f"[error] {e}", file=sys.stderr)
        return 1
    except service_error_cls as e:
        print(f"[error] panda_data service error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(_main())
