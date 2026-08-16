from __future__ import annotations

import csv
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "audit_rolls.py"
SPEC = importlib.util.spec_from_file_location("audit_rolls", SCRIPT)
assert SPEC and SPEC.loader
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


class FuturesRollAuditorTests(unittest.TestCase):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-B", str(SCRIPT), *args],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def write_csv(self, directory: str, rows: list[dict[str, str]]) -> Path:
        path = Path(directory) / "rolls.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        return path

    def test_demo_cli_emits_valid_json(self) -> None:
        result = self.run_cli("--demo")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "warning")
        self.assertEqual(payload["domain_result"]["roll_count"], 1)

    def test_input_cli_writes_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = self.write_csv(directory, AUDIT.DEMO)
            output = Path(directory) / "report.json"
            result = self.run_cli("--input", str(source), "--out", str(output))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["status"], "warning")

    def test_cli_rejects_both_sources(self) -> None:
        result = self.run_cli("--demo", "--input", "unused.csv")
        self.assertEqual(result.returncode, 2)

    def test_cli_rejects_missing_source(self) -> None:
        result = self.run_cli()
        self.assertEqual(result.returncode, 2)

    def test_each_adjustment_method_is_recorded(self) -> None:
        for method in ("none", "difference", "ratio"):
            with self.subTest(method=method):
                result = AUDIT.analyze(AUDIT._demo_rows(AUDIT.DEMO), method)
                self.assertEqual(result["_assumptions"]["adjustment_method"], method)
                self.assertEqual(result["roll_events"][0]["roll_gap"], 2.0)
                self.assertAlmostEqual(result["roll_events"][0]["ratio_adjustment"], 80.5 / 78.5)

    def test_invalid_adjustment_method_is_insufficient_evidence(self) -> None:
        report = AUDIT.build_report(AUDIT.analyze(AUDIT._demo_rows(AUDIT.DEMO), "bad"))
        self.assertEqual(report["status"], "insufficient-evidence")
        self.assertTrue(report["domain_result"]["analysis_skipped"])

    def test_invalid_selected_contract_fails(self) -> None:
        rows = AUDIT._demo_rows(AUDIT.DEMO)
        rows[0]["selected"] = "INVALID"
        report = AUDIT.build_report(AUDIT.analyze(rows))
        self.assertEqual(report["status"], "fail")
        reasons = report["domain_result"]["findings"][0]["reasons"]
        self.assertIn("selected_not_front_or_back", reasons)

    def test_duplicate_and_invalid_date_fail(self) -> None:
        rows = AUDIT._demo_rows(AUDIT.DEMO)
        rows[1]["date"] = "2024-5-10"
        rows.append(dict(rows[1]))
        report = AUDIT.build_report(AUDIT.analyze(rows))
        self.assertEqual(report["status"], "fail")
        reasons = [reason for item in report["domain_result"]["findings"] for reason in item["reasons"]]
        self.assertIn("invalid_date", reasons)
        self.assertIn("duplicate_date", reasons)

    def test_zero_padded_dates_sort_chronologically(self) -> None:
        rows = [
            {"date": "2024-10-01", "front": "CLV4", "back": "CLX4", "selected": "CLX4", "front_price": "70", "back_price": "71"},
            {"date": "2024-09-30", "front": "CLV4", "back": "CLX4", "selected": "CLV4", "front_price": "69", "back_price": "70"},
        ]
        result = AUDIT.analyze(rows)
        self.assertTrue(result["passed"])
        self.assertEqual(result["roll_events"][0]["date"], "2024-10-01")

    def test_non_positive_price_fails(self) -> None:
        rows = AUDIT._demo_rows(AUDIT.DEMO)
        rows[0]["front_price"] = "0"
        report = AUDIT.build_report(AUDIT.analyze(rows))
        self.assertEqual(report["status"], "fail")


if __name__ == "__main__":
    unittest.main()
