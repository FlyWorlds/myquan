"""Tests for universe resolution (scripts/universe.py)."""

import pandas as pd
import pytest

from scripts.universe import filter_universe, resolve_universe


class TestFilterUniverse:
    def test_extracts_symbols(self, sample_weights_df):
        symbols = filter_universe(sample_weights_df)
        assert len(symbols) == 5
        assert "000001.SZ" in symbols
        assert "600519.SH" in symbols

    def test_sorted_output(self, sample_weights_df):
        symbols = filter_universe(sample_weights_df)
        assert symbols == sorted(symbols)

    def test_empty_weights_raises(self):
        df = pd.DataFrame(columns=["index_symbol", "date", "stock_symbol", "weight"])
        with pytest.raises(RuntimeError, match="empty"):
            filter_universe(df)

    def test_exclude_st_option(self, sample_weights_df):
        """exclude_st flag should not crash (v1 does not implement ST filtering yet)."""
        symbols = filter_universe(sample_weights_df, exclude_st=True)
        assert len(symbols) == 5  # v1: no ST data, all pass through
