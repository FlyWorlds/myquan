"""策略十二决策：因子18 恐慌日禁止新开仓，其余同策略一。"""

from __future__ import annotations

from strategy.core.context import Decision, MarketContext
from strategy.core.protocols import StrategySpec
from strategy.factors.factor18 import factor18_signal
from strategy.strategies.strategy1.decision import Strategy1Decision
from strategy.strategies.strategy12.bindings import FACTOR_BINDINGS, STRATEGY_ID, STRATEGY_NAME


class Strategy12Decision(Strategy1Decision):
    """空仓且因子18=恐慌 → hold；已有仓仍走因子1 止损。"""

    strategy_id = STRATEGY_ID
    strategy_name = STRATEGY_NAME

    def decide(self, ctx: MarketContext) -> Decision:
        if not ctx.has_position and self._is_panic(ctx):
            binding = self.binding("factor1")
            levels = self.levels_for(binding, ctx) if binding is not None else {}
            return Decision.hold(
                "因子18恐慌：禁止新开仓",
                buy_price=levels.get("buy"),
                stop_price=levels.get("stop"),
                tags=("factor18", "panic_halt"),
            )
        return super().decide(ctx)

    @staticmethod
    def _is_panic(ctx: MarketContext) -> bool:
        meta = dict(ctx.meta or {})
        phase = meta.get("ldPhase")
        if phase is None and meta.get("ld_open") is not None:
            try:
                phase = factor18_signal(ld_open=int(meta["ld_open"])).get("ldPhase")
            except (TypeError, ValueError):
                phase = None
        return str(phase or "") == "panic"


def create_decision_engine(spec: StrategySpec | None = None) -> Strategy12Decision:
    bindings = spec.factor_bindings if spec is not None else FACTOR_BINDINGS
    return Strategy12Decision(bindings=bindings)


__all__ = ["Strategy12Decision", "create_decision_engine"]
