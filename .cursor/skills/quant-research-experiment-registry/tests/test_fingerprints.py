import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import fingerprint

class FingerprintTests(unittest.TestCase):
    def test_key_order_does_not_change_fingerprint(self):
        self.assertEqual(fingerprint.fingerprint({"a": 1, "b": 2}), fingerprint.fingerprint({"b": 2, "a": 1}))

    def test_absolute_path_is_not_used_when_payload_is_normalized(self):
        payload_a = {"source_config": "C:/one/config.json", "features": ["x"]}
        payload_b = {"source_config": "D:/two/config.json", "features": ["x"]}
        self.assertNotEqual(fingerprint.fingerprint(payload_a), fingerprint.fingerprint(payload_b))

if __name__ == "__main__":
    unittest.main()
