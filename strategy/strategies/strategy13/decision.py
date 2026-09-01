"""策略十三 · 纯因子1 ETF 决策（与策略一因子1 口径一致）。"""

from __future__ import annotations

from strategy.core.context import Decision, MarketContext
from strategy.core.decision import BaseDecisionEngine
from strategy.core.protocols import StrategySpec
from strategy.strategies.strategy13.bindings import (
    FACTOR_BINDINGS,
    STRATEGY_ID,
    STRATEGY_NAME,
)


class Strategy13Decision(BaseDecisionEngine):
    strategy_id = STRATEGY_ID
    strategy_name = STRATEGY_NAME

    def decide(self, ctx: MarketContext) -> Decision:
        binding = self.binding("factor1")
        if binding is None:
            return Decision.hold("策略十三未绑定因子1")

        levels = self.levels_for(binding, ctx)
        buy_px = float(levels.get("buy") or 0)
        stop_px = float(levels.get("stop") or 0)
        if buy_px <= 0 or stop_px <= 0:
            return Decision.hold("开盘价无效")

        high = float(ctx.high)
        low = float(ctx.low)

        if ctx.has_position:
            if ctx.t_plus_one:
                return Decision.hold("T+1 禁卖", buy_price=buy_px, stop_price=stop_px, tags=("t1",))
            if low <= stop_px + 1e-12:
                return Decision.sell(
                    stop_px,
                    reason=f"触止损 {stop_px:.2f}",
                    factor_id="factor1",
                    buy_price=buy_px,
                    stop_price=stop_px,
                    tags=("stop", "factor1"),
                )
            return Decision.hold("持仓未触止损", buy_price=buy_px, stop_price=stop_px)

        if not self.factor_allowed(binding, ctx):
            return Decision.hold("因子过滤未过", buy_price=buy_px, stop_price=stop_px)

        if high >= buy_px - 1e-12:
            return Decision.buy(
                buy_px,
                reason=f"触买点 {buy_px:.2f}",
                factor_id="factor1",
                buy_price=buy_px,
                stop_price=stop_px,
                tags=("entry", "factor1"),
            )
        return Decision.hold("未触买点", buy_price=buy_px, stop_price=stop_px)


def create_decision_engine(spec: StrategySpec | None = None) -> Strategy13Decision:
    del spec
    return Strategy13Decision(bindings=FACTOR_BINDINGS)


__all__ = ["Strategy13Decision", "create_decision_engine"]
