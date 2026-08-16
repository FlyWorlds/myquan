"""Tests for data layer (scripts/data.py)."""

import pandas as pd
import pytest

from scripts.data import EXPECTED_COLUMNS, _assert_columns


class TestAssertColumns:
    def test_all_present(self):
        df = pd.DataFrame(columns=["symbol", "quarter", "date", "agency", "audit_type", "opinion"])
        _assert_columns(df, "audit_opinion")

    def test_missing_column_raises(self):
        df = pd.DataFrame(columns=["symbol", "quarter", "date"])
        with pytest.raises(ValueError, match="missing columns"):
            _assert_columns(df, "audit_opinion")

    def test_empty_df_still_checks(self):
        df = pd.DataFrame()
        with pytest.raises(ValueError, match="missing columns"):
            _assert_columns(df, "audit_opinion")

    def test_index_weights_check(self):
        df = pd.DataFrame(columns=["index_symbol", "date", "stock_symbol", "weight"])
        _assert_columns(df, "index_weights")  # should pass; weight is extra

    def test_stock_detail_check(self):
        df = pd.DataFrame(columns=["symbol", "name", "extra_col"])
        _assert_columns(df, "stock_detail")


class TestLoadStockNames:
    def test_empty_input(self):
        from scripts.data import load_stock_names
        result = load_stock_names([])
        assert result == {}
