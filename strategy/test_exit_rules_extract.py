"""开盘保护 / working_stop 规则 characterization（不改 paper 调用路径）。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_HOLD = _ROOT / "holdingStocks"
for p in (str(_ROOT), str(_HOLD)):
    if p not in sys.path:
        sys.path.insert(0, p)

from strategy.core.exit_decision import ReasonCode
from strategy.core.factor_result import DecisionContext
from strategy.exit_rules import (
    evaluate_overnight_open_protect,
    evaluate_working_stop,
    resolve_peak_for_open_protect,
)


class TestOpenProtectExtract(unittest.TestCase):
    def test_gap_down_triggers_like_paper(self) -> None:
        from index import paper_exit_decision

        kw = dict(
            qty=2600,
            sellable=2600,
            t1_today=False,
            last=34.59,
            open_px=33.84,
            prev_close=34.49,
            cost=33.48,
            peak_high=34.78,
            working_stop=34.13,
            path_hit=False,
            overnight_high_ok=True,
        )
        paper = paper_exit_decision(**kw)
        ctx = DecisionContext(
            entry_price=33.48,
            open_px=33.84,
            prev_close=34.49,
            peak_high=34.78,
            qty=2600,
            overnight_high_ok=True,
            current_price=34.59,
            working_stop=34.13,
        )
        rule = evaluate_overnight_open_protect(ctx)
        self.assertTrue(paper["hit"])
        self.assertEqual(paper["kind"], "open_protect")
        self.assertTrue(rule.triggered)
        self.assertEqual(rule.reason_code, ReasonCode.OPEN_PROTECT)
        self.assertAlmostEqual(float(rule.price or 0), float(paper["fill_px"]), places=6)

    def test_heimiao_gap_up_peak_not_trigger(self) -> None:
        from index import paper_exit_decision

        paper = paper_exit_decision(
            qty=7200,
            sellable=7200,
            t1_today=False,
            last=10.60,
            open_px=10.48,
            prev_close=10.14,
            cost=10.13,
            peak_high=11.15,
            working_stop=9.88,
            path_hit=False,
            overnight_high_ok=True,
            buy_time="2026-09-16 09:31:00",
            session="2026-09-17",
        )
        ctx = DecisionContext(
            entry_price=10.13,
            open_px=10.48,
            prev_close=10.14,
            peak_high=11.15,
            qty=7200,
            overnight_high_ok=True,
            buy_time="2026-09-16 09:31:00",
            session="2026-09-17",
        )
        rule = evaluate_overnight_open_protect(ctx)
        self.assertFalse(paper.get("hit"))
        self.assertFalse(rule.triggered)
        # 峰值兜底：高开且 peak≥开 → 不用 11.15
        peak = resolve_peak_for_open_protect(
            cost=10.13, open_px=10.48, prev_close=10.14, peak_high=11.15
        )
        self.assertLess(float(peak or 0), 11.0)


class TestWorkingStopExtract(unittest.TestCase):
    def test_last_below_stop_triggers(self) -> None:
        from index import paper_exit_decision

        paper = paper_exit_decision(
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
        )
        rule = evaluate_working_stop(
            DecisionContext(current_price=96.0, working_stop=97.5)
        )
        self.assertTrue(paper["hit"])
        self.assertEqual(paper["kind"], "last")
        self.assertTrue(rule.triggered)
        self.assertEqual(rule.reason_code, ReasonCode.WORKING_STOP)
        self.assertAlmostEqual(float(rule.price or 0), 97.5, places=6)

    def test_last_above_stop_idle(self) -> None:
        rule = evaluate_working_stop(
            DecisionContext(current_price=100.5, working_stop=97.5)
        )
        self.assertFalse(rule.triggered)


if __name__ == "__main__":
    unittest.main()
