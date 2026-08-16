"""
Acceptance gate and validation for Munger mental model analysis output.

Implements pre-deployment checks on analysis records:
- Record field completeness and value ranges
- Verdict enum correctness
- Data-gap marker presence
- One-vote veto logic enforcement

Pure assert-based testing; no external dependencies beyond standard library + pandas/numpy.
"""

from __future__ import annotations

from datetime import datetime

import config
import data
import analyze


def check_record_fields(rec: dict) -> None:
    """
    Assert all required fields are present with valid ranges.

    Checks:
    - All spec §6 fields present (symbol, trade_date, dim_scores, dim_passed,
      sub_scores, veto_flags, data_flags, radar_scores, high_confidence, verdict,
      data_version, update_time)
    - data_version == "real-v1"
    - verdict is in frozenset {"pass", "fail", "veto", "insufficient_data"}
    - dim_scores all in [0, 100]
    - radar_scores length == 5
    - radar_scores all in [0, 100]
    - high_confidence is bool
    - dim_passed values are bool or None

    Args:
        rec: Analysis record dict

    Raises:
        AssertionError: If any check fails
    """
    # Check required fields
    required_fields = [
        "symbol",
        "trade_date",
        "dim_scores",
        "dim_passed",
        "sub_scores",
        "veto_flags",
        "data_flags",
        "radar_scores",
        "high_confidence",
        "verdict",
        "data_version",
        "update_time",
    ]
    for field in required_fields:
        assert field in rec, f"Missing required field: {field}"

    # Check data_version
    assert rec["data_version"] == config.DATA_VERSION, (
        f"data_version mismatch: expected {config.DATA_VERSION}, got {rec['data_version']}"
    )

    # Check verdict enum
    assert rec["verdict"] in config.VERDICTS, (
        f"verdict not in enum: {rec['verdict']} not in {config.VERDICTS}"
    )

    # Check dim_scores range and keys
    assert isinstance(rec["dim_scores"], dict), "dim_scores must be a dict"
    for key in config.DIM_KEYS:
        assert key in rec["dim_scores"], f"Missing dim_scores key: {key}"
        score = rec["dim_scores"][key]
        assert isinstance(score, (int, float)), f"dim_scores[{key}] must be numeric"
        assert 0 <= score <= 100, f"dim_scores[{key}]={score} out of range [0, 100]"

    # Check dim_passed range and keys
    assert isinstance(rec["dim_passed"], dict), "dim_passed must be a dict"
    for key in config.DIM_KEYS:
        assert key in rec["dim_passed"], f"Missing dim_passed key: {key}"
        passed = rec["dim_passed"][key]
        assert passed is None or isinstance(passed, bool), (
            f"dim_passed[{key}] must be bool or None, got {type(passed)}"
        )

    # Check radar_scores
    assert isinstance(rec["radar_scores"], list), "radar_scores must be a list"
    assert len(rec["radar_scores"]) == 5, (
        f"radar_scores length must be 5, got {len(rec['radar_scores'])}"
    )
    for i, score in enumerate(rec["radar_scores"]):
        assert isinstance(score, (int, float)), f"radar_scores[{i}] must be numeric"
        assert 0 <= score <= 100, (
            f"radar_scores[{i}]={score} out of range [0, 100]"
        )

    # Check high_confidence is bool
    assert isinstance(rec["high_confidence"], bool), (
        f"high_confidence must be bool, got {type(rec['high_confidence'])}"
    )


def check_veto_forces_low_confidence() -> None:
    """
    Offline test: verify veto logic forces high_confidence=False.

    Creates a synthetic adverse audit record (nonstandard opinion) that triggers
    the veto mechanism in score_negative. Verifies that cross_validate() then
    returns high_confidence=False with verdict="veto".

    This test requires NO credentials—uses only in-memory data.

    Raises:
        AssertionError: If veto logic does not force high_confidence=False
    """
    import pandas as pd
    from dimensions import score_negative

    # Create synthetic adverse audit that triggers veto
    # Non-standard opinion triggers veto
    adverse_audit = pd.DataFrame({
        "opinion": ["qualified_opinion"],  # Not in standard opinions
        "agency": ["Agency A"],
        "quarter": ["2025q4"],
        "date": [pd.Timestamp("2026-03-31")],
    })

    # Empty others (no veto)
    empty_status = pd.DataFrame()
    empty_pledge = pd.DataFrame()
    empty_sh_change = pd.DataFrame()

    # Score negative dimension—should trigger veto
    dims_neg = score_negative(adverse_audit, empty_status, empty_pledge, empty_sh_change)

    # Verify veto flag is set
    assert dims_neg["veto"] is True, "Veto not triggered by nonstandard audit"
    assert dims_neg["passed"] is False, "passed should be False on veto"

    # Now test cross_validate logic
    dims = {
        "fin": {"score": 100.0, "passed": True, "veto": False, "flags": [], "sub_scores": {}},
        "comp": {"score": 100.0, "passed": True, "veto": False, "flags": [], "sub_scores": {}},
        "incentive": {"score": 100.0, "passed": True, "veto": False, "flags": [], "sub_scores": {}},
        "psych": {"score": 100.0, "passed": True, "veto": False, "flags": [], "sub_scores": {}},
        "neg": dims_neg,  # Has veto=True
    }

    xval = analyze.cross_validate(dims)

    # Verify cross_validate returns veto verdict with high_confidence=False
    assert xval["verdict"] == "veto", f"Expected verdict='veto', got {xval['verdict']}"
    assert xval["high_confidence"] is False, (
        f"Expected high_confidence=False on veto, got {xval['high_confidence']}"
    )


def check_data_gap_markers(rec: dict) -> None:
    """
    Assert all three data-gap markers are present in data_flags.

    Checks that these exact markers are in the data_flags list:
    - "related_party: data_unavailable"
    - "qa_sentiment: not_available"
    - "hostile_takeover: weak_proxy" (from neg dimension if controlling shareholder reduces)

    Note: hostile_takeover is only added if shareholder reduction occurred.
    At minimum, related_party and qa_sentiment must always be present.

    Args:
        rec: Analysis record dict

    Raises:
        AssertionError: If required markers missing
    """
    data_flags = rec.get("data_flags", [])

    assert "related_party: data_unavailable" in data_flags, (
        "Missing required marker: 'related_party: data_unavailable'"
    )
    assert "qa_sentiment: not_available" in data_flags, (
        "Missing required marker: 'qa_sentiment: not_available'"
    )


if __name__ == "__main__":
    print("Running validation checks...")

    # Initialize credentials and session
    print("  Initializing panda_data session...")
    data.init()

    # Analyze 000001.SZ with current date
    symbol = "000001.SZ"
    update_time = datetime.now().isoformat(sep=" ", timespec="seconds")
    print(f"  Analyzing {symbol}...")
    rec = analyze.analyze_symbol(symbol, None, update_time)

    # Run checks
    print("  Checking record fields...")
    check_record_fields(rec)

    print("  Checking veto logic...")
    check_veto_forces_low_confidence()

    print("  Checking data-gap markers...")
    check_data_gap_markers(rec)

    # Success message in Chinese per spec
    print("验证通过：字段完整、取值范围合法、verdict 枚举合法、一票否决生效、数据缺口标记就位")
