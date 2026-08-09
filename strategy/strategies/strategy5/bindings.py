"""策略五 · 因子绑定：仅因子4·动量。"""

from __future__ import annotations

from strategy.core.protocols import bind_factor
from strategy.momentum import DEFAULT_KIND, DEFAULT_PARAMS

STRATEGY_ID = "strategy5"
STRATEGY_NAME = "策略五·动量"

FACTOR_BINDINGS = (
    bind_factor(
        "factor4",
        role="both",
        label="因子4·动量",
        kind=DEFAULT_KIND,
        **DEFAULT_PARAMS,
        filter_desc="独立动量：收盘确认、次日开盘调仓；不叠因子1",
    ),
)
