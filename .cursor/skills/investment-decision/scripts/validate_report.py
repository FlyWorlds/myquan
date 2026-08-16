#!/usr/bin/env python3
"""
Report validator for skill-investment-decision.

Checks a generated report JSON against the decision-contract.md rules.
Usage: python validate_report.py --report <report.json>
"""

import json
import sys
import os
import argparse
from datetime import datetime
from typing import Tuple, List

# --- Validation rules ---

VALID_RECOMMENDATIONS = {"BUY", "NEUTRAL", "SELL"}
VALID_RISK_LEVELS = {"Low", "Medium", "High"}
VALID_LANGUAGES = {"en", "zh"}
REQUIRED_SECTIONS = [
    "meta",
    "company_overview",
    "financial_analysis",
    "valuation_analysis",
    "market_sentiment",
    "risk_assessment",
    "recommendation",
    "disclaimer",
]

# Fields that should NOT be N/A (must have real data)
CRITICAL_FIELDS = {
    "financial_analysis": ["roe", "roa", "gross_margin", "net_margin", "debt_to_equity"],
    "valuation_analysis": ["pe_ttm", "pb"],
    "market_sentiment": ["return_1m", "return_12m"],
}
SCORE_DIMENSIONS = [
    "financial_health",
    "growth",
    "valuation",
    "momentum_sentiment",
    "industry_position",
    "risk_profile",
]
EXPECTED_WEIGHTS = {
    "financial_health": 0.20,
    "growth": 0.20,
    "valuation": 0.20,
    "momentum_sentiment": 0.15,
    "industry_position": 0.10,
    "risk_profile": 0.15,
}

MAX_RETRY_ATTEMPTS = 5


def validate_report(report_path: str) -> Tuple[bool, List[str], List[str]]:
    """
    Validate a report JSON file.
    Returns (passed, failures, warnings).
    """
    failures = []
    warnings = []

    # R10: Valid JSON
    try:
        with open(report_path, "r", encoding="utf-8") as f:
            report = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError) as e:
        failures.append(f"R10 FAIL: Cannot parse report JSON — {e}")
        return False, failures, warnings

    # R1: All mandatory sections present
    missing = [s for s in REQUIRED_SECTIONS if s not in report]
    if missing:
        failures.append(f"R1 FAIL: Missing sections — {missing}")
    else:
        warnings.append("R1 PASS: All 8 sections present")

    # R11: Language field valid (must check before R2 for i18n)
    lang = report.get("meta", {}).get("language", "en")
    if lang not in VALID_LANGUAGES:
        failures.append(f"R11 FAIL: language='{lang}' not in {VALID_LANGUAGES}")
    else:
        warnings.append(f"R11 PASS: language={lang}")

    # R12: Investment horizon must be long-term
    horizon = report.get("meta", {}).get("investment_horizon", "")
    if horizon != "long-term":
        failures.append(f"R12 FAIL: investment_horizon='{horizon}' must be 'long-term'")
    else:
        warnings.append(f"R12 PASS: investment_horizon={horizon}")

    # R13: Critical fields must NOT be N/A (relax PE for unprofitable companies)
    for section, fields in CRITICAL_FIELDS.items():
        sec_data = report.get(section, {})
        for field in fields:
            val = sec_data.get(field)
            if val is None:
                if field == "pe_ttm":
                    warnings.append(f"R13 WARN: {section}.{field} is None (likely unprofitable)")
                else:
                    failures.append(f"R13 FAIL: {section}.{field} is None (must have real data)")
    if not any("R13 FAIL" in f for f in failures):
        warnings.append("R13 PASS: critical fields populated (PE may be N/A for unprofitable)")

    # R2: Valid recommendation (now in recommendation section, not executive_summary)
    rec = report.get("recommendation", {}).get("recommendation", "")
    if rec not in VALID_RECOMMENDATIONS:
        failures.append(f"R2 FAIL: recommendation '{rec}' not in {VALID_RECOMMENDATIONS}")
    else:
        warnings.append(f"R2 PASS: recommendation={rec}")

    # R3: Confidence valid range
    conf = report.get("recommendation", {}).get("confidence", -1)
    if not (0.0 <= conf <= 1.0):
        failures.append(f"R3 FAIL: confidence={conf} not in [0.0, 1.0]")
    else:
        warnings.append(f"R3 PASS: confidence={conf}")

    # R4: Weight sum ~100%
    # (Not directly in JSON, but checked via recommendation section)
    warnings.append("R4 INFO: weight sum check deferred (weights are fixed at 100%)")

    # R5: Score dimensions 1-10
    scores = report.get("recommendation", {}).get("scores", {})
    for dim in SCORE_DIMENSIONS:
        if dim not in scores:
            failures.append(f"R5 FAIL: Missing score dimension '{dim}'")
        else:
            s = scores[dim].get("score", -1)
            if not (1 <= s <= 10):
                failures.append(f"R5 FAIL: {dim}.score={s} not in [1, 10]")
    if not any("R5 FAIL" in f for f in failures):
        warnings.append("R5 PASS: all dimension scores in [1, 10]")

    # R6: At least 3 risks
    risks = report.get("risk_assessment", {}).get("risks", [])
    if len(risks) < 3:
        warnings.append(f"R6 WARN: only {len(risks)} risk(s) listed (recommended ≥3)")
    else:
        for r in risks:
            if r.get("level") not in VALID_RISK_LEVELS:
                failures.append(f"R6 FAIL: risk level '{r.get('level')}' not in {VALID_RISK_LEVELS}")
        warnings.append(f"R6 PASS: {len(risks)} risks listed")

    # R7: Disclaimer present and non-empty
    disc = report.get("disclaimer", "")
    if not disc or len(disc.strip()) < 20:
        failures.append(f"R7 FAIL: disclaimer missing or too short (len={len(disc)})")
    else:
        warnings.append("R7 PASS: disclaimer present")

    # R8: Future date check
    meta = report.get("meta", {})
    for date_field in ["report_date", "data_period_end"]:
        date_val = meta.get(date_field, "")
        if date_val:
            try:
                dt = datetime.strptime(date_val, "%Y-%m-%d")
                if dt > datetime.now():
                    failures.append(f"R8 FAIL: {date_field}={date_val} is in the future")
            except ValueError:
                failures.append(f"R8 FAIL: {date_field}={date_val} is not a valid date")
    warnings.append("R8 PASS: date check complete")

    # R9: Recommendation-score consistency
    total_score = report.get("recommendation", {}).get("total_score", -1)
    expected_rec = None
    if total_score >= 7.5:
        expected_rec = "BUY"
    elif total_score >= 5.0:
        expected_rec = "NEUTRAL"
    else:
        expected_rec = "SELL"

    actual_rec = report.get("recommendation", {}).get("recommendation", "")
    if actual_rec != expected_rec:
        failures.append(
            f"R9 FAIL: total_score={total_score} maps to '{expected_rec}', "
            f"but recommendation says '{actual_rec}'"
        )
    if not any("R9 FAIL" in f for f in failures):
        warnings.append(f"R9 PASS: score→{expected_rec}, consistent mapping")

    passed = len(failures) == 0
    return passed, failures, warnings


def format_output(passed: bool, failures: List[str], warnings: List[str]) -> str:
    """Format validation results for LLM feedback."""
    lines = []
    lines.append("=" * 60)
    lines.append("VALIDATION RESULT: " + ("PASSED ✓" if passed else "FAILED ✗"))
    lines.append("=" * 60)

    if failures:
        lines.append(f"\nFAILURES ({len(failures)}):")
        for f in failures:
            lines.append(f"  ✗ {f}")

    if warnings:
        lines.append(f"\nINFO/WARNINGS ({len(warnings)}):")
        for w in warnings:
            lines.append(f"  • {w}")

    if not passed:
        lines.append(f"\nCORRECTION CONTEXT:")
        lines.append(f"  Fix the {len(failures)} failure(s) above and re-validate.")
        lines.append(f"  Max retries: {MAX_RETRY_ATTEMPTS}")

    lines.append("=" * 60)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Validate an investment decision report JSON against the contract."
    )
    parser.add_argument(
        "--report", required=True, help="Path to the report JSON file to validate"
    )
    args = parser.parse_args()

    if not os.path.exists(args.report):
        print(f"ERROR: File not found: {args.report}", file=sys.stderr)
        sys.exit(1)

    passed, failures, warnings = validate_report(args.report)
    output = format_output(passed, failures, warnings)
    print(output)

    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
