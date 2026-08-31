"""策略九 · 低开跌停情绪：挂载因子18。"""

from __future__ import annotations

from strategy.core.protocols import bind_factor

STRATEGY_ID = "strategy9"
STRATEGY_NAME = "策略九·低开跌停情绪"

FACTOR_BINDINGS = (
    bind_factor(
        "factor18",
        label="低开跌停情绪",
        role="custom",
        filter_desc="中证1000 低开开盘跌停家数 → 平静/正常/恐慌，对照上证当日涨跌",
    ),
)

__all__ = ["STRATEGY_ID", "STRATEGY_NAME", "FACTOR_BINDINGS"]
