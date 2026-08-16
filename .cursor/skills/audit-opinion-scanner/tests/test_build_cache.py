"""Tests for derived ratio computation & utility functions."""

import pandas as pd
import numpy as np
import pytest

from scripts.build_cache import (
    _div, _pct, compute_ratios_df, resolve_quarters, get_industry_map,
    KEY_FIELDS, RATIOS, RATIO_LABELS,
)


class TestDiv:
    def test_normal(self):
        assert _div(10, 2) == 5.0

    def test_zero_denominator(self):
        assert _div(10, 0) is None

    def test_none(self):
        assert _div(None, 5) is None
        assert _div(5, None) is None

    def test_nan(self):
        assert _div(np.nan, 5) is None
        assert _div(5, np.nan) is None

    def test_negative(self):
        assert _div(-10, 2) == -5.0


class TestPct:
    def test_normal(self):
        assert _pct(5, 10) == 50.0

    def test_zero_denom(self):
        assert _pct(5, 0) is None

    def test_none(self):
        assert _pct(None, 10) is None


class TestResolveQuarters:
    def test_default_count(self):
        qs = resolve_quarters(4)
        assert len(qs) == 4
        for q in qs:
            assert "q" in q

    def test_all_valid_format(self):
        qs = resolve_quarters(8)
        for q in qs:
            parts = q.split("q")
            assert len(parts) == 2
            assert 1 <= int(parts[1]) <= 4

    def test_descending_order(self):
        qs = resolve_quarters(8)
        # Q1 → Q4 group within same year descending
        for i in range(1, len(qs)):
            # Each preceding quarter should be chronologically before the next
            y1, q1 = int(qs[i - 1][:4]), int(qs[i - 1][5])
            y2, q2 = int(qs[i][:4]), int(qs[i][5])
            # descending means current > next chronologically
            assert (y1 > y2) or (y1 == y2 and q1 > q2)


class TestComputeRatios:
    @pytest.fixture
    def sample_fina_df(self):
        """A minimal DataFrame with key financial fields for 2 quarters."""
        return pd.DataFrame([
            {
                "symbol": "TEST.SZ", "quarter": "2024q4",
                "is_revenue": 100, "is_oper_cost": 40,
                "is_gross_profit": 60, "is_operate_profit": 30,
                "is_total_profit": 28, "is_n_income_attr_p": 20,
                "is_n_income": 22, "is_sell_exp": 10, "is_admin_exp": 8,
                "is_rd_exp": 5, "is_fin_exp": 2,
                "bs_total_assets": 500, "bs_total_liab": 200,
                "bs_total_hldr_eqy_exc_min_int": 300,
                "bs_total_cur_assets": 150, "bs_total_cur_liab": 80,
                "bs_money_cap": 50, "bs_inventory": 30,
                "bs_acct_payable": 25, "bs_goodwill": 60, "bs_lt_borr": 120,
                "cfs_net_cash_operating": 25,
                "cfs_net_cash_investing": -10,
                "cfs_net_cash_financing": -5,
                "cfs_end_cash_equiv": 80,
            },
            {
                "symbol": "TEST.SZ", "quarter": "2025q1",
                "is_revenue": 120, "is_oper_cost": 50,
                "is_gross_profit": 70, "is_operate_profit": 35,
                "is_total_profit": 33, "is_n_income_attr_p": 25,
                "is_n_income": 27, "is_sell_exp": 12, "is_admin_exp": 9,
                "is_rd_exp": 6, "is_fin_exp": 3,
                "bs_total_assets": 550, "bs_total_liab": 220,
                "bs_total_hldr_eqy_exc_min_int": 330,
                "bs_total_cur_assets": 160, "bs_total_cur_liab": 85,
                "bs_money_cap": 55, "bs_inventory": 35,
                "bs_acct_payable": 28, "bs_goodwill": 60, "bs_lt_borr": 130,
                "cfs_net_cash_operating": 30,
                "cfs_net_cash_investing": -12,
                "cfs_net_cash_financing": -6,
                "cfs_end_cash_equiv": 90,
            },
        ])

    def test_basic_ratios_computed(self, sample_fina_df):
        result = compute_ratios_df(sample_fina_df)
        assert len(result) == 2

        # ROE = 20/300 = 6.67%
        assert abs(result["roe"].iloc[0] - 6.67) < 0.1
        # ROA = 20/500 = 4%
        assert abs(result["roa"].iloc[0] - 4.0) < 0.1
        # net_margin = 20/100 = 20%
        assert abs(result["net_margin"].iloc[0] - 20.0) < 0.1
        # debt_ratio = 200/500 = 40%
        assert abs(result["debt_ratio"].iloc[0] - 40.0) < 0.1
        # current_ratio = 150/80 = 1.875
        assert abs(result["current_ratio"].iloc[0] - 1.875) < 0.01
        # cfo_to_np = 25/20 = 1.25
        assert abs(result["cfo_to_np"].iloc[0] - 1.25) < 0.01
        # asset_turnover = 100/500 = 0.2
        assert abs(result["asset_turnover"].iloc[0] - 0.2) < 0.01
        # equity_multiplier = 500/300 = 1.667
        assert abs(result["equity_multiplier"].iloc[0] - 1.667) < 0.1
        # goodwill_to_equity = 60/300 = 20%
        assert abs(result["goodwill_to_equity"].iloc[0] - 20.0) < 0.1
        # rd_to_revenue = 5/100 = 5%
        assert abs(result["rd_to_revenue"].iloc[0] - 5.0) < 0.1

    def test_second_quarter_ratios(self, sample_fina_df):
        result = compute_ratios_df(sample_fina_df)
        # Q2: ROE = 25/330 = 7.58%
        assert abs(result["roe"].iloc[1] - 7.58) < 0.1
        # growth visible
        assert result["is_revenue"].iloc[1] == 120

    def test_empty_input(self):
        df = pd.DataFrame(columns=["symbol", "quarter"] + KEY_FIELDS)
        result = compute_ratios_df(df)
        assert result.empty

    def test_all_null_fields(self):
        """Should not crash when all fields are None."""
        df = pd.DataFrame([{
            "symbol": "X.SZ", "quarter": "2024q4",
            **{f: None for f in KEY_FIELDS}
        }])
        result = compute_ratios_df(df)
        assert len(result) == 1
        assert all(pd.isna(result[rname].iloc[0]) for rname, _ in RATIOS)


class TestGetIndustryMap:
    @pytest.fixture
    def sample_indu_df(self):
        return pd.DataFrame([
            {"stock_symbol": "000001.SZ", "l1_name": "银行", "l1_code": "801780",
             "l2_name": "股份制银行Ⅱ", "l3_name": "股份制银行Ⅲ", "in_date": "19910403"},
            {"stock_symbol": "600519.SH", "l1_name": "食品饮料", "l1_code": "801120",
             "l2_name": "白酒Ⅱ", "l3_name": "白酒Ⅲ", "in_date": "20010827"},
            {"stock_symbol": "000001.SZ", "l1_name": "银行", "l1_code": "801780",
             "l2_name": "股份制银行Ⅱ", "l3_name": "股份制银行Ⅲ", "in_date": "19900403"},
        ])

    def test_dedup_keeps_latest(self, sample_indu_df):
        result = get_industry_map(sample_indu_df)
        assert len(result) == 2  # deduped

    def test_correct_mapping(self, sample_indu_df):
        result = get_industry_map(sample_indu_df)
        assert result["600519.SH"]["l1_name"] == "食品饮料"
        assert result["000001.SZ"]["l1_name"] == "银行"

    def test_empty(self):
        result = get_industry_map(pd.DataFrame())
        assert result == {}


class TestRatioLabels:
    def test_all_ratios_have_labels(self):
        for rname, _ in RATIOS:
            assert rname in RATIO_LABELS, f"{rname} missing label"

    def test_no_stale_labels(self):
        ratio_names = {r[0] for r in RATIOS}
        for rname in RATIO_LABELS:
            assert rname in ratio_names, f"{rname} in labels but not in RATIOS"
