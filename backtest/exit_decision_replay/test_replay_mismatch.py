"""Mismatch record → replay Legacy vs Unified. Does not enable production flags."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backtest.exit_decision_replay.replay_mismatch import (
    REQUIRED_KEYS,
    replay_file,
    replay_mismatch_record,
)
from holdingStocks.index import _paper_exit_decision_legacy
from strategy.exit_rules.engine import ExitDecisionEngine
from strategy.exit_rules.shadow import (
    SHADOW_UNIFIED_EXIT_ENGINE,
    USE_UNIFIED_EXIT_ENGINE,
    build_exit_context_from_paper_kwargs,
    build_replayable_record,
    compare_paper_vs_exit,
    paper_kwargs_from_record,
)


def _sell_kwargs() -> dict:
    return dict(
        symbol="600552",
        qty=400,
        sellable=400,
        t1_today=False,
        last=96.0,
        open_px=100.0,
        prev_close=99.0,
        cost=100.0,
        peak_high=101.0,
        working_stop=97.5,
        path_hit=False,
        session="2026-09-17",
    )


class TestReplayMismatch(unittest.TestCase):
    def test_flags_stay_false(self) -> None:
        self.assertFalse(USE_UNIFIED_EXIT_ENGINE)
        self.assertFalse(SHADOW_UNIFIED_EXIT_ENGINE)

    def test_sell_record_round_trips(self) -> None:
        kw = _sell_kwargs()
        legacy = _paper_exit_decision_legacy(**{k: v for k, v in kw.items() if k != "symbol"})
        ctx = build_exit_context_from_paper_kwargs(**kw)
        dec = ExitDecisionEngine().evaluate(ctx)
        rec = compare_paper_vs_exit(legacy, dec, ctx)
        payload = build_replayable_record(rec, paper_kwargs=kw)
        for key in REQUIRED_KEYS:
            self.assertIn(key, payload, msg=key)
        self.assertNotIn("bars", payload["paper_kwargs"])
        rebuilt = paper_kwargs_from_record(payload)
        self.assertEqual(int(rebuilt["qty"]), 400)
        self.assertAlmostEqual(float(rebuilt["last"]), 96.0)
        result = replay_mismatch_record(payload)
        self.assertTrue(result["exact_match"])
        self.assertFalse(result["live_mismatch"])
        self.assertFalse(result["reproduced"])
        self.assertEqual(result["legacy_action"], "SELL")
        self.assertEqual(result["unified_action"], "SELL")
        self.assertEqual(result["legacy_reason_code"], "WORKING_STOP")
        self.assertEqual(result["unified_reason_code"], "WORKING_STOP")
        self.assertFalse(result["USE_UNIFIED_EXIT_ENGINE"])
        self.assertFalse(result["SHADOW_UNIFIED_EXIT_ENGINE"])

    def test_injected_mismatch_is_reproducible_from_kwargs(self) -> None:
        kw = _sell_kwargs()
        ctx = build_exit_context_from_paper_kwargs(**kw)
        dec = ExitDecisionEngine().evaluate(ctx)
        fake_legacy = {
            "hit": False,
            "hit_show": False,
            "fill_px": 0.0,
            "kind": "",
            "action_kind": "",
            "reason": "",
        }
        rec = compare_paper_vs_exit(fake_legacy, dec, ctx)
        payload = build_replayable_record(rec, paper_kwargs=kw)
        self.assertEqual(payload["legacy_action"], "HOLD")
        self.assertEqual(payload["unified_action"], "SELL")
        self.assertFalse(payload["match_action"])
        # Live replay uses paper_kwargs, so both orchestrators see the real state.
        live = replay_mismatch_record(payload)
        self.assertTrue(live["exact_match"])
        self.assertFalse(live["reproduced"])
        # The saved snapshot still reconstructs the same Unified SELL.
        self.assertEqual(live["unified_action"], "SELL")
        self.assertEqual(live["unified_reason_code"], "WORKING_STOP")

    def test_replay_file_json(self) -> None:
        kw = _sell_kwargs()
        legacy = _paper_exit_decision_legacy(**{k: v for k, v in kw.items() if k != "symbol"})
        ctx = build_exit_context_from_paper_kwargs(**kw)
        rec = compare_paper_vs_exit(legacy, ExitDecisionEngine().evaluate(ctx), ctx)
        payload = build_replayable_record(rec, paper_kwargs=kw)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mismatch.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            summary = replay_file(path)
        self.assertEqual(summary["n"], 1)
        self.assertEqual(summary["exact_match"], 1)
        self.assertEqual(summary["live_mismatch"], 0)
        self.assertFalse(USE_UNIFIED_EXIT_ENGINE)
        self.assertFalse(SHADOW_UNIFIED_EXIT_ENGINE)


if __name__ == "__main__":
    unittest.main()
