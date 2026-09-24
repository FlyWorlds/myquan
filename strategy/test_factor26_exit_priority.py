# -*- coding: utf-8 -*-
"""Lock FACTOR26_EXIT_PRIORITY_1M against eval_multi_tp_bar control flow."""

from __future__ import annotations

import unittest

from strategy.pullback_wave_stop import (
    CURRENT_INTRABAR_POLICY,
    FACTOR26_EXIT_PRIORITY_1M,
    FACTOR26_OBSERVATION_PRIORITY_REALTIME,
    eval_multi_tp_bar,
)


class TestFactor26ExitPriority(unittest.TestCase):
    def test_policy_constant(self) -> None:
        self.assertEqual(CURRENT_INTRABAR_POLICY, "PRIORITY_ENVELOPE")
        self.assertEqual(
            FACTOR26_OBSERVATION_PRIORITY_REALTIME,
            ("open_protect", "path", "last"),
        )
        self.assertIn("ladder_full_15", FACTOR26_EXIT_PRIORITY_1M)
        self.assertLess(
            FACTOR26_EXIT_PRIORITY_1M.index("ladder_half_10"),
            FACTOR26_EXIT_PRIORITY_1M.index("peak_pullback_clear"),
        )

    def test_hard_gap_beats_t1_trail(self) -> None:
        """低开破硬保护优先于 overnight T1 trail。"""
        r = eval_multi_tp_bar(
            bar_open=97.0,
            bar_high=97.2,
            bar_low=96.0,
            cost_px=100.0,
            peak_before=100.0,
            shares=400,
            overnight_armed=True,
            day_open=97.0,
            vol20_daily=0.05,
        )
        self.assertIsNotNone(r["action"])
        self.assertEqual(r["action"]["reason"], "hard_from_cost")
        self.assertEqual(r["resolution_policy"], "PRIORITY_ENVELOPE")

    def test_ladder15_beats_mid_gain_downside(self) -> None:
        """同 bar high≥15% 与 low 刺中赚线 → ladder_full_15 优先。"""
        cost = 100.0
        r = eval_multi_tp_bar(
            bar_open=110.0,
            bar_high=116.0,  # >= 15%
            bar_low=104.0,  # would hit mid giveback from peak~116
            cost_px=cost,
            peak_before=112.0,
            shares=400,
            overnight_armed=False,
            day_open=110.0,
            vol20_daily=0.05,
        )
        self.assertEqual(r["action"]["reason"], "ladder_full_15")
        self.assertTrue(r["intrabar_ambiguous"])
        self.assertEqual(r["resolved_by"], "PRIORITY_ENVELOPE")

    def test_ladder10_beats_peak_pullback_same_bar(self) -> None:
        """大赚同 bar：10% 半仓优先于 peak_pullback。"""
        cost = 100.0
        r = eval_multi_tp_bar(
            bar_open=108.0,
            bar_high=110.5,  # >= 10%
            bar_low=107.0,  # may pierce peak pullback from peak_before
            cost_px=cost,
            peak_before=110.0,
            shares=400,
            tp_stage=0,
            overnight_armed=False,
            day_open=108.0,
            vol20_daily=0.05,
        )
        self.assertEqual(r["action"]["kind"], "half")
        self.assertEqual(r["action"]["reason"], "ladder_half_10")

    def test_mid_gain_deterministic_between_half_and_vol(self) -> None:
        """中赚：同 bar 两线都触 → mid_gain_first_hit 取卖价更高者（deterministic）。"""
        cost = 100.0
        peak = 106.0  # ~6% gain band
        r = eval_multi_tp_bar(
            bar_open=104.0,
            bar_high=106.0,
            bar_low=102.0,
            cost_px=cost,
            peak_before=peak,
            shares=400,
            overnight_armed=False,
            day_open=104.0,
            vol20_daily=0.05,
        )
        self.assertIsNotNone(r["action"])
        self.assertIn(r["action"]["reason"], ("half_gain", "vol_giveback"))
        # second call identical
        r2 = eval_multi_tp_bar(
            bar_open=104.0,
            bar_high=106.0,
            bar_low=102.0,
            cost_px=cost,
            peak_before=peak,
            shares=400,
            overnight_armed=False,
            day_open=104.0,
            vol20_daily=0.05,
        )
        self.assertEqual(r["action"], r2["action"])

    def test_t1_trail_before_ladder_when_not_live_ok(self) -> None:
        """overnight_armed 且未过 3%：T1 trail 先于阶梯。"""
        r = eval_multi_tp_bar(
            bar_open=100.5,
            bar_high=101.0,  # < 3%
            bar_low=97.0,
            cost_px=100.0,
            peak_before=101.0,
            shares=400,
            overnight_armed=True,
            day_open=100.5,
            session_peak_before=101.0,
            vol20_daily=0.05,
        )
        self.assertEqual(r["action"]["reason"], "t1_peak_trail")


if __name__ == "__main__":
    unittest.main()
