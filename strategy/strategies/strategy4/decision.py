"""策略四 · 决策层骨架（factor4 未实现前恒 hold）。"""

from __future__ import annotations

from strategy.core.context import Decision, MarketContext
from strategy.core.decision import BaseDecisionEngine
from strategy.core.protocols import StrategySpec
from strategy.strategies.strategy4.bindings import FACTOR_BINDINGS, STRATEGY_ID, STRATEGY_NAME


class Strategy4Decision(BaseDecisionEngine):
    strategy_id = STRATEGY_ID
    strategy_name = STRATEGY_NAME

    def decide(self, ctx: MarketContext) -> Decision:
        del ctx
        binding = self.binding("factor4")
        if binding is None:
            return Decision.hold("策略四未绑定因子4")
        return Decision.hold(
            "策略四决策骨架：因子4 尚未实现信号/价位",
            window=binding.params.get("window"),
            tags=("stub", "factor4"),
        )


def create_decision_engine(spec: StrategySpec | None = None) -> Strategy4Decision:
    bindings = spec.factor_bindings if spec is not None else FACTOR_BINDINGS
    return Strategy4Decision(bindings=bindings)
