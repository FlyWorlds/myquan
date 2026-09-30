"""策略十六B·条件选股 · 因子绑定（复刻策略16，选股参数可动态生成）。"""

from __future__ import annotations

from strategy.strategies.strategy16.bindings import FACTOR_BINDINGS as STRATEGY16_BINDINGS

STRATEGY_ID = "strategy16b"
STRATEGY_NAME = "策略十六B·条件选股"

# 16B 复刻策略16的买卖绑定；差异在盯盘页面按参数重新生成核心龙头池。
FACTOR_BINDINGS = STRATEGY16_BINDINGS
