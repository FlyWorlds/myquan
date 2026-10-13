"""Market data source adapters and cross-source validation helpers.

This package is intentionally independent from the watch trading loop.  It
collects market facts from free public interfaces and normalizes provenance so
strategy code can decide what is safe to consume.
"""

from .models import DataSourceResult, LimitUpRecord, QuoteRecord
from .reconcile import QuoteDisagreement, compare_quote_records

__all__ = [
    "DataSourceResult",
    "LimitUpRecord",
    "QuoteDisagreement",
    "QuoteRecord",
    "compare_quote_records",
]
