"""策略五 · 决策层：因子4 动量。"""

from __future__ import annotations

from strategy.core.context import Decision, MarketContext
from strategy.core.decision import BaseDecisionEngine
from strategy.core.protocols import StrategySpec
from strategy.strategies.strategy5.bindings import FACTOR_BINDINGS, STRATEGY_ID, STRATEGY_NAME


class Strategy5Decision(BaseDecisionEngine):
    strategy_id = STRATEGY_ID
    strategy_name = STRATEGY_NAME

    def decide(self, ctx: MarketContext) -> Decision:
        del ctx
        binding = self.binding("factor4")
        if binding is None:
            return Decision.hold("策略五未绑定因子4")
        return Decision.hold(
            "动量仓位由收盘因子确认、次日开盘执行（见 MomentumStrategy）",
            kind=binding.params.get("kind"),
            tags=("momentum", "factor4"),
        )


def create_decision_engine(spec: StrategySpec | None = None) -> Strategy5Decision:
    bindings = spec.factor_bindings if spec is not None else FACTOR_BINDINGS
    return Strategy5Decision(bindings=bindings)
