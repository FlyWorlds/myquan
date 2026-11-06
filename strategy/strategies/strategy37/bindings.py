"""策略三十七·跌停开板缠论反转策略 · 因子绑定。"""

from __future__ import annotations

from strategy.core.protocols import bind_factor
from strategy.factors.factor37 import (
    DEFAULT_BUY_PRICE_TYPE,
    DEFAULT_HOLDING_DAYS,
    DEFAULT_LIMIT_RATIO,
    DEFAULT_TICK_TOLERANCE,
    DEFAULT_WINDOW_DAYS,
)

STRATEGY_ID = "strategy37"
STRATEGY_NAME = "策略三十七·跌停开板缠论反转策略"

FACTOR_BINDINGS = (
    bind_factor(
        "factor37",
        label="跌停开板缠论反转因子",
        role="entry",
        window_days=DEFAULT_WINDOW_DAYS,
        limit_ratio=DEFAULT_LIMIT_RATIO,
        tick_tolerance=DEFAULT_TICK_TOLERANCE,
        holding_days=DEFAULT_HOLDING_DAYS,
        buy_price_type=DEFAULT_BUY_PRICE_TYPE,
        filter_desc=(
            f"主板标的跌停开板(容差{DEFAULT_TICK_TOLERANCE}元) + "
            f"缠论日线下跌笔+中枢+离开下跌笔({DEFAULT_WINDOW_DAYS}天内背驰段)买入，"
            f"目标持有{DEFAULT_HOLDING_DAYS}个交易日收盘卖出。"
        ),
        enabled=True,
    ),
)

__all__ = ["STRATEGY_ID", "STRATEGY_NAME", "FACTOR_BINDINGS"]
