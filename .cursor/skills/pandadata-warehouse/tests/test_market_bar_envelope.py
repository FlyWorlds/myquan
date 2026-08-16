import copy
import json
import math
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from market_bar_envelope import ContractError, to_envelope


class MarketBarEnvelopeTests(unittest.TestCase):
    def setUp(self):
        fixture = ROOT / "tests" / "fixtures" / "pandadata-market-bar-native.json"
        self.native = json.loads(fixture.read_text(encoding="utf-8"))

    def test_converts_native_pandadata_record_losslessly(self):
        envelope = to_envelope(self.native)
        self.assertEqual(envelope["$contract"]["profile"], "market-bar")
        self.assertEqual(envelope["payload"]["records"][0]["instrument_id"], "600000.SH")
        self.assertEqual(envelope["payload"]["records"][0]["timestamp"], "2026-08-10T07:00:00Z")
        self.assertEqual(envelope["schema"]["fields"]["volume"]["unit"], "shares")
        self.assertIn("pandadata-market-bar-v1", envelope["quality"]["checks"])
        self.assertEqual(envelope["payload"]["native"]["raw_records"], [self.native])

    def test_rejects_invalid_ohlc_and_nonfinite_values(self):
        invalid = copy.deepcopy(self.native)
        invalid["records"][0]["low"] = 11.0
        with self.assertRaises(ContractError):
            to_envelope(invalid)
        invalid = copy.deepcopy(self.native)
        invalid["records"][0]["close"] = math.nan
        with self.assertRaises(ContractError):
            to_envelope(invalid)

    def test_rejects_cycles(self):
        invalid = copy.deepcopy(self.native)
        invalid["records"].append(invalid)
        with self.assertRaises(ContractError):
            to_envelope(invalid)


if __name__ == "__main__":
    unittest.main()
