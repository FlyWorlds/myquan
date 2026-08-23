"""策略五决策层：周频近高 Top5 轮入轮出。"""

from __future__ import annotations

from strategy.core.context import Decision, MarketContext
from strategy.core.decision import BaseDecisionEngine
from strategy.core.protocols import StrategySpec
from strategy.open_break import cannot_buy_limit_up, limit_down_state
from strategy.strategies.strategy5.bindings import (
    FACTOR_BINDINGS,
    STRATEGY_ID,
    STRATEGY_NAME,
)


def _as_targets(raw: object) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw] if raw else []
    if isinstance(raw, (list, tuple, set)):
        return [str(x) for x in raw]
    return []


class Strategy5Decision(BaseDecisionEngine):
    strategy_id = STRATEGY_ID
    strategy_name = STRATEGY_NAME

    def decide(self, ctx: MarketContext) -> Decision:
        if self.binding("factor11") is None:
            return Decision.hold("策略五未绑定因子11")
        if "target" not in ctx.meta:
            return Decision.hold(
                "等待因子11周频近高名单",
                kind="near_high_hold",
                tags=("factor11", "weekly"),
            )
        symbol = str(ctx.meta.get("symbol") or "")
        target = _as_targets(ctx.meta.get("target"))
        in_target = bool(symbol) and symbol in target
        if ctx.has_position:
            if ctx.t_plus_one:
                return Decision.hold("T+1不可卖", tags=("t1", "factor11"))
            if not in_target:
                st = limit_down_state(
                    prev_close=ctx.prev_close,
                    open_px=float(ctx.open) if ctx.open else 0.0,
                    high_px=float(ctx.high) if ctx.high else 0.0,
                    low_px=float(ctx.low) if ctx.low else 0.0,
                    close_px=float(ctx.close) if ctx.close else 0.0,
                    limit_down_pct=float(ctx.meta.get("limit_down_pct") or 0.10),
                )
                if bool(st["locked"]):
                    return Decision.hold("一字跌停封单不可卖", tags=("limit_down", "factor11"))
                px = float(ctx.open) if ctx.open else ctx.price
                return Decision.sell(
                    px,
                    reason="因子11周频轮出",
                    factor_id="factor11",
                    qty=ctx.available_qty or ctx.position_qty,
                    tags=("rotate", "factor11"),
                )
            return Decision.hold("持有因子11近高Top5", tags=("hold", "factor11"))
        if in_target:
            if cannot_buy_limit_up(
                prev_close=ctx.prev_close,
                open_px=float(ctx.open) if ctx.open else 0.0,
                high_px=float(ctx.high) if ctx.high else float(ctx.price),
                low_px=float(ctx.low) if ctx.low else float(ctx.price),
                close_px=float(ctx.close) if ctx.close else float(ctx.price),
                limit_up_pct=float(ctx.meta.get("limit_up_pct") or 0.10),
            ):
                return Decision.hold(
                    "一字涨停开盘不可买入",
                    tags=("limit_up", "factor11"),
                )
            px = float(ctx.open) if ctx.open else ctx.price
            return Decision.buy(
                px,
                reason="因子11近高Top5轮入",
                factor_id="factor11",
                tags=("rotate", "factor11"),
            )
        return Decision.hold("非因子11近高目标", tags=("factor11", "weekly"))


Strategy10Decision = Strategy5Decision


def create_decision_engine(spec: StrategySpec | None = None) -> Strategy5Decision:
    bindings = spec.factor_bindings if spec is not None else FACTOR_BINDINGS
    return Strategy5Decision(bindings=bindings)
