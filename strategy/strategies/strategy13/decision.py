"""策略十三决策层：周频目标池轮入轮出（重叠留仓）。"""

from __future__ import annotations

from strategy.core.context import Decision, MarketContext
from strategy.core.decision import BaseDecisionEngine
from strategy.core.protocols import StrategySpec
from strategy.open_break import cannot_buy_limit_up, limit_down_state
from strategy.strategies.strategy13.bindings import (
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


class Strategy13Decision(BaseDecisionEngine):
    strategy_id = STRATEGY_ID
    strategy_name = STRATEGY_NAME

    def decide(self, ctx: MarketContext) -> Decision:
        if self.binding("factor13a") is None:
            return Decision.hold("策略十三未绑定因子13A")
        if "target" not in ctx.meta:
            return Decision.hold(
                "等待周频轮动名单",
                kind="s1_weekly_rotate",
                tags=("factor13a", "weekly"),
            )
        symbol = str(ctx.meta.get("symbol") or "")
        target = _as_targets(ctx.meta.get("target"))
        in_target = bool(symbol) and symbol in target
        if ctx.has_position:
            if ctx.t_plus_one:
                return Decision.hold("T+1不可卖", tags=("t1", "strategy13"))
            if in_target:
                return Decision.hold("仍在周频名单·留仓", tags=("keep", "strategy13"))
            st = limit_down_state(
                prev_close=ctx.prev_close,
                open_px=float(ctx.open) if ctx.open else 0.0,
                high_px=float(ctx.high) if ctx.high else 0.0,
                low_px=float(ctx.low) if ctx.low else 0.0,
                close_px=float(ctx.close) if ctx.close else 0.0,
                limit_down_pct=float(ctx.meta.get("limit_down_pct") or 0.10),
            )
            if bool(st["locked"]):
                return Decision.hold("一字跌停封单不可卖", tags=("limit_down", "strategy13"))
            px = float(ctx.open) if ctx.open else ctx.price
            return Decision.sell(
                px,
                reason="周频轮出",
                factor_id="factor13a",
                kind="s1_weekly_rotate",
                tags=("rotate_out",),
            )
        if not in_target:
            return Decision.hold("不在本周目标池", tags=("strategy13",))
        if cannot_buy_limit_up(
            prev_close=ctx.prev_close,
            open_px=float(ctx.open) if ctx.open else 0.0,
            high_px=float(ctx.high) if ctx.high else 0.0,
            low_px=float(ctx.low) if ctx.low else 0.0,
            close_px=float(ctx.close) if ctx.close else 0.0,
            limit_up_pct=float(ctx.meta.get("limit_up_pct") or 0.10),
        ):
            return Decision.hold("一字涨停开盘不可买", tags=("limit_up", "strategy13"))
        px = float(ctx.open) if ctx.open else ctx.price
        return Decision.buy(
            px,
            reason="周频轮入",
            factor_id="factor16",
            kind="s1_weekly_rotate",
            tags=("rotate_in",),
        )


def create_decision_engine(spec: StrategySpec | None = None) -> Strategy13Decision:
    return Strategy13Decision(bindings=FACTOR_BINDINGS if spec is None else spec.factor_bindings)
