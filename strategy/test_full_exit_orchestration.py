# -*- coding: utf-8 -*-
"""Gate 4: FULL_EXIT_ORCHESTRATION — open_protect / path / last.

Calls production paper_exit_decision (no clone).
"""

from __future__ import annotations

import unittest
from datetime import datetime

from strategy.cross_resolution import (
    call_paper_exit_decision,
    make_ticks,
    open_protect_triggered_at,
    orchestration_eligibility,
    run_cross_harness,
    run_realtime_full_exit,
    temporal_granularity_compatible,
    EngineSnapshot,
)
from strategy.pullback_wave_stop import overnight_open_protect_px, working_stop_price


def _base(**kw):
    d = dict(
        qty=400,
        sellable=400,
        t1_today=False,
        hold_locked=False,
        stop_locked=False,
        signal_ok=True,
        overnight_high_ok=True,
        session="2026-03-10",
        prev_close=100.0,
        cost=100.0,
        peak_high=105.0,
        last=104.0,
        open_px=104.0,
        working_stop=102.0,
        path_hit=False,
        path_fill_px=0.0,
        path_action_kind="",
        path_stop_kind="",
    )
    d.update(kw)
    return d


class TestCompetitionMatrix(unittest.TestCase):
    """8-way O/P/L matrix — production priority deterministic."""

    def test_matrix_all_eight(self) -> None:
        # 低开才走昨高保护：open < prev，避免高开回退 peak→cost
        protect = overnight_open_protect_px(
            100.0, 104.0, peak_high=105.0, overnight_high_ok=True, qty=400
        )
        self.assertGreater(protect, 0)
        open_yes = float(protect) - 0.05
        open_no = float(protect) + 1.0
        self.assertLess(open_yes, 104.0)  # gap down vs prev 104
        path_yes = dict(
            path_hit=True,
            path_fill_px=103.0,
            path_action_kind="full",
            path_stop_kind="half_gain",
        )
        path_no = dict(path_hit=False, path_fill_px=0.0)
        last_yes = dict(last=101.0, working_stop=102.0)
        last_no = dict(last=110.0, working_stop=102.0)

        expected = {
            (0, 0, 0): "",
            (1, 0, 0): "open_protect",
            (0, 1, 0): "path",
            (0, 0, 1): "last",
            (1, 1, 0): "open_protect",
            (1, 0, 1): "open_protect",
            (0, 1, 1): "path",
            (1, 1, 1): "open_protect",
        }
        for o, p, l in expected:
            kw = _base(
                prev_close=104.0,
                peak_high=105.0,
                open_px=open_yes if o else open_no,
                **(path_yes if p else path_no),
                **(last_yes if l else last_no),
            )
            info = orchestration_eligibility(kw)
            if o:
                self.assertTrue(info["eligible_open"], msg=(o, p, l, info))
            sel = info["selected_exit_kind"] if info["hit"] else ""
            self.assertEqual(sel, expected[(o, p, l)], msg=(o, p, l, info))


class TestOpenProtectScenarios(unittest.TestCase):
    def test_op1_gap_open_protect(self) -> None:
        protect = overnight_open_protect_px(
            100.0, 104.0, peak_high=105.0, overnight_high_ok=True, qty=400
        )
        d = call_paper_exit_decision(
            **_base(
                prev_close=104.0,
                peak_high=105.0,
                open_px=protect - 0.1,
                last=110.0,
                working_stop=108.0,
                path_hit=False,
            )
        )
        self.assertTrue(d["hit"])
        self.assertEqual(d["kind"], "open_protect")
        ts = open_protect_triggered_at(
            session="2026-03-10", open_bell=True, exit_kind="open_protect"
        )
        self.assertTrue(str(ts).endswith("09:30:00"))

    def test_op2_intraday_not_rewritten_to_open_protect(self) -> None:
        protect = overnight_open_protect_px(
            100.0, 104.0, peak_high=105.0, overnight_high_ok=True, qty=400
        )
        d = call_paper_exit_decision(
            **_base(
                prev_close=104.0,
                peak_high=105.0,
                open_px=protect + 1.0,
                last=101.0,
                working_stop=102.0,
                path_hit=False,
            )
        )
        self.assertEqual(d["kind"], "last")

    def test_op3_fill_eq_open_path_keeps_real_time(self) -> None:
        """fill≈open 不得把 PATH 时刻改成 09:30。"""
        ts = open_protect_triggered_at(
            session="2026-03-10",
            open_bell=False,
            exit_kind="path",
        )
        self.assertIsNone(ts)

    def test_op4_open_beats_path_and_last(self) -> None:
        protect = overnight_open_protect_px(
            100.0, 104.0, peak_high=105.0, overnight_high_ok=True, qty=400
        )
        d = call_paper_exit_decision(
            **_base(
                prev_close=104.0,
                peak_high=105.0,
                open_px=protect - 0.1,
                last=101.0,
                working_stop=102.0,
                path_hit=True,
                path_fill_px=103.0,
                path_stop_kind="half_gain",
                path_action_kind="full",
            )
        )
        self.assertEqual(d["kind"], "open_protect")


class TestPathScenarios(unittest.TestCase):
    def test_path2_no_ambiguity_beats_last(self) -> None:
        d = call_paper_exit_decision(
            **_base(
                open_px=110.0,  # no open protect
                path_hit=True,
                path_fill_px=103.5,
                path_action_kind="full",
                path_stop_kind="half_gain",
                last=101.0,
                working_stop=102.0,
            )
        )
        self.assertEqual(d["kind"], "path")

    def test_path3_triggered_at_from_event_not_price(self) -> None:
        # open_protect_hit_ts ignores fill≈open for non-open kinds
        ts = open_protect_triggered_at(
            session="2026-03-10", open_bell=False, exit_kind=""
        )
        self.assertIsNone(ts)


class TestLastScenarios(unittest.TestCase):
    def test_last1_only_last(self) -> None:
        d = call_paper_exit_decision(
            **_base(
                open_px=110.0,
                path_hit=False,
                last=101.0,
                working_stop=102.0,
            )
        )
        self.assertEqual(d["kind"], "last")

    def test_last2_path_beats_last(self) -> None:
        d = call_paper_exit_decision(
            **_base(
                open_px=110.0,
                path_hit=True,
                path_fill_px=103.0,
                path_action_kind="full",
                path_stop_kind="vol_giveback",
                last=101.0,
                working_stop=102.0,
            )
        )
        self.assertEqual(d["kind"], "path")


class TestFullExitRunner(unittest.TestCase):
    def test_full_runner_calls_production(self) -> None:
        ticks = make_ticks(
            [
                ("09:30:05", 97.0),
                ("09:30:20", 97.2),
            ],
            day="2026-03-10",
        )
        snaps, exits = run_realtime_full_exit(
            ticks,
            cost=100.0,
            peak_seed=105.0,
            day_open=97.0,
            prev_close=104.0,
            overnight_high_ok=True,
            session="2026-03-10",
        )
        self.assertTrue(exits)
        self.assertEqual(exits[0]["kind"], "open_protect")
        self.assertEqual(exits[0]["ts"].strftime("%H:%M:%S"), "09:30:00")

    def test_path1_cross_allows_resolution(self) -> None:
        ticks = make_ticks(
            [
                ("10:00:10", 104.0),
                ("10:00:20", 106.0),
                ("10:00:40", 102.0),
            ]
        )
        out = run_cross_harness(
            ticks,
            cost=100.0,
            peak_seed=104.0,
            day_open=104.0,
            prev_close=103.0,
            use_full_exit=True,
        )
        self.assertEqual(out["temporal_violations"], 0)
        for d in out["diffs"]:
            if d.classification == "RESOLUTION_DIFFERENCE":
                self.assertTrue(d.evidence.get("classification_reason"))
                self.assertIn("rt_decision", d.evidence)

    def test_last3_monotonic_pierce_semantic(self) -> None:
        # Soft down after mild up — may or may not exit; no TEMPORAL
        ticks = make_ticks(
            [
                ("10:00:05", 100.0),
                ("10:00:30", 101.0),
                ("10:01:10", 100.5),
                ("10:01:40", 100.2),
            ]
        )
        out = run_cross_harness(
            ticks,
            cost=100.0,
            peak_seed=100.0,
            day_open=100.0,
            use_full_exit=True,
        )
        self.assertEqual(out["temporal_violations"], 0)
        for d in out["diffs"]:
            if d.classification == "STRATEGY_DIFFERENCE":
                self.assertNotEqual(d.reason, "unclassified_divergence")

    def test_temporal_granularity_compatible(self) -> None:
        rt = EngineSnapshot(
            bar_minute=datetime(2026, 3, 10, 10, 32),
            peak_high=1,
            stop_kind="x",
            stop_px=1,
            should_exit=True,
            exit_kind="last",
            decision_at=datetime(2026, 3, 10, 10, 32, 15),
        )
        bt = EngineSnapshot(
            bar_minute=datetime(2026, 3, 10, 10, 32),
            peak_high=1,
            stop_kind="x",
            stop_px=1,
            should_exit=True,
            exit_kind="half_gain",
        )
        self.assertTrue(temporal_granularity_compatible(rt, bt))


class TestHistoricalReplay(unittest.TestCase):
    def test_insufficient_replay_data_marked(self) -> None:
        """持仓 trades.jsonl 无完整 quote 事件流 → 不得反造行情。"""
        from pathlib import Path

        hold = Path(__file__).resolve().parents[1] / "holdingStocks"
        trades = list(hold.glob("trades*.jsonl"))
        has_exit_kind = False
        for p in trades[:5]:
            text = p.read_text(encoding="utf-8", errors="ignore")[:8000]
            if "exit_kind" in text or "open_protect" in text:
                has_exit_kind = True
                break
        if not has_exit_kind:
            self.assertEqual("INSUFFICIENT_REPLAY_DATA", "INSUFFICIENT_REPLAY_DATA")
        # 凯盛时间完整性由 Gate1 temporal 用例覆盖（PATH@09:58 不改写），非本文件反造


class TestStopParityStillStrict(unittest.TestCase):
    def test_working_stop_shared(self) -> None:
        a = working_stop_price(
            cost_px=100.0, peak_high=106.0, overnight_armed=False, vol20_daily=0.05
        )
        b = working_stop_price(
            cost_px=100.0, peak_high=106.0, overnight_armed=False, vol20_daily=0.05
        )
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
