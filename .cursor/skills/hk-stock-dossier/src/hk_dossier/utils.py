"""Formatting utilities for the HK stock dossier."""

from decimal import Decimal
from typing import Any


def fmt_number(value: Any, decimals: int = 2) -> str:
    """Format a number with thousand separators and fixed decimals."""
    if value is None or value == "" or (isinstance(value, float) and value != value):
        return "—"
    try:
        v = float(value)
        return f"{v:,.{decimals}f}"
    except (ValueError, TypeError):
        return str(value)


def fmt_pct(value: Any) -> str:
    """Format a percentage value."""
    if value is None or value == "" or (isinstance(value, float) and value != value):
        return "—"
    try:
        v = float(value)
        return f"{v:.2f}%"
    except (ValueError, TypeError):
        return str(value)


def fmt_date(value: Any) -> str:
    """Format a date string (YYYYMMDD or YYYY-MM-DD) for display."""
    if value is None or value == "":
        return "—"
    s = str(value).replace("-", "")
    if len(s) == 8:
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return str(value)


def fmt_market_cap(value: Any, currency: str = "HKD") -> str:
    """Format market cap into human-readable form."""
    if value is None or value == "" or (isinstance(value, float) and value != value):
        return "—"
    try:
        v = float(value)
        sign = "-" if v < 0 else ""
        v = abs(v)
        if v >= 1e12:
            return f"{sign}{v / 1e12:.2f} 万亿 {currency}"
        elif v >= 1e8:
            return f"{sign}{v / 1e8:.2f} 亿 {currency}"
        elif v >= 1e4:
            return f"{sign}{v / 1e4:.2f} 万 {currency}"
        else:
            return f"{sign}{v:.2f} {currency}"
    except (ValueError, TypeError):
        return str(value)


def fmt_shares(value: Any) -> str:
    """Format share count."""
    if value is None or value == "" or (isinstance(value, float) and value != value):
        return "—"
    try:
        v = float(value)
        if v >= 1e8:
            return f"{v / 1e8:.2f} 亿股"
        elif v >= 1e4:
            return f"{v / 1e4:.2f} 万股"
        else:
            return f"{v:.2f} 股"
    except (ValueError, TypeError):
        return str(value)


def get_first_value(df: Any, field: str) -> Any:
    """Safely get the first non-null value from a DataFrame column."""
    if df is None or df.empty:
        return None
    try:
        col = df[field]
        valid = col.dropna()
        if valid.empty:
            return None
        return valid.iloc[0]
    except (KeyError, IndexError, TypeError, AttributeError):
        return None


def get_value_map(df: Any, key_col: str, val_col: str) -> dict[str, Any]:
    """Convert a DataFrame with item_name / item_num columns to a dict."""
    result = {}
    if df is None or df.empty:
        return result
    try:
        for _, row in df.iterrows():
            key = row.get(key_col)
            val = row.get(val_col)
            if key and val is not None:
                result[str(key)] = val
        return result
    except (KeyError, IndexError, TypeError, AttributeError):
        return result
