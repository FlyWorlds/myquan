"""策略八决策层：根据月度 Top3 目标做轮入轮出。"""

from __future__ import annotations

from strategy.core.context import Decision, MarketContext
from strategy.core.decision import BaseDecisionEngine
from strategy.core.protocols import StrategySpec
from strategy.strategies._unreg_s8.bindings import (
    FACTOR_BINDINGS,
    STRATEGY_ID,
    STRATEGY_NAME,
)


class Strategy8Decision(BaseDecisionEngine):
    strategy_id = STRATEGY_ID
    strategy_name = STRATEGY_NAME

    def decide(self, ctx: MarketContext) -> Decision:
        if self.binding("factor7") is None:
            return Decision.hold("策略八未绑定因子7")
        raw_target = ctx.meta.get("target")
        if raw_target is None:
            return Decision.hold(
                "等待月末因子7目标",
                kind="industry_etf_dual_momentum",
                tags=("factor7", "monthly"),
            )
        target = (
            [str(raw_target)]
            if isinstance(raw_target, str)
            else [str(value) for value in raw_target]
        )
        symbol = str(ctx.meta.get("symbol") or "")
        in_target = bool(symbol) and symbol in target
        if ctx.has_position:
            if ctx.t_plus_one:
                return Decision.hold("T+1不可卖", tags=("t1", "factor7"))
            if not in_target:
                return Decision.sell(
                    float(ctx.open) if ctx.open else ctx.price,
                    reason="因子7月度轮出",
                    factor_id="factor7",
                    qty=ctx.available_qty or ctx.position_qty,
                    tags=("rotate", "factor7"),
                )
            return Decision.hold("持有因子7月度Top3", tags=("hold", "factor7"))
        if in_target:
            return Decision.buy(
                float(ctx.open) if ctx.open else ctx.price,
                reason="因子7月度Top3轮入",
                factor_id="factor7",
                tags=("rotate", "factor7"),
            )
        return Decision.hold("非因子7月度目标", tags=("factor7", "monthly"))


def create_decision_engine(spec: StrategySpec | None = None) -> Strategy8Decision:
    bindings = spec.factor_bindings if spec is not None else FACTOR_BINDINGS
    return Strategy8Decision(bindings=bindings)

