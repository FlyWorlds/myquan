"""策略二 · 决策层骨架：复用因子1 买卖点逻辑（参数/过滤来自本策略绑定）。"""

from __future__ import annotations

from strategy.core.context import Decision, MarketContext
from strategy.core.decision import BaseDecisionEngine
from strategy.core.protocols import StrategySpec
from strategy.strategies.strategy2.bindings import FACTOR_BINDINGS, STRATEGY_ID, STRATEGY_NAME


class Strategy2Decision(BaseDecisionEngine):
    """与策略一同构，但用策略二自己的 factor1 绑定（±3% / 仅阴）。factor2 为权益叠加，决策不参与。"""

    strategy_id = STRATEGY_ID
    strategy_name = STRATEGY_NAME

    def decide(self, ctx: MarketContext) -> Decision:
        binding = self.binding("factor1")
        if binding is None:
            return Decision.hold("策略二未绑定因子1")

        levels = self.levels_for(binding, ctx)
        buy_px = float(levels.get("buy") or 0)
        stop_px = float(levels.get("stop") or 0)
        if buy_px <= 0 or stop_px <= 0:
            return Decision.hold("开盘价无效，无法计算买卖点")

        if ctx.has_position:
            if ctx.t_plus_one:
                return Decision.hold(
                    "T+1 禁卖",
                    buy_price=buy_px,
                    stop_price=stop_px,
                    tags=("t1",),
                )
            if ctx.price <= stop_px:
                return Decision.sell(
                    stop_px,
                    reason=f"触止损 {stop_px:.2f}",
                    factor_id="factor1",
                    buy_price=buy_px,
                    stop_price=stop_px,
                    tags=("stop", "factor1"),
                )
            return Decision.hold(
                "持仓未触止损",
                buy_price=buy_px,
                stop_price=stop_px,
            )

        if not self.factor_allowed(binding, ctx):
            return Decision.hold(
                "因子过滤未通过（仅阴线）",
                buy_price=buy_px,
                stop_price=stop_px,
                tags=("filter",),
            )
        if ctx.price >= buy_px:
            return Decision.buy(
                buy_px,
                reason=f"触买点 {buy_px:.2f}",
                factor_id="factor1",
                buy_price=buy_px,
                stop_price=stop_px,
                tags=("entry", "factor1"),
            )
        return Decision.hold(
            "空仓未触买点",
            buy_price=buy_px,
            stop_price=stop_px,
        )


def create_decision_engine(spec: StrategySpec | None = None) -> Strategy2Decision:
    bindings = spec.factor_bindings if spec is not None else FACTOR_BINDINGS
    return Strategy2Decision(bindings=bindings)
