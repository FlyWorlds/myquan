import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_manifest
import normalize_config
import scan_experiment
import validate_manifest

FIXTURES = ROOT / "tests" / "fixtures"

class ManifestTests(unittest.TestCase):
    def test_complete_fixture_is_partial_until_external_checks_exist(self):
        scan = scan_experiment.scan(FIXTURES / "minimal_experiment")
        config = normalize_config.normalize(FIXTURES / "minimal_experiment" / "config.json")
        manifest = build_manifest.build(scan, config)
        self.assertEqual(manifest["reproducibility"]["overall_status"], "partial")
        self.assertEqual(validate_manifest.validate(manifest), [])

    def test_missing_config_is_blocked(self):
        scan = scan_experiment.scan(FIXTURES / "missing_core_config")
        config = normalize_config.normalize(FIXTURES / "missing_core_config" / "bad.json")
        manifest = build_manifest.build(scan, config)
        self.assertEqual(manifest["reproducibility"]["overall_status"], "blocked")

if __name__ == "__main__":
    unittest.main()
