"""Tests for classification rules (scripts/rules.py)."""

import pandas as pd
import pytest

from scripts.rules import (
    RISK_LOW, RISK_MEDIUM, RISK_HIGH, RISK_CRITICAL, RISK_UNKNOWN,
    classify_opinion, classify_audit_type, get_risk_label,
    summarize, get_unknown_opinion_values,
)


class TestClassifyOpinion:
    def test_unqualified_is_low(self):
        assert classify_opinion("unqualified_opinion") == RISK_LOW

    def test_no_audit_is_unknown(self):
        assert classify_opinion("no_audit_performed") == RISK_UNKNOWN

    def test_empty_returns_unknown(self):
        assert classify_opinion("") == RISK_UNKNOWN

    def test_none_returns_unknown(self):
        assert classify_opinion(None) == RISK_UNKNOWN

    def test_non_string_returns_unknown(self):
        assert classify_opinion(123) == RISK_UNKNOWN

    def test_case_insensitive(self):
        assert classify_opinion("UNQUALIFIED_OPINION") == RISK_LOW

    def test_unknown_value_returns_unknown(self):
        assert classify_opinion("some_future_opinion_type") == RISK_UNKNOWN

    def test_whitespace_only_returns_unknown(self):
        assert classify_opinion("   ") == RISK_UNKNOWN


class TestClassifyAuditType:
    def test_financial_statements_true(self):
        assert classify_audit_type("financial_statements") is True

    def test_internal_control_false(self):
        assert classify_audit_type("internal_control") is False

    def test_non_string_false(self):
        assert classify_audit_type(None) is False

    def test_case_insensitive(self):
        assert classify_audit_type("Financial_Statements") is True


class TestRiskLabel:
    def test_all_levels_have_label(self):
        for level in [RISK_LOW, RISK_MEDIUM, RISK_HIGH, RISK_CRITICAL, RISK_UNKNOWN]:
            label = get_risk_label(level)
            assert isinstance(label, str)
            assert len(label) > 0

    def test_unknown_level_returns_generic(self):
        assert get_risk_label(999) == "未知"


class TestSummarize:
    def test_empty_df(self):
        df = pd.DataFrame({"risk_level": pd.Series([], dtype=int), "opinion": pd.Series([], dtype=str)})
        s = summarize(df)
        assert s["total"] == 0
        assert s["low"] == 0
        assert s["high"] == 0

    def test_mixed_risks(self,):
        df = pd.DataFrame({
            "risk_level": [RISK_LOW, RISK_LOW, RISK_HIGH, RISK_CRITICAL, RISK_UNKNOWN],
            "opinion": ["unqualified_opinion", "unqualified_opinion",
                         "qualified_opinion", "adverse_opinion", "weird_value"],
        })
        s = summarize(df)
        assert s["total"] == 5
        assert s["low"] == 2
        assert s["high"] == 1
        assert s["critical"] == 1
        assert s["unknown"] == 1
        assert "weird_value" in s["unknown_opinions"]


class TestGetUnknownOpinionValues:
    def test_all_known(self):
        series = pd.Series(["unqualified_opinion", "no_audit_performed"])
        unknown = get_unknown_opinion_values(series)
        assert len(unknown) == 0

    def test_mixed(self):
        series = pd.Series(["unqualified_opinion", "brand_new_type", "no_audit_performed"])
        unknown = get_unknown_opinion_values(series)
        assert "brand_new_type" in unknown
        assert "unqualified_opinion" not in unknown

    def test_case_normalized(self):
        series = pd.Series(["UNQUALIFIED_OPINION", "Unqualified_Opinion"])
        unknown = get_unknown_opinion_values(series)
        assert len(unknown) == 0  # all normalize to lowercase known
