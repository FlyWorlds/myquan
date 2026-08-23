"""策略四 · 决策层：roll12 Top3 池内反转说明。"""

from __future__ import annotations

from strategy.core.context import Decision, MarketContext
from strategy.core.decision import BaseDecisionEngine
from strategy.core.protocols import StrategySpec
from strategy.strategies._unreg_s4.bindings import FACTOR_BINDINGS, STRATEGY_ID, STRATEGY_NAME


class Strategy4Decision(BaseDecisionEngine):
    strategy_id = STRATEGY_ID
    strategy_name = STRATEGY_NAME

    def decide(self, ctx: MarketContext) -> Decision:
        del ctx
        f1 = self.binding("factor1")
        f3 = self.binding("factor3")
        if f1 is None or f3 is None:
            return Decision.hold("策略四未完整绑定因子1+池内因子3")
        p1, p3 = f1.params, f3.params
        return Decision.hold(
            (
                f"池：因子1 {p1.get('score_mode')} Top{p1.get('pool_n')}；"
                f"交易：池内 {p3.get('kind')}(n={p3.get('n')}) "
                f"Top{p3.get('top_k')} / 持有{p3.get('hold_days')}日"
            ),
            tags=("strategy4", "roll12_pool", "rev"),
        )


def create_decision_engine(spec: StrategySpec | None = None) -> Strategy4Decision:
    bindings = spec.factor_bindings if spec is not None else FACTOR_BINDINGS
    return Strategy4Decision(bindings=bindings)
