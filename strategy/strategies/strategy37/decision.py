"""策略三十七决策层：跌停开板缠论反转策略决策引擎。

核心逻辑：
1. 买入（空仓时）：
   - 必须为沪深主板正股（剔除创业板/科创板/北交所/ST）；
   - 当日最低价触及 10% 跌停价且收盘打开（Close > Low）；
   - 缠论日线呈现标准的“下跌笔 + 中枢 + 离开下跌笔”结构，且距离中枢结束在窗口期内（默认 90 天/3 个月）；
   - 触发 Decision.buy。
2. 卖出（持仓时）：
   - 持有达到设定交易日数（默认 d5），在收盘卖出；
   - 触发 Decision.sell。
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from czsc import CZSC

from strategy.core.context import Decision, MarketContext
from strategy.core.decision import BaseDecisionEngine
from strategy.core.protocols import FactorBinding
from strategy.factors.factor37 import (
    DEFAULT_BUY_PRICE_TYPE,
    DEFAULT_HOLDING_DAYS,
    DEFAULT_LIMIT_RATIO,
    DEFAULT_TICK_TOLERANCE,
    DEFAULT_WINDOW_DAYS,
    evaluate_limit_down_chan_signal,
    is_mainboard,
)
from strategy.strategies.strategy37.bindings import FACTOR_BINDINGS, STRATEGY_ID, STRATEGY_NAME


class Strategy37Decision(BaseDecisionEngine):
    strategy_id = STRATEGY_ID
    strategy_name = STRATEGY_NAME

    def __init__(
        self,
        bindings: tuple[FactorBinding, ...] = FACTOR_BINDINGS,
        *,
        window_days: int = DEFAULT_WINDOW_DAYS,
        holding_days: int = DEFAULT_HOLDING_DAYS,
        buy_price_type: str = DEFAULT_BUY_PRICE_TYPE,
        limit_ratio: float = DEFAULT_LIMIT_RATIO,
        tick_tolerance: float = DEFAULT_TICK_TOLERANCE,
        **kwargs: Any,
    ) -> None:
        super().__init__(bindings=bindings)
        self.window_days = window_days
        self.holding_days = holding_days
        self.buy_price_type = buy_price_type
        self.limit_ratio = limit_ratio
        self.tick_tolerance = tick_tolerance

    def decide(self, ctx: MarketContext) -> Decision:
        symbol = str(ctx.meta.get("symbol") or "")
        bar_dt = pd.to_datetime(ctx.meta.get("date") or ctx.session or pd.Timestamp.now())
        if bar_dt.tz is not None:
            bar_dt = bar_dt.tz_localize(None)

        # 1. 持仓退出决策
        if ctx.holding:
            if ctx.t_plus_one:
                return Decision.hold(reason="T+1禁卖期持有")

            held_days = int(ctx.meta.get("held_days", 0))
            if held_days >= self.holding_days:
                return Decision.sell(
                    float(ctx.close),
                    reason=f"达到目标持有期(d{held_days})收盘平仓",
                    factor_id="factor37",
                )
            return Decision.hold(reason=f"持有中(第{held_days}天/目标d{self.holding_days})")

        # 2. 开仓买入决策
        if not is_mainboard(symbol):
            return Decision.hold(reason="非主板股票不交易")

        is_st = bool(ctx.meta.get("is_st", False))
        if is_st:
            return Decision.hold(reason="ST股票排除")

        prev_close = float(ctx.prev_close or 0.0)
        open_px = float(ctx.open)
        high_px = float(ctx.high)
        low_px = float(ctx.low)
        close_px = float(ctx.close)

        czsc_engine: CZSC | None = ctx.meta.get("czsc_engine")
        if czsc_engine is None:
            return Decision.hold(reason="缺失CZSC日线引擎")

        eval_res = evaluate_limit_down_chan_signal(
            symbol=symbol,
            prev_close=prev_close,
            open_px=open_px,
            high_px=high_px,
            low_px=low_px,
            close_px=close_px,
            bar_dt=bar_dt,
            czsc_engine=czsc_engine,
            window_days=self.window_days,
            limit_ratio=self.limit_ratio,
            tick_tolerance=self.tick_tolerance,
            is_st=is_st,
        )

        if eval_res.get("signal"):
            limit_down = float(eval_res["limit_down"])
            buy_px = limit_down if self.buy_price_type == "limit_down" else close_px
            return Decision.buy(
                buy_px,
                reason=eval_res.get("reason", "跌停开板缠论反转买点"),
                factor_id="factor37",
                meta=eval_res,
            )

        return Decision.hold(reason=eval_res.get("reason", "观望"))


def create_decision_engine(**kwargs: Any) -> Strategy37Decision:
    return Strategy37Decision(**kwargs)


__all__ = ["Strategy37Decision", "create_decision_engine"]
