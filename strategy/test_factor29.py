"""因子29：9:20–9:25 路径武装，成交锁正式开盘。"""

from __future__ import annotations

import unittest

from strategy.factors.factor29 import (
    fill_at_official_open,
    levels,
    merge_auction_path,
    observe_auction_tick,
    quote_in_lock_window,
    signal,
)
from strategy.open_break import entry_trigger_price


class TestFactor29Window(unittest.TestCase):
    def test_lock_window_excludes_915_and_925(self) -> None:
        self.assertFalse(quote_in_lock_window("2026-10-13 09:15:00"))
        self.assertFalse(quote_in_lock_window("2026-10-13 09:19:59"))
        self.assertTrue(quote_in_lock_window("2026-10-13 09:20:00"))
        self.assertTrue(quote_in_lock_window("2026-10-13 09:24:59"))
        self.assertFalse(quote_in_lock_window("2026-10-13 09:25:00"))
        self.assertFalse(quote_in_lock_window("2026-10-13 09:30:00"))


class TestFactor29ShengyangJinan(unittest.TestCase):
    def test_shengyang_buy_fill_is_official_open(self) -> None:
        base = 17.90
        trig = float(entry_trigger_price(base, entry_pct=0.025, tick=0.01))
        self.assertAlmostEqual(trig, 18.35, places=2)
        sig = signal(baseline_px=base, auction_high=18.35, auction_low=17.90, threshold_pct=0.025)
        self.assertTrue(sig["hit_buy"])
        self.assertFalse(sig["hit_sell"])
        self.assertAlmostEqual(float(fill_at_official_open(18.53) or 0), 18.53, places=2)
        self.assertNotAlmostEqual(float(sig["buy_trigger"]), 18.53, places=2)

    def test_jinan_buy_fill_is_official_open(self) -> None:
        base = 58.50
        trig = float(entry_trigger_price(base, entry_pct=0.025, tick=0.01))
        self.assertAlmostEqual(trig, 59.97, places=2)
        sig = signal(baseline_px=base, auction_high=59.97, auction_low=58.50, threshold_pct=0.025)
        self.assertTrue(sig["hit_buy"])
        self.assertAlmostEqual(float(fill_at_official_open(60.00) or 0), 60.00, places=2)
        lv = levels(base, threshold_pct=0.025)
        self.assertAlmostEqual(lv["buy_trigger"], 59.97, places=2)


class TestFactor29PathIntegrity(unittest.TestCase):
    def test_observe_ignores_pre_920_and_official_open(self) -> None:
        st: dict = {}
        st = observe_auction_tick(st, last=17.70, ts="2026-10-13 09:15:10", session="2026-10-13")
        self.assertIsNone(st.get("baseline"))
        st = observe_auction_tick(st, last=17.90, ts="2026-10-13 09:20:00", session="2026-10-13")
        st = observe_auction_tick(st, last=18.35, ts="2026-10-13 09:24:40", session="2026-10-13")
        st = observe_auction_tick(st, last=18.53, ts="2026-10-13 09:25:00", session="2026-10-13")
        self.assertAlmostEqual(float(st["baseline"]), 17.90, places=2)
        self.assertAlmostEqual(float(st["high"]), 18.35, places=2)

    def test_merge_does_not_use_official_ohlc(self) -> None:
        path = merge_auction_path(
            quote={
                "session": "2026-10-13",
                "open": 18.53,
                "high": 19.18,
                "low": 18.53,
                "last": 19.00,
            },
            sticky={"session": "2026-10-13", "baseline": 17.90, "high": 18.35, "low": 17.90},
            session="2026-10-13",
        )
        self.assertAlmostEqual(float(path["baseline"]), 17.90, places=2)
        self.assertAlmostEqual(float(path["high"]), 18.35, places=2)
        self.assertNotAlmostEqual(float(path["high"] or 0), 19.18, places=2)

    def test_missing_path_fail_closed(self) -> None:
        sig = signal(baseline_px=None, auction_high=None, auction_low=None)
        self.assertFalse(sig["ready"])
        self.assertFalse(sig["hit_buy"])
        self.assertIsNone(fill_at_official_open(0))


if __name__ == "__main__":
    unittest.main()
