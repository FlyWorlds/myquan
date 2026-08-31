"""策略十二决策：昨收涨停且今日低开未封则开盘买；恐慌日空仓；T+1 收盘清。"""

from __future__ import annotations

from strategy.core.context import Decision, MarketContext
from strategy.core.decision import BaseDecisionEngine
from strategy.core.protocols import StrategySpec
from strategy.factors.factor21 import factor21_signal
from strategy.strategies.strategy12.bindings import FACTOR_BINDINGS, STRATEGY_ID, STRATEGY_NAME


class Strategy12Decision(BaseDecisionEngine):
    strategy_id = STRATEGY_ID
    strategy_name = STRATEGY_NAME

    def decide(self, ctx: MarketContext) -> Decision:
        open_px = float(ctx.open)

        if ctx.has_position:
            if ctx.t_plus_one:
                return Decision.hold(
                    "T+1 禁卖",
                    buy_price=open_px,
                    tags=("t1", "factor21"),
                )
            return Decision.sell(
                float(ctx.close),
                reason="T+1收盘清仓",
                factor_id="factor21",
                buy_price=open_px,
                tags=("eod", "factor21"),
            )

        sig = factor21_signal(
            yest_close_limit_up=_flag(ctx, "yest_close_limit_up"),
            today_limit_up_open=_flag(ctx, "today_limit_up_open"),
            ld_open=_ld_open(ctx),
            gap=_gap(ctx),
            open_px=open_px,
        )
        if not sig.get("allow"):
            return Decision.hold(
                _hold_reason(sig),
                buy_price=open_px,
                tags=("factor21",),
            )
        return Decision.buy(
            open_px,
            reason="涨停次日低开：开盘买入",
            factor_id="factor21",
            buy_price=open_px,
            tags=("factor21", "lu_next_gap"),
        )


def _flag(ctx: MarketContext, key: str) -> bool:
    return bool(dict(ctx.meta or {}).get(key))


def _ld_open(ctx: MarketContext) -> int | None:
    meta = dict(ctx.meta or {})
    if meta.get("ld_open") is not None:
        try:
            return int(meta["ld_open"])
        except (TypeError, ValueError):
            return None
    return None


def _gap(ctx: MarketContext) -> float | None:
    meta = dict(ctx.meta or {})
    if meta.get("gap") is not None:
        try:
            return float(meta["gap"])
        except (TypeError, ValueError):
            return None
    if ctx.prev_close and float(ctx.prev_close) > 0 and float(ctx.open) > 0:
        return float(ctx.open) / float(ctx.prev_close) - 1.0
    return None


def _hold_reason(sig: dict) -> str:
    if sig.get("panic"):
        return "因子18恐慌：空仓"
    if not sig.get("yest_lu"):
        return "昨日未收盘涨停"
    if not sig.get("gap_ok"):
        return "今日低开不在因子21 带内"
    if not sig.get("opened"):
        return "今日开盘封涨停，买不进"
    return "因子21 未通过"


def create_decision_engine(spec: StrategySpec | None = None) -> Strategy12Decision:
    bindings = spec.factor_bindings if spec is not None else FACTOR_BINDINGS
    return Strategy12Decision(bindings=bindings)


__all__ = ["Strategy12Decision", "create_decision_engine"]
