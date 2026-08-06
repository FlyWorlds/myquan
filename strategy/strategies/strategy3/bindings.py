"""策略三 · 因子绑定（与策略二共用 factor2，参数不同）。"""

from __future__ import annotations

from strategy.core.protocols import bind_factor

STRATEGY_ID = "strategy3"
STRATEGY_NAME = "策略三"

FACTOR_BINDINGS = (
    bind_factor(
        "factor2",
        label="因子2(策略三配置)",
        role="both",
        lookback=5,
        threshold=0.02,
        filter_desc="占位：lookback=5, threshold=2%（与策略二挂同一因子但参数不同）",
    ),
)
