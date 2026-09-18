"""Phase 3C+ characterization: rule-order collision, boundaries, T+1 priority, half qty.

Locks current comparison operators. Does not change exit rules.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_HOLD = _ROOT / "holdingStocks"
for p in (str(_ROOT), str(_HOLD)):
    if p not in sys.path:
        sys.path.insert(0, p)

from strategy.core.exit_decision import ExitAction, ReasonCode, paper_reason_to_code
from strategy.exit_rules.engine import ExitDecisionEngine, exit_decision_to_paper_dict
from strategy.exit_rules.shadow import build_exit_context_from_paper_kwargs, compare_paper_vs_exit
from strategy.open_break import TICK_SIZE
from strategy.pullback_wave_stop import cost_hard_stop_px, overnight_open_protect_px


def _paper(**kw: Any) -> dict[str, Any]:
    from index import _paper_exit_decision_legacy

    return _paper_exit_decision_legacy(**kw)


def _four_way(kw: dict[str, Any]) -> tuple[dict[str, Any], Any]:
    paper = _paper(**kw)
    eng = ExitDecisionEngine()
    ctx = build_exit_context_from_paper_kwargs(**kw)
    dec = eng.evaluate(ctx)
    rec = compare_paper_vs_exit(paper, dec, ctx)
    adapted = exit_decision_to_paper_dict(dec)
    legacy_code = paper_reason_to_code(paper.get("reason"), paper.get("kind"))
    assert rec.match_action, (paper, adapted)
    assert rec.match_price, (paper, adapted)
    assert rec.match_qty, (paper, adapted)
    assert rec.match_reason, (legacy_code, dec.reason_code)
    assert legacy_code == dec.reason_code
    if paper.get("hit"):
        assert abs(float(adapted["fill_px"]) - float(paper["fill_px"])) <= 1e-6
        if str(paper.get("action_kind") or "") == "half":
            assert abs(dec.quantity_ratio - 0.5) < 1e-9
        else:
            assert abs(dec.quantity_ratio - 1.0) < 1e-9
    return paper, dec


class TestRuleOrderCollision(unittest.TestCase):
    def test_open_protect_beats_working_stop(self) -> None:
        paper, dec = _four_way(
            dict(
                qty=400,
                sellable=400,
                t1_today=False,
                last=96.0,
                open_px=97.0,
                prev_close=100.0,
                cost=100.0,
                peak_high=100.0,
                working_stop=97.5,
                path_hit=False,
                overnight_high_ok=True,
            )
        )
        self.assertTrue(paper["hit"])
        self.assertEqual(paper["kind"], "open_protect")
        self.assertEqual(dec.rule_id, ReasonCode.OPEN_PROTECT.value)

    def test_working_stop_plus_factor26_path_wins(self) -> None:
        paper, dec = _four_way(
            dict(
                qty=400,
                sellable=400,
                t1_today=False,
                last=103.0,
                open_px=105.0,
                prev_close=104.0,
                cost=100.0,
                peak_high=108.0,
                working_stop=104.0,
                path_hit=True,
                path_fill_px=103.5,
                path_action_kind="full",
                path_stop_kind="half_gain",
            )
        )
        self.assertEqual(paper["kind"], "path")
        self.assertEqual(dec.rule_id, ReasonCode.PATH.value)
        self.assertAlmostEqual(dec.quantity_ratio, 1.0)

    def test_open_protect_plus_factor26_open_wins(self) -> None:
        paper, dec = _four_way(
            dict(
                qty=400,
                sellable=400,
                t1_today=False,
                last=97.0,
                open_px=97.0,
                prev_close=100.0,
                cost=100.0,
                peak_high=100.0,
                working_stop=97.5,
                path_hit=True,
                path_fill_px=97.2,
                path_action_kind="full",
                path_stop_kind="hard_from_cost",
                overnight_high_ok=True,
            )
        )
        self.assertEqual(paper["kind"], "open_protect")
        self.assertEqual(dec.rule_id, ReasonCode.OPEN_PROTECT.value)

    def test_half_position_plus_open_protect_full_wins(self) -> None:
        paper, dec = _four_way(
            dict(
                qty=600,
                sellable=600,
                t1_today=False,
                last=96.0,
                open_px=97.0,
                prev_close=100.0,
                cost=100.0,
                peak_high=100.0,
                working_stop=97.5,
                path_hit=True,
                path_fill_px=110.0,
                path_stop_kind="ladder_half_10",
                path_action_kind="half",
                overnight_high_ok=True,
            )
        )
        self.assertEqual(paper["kind"], "open_protect")
        self.assertEqual(paper["action_kind"], "full")
        self.assertAlmostEqual(dec.quantity_ratio, 1.0)
        self.assertEqual(dec.rule_id, ReasonCode.OPEN_PROTECT.value)

    def test_half_position_plus_working_stop_half_wins(self) -> None:
        paper, dec = _four_way(
            dict(
                qty=600,
                sellable=600,
                t1_today=False,
                last=96.0,
                open_px=110.0,
                prev_close=109.0,
                cost=100.0,
                peak_high=112.0,
                working_stop=97.5,
                path_hit=True,
                path_fill_px=110.0,
                path_stop_kind="ladder_half_10",
                path_action_kind="half",
            )
        )
        self.assertEqual(paper["kind"], "path")
        self.assertEqual(paper["action_kind"], "half")
        self.assertAlmostEqual(dec.quantity_ratio, 0.5)
        self.assertEqual(dec.rule_id, ReasonCode.PATH.value)


class TestT1Priority(unittest.TestCase):
    def test_t1_plus_open_protect_would_sell_is_hold(self) -> None:
        base = dict(
            qty=400,
            sellable=400,
            last=96.0,
            open_px=97.0,
            prev_close=100.0,
            cost=100.0,
            peak_high=100.0,
            working_stop=97.5,
            path_hit=False,
            overnight_high_ok=True,
        )
        live, live_dec = _four_way({**base, "t1_today": False, "sellable": 400})
        self.assertEqual(live["kind"], "open_protect")
        self.assertEqual(live_dec.action, ExitAction.SELL)
        blocked, blocked_dec = _four_way({**base, "t1_today": True, "sellable": 0})
        self.assertFalse(blocked["hit"])
        self.assertEqual(blocked_dec.action, ExitAction.HOLD)

    def test_t1_plus_working_stop_would_sell(self) -> None:
        base = dict(
            qty=400,
            last=96.0,
            open_px=101.0,
            prev_close=100.5,
            cost=100.0,
            peak_high=101.0,
            working_stop=97.5,
            path_hit=False,
            overnight_high_ok=True,
        )
        live, live_dec = _four_way({**base, "t1_today": False, "sellable": 400})
        self.assertEqual(live["kind"], "last")
        self.assertEqual(live_dec.rule_id, ReasonCode.WORKING_STOP.value)
        blocked, blocked_dec = _four_way({**base, "t1_today": True, "sellable": 0})
        self.assertFalse(blocked["hit"])
        self.assertEqual(blocked_dec.action, ExitAction.HOLD)
        hard = float(cost_hard_stop_px(100.0) or 0)
        if 96.0 <= hard + 1e-12:
            self.assertTrue(blocked.get("hit_show"))
            self.assertEqual(blocked.get("reason"), "t1")
            self.assertEqual(blocked_dec.rule_id, ReasonCode.T1_BLOCK.value)

    def test_t1_plus_factor26_would_sell(self) -> None:
        base = dict(
            qty=400,
            last=104.0,
            open_px=105.0,
            prev_close=104.5,
            cost=100.0,
            peak_high=108.0,
            working_stop=104.0,
            path_hit=True,
            path_fill_px=104.0,
            path_action_kind="full",
            path_stop_kind="half_gain",
        )
        live, live_dec = _four_way({**base, "t1_today": False, "sellable": 400})
        self.assertEqual(live["kind"], "path")
        self.assertEqual(live_dec.rule_id, ReasonCode.PATH.value)
        blocked, blocked_dec = _four_way({**base, "t1_today": True, "sellable": 0})
        self.assertFalse(blocked["hit"])
        self.assertEqual(blocked_dec.action, ExitAction.HOLD)


class TestBoundaryComparators(unittest.TestCase):
    """last/open vs stop/protect use <= + 1e-12. Do not change the operator."""

    def test_working_stop_minus_tick_at_plus_tick(self) -> None:
        stop = 97.50
        tick = float(TICK_SIZE)
        for last, expect_sell in (
            (stop - tick, True),
            (stop, True),
            (stop + tick, False),
        ):
            paper, dec = _four_way(
                dict(
                    qty=400,
                    sellable=400,
                    t1_today=False,
                    last=last,
                    open_px=100.0,
                    prev_close=99.0,
                    cost=100.0,
                    peak_high=101.0,
                    working_stop=stop,
                    path_hit=False,
                )
            )
            self.assertEqual(bool(paper["hit"]), expect_sell, msg=f"last={last}")
            if expect_sell:
                self.assertEqual(dec.rule_id, ReasonCode.WORKING_STOP.value)
                self.assertAlmostEqual(float(paper["fill_px"]), stop, places=6)
                self.assertAlmostEqual(float(dec.price or 0), stop, places=6)

    def test_open_protect_minus_tick_at_plus_tick(self) -> None:
        cost = 100.0
        prev = 100.0
        peak = 100.0
        protect = float(
            overnight_open_protect_px(
                cost,
                prev,
                peak_high=peak,
                overnight_high_ok=True,
                qty=400,
            )
            or 0
        )
        self.assertGreater(protect, 0)
        tick = float(TICK_SIZE)
        for open_px, expect_sell in (
            (protect - tick, True),
            (protect, True),
            (protect + tick, False),
        ):
            paper, dec = _four_way(
                dict(
                    qty=400,
                    sellable=400,
                    t1_today=False,
                    last=open_px,
                    open_px=open_px,
                    prev_close=prev,
                    cost=cost,
                    peak_high=peak,
                    working_stop=90.0,
                    path_hit=False,
                    overnight_high_ok=True,
                )
            )
            self.assertEqual(bool(paper["hit"]), expect_sell, msg=f"open={open_px} protect={protect}")
            if expect_sell:
                self.assertEqual(dec.rule_id, ReasonCode.OPEN_PROTECT.value)
                self.assertAlmostEqual(float(paper["fill_px"]), open_px, places=6)

    def test_path_fill_px_zero_is_not_path_ok(self) -> None:
        paper, dec = _four_way(
            dict(
                qty=400,
                sellable=400,
                t1_today=False,
                last=104.0,
                open_px=105.0,
                prev_close=104.5,
                cost=100.0,
                peak_high=108.0,
                working_stop=90.0,
                path_hit=True,
                path_fill_px=0.0,
                path_action_kind="full",
                path_stop_kind="half_gain",
            )
        )
        self.assertFalse(paper["hit"])
        self.assertEqual(dec.action, ExitAction.HOLD)

    def test_t1_hard_last_boundary(self) -> None:
        cost = 100.0
        hard = float(cost_hard_stop_px(cost) or 0)
        tick = float(TICK_SIZE)
        for last, expect_show in (
            (hard - tick, True),
            (hard, True),
            (hard + tick, False),
        ):
            paper, dec = _four_way(
                dict(
                    qty=400,
                    sellable=0,
                    t1_today=True,
                    last=last,
                    open_px=100.0,
                    prev_close=99.0,
                    cost=cost,
                    peak_high=100.0,
                    working_stop=97.5,
                    path_hit=False,
                )
            )
            self.assertFalse(paper["hit"], msg=f"last={last}")
            self.assertEqual(bool(paper.get("hit_show")), expect_show, msg=f"last={last} hard={hard}")
            if expect_show:
                self.assertEqual(paper.get("reason"), "t1")
                self.assertEqual(dec.rule_id, ReasonCode.T1_BLOCK.value)


class TestPartialQuantity(unittest.TestCase):
    def test_half_quantity_ratio_is_half(self) -> None:
        paper, dec = _four_way(
            dict(
                qty=400,
                sellable=400,
                t1_today=False,
                last=110.0,
                open_px=110.0,
                prev_close=109.0,
                cost=100.0,
                peak_high=112.0,
                working_stop=109.0,
                path_hit=True,
                path_fill_px=110.0,
                path_stop_kind="ladder_half_10",
                path_action_kind="half",
            )
        )
        self.assertEqual(paper["action_kind"], "half")
        self.assertAlmostEqual(dec.quantity_ratio, 0.5, places=9)
        self.assertEqual(dec.rule_id, ReasonCode.PATH.value)


if __name__ == "__main__":
    unittest.main()
