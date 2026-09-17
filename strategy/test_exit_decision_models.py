"""Phase 2A：ExitDecision / ReasonCode 模型烟测。"""

from __future__ import annotations

import unittest

from strategy.core.exit_decision import (
    ExitAction,
    ExitDecision,
    ExitRuleResult,
    ReasonCode,
    paper_reason_to_code,
)


class TestExitDecisionModels(unittest.TestCase):
    def test_hold_and_sell_factories(self) -> None:
        h = ExitDecision.hold(reason="观望", reason_code=ReasonCode.NONE)
        self.assertEqual(h.action, ExitAction.HOLD)
        s = ExitDecision.sell(
            price=10.5,
            reason_code=ReasonCode.OPEN_PROTECT,
            quantity_ratio=1.0,
        )
        self.assertEqual(s.action, ExitAction.SELL)
        self.assertAlmostEqual(float(s.price or 0), 10.5)

    def test_rule_result_and_reason_map(self) -> None:
        idle = ExitRuleResult.idle()
        self.assertFalse(idle.triggered)
        fire = ExitRuleResult.fire(
            reason_code=ReasonCode.WORKING_STOP,
            price=97.5,
            quantity_ratio=1.0,
        )
        self.assertTrue(fire.triggered)
        self.assertEqual(paper_reason_to_code("open_protect"), ReasonCode.OPEN_PROTECT)
        self.assertEqual(paper_reason_to_code("last"), ReasonCode.WORKING_STOP)
        self.assertEqual(paper_reason_to_code("t1"), ReasonCode.T1_BLOCK)


if __name__ == "__main__":
    unittest.main()
