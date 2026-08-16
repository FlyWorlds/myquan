"""Formatting utilities for crude oil briefing."""

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


def fmt_price(value: Any, unit: str = "元/桶") -> str:
    """Format a price value."""
    if value is None or value == "" or (isinstance(value, float) and value != value):
        return "—"
    try:
        v = float(value)
        return f"{v:.2f} {unit}"
    except (ValueError, TypeError):
        return str(value)


def fmt_pct(value: Any) -> str:
    """Format a percentage value."""
    if value is None or value == "" or (isinstance(value, float) and value != value):
        return "—"
    try:
        v = float(value)
        sign = "+" if v > 0 else ""
        return f"{sign}{v:.2f}%"
    except (ValueError, TypeError):
        return str(value)


def fmt_change(value: Any) -> str:
    """Format a price change with sign."""
    if value is None or value == "" or (isinstance(value, float) and value != value):
        return "—"
    try:
        v = float(value)
        sign = "+" if v > 0 else ""
        return f"{sign}{v:.2f}"
    except (ValueError, TypeError):
        return str(value)


def fmt_date(value: Any) -> str:
    """Format a date string for display."""
    if value is None or value == "":
        return "—"
    s = str(value).replace("-", "").replace("/", "")
    if len(s) == 8:
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return str(value)


def fmt_volume(value: Any) -> str:
    """Format trading volume."""
    if value is None or value == "" or (isinstance(value, float) and value != value):
        return "—"
    try:
        v = float(value)
        if v >= 1e8:
            return f"{v / 1e8:.2f} 亿手"
        elif v >= 1e4:
            return f"{v / 1e4:.2f} 万手"
        else:
            return f"{v:.2f} 手"
    except (ValueError, TypeError):
        return str(value)


def fmt_inventory(value: Any, unit: str = "万桶") -> str:
    """Format inventory data."""
    if value is None or value == "" or (isinstance(value, float) and value != value):
        return "—"
    try:
        v = float(value)
        return f"{v:,.0f} {unit}"
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


def get_latest_value(df: Any, field: str) -> Any:
    """Get the latest (last) value from a DataFrame column."""
    if df is None or df.empty:
        return None
    try:
        col = df[field]
        valid = col.dropna()
        if valid.empty:
            return None
        return valid.iloc[-1]
    except (KeyError, IndexError, TypeError, AttributeError):
        return None
