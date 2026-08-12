"""策略六 · 决策层：因子3选股说明 + 因子1止损价。"""

from __future__ import annotations

from strategy.core.context import Decision, MarketContext
from strategy.core.decision import BaseDecisionEngine
from strategy.core.protocols import StrategySpec
from strategy.open_break import stop_trigger_price
from strategy.strategies.strategy6.bindings import FACTOR_BINDINGS, STRATEGY_ID, STRATEGY_NAME


class Strategy6Decision(BaseDecisionEngine):
    strategy_id = STRATEGY_ID
    strategy_name = STRATEGY_NAME

    def decide(self, ctx: MarketContext) -> Decision:
        b3 = self.binding("factor3")
        b1 = self.binding("factor1")
        if b3 is None:
            return Decision.hold("策略六未绑定因子3")
        if b1 is None:
            return Decision.hold("策略六未绑定因子1")

        p3 = b3.params
        stop_pct = float(b1.params.get("stop_pct") or 0.025)
        stop_px = None
        if ctx.open is not None and float(ctx.open) > 0:
            stop_px = stop_trigger_price(float(ctx.open), stop_pct=stop_pct)

        # 有仓：优先判因子1止损（T+1 除外）
        if ctx.has_position:
            if ctx.t_plus_one:
                return Decision.hold(
                    "T+1不可卖",
                    stop_pct=stop_pct,
                    stop_px=stop_px,
                    tags=("t1", "factor1", "factor3"),
                )
            if (
                stop_px is not None
                and ctx.low is not None
                and float(ctx.low) <= float(stop_px) + 1e-12
            ):
                return Decision.sell(
                    float(stop_px),
                    reason=f"因子1触止损 {float(stop_px):.2f}",
                    factor_id="factor1",
                    qty=ctx.available_qty or ctx.position_qty,
                    stop_pct=stop_pct,
                    tags=("stop", "factor1"),
                )
            return Decision.hold(
                "持仓未触因子1止损",
                stop_pct=stop_pct,
                stop_px=stop_px,
                tags=("hold", "factor1", "factor3"),
            )

        # 空仓：选股/买入由截面引擎负责，单票决策层只说明规则
        return Decision.hold(
            (
                f"选股由因子3截面确认：{p3.get('kind')}(n={p3.get('n')}) "
                f"Top{p3.get('top_k')}；止损由因子1开盘-{stop_pct*100:.1f}%"
            ),
            kind=p3.get("kind"),
            stop_pct=stop_pct,
            tags=("momentum_select", "factor3", "factor1"),
        )


def create_decision_engine(spec: StrategySpec | None = None) -> Strategy6Decision:
    bindings = spec.factor_bindings if spec is not None else FACTOR_BINDINGS
    return Strategy6Decision(bindings=bindings)
