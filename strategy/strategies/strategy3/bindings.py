"""策略三 · 挂因子2，档位与策略一不同（演示只改 params）。"""

from __future__ import annotations

from strategy.core.protocols import bind_factor
from strategy.dd_topup import DEFAULT_ADD_PCT, filter_desc as factor2_filter_desc

STRATEGY_ID = "strategy3"
STRATEGY_NAME = "策略三"

# 更高起加档，减少低档频繁进出（相对默认 10/20/30）
_LEVELS = (0.15, 0.25, 0.35)

FACTOR_BINDINGS = (
    bind_factor(
        "factor2",
        label="回撤阶梯补仓(策略三)",
        role="custom",
        add_pct=DEFAULT_ADD_PCT,
        levels=_LEVELS,
        filter_desc=factor2_filter_desc(DEFAULT_ADD_PCT, _LEVELS),
        enabled=True,
    ),
)
