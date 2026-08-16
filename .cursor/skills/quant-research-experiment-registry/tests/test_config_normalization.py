import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import normalize_config

FIXTURES = ROOT / "tests" / "fixtures"

class ConfigTests(unittest.TestCase):
    def test_normalizes_queries_and_complete_config(self):
        result = normalize_config.normalize(FIXTURES / "minimal_experiment" / "config.json")
        variant = result["variants"][0]
        self.assertEqual(variant["status"], "complete")
        self.assertEqual(variant["queries"][0]["id"], "price_panel")

    def test_splits_variants(self):
        result = normalize_config.normalize(FIXTURES / "multi_variant_config" / "experiments.json")
        self.assertEqual([v["variant_id"] for v in result["variants"]], ["baseline", "robust"])

    def test_missing_core_fields(self):
        result = normalize_config.normalize(FIXTURES / "missing_core_config" / "bad.json")
        self.assertIn("features", result["variants"][0]["missing_core_fields"])
        self.assertEqual(result["variants"][0]["status"], "incomplete")

if __name__ == "__main__":
    unittest.main()
