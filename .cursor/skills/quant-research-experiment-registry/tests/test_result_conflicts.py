import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import extract_results

FIXTURES = ROOT / "tests" / "fixtures"

class ResultTests(unittest.TestCase):
    def test_conflicting_structured_and_text_metric_is_unresolved(self):
        root = FIXTURES / "conflicting_metrics"
        root.mkdir(exist_ok=True)
        (root / "results.json").write_text('{"metrics":{"sharpe":1.20}}', encoding="utf-8")
        (root / "report.md").write_text('Sharpe: 1.30\n', encoding="utf-8")
        result = extract_results.extract(root)
        item = next(item for item in result["metrics"] if item["name"] == "sharpe")
        self.assertEqual(item["status"], "conflict_unresolved")
        self.assertTrue(item["requires_review"])

if __name__ == "__main__":
    unittest.main()
