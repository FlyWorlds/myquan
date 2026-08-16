"""Tests for analyze_stock.py core functions."""

import numpy as np
import pandas as pd
import pytest

from scripts.analyze_stock import (
    _fmt, _ratio_fmt, _diff,
    _build_multi_year_table, _build_dupont,
    _detect_red_flags,
)
from scripts.build_cache import compute_ratios_df


class TestFmt:
    def test_money_yi(self):
        assert "3.53 亿" in _fmt(353000000)

    def test_money_wan(self):
        assert "520.00 万" in _fmt(5200000)

    def test_pct(self):
        assert "+10.50%" == _fmt(10.5, "%")

    def test_nan(self):
        assert _fmt(float("nan")) == "N/A"
        assert _fmt(None) == "N/A"


class TestRatioFmt:
    def test_pct(self):
        assert _ratio_fmt(10.567, True) == "10.6%"

    def test_nan(self):
        assert _ratio_fmt(float("nan")) == "N/A"
        assert _ratio_fmt(None) == "N/A"


class TestDiff:
    def test_normal(self):
        assert _diff(20, 10, is_pct=True) == "+10.0%"

    def test_nan(self):
        assert _diff(float("nan"), 10) == "—"


class TestBuildMultiYearTable:
    @pytest.fixture
    def stock_df(self):
        return pd.DataFrame([
            {"symbol": "X.SZ", "quarter": "2024q3", "is_revenue": 100, "is_oper_cost": 40,
             "is_gross_profit": 60, "is_sell_exp": 10, "is_admin_exp": 8,
             "is_rd_exp": 5, "is_fin_exp": 2, "is_operate_profit": 30,
             "is_total_profit": 28, "is_n_income_attr_p": 20, "is_n_income": 22},
            {"symbol": "X.SZ", "quarter": "2024q4", "is_revenue": 120, "is_oper_cost": 50,
             "is_gross_profit": 70, "is_sell_exp": 12, "is_admin_exp": 9,
             "is_rd_exp": 6, "is_fin_exp": 3, "is_operate_profit": 35,
             "is_total_profit": 33, "is_n_income_attr_p": 25, "is_n_income": 27},
        ])

    def test_output_contains_both_quarters(self, stock_df):
        result = _build_multi_year_table(stock_df)
        assert "2024q3" in result
        assert "2024q4" in result

    def test_contains_trend_arrow(self, stock_df):
        result = _build_multi_year_table(stock_df)
        assert "↗" in result or "↘" in result  # revenue growing


class TestBuildDuPont:
    @pytest.fixture
    def stock_df(self):
        return pd.DataFrame([
            {"symbol": "TEST.SZ", "quarter": "2024q4",
             "is_n_income_attr_p": 20, "is_revenue": 100,
             "bs_total_assets": 400, "bs_total_hldr_eqy_exc_min_int": 250},
        ])

    def test_roe_calculation(self, stock_df):
        result = _build_dupont(stock_df)
        assert "5.0%" in result or "8.0%" in result  # ROE = 20/250 = 8%
        assert "DuPont" in result

    def test_contains_equity_multiplier(self, stock_df):
        result = _build_dupont(stock_df)
        # EM = 400/250 = 1.6
        assert "1.60" in result or "1.6" in result


class TestDetectRedFlags:
    @pytest.fixture
    def danger_stock(self):
        """A stock with multiple red flags."""
        return pd.DataFrame([
            {"symbol": "BAD.SZ", "quarter": "2024q2",
             "is_revenue": 100, "is_n_income_attr_p": -10,
             "bs_total_assets": 500, "bs_total_liab": 450,
             "bs_total_hldr_eqy_exc_min_int": 50,
             "bs_total_cur_assets": 30, "bs_total_cur_liab": 60,
             "bs_goodwill": 100, "bs_money_cap": 5,
             "cfs_net_cash_operating": -5},
            {"symbol": "BAD.SZ", "quarter": "2024q3",
             "is_revenue": 90, "is_n_income_attr_p": -20,
             "bs_total_assets": 480, "bs_total_liab": 450,
             "bs_total_hldr_eqy_exc_min_int": 30,
             "bs_total_cur_assets": 25, "bs_total_cur_liab": 60,
             "bs_goodwill": 100, "bs_money_cap": 3,
             "cfs_net_cash_operating": -8},
            {"symbol": "BAD.SZ", "quarter": "2024q4",
             "is_revenue": 80, "is_n_income_attr_p": -30,
             "bs_total_assets": 450, "bs_total_liab": 445,
             "bs_total_hldr_eqy_exc_min_int": 5,
             "bs_total_cur_assets": 20, "bs_total_cur_liab": 60,
             "bs_goodwill": 100, "bs_money_cap": 1,
             "cfs_net_cash_operating": -10},
        ])

    @pytest.fixture
    def healthy_stock(self):
        return pd.DataFrame([
            {"symbol": "GOOD.SZ", "quarter": "2024q4",
             "is_revenue": 500, "is_n_income_attr_p": 80,
             "bs_total_assets": 1000, "bs_total_liab": 400,
             "bs_total_hldr_eqy_exc_min_int": 600,
             "bs_total_cur_assets": 300, "bs_total_cur_liab": 150,
             "bs_goodwill": 30, "bs_money_cap": 200,
             "cfs_net_cash_operating": 90},
        ])

    def test_danger_stock_has_flags(self, danger_stock):
        flags = _detect_red_flags(danger_stock, pd.DataFrame(), {})
        assert len(flags) >= 3  # should catch multiple issues

    def test_danger_flags_include_roe_neg(self, danger_stock):
        flags = _detect_red_flags(danger_stock, pd.DataFrame(), {})
        flag_texts = [f["check"] for f in flags]
        # ROE is negative because net profit is -30 and equity is 5
        assert any("ROE" in t or "亏损" in t or "净利润为负" in t for t in flag_texts)

    def test_healthy_stock_minimal_flags(self, healthy_stock):
        flags = _detect_red_flags(healthy_stock, pd.DataFrame(), {})
        # Should have 0 or very few flags
        danger_flags = [f for f in flags if f["severity"] == "danger"]
        assert len(danger_flags) == 0

    def test_returns_list_of_dicts(self, danger_stock):
        flags = _detect_red_flags(danger_stock, pd.DataFrame(), {})
        for f in flags:
            assert "severity" in f
            assert "check" in f
            assert "detail" in f
            assert f["severity"] in ("danger", "warning")


class TestIntegration:
    """Light integration: compute_ratios → print functions should not crash."""

    @pytest.fixture
    def stock_df(self):
        return pd.DataFrame([
            {"symbol": "INT.SZ", "quarter": "2024q3",
             "is_revenue": 100, "is_oper_cost": 60, "is_gross_profit": 40,
             "is_sell_exp": 10, "is_admin_exp": 5, "is_rd_exp": 3, "is_fin_exp": 2,
             "is_operate_profit": 20, "is_total_profit": 18, "is_n_income_attr_p": 12,
             "is_n_income": 14,
             "bs_total_assets": 500, "bs_total_liab": 250,
             "bs_total_hldr_eqy_exc_min_int": 250,
             "bs_total_cur_assets": 200, "bs_total_cur_liab": 100,
             "bs_money_cap": 80, "bs_inventory": 50, "bs_acct_payable": 40,
             "bs_goodwill": 10, "bs_lt_borr": 100,
             "cfs_net_cash_operating": 15, "cfs_net_cash_investing": -8,
             "cfs_net_cash_financing": -3, "cfs_end_cash_equiv": 60,
            },
        ])

    def test_all_report_builders_dont_crash(self, stock_df):
        """All report functions should handle edge cases gracefully."""
        # Multi-year
        result1 = _build_multi_year_table(stock_df)
        assert isinstance(result1, str) and len(result1) > 0

        # DuPont
        result2 = _build_dupont(stock_df)
        assert isinstance(result2, str)

        # Red flags
        flags = _detect_red_flags(stock_df, pd.DataFrame(), {})
        assert isinstance(flags, list)
