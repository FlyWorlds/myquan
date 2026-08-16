import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import compare_runs

class ReproducibilityTests(unittest.TestCase):
    def test_declared_tolerance_matches(self):
        result = compare_runs.compare({"sharpe": 1.20}, {"sharpe": 1.205}, {"sharpe": {"method": "absolute_tolerance", "tolerance": 0.01}})
        self.assertEqual(result["status"], "reproduced")

    def test_missing_rules_cannot_reproduce(self):
        result = compare_runs.compare({"sharpe": 1.20}, {"sharpe": 1.20}, {})
        self.assertEqual(result["status"], "comparison_rule_missing")

if __name__ == "__main__":
    unittest.main()
