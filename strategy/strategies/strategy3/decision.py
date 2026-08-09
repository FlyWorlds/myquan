"""策略三 · 决策层骨架（仅挂因子2 叠加，不产出买卖价 → hold）。"""

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
            "策略三：factor2 为权益补仓叠加因子，不直接产出买卖价",
            add_pct=binding.params.get("add_pct"),
            levels=binding.params.get("levels"),
            tags=("overlay", "factor2"),
        )


def create_decision_engine(spec: StrategySpec | None = None) -> Strategy3Decision:
    bindings = spec.factor_bindings if spec is not None else FACTOR_BINDINGS
    return Strategy3Decision(bindings=bindings)
