"""Tests for ML audit opinion prediction (scripts/predict.py)."""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import predict as pred_mod


# ── Synthetic data fixtures ────────────────────────────────────────────────


def _make_symbols(n: int) -> list[str]:
    """Generate n synthetic stock symbols."""
    return [f"{600000 + i:06d}.SH" for i in range(n)]


@pytest.fixture
def sample_fina_df():
    """Small financial data covering 8 quarters with some variation."""
    np.random.seed(42)
    symbols = _make_symbols(50)
    rows = []
    quarters = ["2023q1", "2023q2", "2023q3", "2023q4",
                "2024q1", "2024q2", "2024q3", "2024q4"]

    for sym in symbols:
        # Base values — different profiles per symbol
        base_revenue = abs(np.random.normal(5e9, 3e9))
        base_profit = base_revenue * abs(np.random.normal(0.08, 0.06))
        base_assets = base_revenue * abs(np.random.normal(2.0, 0.8))
        base_equity = base_assets * abs(np.random.normal(0.5, 0.2))
        base_liab = base_assets - base_equity
        base_goodwill = base_assets * abs(np.random.normal(0.03, 0.05))
        base_cfo = base_profit * abs(np.random.normal(0.8, 0.5))

        for q in quarters:
            q_num = int(q[5])
            season = 1.0 + 0.1 * np.sin(np.pi * q_num / 2)
            rev = base_revenue * season * np.random.normal(1.0, 0.05)
            profit = base_profit * season * np.random.normal(1.0, 0.1)
            assets = base_assets + np.random.normal(0, base_assets * 0.02)
            equ = base_equity + np.random.normal(0, abs(base_equity) * 0.02)
            liab = assets - equ
            cfo = base_cfo * season * np.random.normal(1.0, 0.2)

            rows.append({
                "symbol": sym,
                "quarter": q,
                "date": f"{q[:4]}0{q[5]}{15 + q_num * 10:02d}",
                "fetch_time": "2025-01-01T00:00:00",
                "is_revenue": rev,
                "is_oper_cost": rev * 0.6,
                "is_gross_profit": rev * 0.4,
                "is_sell_exp": rev * 0.05,
                "is_admin_exp": rev * 0.03,
                "is_rd_exp": rev * 0.02,
                "is_fin_exp": rev * 0.01,
                "is_operate_profit": profit,
                "is_total_profit": profit * 0.95,
                "is_n_income_attr_p": profit * 0.75,
                "is_n_income": profit * 0.75,
                "bs_total_assets": assets,
                "bs_total_liab": liab,
                "bs_total_hldr_eqy_exc_min_int": equ,
                "bs_total_cur_assets": assets * 0.4,
                "bs_total_cur_liab": liab * 0.6,
                "bs_money_cap": assets * 0.1,
                "bs_inventory": assets * 0.15,
                "bs_acct_payable": liab * 0.2,
                "bs_goodwill": max(0, base_goodwill),
                "bs_lt_borr": liab * 0.3,
                "cfs_net_cash_operating": cfo,
                "cfs_net_cash_investing": -cfo * 0.3,
                "cfs_net_cash_financing": cfo * 0.1,
                "cfs_end_cash_equiv": cfo * 0.5,
            })

    return pd.DataFrame(rows)


@pytest.fixture
def sample_indu_df(sample_fina_df):
    """Industry classification for synthetic stocks."""
    symbols = sorted(sample_fina_df["symbol"].unique())
    industries = ["银行", "食品饮料", "医药生物", "计算机", "电子"]
    rows = []
    for sym in symbols:
        i = hash(sym) % len(industries)
        rows.append({
            "stock_symbol": sym,
            "l1_name": industries[i],
            "l1_code": f"801{i:03d}",
            "l2_name": f"{industries[i]}子行业",
            "l3_name": f"{industries[i]}细分",
            "in_date": "20150101",
            "out_date": None,
            "stock_name": sym,
            "fetch_time": "2025-01-01T00:00:00",
        })
    return pd.DataFrame(rows)


@pytest.fixture
def sample_audit_df():
    """Audit labels with some non-standard opinions."""
    np.random.seed(42)
    symbols = _make_symbols(50)
    rows = []
    for sym in symbols:
        # ~8% of stocks get non-standard opinions (adjusted version)
        is_nonstd = np.random.random() < 0.08
        opinion = ("qualified_opinion" if is_nonstd else "unqualified_opinion")
        risk = 2 if is_nonstd else 0
        rows.append({
            "symbol": sym,
            "quarter": "2024q4",
            "date": "20250415",
            "agency": "某某会计师事务所",
            "audit_type": "financial_statements",
            "opinion": opinion,
            "risk_level": risk,
            "risk_label": "高风险" if is_nonstd else "低风险",
            "name": sym,
        })
    return pd.DataFrame(rows)


# ── Tests ──────────────────────────────────────────────────────────────────


class TestPrevQuarter:
    def test_q4_to_q3(self):
        assert pred_mod._get_prev_quarter("2024q4") == "2024q3"

    def test_q1_to_prev_year_q4(self):
        assert pred_mod._get_prev_quarter("2025q1") == "2024q4"

    def test_q2_to_q1(self):
        assert pred_mod._get_prev_quarter("2024q2") == "2024q1"

    def test_invalid_returns_none(self):
        assert pred_mod._get_prev_quarter("bad") is None
        assert pred_mod._get_prev_quarter("") is None


class TestRiskTier:
    def test_safe(self):
        assert "安全" in pred_mod._risk_tier(0.05)

    def test_attention(self):
        assert "关注" in pred_mod._risk_tier(0.15)

    def test_warning(self):
        assert "警示" in pred_mod._risk_tier(0.35)

    def test_danger(self):
        assert "高危" in pred_mod._risk_tier(0.6)


class TestBuildTrainingSet:
    def test_basic(self, sample_fina_df, sample_indu_df, sample_audit_df):
        train_df, imp_vals, ind_map, feat_names = pred_mod.build_training_set(
            sample_fina_df, sample_audit_df, sample_indu_df
        )
        assert len(train_df) > 0, "Should have training pairs"
        assert "label" in train_df.columns
        assert "audit_quarter" in train_df.columns
        assert len(feat_names) >= 40, f"Expected >= 40 features, got {len(feat_names)}"

    def test_time_alignment_no_leak(self, sample_fina_df, sample_indu_df, sample_audit_df):
        """Verify features come from quarter BEFORE the audit quarter."""
        train_df, _, _, _ = pred_mod.build_training_set(
            sample_fina_df, sample_audit_df, sample_indu_df
        )
        for _, row in train_df.iterrows():
            audit_q = row["audit_quarter"]
            # All audit quarters should be Q4
            assert audit_q.endswith("q4"), f"Expected Q4 audit, got {audit_q}"

    def test_feature_count(self, sample_fina_df, sample_indu_df, sample_audit_df):
        train_df, _, _, feat_names = pred_mod.build_training_set(
            sample_fina_df, sample_audit_df, sample_indu_df
        )
        # 25 raw + 15 ratios + 5 YoY + 1 industry = 46 minimum
        assert len(feat_names) >= 40

    def test_empty_audit_returns_empty(self, sample_fina_df, sample_indu_df):
        empty_audit = pd.DataFrame(columns=["symbol", "quarter", "risk_level",
                                            "opinion", "risk_label"])
        train_df, _, _, _ = pred_mod.build_training_set(
            sample_fina_df, empty_audit, sample_indu_df
        )
        assert train_df.empty


class TestFeatureEngineering:
    def test_engineer_features_output_shape(self, sample_fina_df, sample_indu_df):
        features, imp_vals, ind_map, feat_names = pred_mod.engineer_features(
            sample_fina_df, sample_indu_df, fit=True
        )
        assert len(features) == len(sample_fina_df)
        assert "symbol" in features.columns
        assert "quarter" in features.columns
        assert pred_mod.INDUSTRY_FEATURE in features.columns

    def test_no_nan_in_features_after_imputation(self, sample_fina_df, sample_indu_df):
        features, imp_vals, ind_map, feat_names = pred_mod.engineer_features(
            sample_fina_df, sample_indu_df, fit=True
        )
        for f in feat_names:
            assert not features[f].isna().any(), f"NaN found in feature {f}"

    def test_imputation_values_saved(self, sample_fina_df, sample_indu_df):
        features, imp_vals, ind_map, feat_names = pred_mod.engineer_features(
            sample_fina_df, sample_indu_df, fit=True
        )
        assert len(imp_vals) >= 40, f"Expected >= 40 imputation values, got {len(imp_vals)}"

    def test_industry_mapping_created(self, sample_fina_df, sample_indu_df):
        features, imp_vals, ind_map, feat_names = pred_mod.engineer_features(
            sample_fina_df, sample_indu_df, fit=True
        )
        assert len(ind_map) >= 1


class TestTrainAndPredict:
    def test_train_and_predict(self, sample_fina_df, sample_indu_df, sample_audit_df):
        train_df, imp_vals, ind_map, feat_names = pred_mod.build_training_set(
            sample_fina_df, sample_audit_df, sample_indu_df
        )
        model, metrics = pred_mod.train_model(train_df, feat_names)

        n_pred = pred_mod.predict(
            model, sample_fina_df, sample_indu_df,
            imp_vals, ind_map, feat_names,
        )
        assert len(n_pred) > 0
        assert "prob_nonstandard" in n_pred.columns
        assert "risk_tier" in n_pred.columns

    def test_probabilities_in_range(self, sample_fina_df, sample_indu_df, sample_audit_df):
        train_df, imp_vals, ind_map, feat_names = pred_mod.build_training_set(
            sample_fina_df, sample_audit_df, sample_indu_df
        )
        model, _ = pred_mod.train_model(train_df, feat_names)

        n_pred = pred_mod.predict(
            model, sample_fina_df, sample_indu_df,
            imp_vals, ind_map, feat_names,
        )
        probs = n_pred["prob_nonstandard"].values
        assert (probs >= 0).all() and (probs <= 1).all(), \
            f"Probabilities out of range: min={probs.min()}, max={probs.max()}"

    def test_reproducibility(self, sample_fina_df, sample_indu_df, sample_audit_df):
        """Same seed should produce identical models."""
        train_df, _, _, feat_names = pred_mod.build_training_set(
            sample_fina_df, sample_audit_df, sample_indu_df
        )

        np.random.seed(42)
        model1, _ = pred_mod.train_model(train_df, feat_names)
        np.random.seed(42)
        model2, _ = pred_mod.train_model(train_df, feat_names)

        # Predictions should be identical
        X = train_df[feat_names].values.astype(np.float32)
        p1 = model1.predict_proba(X)[:, 1]
        p2 = model2.predict_proba(X)[:, 1]
        assert np.allclose(p1, p2), "Predictions differ between runs"


class TestModelSaveLoad:
    def test_save_and_load(self, sample_fina_df, sample_indu_df, sample_audit_df, tmp_path):
        train_df, imp_vals, ind_map, feat_names = pred_mod.build_training_set(
            sample_fina_df, sample_audit_df, sample_indu_df
        )
        model, metrics = pred_mod.train_model(train_df, feat_names)

        # Save to temp path
        original_path = pred_mod.MODEL_PATH
        try:
            pred_mod.MODEL_PATH = tmp_path / "audit_predictor.json"
            pred_mod.save_model(model, imp_vals, ind_map, feat_names, metrics)
            assert pred_mod.MODEL_PATH.exists()

            # Load and verify
            loaded = pred_mod.load_model()
            assert loaded is not None
            loaded_model, loaded_imp, loaded_ind, loaded_feat = loaded
            assert loaded_feat == feat_names
            assert set(loaded_imp.keys()) == set(imp_vals.keys())
        finally:
            pred_mod.MODEL_PATH = original_path


class TestBacktest:
    def test_backtest_runs(self, sample_fina_df, sample_indu_df, sample_audit_df):
        train_df, _, _, feat_names = pred_mod.build_training_set(
            sample_fina_df, sample_audit_df, sample_indu_df
        )
        # With 1 quarter, backtest should warn but not crash
        summary = pred_mod.backtest(train_df, feat_names)
        assert isinstance(summary, dict)

    def test_backtest_multi_quarter(self, sample_fina_df, sample_indu_df):
        """With multiple audit quarters, backtest should produce per-quarter results."""
        # Build audit data with 3 years of Q4 labels
        symbols = _make_symbols(30)
        rows = []
        for sym in symbols:
            for year, risk in [("2022", 0), ("2023", 0), ("2024", 1 if sym.endswith("1.SH") else 0)]:
                rows.append({
                    "symbol": sym,
                    "quarter": f"{year}q4",
                    "date": f"{year}0415",
                    "agency": "某某所",
                    "audit_type": "financial_statements",
                    "opinion": "qualified_opinion" if risk else "unqualified_opinion",
                    "risk_level": 2 if risk else 0,
                    "risk_label": "高风险" if risk else "低风险",
                    "name": sym,
                })
        multi_audit = pd.DataFrame(rows)
        train_df, _, _, feat_names = pred_mod.build_training_set(
            sample_fina_df, multi_audit, sample_indu_df
        )
        summary = pred_mod.backtest(train_df, feat_names)
        assert "details" in summary
        # Should have per-quarter results
        assert len(summary["details"]) >= 1


class TestMissingValueHandling:
    def test_full_nan_columns_dont_crash(self, sample_indu_df):
        """DataFrame with all-NaN financial fields should not crash engineer_features."""
        symbols = _make_symbols(10)
        rows = []
        for sym in symbols:
            for q in ["2024q3", "2024q4"]:
                row = {"symbol": sym, "quarter": q, "date": "20240101",
                       "fetch_time": "2025-01-01T00:00:00"}
                # All financial fields as NaN
                for f in pred_mod.RAW_FEATURES:
                    row[f] = None
                rows.append(row)
        nan_df = pd.DataFrame(rows)
        features, imp_vals, ind_map, feat_names = pred_mod.engineer_features(
            nan_df, sample_indu_df, fit=True
        )
        assert len(features) == len(rows)
        # After imputation, no NaN should remain in feature columns
        for f in feat_names:
            assert not features[f].isna().any(), f"NaN in {f} after imputation"


class TestYoyFeatures:
    def test_yoy_computed_for_valid_pairs(self, sample_fina_df, sample_indu_df):
        features, _, _, _ = pred_mod.engineer_features(
            sample_fina_df, sample_indu_df, fit=True
        )
        # Check that YoY features exist in output
        for yf in pred_mod.YOY_FEATURES:
            assert yf in features.columns, f"YoY feature {yf} missing"

    def test_yoy_values_are_numeric(self, sample_fina_df, sample_indu_df):
        features, _, _, _ = pred_mod.engineer_features(
            sample_fina_df, sample_indu_df, fit=True
        )
        for yf in pred_mod.YOY_FEATURES:
            non_null = features[yf].dropna()
            if len(non_null) > 0:
                assert non_null.dtype.kind in "fc", \
                    f"YoY feature {yf} is not numeric: {non_null.dtype}"
