"""策略三 · 决策层：动量因子组合（截面选股说明）· 因子3。"""

from __future__ import annotations

from strategy.core.context import Decision, MarketContext
from strategy.core.decision import BaseDecisionEngine
from strategy.core.protocols import StrategySpec
from strategy.strategies._unreg_s3.bindings import FACTOR_BINDINGS, STRATEGY_ID, STRATEGY_NAME


class Strategy3Decision(BaseDecisionEngine):
    strategy_id = STRATEGY_ID
    strategy_name = STRATEGY_NAME

    def decide(self, ctx: MarketContext) -> Decision:
        del ctx
        binding = self.binding("factor3")
        if binding is None:
            return Decision.hold("策略三未绑定因子3")
        p = binding.params
        return Decision.hold(
            (
                f"组合调仓由截面因子确认：{p.get('kind')}(n={p.get('n')}) "
                f"Top{p.get('top_k')} / 持有{p.get('hold_days')}日"
            ),
            kind=p.get("kind"),
            tags=("momentum_portfolio", "factor3"),
        )


def create_decision_engine(spec: StrategySpec | None = None) -> Strategy3Decision:
    bindings = spec.factor_bindings if spec is not None else FACTOR_BINDINGS
    return Strategy3Decision(bindings=bindings)
