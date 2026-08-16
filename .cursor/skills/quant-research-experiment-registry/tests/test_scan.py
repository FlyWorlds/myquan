#!/usr/bin/env python3
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import scan_experiment

FIXTURES = ROOT / "tests" / "fixtures"

class ScanTests(unittest.TestCase):
    def test_classifies_and_excludes(self):
        result = scan_experiment.scan(FIXTURES / "minimal_experiment")
        roles = {item["path"]: item["role"] for item in result["assets"]}
        self.assertEqual(roles["research.py"], "code")
        self.assertEqual(roles["results.json"], "config")
        self.assertGreaterEqual(result["counts"]["scanned"], 4)

    def test_sensitive_content_is_flagged(self):
        result = scan_experiment.scan(FIXTURES / "sensitive_and_excluded_files")
        item = next(item for item in result["assets"] if item["path"] == "secrets.py")
        self.assertTrue(item["sensitive"])
        self.assertNotIn("sk-123456789012345678901234", json.dumps(result))

if __name__ == "__main__":
    unittest.main()
