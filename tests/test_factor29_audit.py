from __future__ import annotations

import unittest

import pandas as pd

from backtest.strategy16_core_leader.audit_factor29 import auction_rows


class TestFactor29Audit(unittest.TestCase):
    def test_window_excludes_final_auction_open_and_continuous_bars(self):
        frame = pd.DataFrame({"ts": pd.to_datetime([
            "2026-10-13 09:19:59", "2026-10-13 09:20:00",
            "2026-10-13 09:24:59", "2026-10-13 09:25:00", "2026-10-13 09:31:00",
        ])})
        self.assertEqual(auction_rows(frame), 2)

    def test_regular_minutes_do_not_prove_auction_path_coverage(self):
        frame = pd.DataFrame({"ts": pd.to_datetime(["2026-10-13 09:30:00", "2026-10-13 09:31:00"])})
        self.assertEqual(auction_rows(frame), 0)

    def test_aware_timestamps_use_shanghai_window(self):
        frame = pd.DataFrame({"ts": pd.to_datetime(["2026-10-13 01:20:00Z", "2026-10-13 01:25:00Z"])})
        self.assertEqual(auction_rows(frame), 1)


if __name__ == "__main__":
    unittest.main()
