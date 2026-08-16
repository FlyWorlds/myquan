"""
Tests for analyze.py orchestration layer with cross-validation logic.

Covers cross_validate, build_record, analyze_symbol, and main CLI.
"""

from __future__ import annotations

import pytest

import config


# Helper functions from plan Step 1
def _dim(
    score: float = 50.0,
    passed: bool | None = True,
    veto: bool = False,
    flags: list[str] | None = None,
    sub_scores: dict | None = None,
) -> dict:
    """Build a dimension result dict for testing."""
    return {
        "score": score,
        "passed": passed,
        "veto": veto,
        "flags": flags or [],
        "sub_scores": sub_scores or {},
    }


def _dims(
    fin: dict | None = None,
    comp: dict | None = None,
    incentive: dict | None = None,
    psych: dict | None = None,
    neg: dict | None = None,
) -> dict:
    """Build a dims dict (mapping DIM_KEYS to dimension results)."""
    return {
        "fin": fin or _dim(),
        "comp": comp or _dim(),
        "incentive": incentive or _dim(),
        "psych": psych or _dim(),
        "neg": neg or _dim(),
    }


class TestCrossValidate:
    """Tests for cross_validate function."""

    def test_all_pass_high_confidence(self):
        """All five dims passed=True → verdict=pass, high_confidence=True."""
        from analyze import cross_validate

        dims = _dims(
            fin=_dim(passed=True),
            comp=_dim(passed=True),
            incentive=_dim(passed=True),
            psych=_dim(passed=True),
            neg=_dim(passed=True),
        )
        result = cross_validate(dims)
        assert result["verdict"] == "pass"
        assert result["high_confidence"] is True
        assert result["radar_scores"] == [50.0, 50.0, 50.0, 50.0, 50.0]

    def test_veto_overrides_everything(self):
        """neg.veto=True → verdict=veto, high_confidence=False."""
        from analyze import cross_validate

        dims = _dims(
            fin=_dim(passed=True),
            comp=_dim(passed=True),
            incentive=_dim(passed=True),
            psych=_dim(passed=True),
            neg=_dim(passed=True, veto=True),
        )
        result = cross_validate(dims)
        assert result["verdict"] == "veto"
        assert result["high_confidence"] is False

    def test_one_dim_fail_not_high_confidence(self):
        """One dim failed (passed=False) → verdict=fail, high_confidence=False."""
        from analyze import cross_validate

        dims = _dims(
            fin=_dim(passed=True),
            comp=_dim(passed=False),
            incentive=_dim(passed=True),
            psych=_dim(passed=True),
            neg=_dim(passed=True),
        )
        result = cross_validate(dims)
        assert result["verdict"] == "fail"
        assert result["high_confidence"] is False

    def test_insufficient_data(self):
        """One dim with passed=None → verdict=insufficient_data, high_confidence=False."""
        from analyze import cross_validate

        dims = _dims(
            fin=_dim(passed=None),
            comp=_dim(passed=True),
            incentive=_dim(passed=True),
            psych=_dim(passed=True),
            neg=_dim(passed=True),
        )
        result = cross_validate(dims)
        assert result["verdict"] == "insufficient_data"
        assert result["high_confidence"] is False


class TestBuildRecord:
    """Tests for build_record function."""

    def test_build_record_fields(self):
        """build_record assembles all required fields per spec §6."""
        from analyze import build_record

        dims = _dims(
            fin=_dim(score=75.0, passed=True, flags=["flag1"], sub_scores={"sub1": 0.8}),
            comp=_dim(score=65.0, passed=True, flags=[], sub_scores={}),
            incentive=_dim(score=70.0, passed=True, flags=["flag2"], sub_scores={}),
            psych=_dim(score=55.0, passed=False, flags=[], sub_scores={}),
            neg=_dim(score=100.0, passed=True, veto=False, flags=[], sub_scores={}),
        )

        record = build_record(
            symbol="000001.SZ",
            trade_date="2026-06-30",
            dims=dims,
            update_time="2026-07-10 12:00:00",
        )

        # Check required spec §6 fields
        assert record["symbol"] == "000001.SZ"
        assert record["trade_date"] == "2026-06-30"
        assert isinstance(record["dim_scores"], dict)
        assert isinstance(record["dim_passed"], dict)
        assert isinstance(record["sub_scores"], dict)
        assert isinstance(record["veto_flags"], list)
        assert isinstance(record["data_flags"], list)
        assert isinstance(record["radar_scores"], list)
        assert record["high_confidence"] is False
        assert record["verdict"] == "fail"
        assert record["data_version"] == "real-v1"
        assert record["update_time"] == "2026-07-10 12:00:00"

        # Check dim_scores mapping
        assert record["dim_scores"]["fin"] == 75.0
        assert record["dim_scores"]["comp"] == 65.0
        assert record["dim_scores"]["incentive"] == 70.0
        assert record["dim_scores"]["psych"] == 55.0
        assert record["dim_scores"]["neg"] == 100.0

        # Check radar_scores order
        assert record["radar_scores"] == [75.0, 65.0, 70.0, 55.0, 100.0]


def test_radar_writes_png(tmp_path):
    """render(record, out_path) writes PNG file with radar chart."""
    from radar import render

    record = {
        "radar_scores": [80, 70, 60, 50, 100],
        "symbol": "000001.SZ",
    }
    out_path = str(tmp_path / "test_radar.png")
    result = render(record, out_path)

    # Check return value is the path
    assert result == out_path

    # Check PNG file was created with non-zero size
    import os
    assert os.path.exists(out_path)
    assert os.path.getsize(out_path) > 0


class TestScoreIncentive:
    """Tests for score_incentive function with edge cases."""

    @staticmethod
    def _make_sh_change(nature_vals, net_changes, holder_types, ratios):
        """Build a sh_change DataFrame for testing."""
        import pandas as pd
        n = max(len(nature_vals), len(holder_types))
        data = {
            "nature": list(nature_vals) + [""] * (n - len(nature_vals)),
            "net_change": list(net_changes) + [0.0] * (n - len(net_changes)),
            "holder_type": list(holder_types) + [""] * (n - len(holder_types)),
            "ratio_up_limit": list(ratios) + [0.0] * (n - len(ratios)),
        }
        return pd.DataFrame(data)

    @staticmethod
    def _make_pledge(ratios):
        """Build a pledge DataFrame for testing."""
        import pandas as pd
        return pd.DataFrame({"pledge_ratio": list(ratios)})

    def test_all_neutral_defaults(self):
        """Empty data → all signals at 60 baseline → score = 60."""
        from dimensions import score_incentive
        import pandas as pd
        result = score_incentive(pd.DataFrame(), pd.DataFrame())
        assert result["score"] == 60.0
        assert result["sub_scores"]["mgmt_trade_score"] == 60.0
        assert result["sub_scores"]["pledge_score"] == 60.0
        assert result["sub_scores"]["controlling_trade_score"] == 60.0

    def test_management_buy(self):
        """Management net buy → mgmt = 100, others neutral → score > 60."""
        from dimensions import score_incentive
        import pandas as pd
        sh = self._make_sh_change(
            nature_vals=["管理层"], net_changes=[100000.0],
            holder_types=[""], ratios=[0.0],
        )
        result = score_incentive(sh, pd.DataFrame())
        assert result["sub_scores"]["mgmt_trade_score"] == 100.0
        # (100 + 60 + 60) / 3 = 73.33
        assert 73.0 <= result["score"] <= 74.0

    def test_management_sell(self):
        """Management net sell → mgmt = 20."""
        from dimensions import score_incentive
        import pandas as pd
        sh = self._make_sh_change(
            nature_vals=["管理层"], net_changes=[-50000.0],
            holder_types=[""], ratios=[0.0],
        )
        result = score_incentive(sh, pd.DataFrame())
        assert result["sub_scores"]["mgmt_trade_score"] == 20.0

    def test_controlling_increase(self):
        """Controlling shareholder net increase → 100."""
        from dimensions import score_incentive
        import pandas as pd
        sh = self._make_sh_change(
            nature_vals=[""], net_changes=[0.0],
            holder_types=["controlling"], ratios=[0.0],
        )
        # Override net_change for the controlling row
        sh.loc[0, "net_change"] = 200000.0
        result = score_incentive(sh, pd.DataFrame())
        assert result["sub_scores"]["controlling_trade_score"] == 100.0

    def test_controlling_neutral(self):
        """Controlling shareholder net_change == 0 → neutral 60 (was buggy)."""
        from dimensions import score_incentive
        import pandas as pd
        sh = self._make_sh_change(
            nature_vals=[""], net_changes=[0.0],
            holder_types=["controlling"], ratios=[0.005],  # ratio exists but net_change==0
        )
        result = score_incentive(sh, pd.DataFrame())
        # Bug fix: net_change == 0 should NOT trigger decrease logic
        assert result["sub_scores"]["controlling_trade_score"] == 60.0

    def test_controlling_small_decrease(self):
        """Controlling net decrease ≤ 2% → 40."""
        from dimensions import score_incentive
        import pandas as pd
        sh = self._make_sh_change(
            nature_vals=[""], net_changes=[-10000.0],
            holder_types=["controlling"], ratios=[0.01],
        )
        result = score_incentive(sh, pd.DataFrame())
        assert result["sub_scores"]["controlling_trade_score"] == 40.0

    def test_controlling_large_decrease(self):
        """Controlling net decrease > 2% → 20."""
        from dimensions import score_incentive
        import pandas as pd
        sh = self._make_sh_change(
            nature_vals=[""], net_changes=[-500000.0],
            holder_types=["controlling"], ratios=[0.05],
        )
        result = score_incentive(sh, pd.DataFrame())
        assert result["sub_scores"]["controlling_trade_score"] == 20.0

    def test_ratio_up_limit_percentage_form(self):
        """ratio_up_limit in percentage (e.g. 5.0 = 5%) → normalized correctly."""
        from dimensions import score_incentive
        import pandas as pd
        sh = self._make_sh_change(
            nature_vals=[""], net_changes=[-10000.0],
            holder_types=["controlling"], ratios=[5.0],  # percentage form: 5%
        )
        result = score_incentive(sh, pd.DataFrame())
        # 5% > 2% → large decrease → 20
        assert result["sub_scores"]["controlling_trade_score"] == 20.0

    def test_ratio_up_limit_decimal_form(self):
        """ratio_up_limit in decimal (e.g. 0.01 = 1%) → handled directly."""
        from dimensions import score_incentive
        import pandas as pd
        sh = self._make_sh_change(
            nature_vals=[""], net_changes=[-10000.0],
            holder_types=["controlling"], ratios=[0.01],  # decimal: 1%
        )
        result = score_incentive(sh, pd.DataFrame())
        # 1% ≤ 2% → small decrease → 40
        assert result["sub_scores"]["controlling_trade_score"] == 40.0

    def test_pledge_normal(self):
        """Pledge ratio 18.86% → score computed from formula."""
        from dimensions import score_incentive
        import pandas as pd
        pledge = self._make_pledge([18.86])  # percentage form
        result = score_incentive(pd.DataFrame(), pledge)
        # 60 + (1 - 0.1886/0.50) * 40 = 60 + 0.6228 * 40 = 84.91
        assert 84.0 <= result["sub_scores"]["pledge_score"] <= 86.0

    def test_pledge_multiple_rows_uses_max(self):
        """Multiple pledge rows → use max (consistent with score_negative)."""
        from dimensions import score_incentive
        import pandas as pd
        pledge = self._make_pledge([1.94, 18.86, 5.0])  # max = 18.86%
        result = score_incentive(pd.DataFrame(), pledge)
        # Should use 18.86 (max), not 1.94 (first row)
        assert 84.0 <= result["sub_scores"]["pledge_score"] <= 86.0

    def test_pledge_empty_defaults_neutral(self):
        """Empty pledge → score = 60 (neutral), not 100."""
        from dimensions import score_incentive
        import pandas as pd
        result = score_incentive(pd.DataFrame(), pd.DataFrame())
        assert result["sub_scores"]["pledge_score"] == 60.0
        # Verify data_unavailable flag
        assert "pledge: data_unavailable" in result["flags"]

    def test_controlling_mixed_buy_and_sell(self):
        """Multiple controlling rows: one buy + one sell → buy dominates."""
        from dimensions import score_incentive
        import pandas as pd
        sh = pd.DataFrame({
            "nature": ["", ""],
            "net_change": [50000.0, -20000.0],  # buy + sell
            "holder_type": ["controlling", "controlling"],
            "ratio_up_limit": [0.0, 0.05],
        })
        result = score_incentive(sh, pd.DataFrame())
        # has_inc=True → 100 (sum would have given 30000 which is also > 0,
        # but the per-row logic correctly identifies a buy exists)
        assert result["sub_scores"]["controlling_trade_score"] == 100.0

    def test_management_fallback_chinese_values(self):
        """Management detection via fallback Chinese values."""
        from dimensions import score_incentive
        import pandas as pd
        # Test with "高管" which is in the fallback set
        sh = self._make_sh_change(
            nature_vals=["高管"], net_changes=[100000.0],
            holder_types=[""], ratios=[0.0],
        )
        result = score_incentive(sh, pd.DataFrame())
        assert result["sub_scores"]["mgmt_trade_score"] == 100.0

    def test_controlling_fallback_chinese_values(self):
        """Controlling shareholder detection via fallback Chinese values."""
        from dimensions import score_incentive
        import pandas as pd
        sh = self._make_sh_change(
            nature_vals=[""], net_changes=[0.0],
            holder_types=["控股股东"], ratios=[0.0],
        )
        sh.loc[0, "net_change"] = 200000.0
        result = score_incentive(sh, pd.DataFrame())
        assert result["sub_scores"]["controlling_trade_score"] == 100.0
