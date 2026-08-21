"""策略二 · 缠论状态机决策层。"""

from __future__ import annotations

from typing import Any

from strategy.chan.signals import ChanSignalSnapshot
from strategy.chan.state_machine import ChanStateMachine
from strategy.core.context import Decision, MarketContext
from strategy.core.decision import BaseDecisionEngine
from strategy.core.protocols import StrategySpec
from strategy.strategies.strategy2.bindings import FACTOR_BINDINGS, STRATEGY_ID, STRATEGY_NAME


class Strategy2Decision(BaseDecisionEngine):
    """每个标的维护独立的一买→二买→二/三卖状态。"""

    strategy_id = STRATEGY_ID
    strategy_name = STRATEGY_NAME

    def __init__(self, bindings=FACTOR_BINDINGS) -> None:
        super().__init__(bindings=bindings)
        self._machines: dict[str, ChanStateMachine] = {}

    def _machine(self, symbol: str, timeout: int) -> ChanStateMachine:
        if symbol not in self._machines:
            self._machines[symbol] = ChanStateMachine(candidate_timeout_bars=timeout)
        return self._machines[symbol]

    def decide(self, ctx: MarketContext) -> Decision:
        binding = self.binding("factor8")
        if binding is None:
            return Decision.hold("策略二未绑定因子8")
        params = binding.merged_params()
        symbol = str(ctx.meta.get("symbol") or "default")
        when: Any = ctx.meta.get("dt") or ctx.session
        if not when:
            return Decision.hold("缺少信号时间")
        snapshot = ChanSignalSnapshot.from_mapping(ctx.meta.get("chan_signals", ctx.meta))
        transition = self._machine(
            symbol, int(params.get("candidate_timeout_bars", 20))
        ).update(
            when,
            snapshot,
            has_position=ctx.has_position,
            can_sell=not ctx.t_plus_one,
        )
        common = {
            "chan_state": transition.state.value,
            "strengthened": transition.strengthened,
            "execution": "next_day_open",
        }
        if transition.action == "buy":
            return Decision.buy(
                ctx.price,
                reason=transition.reason,
                factor_id="factor8",
                target_pct=float(params.get("target_pct", 0.10)),
                **common,
            )
        if transition.action == "sell":
            return Decision.sell(
                ctx.price,
                reason=transition.reason,
                factor_id="factor8",
                **common,
            )
        return Decision.hold(transition.reason, **common)


def create_decision_engine(spec: StrategySpec | None = None) -> Strategy2Decision:
    bindings = spec.factor_bindings if spec is not None else FACTOR_BINDINGS
    return Strategy2Decision(bindings=bindings)
