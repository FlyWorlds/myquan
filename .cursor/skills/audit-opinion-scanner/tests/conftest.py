"""Shared test fixtures for audit-opinion-scanner."""

import os
import sys
from pathlib import Path

import pandas as pd
import pytest

# Make scripts importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def sample_opinions_df():
    """A representative raw audit opinion DataFrame covering all expected patterns."""
    return pd.DataFrame({
        "symbol": [
            "000001.SZ", "000001.SZ", "000001.SZ",
            "600519.SH", "600519.SH", "600519.SH",
            "300750.SZ",
            "000002.SZ", "000002.SZ",
        ],
        "quarter": [
            "2024q1", "2024q2", "2024q4",
            "2024q3", "2024q4", "2024q4",
            "2024q4",
            "2024q4", "2024q4",
        ],
        "date": [
            "20240420", "20240816", "20250315",
            "20241025", "20250328", "20250328",
            "20250410",
            "20250330", "20250330",
        ],
        "agency": [
            None, None, "安永华明",
            None, "普华永道", "普华永道",
            "毕马威",
            "德勤", "德勤",
        ],
        "audit_type": [
            "financial_statements", "financial_statements", "financial_statements",
            "financial_statements", "financial_statements", "internal_control",
            "financial_statements",
            "financial_statements", "internal_control",
        ],
        "opinion": [
            "no_audit_performed", "no_audit_performed", "unqualified_opinion",
            "no_audit_performed", "unqualified_opinion", "unqualified_opinion",
            "qualified_opinion",
            "unqualified_opinion", "unqualified_opinion",
        ],
    })


@pytest.fixture
def sample_weights_df():
    """Mock CSI300 index weights."""
    return pd.DataFrame({
        "index_symbol": ["000300.SH"] * 5,
        "date": ["20250331"] * 5,
        "stock_symbol": [
            "000001.SZ", "000002.SZ", "600519.SH", "300750.SZ", "601318.SH",
        ],
        "weight": [0.05, 0.04, 0.07, 0.06, 0.05],
    })


@pytest.fixture
def universe_symbols(sample_weights_df):
    """Extracted symbol list from sample weights."""
    return sorted(sample_weights_df["stock_symbol"].unique().tolist())
