from __future__ import annotations

import argparse
import csv
import json
import math
import re
from datetime import datetime
from pathlib import Path


_INPUT_ISSUES: list[dict[str, object]] = []


def _demo_rows(demo_rows: list[dict[str, object]]) -> list[dict[str, str]]:
    return [{k: str(v) for k, v in row.items()} for row in demo_rows]


def load_rows(path: str | None, demo_rows: list[dict[str, object]]) -> list[dict[str, str]]:
    _INPUT_ISSUES.clear()
    if path is None:
        return _demo_rows(demo_rows)
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    required = set(globals().get("REQUIRED_COLUMNS", set(demo_rows[0]) if demo_rows else set()))
    numeric_columns = set(globals().get("NUMERIC_COLUMNS", set()))
    optional_numeric = set(globals().get("OPTIONAL_NUMERIC_COLUMNS", set()))
    actual = set(rows[0]) if rows else set()
    missing = sorted(required - actual)
    if not rows:
        _INPUT_ISSUES.append({"reason": "empty_input", "required_columns": sorted(required)})
    if missing:
        _INPUT_ISSUES.append({"reason": "missing_columns", "columns": missing})
    for row_number, row in enumerate(rows, 2):
        for key in numeric_columns:
            value = row.get(key)
            if value in (None, "") and key in optional_numeric:
                continue
            try:
                parsed = float(value) if value not in (None, "") else math.nan
            except (TypeError, ValueError):
                parsed = math.nan
            if not math.isfinite(parsed):
                _INPUT_ISSUES.append({"reason": "invalid_numeric", "row": row_number, "column": key, "value": value})
    if _INPUT_ISSUES:
        return _demo_rows(demo_rows)
    return rows


def number(value: object, default: float = 0.0) -> float:
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else default
    except (TypeError, ValueError):
        return default


def _normalize_finding(item: object, index: int, source: str) -> dict[str, object]:
    if isinstance(item, dict):
        evidence = item.get("evidence", item)
        severity = item.get("severity", "medium")
        finding_id = item.get("id", f"{source}-{index}")
        impact = item.get("impact", "Review the domain result and confirm whether the issue changes the research conclusion.")
        recommended_fix = item.get("recommended_fix", "Inspect the cited record, correct the input or assumptions, and rerun the check.")
    else:
        evidence = item
        severity = "medium"
        finding_id = f"{source}-{index}"
        impact = "The detected condition may affect the reliability of the quantitative result."
        recommended_fix = "Review the condition, document the decision, and rerun after correction when applicable."
    return {
        "id": finding_id,
        "severity": severity,
        "evidence": evidence,
        "impact": impact,
        "recommended_fix": recommended_fix,
    }


def _json_safe(value: object) -> object:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    return value


def build_report(result: dict[str, object]) -> dict[str, object]:
    evidence_issues = list(_INPUT_ISSUES)
    parameter_errors = result.get("_parameter_errors", [])
    if parameter_errors:
        evidence_issues.extend(parameter_errors if isinstance(parameter_errors, list) else [parameter_errors])

    issue_keys = ("findings", "violations", "warnings", "flags", "timing_findings")
    findings: list[dict[str, object]] = []
    if evidence_issues:
        findings.extend(_normalize_finding(item, index, "insufficient-evidence") for index, item in enumerate(evidence_issues, 1))
    else:
        for key in issue_keys:
            value = result.get(key)
            if value in (None, "", [], {}):
                continue
            values = value if isinstance(value, list) else [value]
            findings.extend(_normalize_finding(item, index, key) for index, item in enumerate(values, 1))
    passed = result.get("passed")
    if evidence_issues:
        status = "insufficient-evidence"
    elif passed is False:
        status = "fail"
    elif findings:
        status = "warning"
    else:
        status = "pass"

    count_keys = ("rows", "records", "orders", "events", "quotes", "symbols", "simulations", "baseline_count", "current_count")
    input_summary = {key: result[key] for key in count_keys if key in result}
    metrics = {
        key: value for key, value in result.items()
        if not key.startswith("_") and not isinstance(value, (list, dict)) and key != "passed"
    }
    domain_result: dict[str, object] = {"analysis_skipped": True} if evidence_issues else result
    report = {
        "status": status,
        "input_summary": input_summary,
        "assumptions": result.get("_assumptions", {"roll_rule": "not supplied"}),
        "metrics": metrics,
        "findings": findings,
        "limitations": result.get("_limitations", [
            "Contract-selection compliance cannot be verified without the stated roll rule and its decision inputs."
        ]),
        "next_actions": ["Supply valid required fields or parameters and rerun."] if evidence_issues else (
            result.get("_next_actions", ["Review the roll ledger and rebuild the continuous series."])
            if findings else []
        ),
        "domain_result": domain_result,
    }
    return _json_safe(report)  # type: ignore[return-value]


def emit(result: dict[str, object], out: str | None) -> None:
    payload = json.dumps(build_report(result), ensure_ascii=False, indent=2, allow_nan=False)
    if out:
        Path(out).write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)

DEMO = [
    {"date": "2024-05-20", "front": "CLM4", "back": "CLN4", "selected": "CLM4", "front_price": "79", "back_price": "80"},
    {"date": "2024-05-21", "front": "CLM4", "back": "CLN4", "selected": "CLN4", "front_price": "78.5", "back_price": "80.5"},
]

REQUIRED_COLUMNS = {'back', 'back_price', 'date', 'front', 'front_price', 'selected'}
NUMERIC_COLUMNS = {'back_price', 'front_price'}
OPTIONAL_NUMERIC_COLUMNS = set()


def analyze(
    rows: list[dict[str, str]],
    adjustment_method: str = "none",
) -> dict[str, object]:
    if adjustment_method not in {"none", "difference", "ratio"}:
        return {"_parameter_errors": ["adjustment-method must be none, difference, or ratio"]}

    findings: list[dict[str, object]] = []
    seen_dates: set[str] = set()
    for row_number, row in enumerate(rows, 2):
        reasons: list[str] = []
        date_value = row.get("date", "")
        try:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_value):
                raise ValueError("date must use YYYY-MM-DD")
            datetime.strptime(date_value, "%Y-%m-%d")
        except ValueError:
            reasons.append("invalid_date")
        if date_value in seen_dates:
            reasons.append("duplicate_date")
        seen_dates.add(date_value)
        if row.get("selected") not in {row.get("front"), row.get("back")}:
            reasons.append("selected_not_front_or_back")
        if number(row.get("front_price")) <= 0 or number(row.get("back_price")) <= 0:
            reasons.append("non_positive_contract_price")
        if reasons:
            findings.append({
                "row": row_number,
                "date": date_value,
                "reasons": reasons,
                "severity": "high",
            })

    rows = sorted(rows, key=lambda x: x.get("date", ""))
    events: list[dict[str, object]] = []
    for prev, cur in zip(rows, rows[1:]):
        if prev.get("selected") != cur.get("selected"):
            price_by_contract = {
                cur.get("front"): number(cur.get("front_price")),
                cur.get("back"): number(cur.get("back_price")),
            }
            old_price = price_by_contract.get(prev.get("selected"), 0.0)
            new_price = price_by_contract.get(cur.get("selected"), 0.0)
            gap = new_price - old_price
            events.append({
                "date": cur.get("date"),
                "from": prev.get("selected"),
                "to": cur.get("selected"),
                "old_contract_price": old_price,
                "new_contract_price": new_price,
                "roll_gap": gap,
                "roll_gap_pct": gap / old_price if old_price else None,
                "additive_adjustment": gap,
                "ratio_adjustment": new_price / old_price if old_price else None,
            })

    warnings: list[dict[str, object]] = []
    if events and adjustment_method == "none":
        warnings.append({
            "id": "unadjusted-roll-gap",
            "severity": "medium",
            "evidence": {"roll_count": len(events)},
            "impact": "Naively stitched prices contain non-tradable jumps at contract changes.",
            "recommended_fix": "Use the roll ledger to create a difference- or ratio-adjusted research series; calculate PnL on executable contracts.",
        })
    if not any(
        {"front_volume", "back_volume", "front_open_interest", "back_open_interest"}
        & set(row)
        for row in rows
    ):
        warnings.append({
            "id": "roll-rule-evidence-missing",
            "severity": "low",
            "evidence": {"missing_optional_evidence": ["volume/open_interest or explicit rule decision fields"]},
            "impact": "The selected-contract sequence can be checked structurally, but not proven to follow a volume/open-interest rule.",
            "recommended_fix": "Add rule inputs and the decision timestamp when rule compliance matters.",
        })

    return {
        "rows": len(rows),
        "roll_events": events,
        "roll_count": len(events),
        "findings": findings,
        "warnings": warnings,
        "passed": not findings,
        "_assumptions": {
            "adjustment_method": adjustment_method,
            "roll_event_definition": "selected contract changes between adjacent dates",
            "price_alignment": "both old and new contracts are priced on the new selection date",
        },
        "_limitations": [
            "The script does not infer a roll rule from prices alone.",
            "Difference/ratio factors describe research-series adjustment; tradable PnL must use contract-level returns and execution costs.",
            "Expiry, notice-day and liquidity eligibility require additional contract metadata.",
        ],
        "_next_actions": [
            "Confirm each event against the declared roll rule and decision timestamp.",
            "Apply the chosen adjustment method to a copy of the series and keep this ledger for reproducibility.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit continuous futures roll construction.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input")
    source.add_argument("--demo", action="store_true")
    parser.add_argument("--out")
    parser.add_argument("--adjustment-method", choices=("none", "difference", "ratio"), default="none")
    args = parser.parse_args()
    emit(analyze(load_rows(args.input, DEMO), args.adjustment_method), args.out)


if __name__ == "__main__": main()
