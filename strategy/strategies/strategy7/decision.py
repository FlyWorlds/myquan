"""策略七 · 决策层：因子1 + 因子4 牛市持股。"""

from __future__ import annotations

from strategy.core.context import Decision, MarketContext
from strategy.core.decision import BaseDecisionEngine
from strategy.core.protocols import StrategySpec
from strategy.open_break import stop_trigger_price
from strategy.strategies.strategy1.decision import Strategy1Decision
from strategy.strategies.strategy7.bindings import FACTOR_BINDINGS, STRATEGY_ID, STRATEGY_NAME


class Strategy7Decision(Strategy1Decision):
    """因子4：牛市内持仓暂停止损（与回测 OpenBreak3 因子4 逻辑对齐）。"""

    strategy_id = STRATEGY_ID
    strategy_name = STRATEGY_NAME

    def _factor4_binding(self):
        return self.binding("factor4")

    def _bull_hold(self, ctx: MarketContext) -> bool:
        b4 = self._factor4_binding()
        if b4 is None or not b4.enabled:
            return False
        return bool(ctx.meta.get("factor4_bull"))

    def decide(self, ctx: MarketContext) -> Decision:
        binding = self.binding("factor1")
        if binding is None:
            return Decision.hold("策略七未绑定因子1")

        levels = self.levels_for(binding, ctx)
        buy_px = float(levels.get("buy") or 0)
        stop_px = float(levels.get("stop") or 0)
        if buy_px <= 0 or stop_px <= 0:
            return Decision.hold("开盘价无效，无法计算买卖点")

        high = float(ctx.high)
        low = float(ctx.low)
        bull = self._bull_hold(ctx)

        if ctx.has_position:
            if ctx.t_plus_one:
                return Decision.hold(
                    "T+1 禁卖",
                    buy_price=buy_px,
                    stop_price=stop_px,
                    tags=("t1",),
                )
            if low <= stop_px + 1e-12:
                if bull:
                    b4 = self._factor4_binding()
                    widen = (
                        float(b4.params.get("stop_widen_mult") or 0.0)
                        if b4 is not None
                        else 0.0
                    )
                    if widen > 1.0:
                        stop_pct = float(binding.params.get("stop_pct") or 0.025)
                        wide_stop = stop_trigger_price(
                            float(ctx.open),
                            stop_pct=stop_pct * widen,
                        )
                        if low <= wide_stop + 1e-12:
                            return Decision.sell(
                                wide_stop,
                                reason=f"因子4放宽止损后触发 {wide_stop:.2f}",
                                factor_id="factor1",
                                buy_price=buy_px,
                                stop_price=wide_stop,
                                tags=("stop", "factor1", "factor4", "widened"),
                            )
                        return Decision.hold(
                            "因子4牛市持股：未触及放宽止损",
                            buy_price=buy_px,
                            stop_price=wide_stop,
                            tags=("factor4", "bull_hold", "widened"),
                        )
                    return Decision.hold(
                        "因子4牛市持股：暂停止损",
                        buy_price=buy_px,
                        stop_price=stop_px,
                        tags=("factor4", "bull_hold"),
                    )
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

        b4 = self._factor4_binding()
        if bull and b4 is not None and bool(b4.params.get("skip_f1_entry_in_bull")):
            return Decision.hold(
                "因子4牛市跳过因子1买点",
                buy_price=buy_px,
                stop_price=stop_px,
                tags=("factor4", "skip_entry"),
            )

        if not self.factor_allowed(binding, ctx):
            return Decision.hold(
                "因子过滤未通过（前日/前前日条件）",
                buy_price=buy_px,
                stop_price=stop_px,
                tags=("filter",),
            )
        if high + 1e-12 >= buy_px:
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


def create_decision_engine(spec: StrategySpec | None = None) -> Strategy7Decision:
    bindings = spec.factor_bindings if spec is not None else FACTOR_BINDINGS
    return Strategy7Decision(bindings=bindings)
