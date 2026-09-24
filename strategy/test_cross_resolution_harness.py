# -*- coding: utf-8 -*-
"""Cross-resolution harness + Gates (Realtime / BT-1m / classification)."""

from __future__ import annotations

import unittest

from strategy.cross_resolution import (
    aggregate_1m_ohlc,
    make_ticks,
    run_cross_harness,
    run_realtime_ticks,
    run_bt_1m,
)
from strategy.pullback_wave_stop import (
    CURRENT_INTRABAR_POLICY,
    working_stop_price,
)


class TestAggregate1m(unittest.TestCase):
    def test_aggregate_from_ticks(self) -> None:
        ticks = make_ticks(
            [
                ("10:00:05", 18.50),
                ("10:00:15", 18.60),
                ("10:00:30", 18.88),
                ("10:00:45", 18.70),
                ("10:00:55", 18.60),
            ]
        )
        bars = aggregate_1m_ohlc(ticks)
        self.assertEqual(len(bars), 1)
        self.assertAlmostEqual(bars[0]["open"], 18.50)
        self.assertAlmostEqual(bars[0]["high"], 18.88)
        self.assertAlmostEqual(bars[0]["low"], 18.50)
        self.assertAlmostEqual(bars[0]["close"], 18.60)


class TestStopFormulaParity(unittest.TestCase):
    def test_same_state_same_stop(self) -> None:
        """STRICT STRATEGY PARITY：相同 HWM/overnight → stop 必须一致。"""
        a = working_stop_price(
            cost_px=100.0,
            peak_high=106.0,
            session_peak=106.0,
            day_open=101.0,
            overnight_armed=False,
            vol20_daily=0.05,
        )
        b = working_stop_price(
            cost_px=100.0,
            peak_high=106.0,
            session_peak=106.0,
            day_open=101.0,
            overnight_armed=False,
            vol20_daily=0.05,
        )
        self.assertEqual(a, b)


class TestHwmBoundaryParity(unittest.TestCase):
    def test_monotonic_up_then_soft_down(self) -> None:
        """无歧义分钟：边界 HWM 应对齐。"""
        ticks = make_ticks(
            [
                ("10:00:05", 18.50),
                ("10:00:20", 18.60),
                ("10:00:40", 18.70),
                ("10:00:55", 18.80),
                ("10:01:10", 18.70),
                ("10:01:40", 18.60),
            ]
        )
        out = run_cross_harness(ticks, cost=18.50, peak_seed=18.50, day_open=18.50)
        self.assertEqual(out["temporal_violations"], 0)
        # At least first minute should MATCH on HWM
        d0 = out["diffs"][0]
        self.assertEqual(d0.classification, "MATCH")
        self.assertAlmostEqual(
            out["realtime_snapshots"][0].peak_high,
            out["bt_snapshots"][0].peak_high,
            places=6,
        )


class TestResolutionDifferenceEvidence(unittest.TestCase):
    def test_new_high_then_trail_hit(self) -> None:
        """先创新高再刺穿 → RT 知序；BT 仅知包络 → RESOLUTION（须有证据）。"""
        # mid-gain band: cost 100, peak rises to 106 then low pierces half_gain
        ticks = make_ticks(
            [
                ("10:00:10", 104.0),
                ("10:00:20", 106.0),  # new HWM (~6%)
                ("10:00:40", 102.0),  # pullback — may hit half_gain from 106
            ]
        )
        out = run_cross_harness(
            ticks, cost=100.0, peak_seed=104.0, day_open=104.0, vol20=0.05
        )
        self.assertEqual(out["temporal_violations"], 0)
        # If diverge, must be RESOLUTION with evidence — not silent STRATEGY
        for d in out["diffs"]:
            if d.classification == "STRATEGY_DIFFERENCE":
                self.fail(f"unexpected strategy diff: {d.reason} {d.evidence}")
            if d.classification == "RESOLUTION_DIFFERENCE":
                self.assertTrue(
                    d.evidence.get("intrabar_ambiguous")
                    or d.evidence.get("tick_order_ambiguous")
                    or d.reason
                )


class TestNoAbuseResolution(unittest.TestCase):
    def test_monotonic_mismatch_is_strategy(self) -> None:
        """无歧义单调行情若 HWM/stop 不一致 → 不得标 RESOLUTION。"""
        ticks = make_ticks(
            [
                ("10:00:05", 100.0),
                ("10:00:20", 100.5),
                ("10:00:40", 101.0),
                ("10:00:55", 101.2),
            ]
        )
        out = run_cross_harness(ticks, cost=100.0, peak_seed=100.0, day_open=100.0)
        for d in out["diffs"]:
            if d.classification == "RESOLUTION_DIFFERENCE":
                self.fail(f"abused RESOLUTION on monotonic: {d}")
        self.assertGreaterEqual(out["matches"], 1)


class TestIntrabarAmbiguityMetadata(unittest.TestCase):
    def test_bt_marks_ambiguity(self) -> None:
        ticks = make_ticks(
            [
                ("10:00:05", 110.0),
                ("10:00:20", 116.0),
                ("10:00:40", 104.0),
            ]
        )
        bars = aggregate_1m_ohlc(ticks)
        snaps, _ = run_bt_1m(bars, cost=100.0, peak_seed=110.0, day_open=110.0)
        self.assertEqual(snaps[0].resolution_policy, CURRENT_INTRABAR_POLICY)
        self.assertTrue(snaps[0].intrabar_ambiguous)


class TestGateSummaries(unittest.TestCase):
    def test_gates_on_mixed_suite(self) -> None:
        cases = [
            make_ticks(
                [
                    ("10:00:05", 18.50),
                    ("10:00:30", 18.88),
                    ("10:00:55", 18.60),
                ]
            ),
            make_ticks(
                [
                    ("10:00:05", 100.0),
                    ("10:00:30", 100.8),
                    ("10:00:50", 101.0),
                    ("10:01:10", 100.6),
                    ("10:01:40", 100.4),
                ]
            ),
        ]
        temporal = 0
        unexplained = 0
        for ticks in cases:
            out = run_cross_harness(
                ticks,
                cost=float(ticks[0].price),
                peak_seed=float(ticks[0].price),
                day_open=float(ticks[0].price),
            )
            temporal += out["temporal_violations"]
            for d in out["diffs"]:
                if d.classification == "STRATEGY_DIFFERENCE" and d.reason == "unclassified_divergence":
                    unexplained += 1
        self.assertEqual(temporal, 0)
        self.assertEqual(unexplained, 0)


if __name__ == "__main__":
    unittest.main()
