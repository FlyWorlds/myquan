from __future__ import annotations

import unittest

from backtest.exit_decision_replay.run import holding_intervals
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


if __name__ == "__main__":
    unittest.main()
