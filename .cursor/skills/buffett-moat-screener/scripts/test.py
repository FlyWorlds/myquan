"""Run self-contained BUILD checks and the full repository suite when present."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.core import DATA_VERSION, InputValidationError
from scripts.soft_scorer import score_payload
from scripts.validation import validate_input, validate_production


def _contract_checks() -> None:
    validate_input({"as_of_date": "20260724", "symbols": ["600519.SH"]})
    for invalid in ({}, {"as_of_date": "20260724", "symbols": []}, {"as_of_date": "2026-07-24"}):
        try:
            validate_input(invalid)
        except InputValidationError:
            pass
        else:
            raise AssertionError(f"invalid input was accepted: {invalid!r}")

    metrics = {
        "roe_mean_pct": 18.0,
        "gross_margin_mean_5y_pct": 50.0,
        "gross_margin_std_5y_pct_points": 0.0,
        "capex_to_profit_5y": 0.10,
        "operating_margin_mean_5y_pct": 25.0,
        "current_pe": 10.0,
        "roa_median_pct": 1.2,
        "roa_floor_pct": 1.0,
        "pb": 0.6,
    }
    ordinary = score_payload({"target_id": "600519.SH", "metrics": metrics})
    assert ordinary["total_score"] == 100.0
    bank = score_payload({"target_id": "600036.SH", "special_case": "bank_roa", "metrics": metrics})
    gross = next(row for row in bank["dimensions"] if row["name"] == "gross_margin")
    assert gross["applicable"] is False and gross["score"] is None and gross["effective_weight"] == 0.0

    production = ROOT / "生产产物" / "数据库.parquet"
    if production.exists():
        validation = validate_production(production)
        assert validation["data_version"] == DATA_VERSION


def main() -> int:
    _contract_checks()
    tests = ROOT / "tests"
    if tests.is_dir():
        return subprocess.call([sys.executable, "-m", "pytest", "-q", "tests"], cwd=ROOT)
    print("BUILD contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
