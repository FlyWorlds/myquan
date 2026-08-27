"""止损当日尾盘再买过滤的轻量单测（不跑 akquant）。"""

from __future__ import annotations

import unittest

from strategy.open_break import is_yang


class _Fake:
    tick = 0.01
    rebuy_require_yang = True
    rebuy_above_stop_pct = 0.0
    rebuy_from_low_pct = 0.0

    def _same_day_rebuy_ok(self, *, open_px, low_px, close_px, stop_px):
        from strategy.backtest import OpenBreak3Strategy

        return OpenBreak3Strategy._same_day_rebuy_ok(
            self,
            open_px=open_px,
            low_px=low_px,
            close_px=close_px,
            stop_px=stop_px,
        )


class TestSameDayRebuyFilter(unittest.TestCase):
    def test_yang_above_stop_auto(self) -> None:
        # open=100, stop=97.5；收阳 close=101 → 自动高于止损约 3.5%
        s = _Fake()
        s.rebuy_require_yang = True
        s.rebuy_above_stop_pct = 0.025
        self.assertTrue(is_yang(100.0, 101.0, tick=0.01))
        self.assertTrue(
            s._same_day_rebuy_ok(open_px=100, low_px=97, close_px=101, stop_px=97.5)
        )

    def test_yin_blocked_when_require_yang(self) -> None:
        s = _Fake()
        s.rebuy_require_yang = True
        self.assertFalse(
            s._same_day_rebuy_ok(open_px=100, low_px=97, close_px=99, stop_px=97.5)
        )

    def test_from_low_gate(self) -> None:
        s = _Fake()
        s.rebuy_require_yang = False
        s.rebuy_from_low_pct = 0.03
        # (99-97)/100=2% < 3%
        self.assertFalse(
            s._same_day_rebuy_ok(open_px=100, low_px=97, close_px=99, stop_px=97.5)
        )
        # (100.5-97)/100=3.5%
        self.assertTrue(
            s._same_day_rebuy_ok(open_px=100, low_px=97, close_px=100.5, stop_px=97.5)
        )


if __name__ == "__main__":
    unittest.main()
