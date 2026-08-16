"""Tests for analyze_quick.py scoring logic."""

import numpy as np
import pandas as pd
import pytest

from scripts.analyze_quick import (
    DIMENSIONS, _sigmoid, _compute_np_yoy, score_stock, build_scores_df,
)


class TestSigmoid:
    def test_zero_input(self):
        assert abs(_sigmoid(0) - 50.0) < 1.0

    def test_extreme_positive(self):
        assert _sigmoid(6) > 95.0

    def test_extreme_negative(self):
        assert _sigmoid(-6) < 5.0

    def test_positive_modest(self):
        s = _sigmoid(2)
        assert 80 < s < 100

    def test_monotonic(self):
        vals = [_sigmoid(z) for z in [-4, -2, 0, 2, 4]]
        assert vals == sorted(vals)


class TestComputeNpYoY:
    def test_normal_growth(self):
        df = pd.DataFrame([
            {"symbol": "A.SZ", "quarter": "2023q1", "is_n_income_attr_p": 100},
            {"symbol": "A.SZ", "quarter": "2023q2", "is_n_income_attr_p": 150},
            {"symbol": "A.SZ", "quarter": "2024q1", "is_n_income_attr_p": 120},
            {"symbol": "A.SZ", "quarter": "2024q2", "is_n_income_attr_p": 180},
        ])
        yoy = _compute_np_yoy(df)
        assert abs(yoy["A.SZ"] - 20.0) < 1.0  # Q1: (120-100)/100 = 20%

    def test_loss_flip_negative(self):
        df = pd.DataFrame([
            {"symbol": "B.SZ", "quarter": "2023q4", "is_n_income_attr_p": 100},
            {"symbol": "B.SZ", "quarter": "2024q4", "is_n_income_attr_p": -50},
        ])
        yoy = _compute_np_yoy(df)
        assert abs(yoy["B.SZ"] - -150.0) < 1.0  # (-50-100)/100 = -150%

    def test_single_quarter_no_yoy(self):
        df = pd.DataFrame([
            {"symbol": "C.SZ", "quarter": "2024q4", "is_n_income_attr_p": 100},
        ])
        yoy = _compute_np_yoy(df)
        assert "C.SZ" not in yoy

    def test_prev_zero_handled(self):
        df = pd.DataFrame([
            {"symbol": "D.SZ", "quarter": "2023q1", "is_n_income_attr_p": 0},
            {"symbol": "D.SZ", "quarter": "2024q1", "is_n_income_attr_p": 100},
        ])
        yoy = _compute_np_yoy(df)
        assert "D.SZ" not in yoy  # division by zero → excluded


class TestScoreStock:
    @pytest.fixture
    def sample_row(self):
        return pd.Series({
            "symbol": "TEST.SZ", "roe": 15, "net_margin": 20,
            "is_revenue": 500, "cfo_to_np": 1.5, "_yoy_np": 25,
        })

    @pytest.fixture
    def industry_medians(self):
        return {
            "roe": 10, "_mad_roe": 5,
            "net_margin": 15, "_mad_net_margin": 5,
            "is_revenue": 300, "_mad_is_revenue": 200,
            "cfo_to_np": 1.0, "_mad_cfo_to_np": 0.5,
            "_yoy_np": 15, "_mad__yoy_np": 10,
        }

    def test_above_median_scores_high(self, sample_row, industry_medians):
        result = score_stock(sample_row, industry_medians, n_peers=50)
        assert result["composite"] > 60
        assert result["light"] in ("🟢", "🟡")

    def test_below_median_scores_low(self, industry_medians):
        row = pd.Series({
            "symbol": "WEAK.SZ",
            "roe": 2, "net_margin": 3, "is_revenue": 100,
            "cfo_to_np": 0.3, "_yoy_np": -30,
        })
        result = score_stock(row, industry_medians, n_peers=50)
        assert result["composite"] < 50

    def test_missing_values_default_neutral(self, sample_row):
        # Empty medians → all dims should get ~50
        result = score_stock(sample_row, {}, n_peers=0)
        assert 45 < result["composite"] < 55

    def test_dims_have_all_keys(self, sample_row, industry_medians):
        result = score_stock(sample_row, industry_medians, n_peers=50)
        for d in DIMENSIONS:
            assert d.key in result["dims"]


class TestBuildScoresDf:
    def test_empty_cache(self, tmp_path, monkeypatch):
        """Should return empty DataFrame when cache is empty."""
        monkeypatch.setattr("scripts.analyze_quick.FINA_CACHE", tmp_path / "nonexistent.parquet")
        monkeypatch.setattr("scripts.analyze_quick.INDU_CACHE", tmp_path / "nonexistent_indu.parquet")
        result = build_scores_df()
        assert result.empty
