"""策略三 · 决策层骨架（factor2 未实现前恒 hold）。"""

from __future__ import annotations

from strategy.core.context import Decision, MarketContext
from strategy.core.decision import BaseDecisionEngine
from strategy.core.protocols import StrategySpec
from strategy.strategies.strategy3.bindings import FACTOR_BINDINGS, STRATEGY_ID, STRATEGY_NAME


class Strategy3Decision(BaseDecisionEngine):
    strategy_id = STRATEGY_ID
    strategy_name = STRATEGY_NAME

    def decide(self, ctx: MarketContext) -> Decision:
        del ctx
        binding = self.binding("factor2")
        if binding is None:
            return Decision.hold("策略三未绑定因子2")
        return Decision.hold(
            "策略三决策骨架：factor2 尚未实现信号/价位",
            lookback=binding.params.get("lookback"),
            threshold=binding.params.get("threshold"),
            tags=("stub", "factor2"),
        )


def create_decision_engine(spec: StrategySpec | None = None) -> Strategy3Decision:
    bindings = spec.factor_bindings if spec is not None else FACTOR_BINDINGS
    return Strategy3Decision(bindings=bindings)
