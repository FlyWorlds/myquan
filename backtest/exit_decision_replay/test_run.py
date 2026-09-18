from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backtest.exit_decision_replay.catalog import normalize_rule_id, path_by_id
from backtest.exit_decision_replay.harness import holding_intervals
from backtest.exit_decision_replay.scan_rules import scan
from backtest.exit_decision_replay.run import load_corpus
from strategy.exit_rules import shadow


class TestExitDecisionReplay(unittest.TestCase):
    def test_holding_intervals_keep_half_sale_open(self) -> None:
        trades = [
            {"side": "buy", "ts": "2026-09-01 09:31:00", "px": 10.0},
            {
                "side": "sell",
                "ts": "2026-09-02 10:00:00",
                "px": 11.0,
                "note": "ladder_half_10",
            },
            {
                "side": "sell",
                "ts": "2026-09-03 10:00:00",
                "px": 11.5,
                "note": "peak_pullback_clear",
            },
        ]

        intervals = holding_intervals(trades)

        self.assertEqual(len(intervals), 1)
        self.assertEqual(str(intervals[0].buy_ts), "2026-09-01 09:31:00")
        self.assertEqual(str(intervals[0].sell_ts), "2026-09-03 10:00:00")

    def test_replay_does_not_enable_unified_engine(self) -> None:
        self.assertFalse(shadow.USE_UNIFIED_EXIT_ENGINE)
        self.assertFalse(shadow.SHADOW_UNIFIED_EXIT_ENGINE)

    def test_rule_aliases(self) -> None:
        self.assertEqual(normalize_rule_id("FACTOR_26_PATH"), "PATH")
        self.assertEqual(normalize_rule_id("last"), "WORKING_STOP")
        self.assertEqual(normalize_rule_id("HALF_POSITION"), "PATH_HALF")
        self.assertIsNotNone(path_by_id("WORKING_STOP"))

    def test_scan_rules_no_legacy_only(self) -> None:
        result = scan()
        self.assertTrue(all(result["paper_reason_map_ok"].values()))
        self.assertEqual(result["legacy_only_rules"], [])
        self.assertEqual(result["unified_only_rules"], [])
        self.assertIn("WORKING_STOP", result["engine_reason_codes"])
        self.assertIn("OPEN_PROTECT", result["engine_reason_codes"])

    def test_load_corpus_list_or_object(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.json"
            path.write_text(
                json.dumps(
                    {
                        "rule_id": "WORKING_STOP",
                        "cases": [
                            {
                                "symbol": "600330",
                                "timestamp": "2026-09-16 10:31:00",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            cases = load_corpus(path)
            self.assertEqual(len(cases), 1)
            self.assertEqual(cases[0]["symbol"], "600330")


if __name__ == "__main__":
    unittest.main()
