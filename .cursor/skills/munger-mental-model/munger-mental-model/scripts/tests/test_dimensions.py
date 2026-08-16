"""
Tests for dimensions.py dimension scoring functions.
Verifies financial, competition, incentive, and psychology dimension scorers.
"""

from __future__ import annotations

import pytest
import pandas as pd
from datetime import datetime

import config
import dimensions


class TestScoreFinancial:
    """Tests for score_financial function."""

    def test_financial_all_above_median(self):
        """Financial: ROE, GM, OCF all above median → score 100, passed=True."""
        target = {"roe": 20.0, "gross_profit": 0.40, "ocf": 1_000_000}
        peers = pd.DataFrame({
            "roe": [15.0, 16.0, 17.0, 18.0, 19.0],
            "gross_profit": [0.35, 0.36, 0.37, 0.38, 0.39],
            "ocf": [500_000, 600_000, 700_000, 800_000, 900_000],
        })
        result = dimensions.score_financial(target, peers)
        assert result["score"] == 100.0
        assert result["passed"] is True
        assert "roe_vs_median" in result["sub_scores"]
        assert "gm_vs_median" in result["sub_scores"]
        assert "ocf_positive_and_vs_median" in result["sub_scores"]

    def test_financial_negative_ocf(self):
        """Financial: Negative OCF → ocf_positive_and_vs_median=0, score < 100."""
        target = {"roe": 20.0, "gross_profit": 0.40, "ocf": -100_000}
        peers = pd.DataFrame({
            "roe": [15.0, 16.0, 17.0, 18.0, 19.0],
            "gross_profit": [0.35, 0.36, 0.37, 0.38, 0.39],
            "ocf": [500_000, 600_000, 700_000, 800_000, 900_000],
        })
        result = dimensions.score_financial(target, peers)
        assert result["sub_scores"]["ocf_positive_and_vs_median"] == 0.0
        assert result["score"] < 100.0

    def test_financial_sub_scores_contain_raw_values(self):
        """Financial: sub_scores includes raw metric values and medians."""
        target = {"roe": 20.0, "gross_profit": 0.40, "ocf": 1_000_000}
        peers = pd.DataFrame({
            "roe": [15.0, 16.0, 17.0, 18.0, 19.0],
            "gross_profit": [0.35, 0.36, 0.37, 0.38, 0.39],
            "ocf": [500_000, 600_000, 700_000, 800_000, 900_000],
        })
        result = dimensions.score_financial(target, peers)
        ss = result["sub_scores"]

        assert ss["roe_value"] == 20.0
        assert ss["roe_median"] == 17.0
        assert ss["gm_value"] == 0.40
        assert ss["gm_median"] == 0.37
        assert ss["ocf_value"] == 1_000_000
        assert ss["ocf_median"] == 700_000


class TestScoreCompetition:
    """Tests for score_competition function."""

    def test_competition_low_confidence(self):
        """Competition: < 3 peers → low_confidence flag, passed=None (insufficient data)."""
        target = {"roe": 20.0, "gross_profit": 0.40}
        peers = pd.DataFrame({
            "roe": [15.0, 16.0],
            "gross_profit": [0.35, 0.36],
        })
        result = dimensions.score_competition(target, peers)
        assert any("low_confidence" in flag for flag in result["flags"])
        assert result["passed"] is None  # Insufficient data returns None

    def test_competition_sub_scores_contain_raw_values(self):
        """Competition: sub_scores includes raw metric values and peer counts."""
        target = {"roe": 20.0, "gross_profit": 0.40}
        peers = pd.DataFrame({
            "roe": [10.0, 12.0, 15.0, 18.0, 22.0],
            "gross_profit": [0.25, 0.30, 0.35, 0.38, 0.42],
        })
        result = dimensions.score_competition(target, peers)
        ss = result["sub_scores"]

        assert ss["roe_value"] == 20.0
        assert ss["gm_value"] == 0.40
        assert ss["peer_count"] == 5
        assert ss["valid_roe_count"] == 5
        assert ss["valid_gm_count"] == 5


class TestScoreIncentive:
    """Tests for score_incentive function (three-signal model, equal 1/3 weights, baseline 60)."""

    # --- helpers ---
    @staticmethod
    def _sh(nature_vals, net_changes, holder_types, ratios):
        """Build a minimal sh_change DataFrame."""
        n = max(len(nature_vals), len(holder_types))
        return pd.DataFrame({
            "nature": list(nature_vals) + [""] * (n - len(nature_vals)),
            "net_change": list(net_changes) + [0.0] * (n - len(net_changes)),
            "holder_type": list(holder_types) + [""] * (n - len(holder_types)),
            "ratio_up_limit": list(ratios) + [0.0] * (n - len(ratios)),
        })

    @staticmethod
    def _pledge(ratios):
        return pd.DataFrame({"pledge_ratio": list(ratios)})

    def test_all_data_unavailable_defaults_60(self):
        """Empty data → all three signals at baseline 60 → score = 60."""
        result = dimensions.score_incentive(pd.DataFrame(), pd.DataFrame())
        assert result["score"] == 60.0
        assert result["passed"] is True
        assert result["sub_scores"]["mgmt_trade_score"] == 60.0
        assert result["sub_scores"]["pledge_score"] == 60.0
        assert result["sub_scores"]["controlling_trade_score"] == 60.0

    def test_mgmt_buy_pledge_zero_controlling_no_data(self):
        """Management net buy (+100), 0% pledge (+100), no controlling data (+60) → (100+100+60)/3 = 86.67."""
        sh = self._sh(
            nature_vals=["管理层"], net_changes=[50_000],
            holder_types=[""], ratios=[0.0],
        )
        pledge = self._pledge([0.0])
        result = dimensions.score_incentive(sh, pledge)

        assert result["sub_scores"]["mgmt_trade_score"] == 100.0
        assert result["sub_scores"]["pledge_score"] == 100.0
        assert result["sub_scores"]["controlling_trade_score"] == 60.0
        assert abs(result["score"] - 86.67) < 0.05
        assert result["passed"] is True

    def test_high_pledge_penalty(self):
        """Pledge ratio 40% (percentage form) → score = 60 + (1-0.40/0.50)*40 = 28."""
        pledge = self._pledge([40.0])
        result = dimensions.score_incentive(pd.DataFrame(), pledge)
        # 60 + (1 - 0.40/0.50) * 40 = 60 + 0.20 * 40 = 68
        # Wait: 40% decimal = 0.40, 0.40/0.50 = 0.80, 1-0.80 = 0.20, 0.20*40 = 8, 60+8 = 68
        assert abs(result["sub_scores"]["pledge_score"] - 68.0) < 0.01

    def test_mgmt_sell(self):
        """Management net sell → mgmt_trade_score = 20."""
        sh = self._sh(
            nature_vals=["管理层", "管理层"], net_changes=[-100_000, -50_000],
            holder_types=["", ""], ratios=[0.0, 0.0],
        )
        result = dimensions.score_incentive(sh, pd.DataFrame())
        assert result["sub_scores"]["mgmt_trade_score"] == 20.0

    def test_controlling_shareholder_decrease_small(self):
        """Controlling net decrease ≤ 2% (ratio_up_limit=0.01) → 40."""
        sh = self._sh(
            nature_vals=[""], net_changes=[-100_000],
            holder_types=["controlling"], ratios=[0.01],
        )
        result = dimensions.score_incentive(sh, pd.DataFrame())
        assert result["sub_scores"]["controlling_trade_score"] == 40.0

    def test_controlling_shareholder_increase(self):
        """Controlling net increase → 100."""
        sh = self._sh(
            nature_vals=[""], net_changes=[200_000],
            holder_types=["controlling"], ratios=[0.0],
        )
        result = dimensions.score_incentive(sh, pd.DataFrame())
        assert result["sub_scores"]["controlling_trade_score"] == 100.0


class TestScorePsychology:
    """Tests for score_psychology function."""

    def test_psychology_qa_sentiment_flag(self):
        """Psychology: Always includes 'qa_sentiment: not_available' flag."""
        activity = pd.DataFrame({
            "activity_date": [
                "2025-01-01", "2025-02-01", "2025-03-01",
                "2025-04-01", "2025-05-01", "2025-06-01",
            ],
            "num_investors": [10, 12, 15, 11, 13, 14],
            "num_institutes": [5, 6, 7, 6, 7, 8],
        })
        result = dimensions.score_psychology(activity)
        assert "qa_sentiment: not_available" in result["flags"]

    def test_psychology_empty_activity(self):
        """Psychology: Empty activity DataFrame → score 0."""
        activity = pd.DataFrame({
            "activity_date": [],
            "num_investors": [],
            "num_institutes": [],
        })
        result = dimensions.score_psychology(activity)
        assert result["score"] == 0.0


def _clean_audit() -> pd.DataFrame:
    """Helper: Return a standard audit opinion row."""
    return pd.DataFrame({
        "opinion": ["unqualified_opinion"],
        "audit_agency": ["Agency A"],
        "audit_date": ["2025-06-30"],
        "agency": ["Agency A"],
        "date": ["2025-06-30"],
        "quarter": ["2024q4"],
    })


def _empty(cols: list[str]) -> pd.DataFrame:
    """Helper: Return an empty DataFrame with given columns."""
    return pd.DataFrame({col: [] for col in cols})


class TestScoreNegative:
    """Tests for score_negative function."""

    def test_negative_clean_pass(self):
        """Negative: clean audit + no status/pledge/agency switch → passed=True, veto=False."""
        audit = _clean_audit()
        status = _empty(["status", "change_date"])
        pledge = pd.DataFrame({
            "pledge_ratio": [10.0],  # 10% in percentage form
        })
        sh_change = pd.DataFrame({
            "holder_type": ["controlling"],
            "ratio_up_limit": [0.01],
        })

        result = dimensions.score_negative(audit, status, pledge, sh_change)

        assert result["score"] == 100.0
        assert result["passed"] is True
        assert result["veto"] is False
        assert result["veto_flags"] == []
        assert result["flags"] == []
        assert result["sub_scores"]["veto_count"] == 0

    def test_negative_nonstandard_audit_veto(self):
        """Negative: nonstandard audit opinion → veto."""
        audit = pd.DataFrame({
            "opinion": ["qualified_opinion"],
            "audit_agency": ["Agency A"],
            "audit_date": ["2025-06-30"],
            "agency": ["Agency A"],
            "date": ["2025-06-30"],
            "quarter": ["2024q4"],
        })
        status = _empty(["status", "change_date"])
        pledge = _empty(["pledge_ratio"])
        sh_change = _empty(["holder_type", "ratio_up_limit"])

        result = dimensions.score_negative(audit, status, pledge, sh_change)

        assert result["score"] == 0.0
        assert result["passed"] is False
        assert result["veto"] is True
        assert "nonstandard_audit:qualified_opinion" in result["veto_flags"]

    def test_negative_agency_switch_veto(self):
        """Negative: switch to unknown/small audit agency (not reputable) → veto with agency_switch_to_unknown flag."""
        audit = pd.DataFrame({
            "opinion": ["unqualified_opinion", "unqualified_opinion"],
            "audit_agency": ["Agency A", "Agency B"],
            "audit_date": ["2025-06-30", "2024-06-30"],
            "agency": ["Agency A", "Agency B"],
            "date": ["2025-06-30", "2024-06-30"],
            "quarter": ["2024q4", "2023q4"],
        })
        status = _empty(["status", "change_date"])
        pledge = _empty(["pledge_ratio"])
        sh_change = _empty(["holder_type", "ratio_up_limit"])

        result = dimensions.score_negative(audit, status, pledge, sh_change)

        assert result["score"] == 0.0
        assert result["passed"] is False
        assert result["veto"] is True
        assert "agency_switch_to_unknown" in result["veto_flags"]

    def test_negative_reputable_agency_rotation_no_veto(self):
        """Negative: switch between reputable agencies (normal rotation) → NO veto, only info flag."""
        audit = pd.DataFrame({
            "opinion": ["unqualified_opinion", "unqualified_opinion", "unqualified_opinion"],
            "audit_agency": ["信永中和会计师事务所", "信永中和会计师事务所", "天健会计师事务所"],
            "agency": ["信永中和会计师事务所", "信永中和会计师事务所", "天健会计师事务所"],
            "audit_date": ["2023-04-20", "2024-04-18", "2025-04-15"],
            "date": ["2023-04-20", "2024-04-18", "2025-04-15"],
            "quarter": ["2022q4", "2023q4", "2024q4"],
        })
        status = _empty(["status", "change_date"])
        pledge = _empty(["pledge_ratio"])
        sh_change = _empty(["holder_type", "ratio_up_limit"])

        result = dimensions.score_negative(audit, status, pledge, sh_change)

        assert result["veto"] is False
        assert result["passed"] is True
        assert result["score"] == 100.0
        assert "agency_switch:normal_rotation" in result["flags"]
        assert all("agency_switch" not in vf for vf in result["veto_flags"])

    def test_negative_status_change_veto(self):
        """Negative: status row present (ST or delisting) → veto."""
        audit = _clean_audit()
        status = pd.DataFrame({
            "status": ["ST"],
            "change_date": ["2025-06-30"],
        })
        pledge = _empty(["pledge_ratio"])
        sh_change = _empty(["holder_type", "ratio_up_limit"])

        result = dimensions.score_negative(audit, status, pledge, sh_change)

        assert result["score"] == 0.0
        assert result["passed"] is False
        assert result["veto"] is True
        assert "status_change:ST_or_delisting" in result["veto_flags"]

    def test_negative_high_pledge_veto(self):
        """Negative: max pledge_ratio > 50% (threshold) → veto."""
        audit = _clean_audit()
        status = _empty(["status", "change_date"])
        pledge = pd.DataFrame({
            "pledge_ratio": [60.0],  # 60% in percentage form, > 50% threshold
        })
        sh_change = _empty(["holder_type", "ratio_up_limit"])

        result = dimensions.score_negative(audit, status, pledge, sh_change)

        assert result["score"] == 0.0
        assert result["passed"] is False
        assert result["veto"] is True
        assert "high_pledge" in result["veto_flags"]

    def test_negative_large_controlling_sell_veto(self):
        """Negative: controlling shareholder 减持 with ratio_up_limit > 0.02 → veto + hostile_takeover flag."""
        audit = _clean_audit()
        status = _empty(["status", "change_date"])
        pledge = _empty(["pledge_ratio"])
        sh_change = pd.DataFrame({
            "holder_type": ["controlling"],
            "ratio_up_limit": [0.03],
        })

        result = dimensions.score_negative(audit, status, pledge, sh_change)

        assert result["score"] == 0.0
        assert result["passed"] is False
        assert result["veto"] is True
        assert "large_controlling_sell" in result["veto_flags"]
        assert "hostile_takeover: weak_proxy" in result["flags"]
