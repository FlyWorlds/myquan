"""策略四 · 决策层（未挂因子 → hold）。"""

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
        if not self.bindings:
            return Decision.hold("策略四未挂因子")
        return Decision.hold("策略四未挂可用交易因子")


def create_decision_engine(spec: StrategySpec | None = None) -> Strategy4Decision:
    bindings = spec.factor_bindings if spec is not None else FACTOR_BINDINGS
    return Strategy4Decision(bindings=bindings)
