"""策略四 · 因子绑定（factor4 占位 + 策略侧参数槽位）。"""

from __future__ import annotations

from strategy.core.protocols import bind_factor

STRATEGY_ID = "strategy4"
STRATEGY_NAME = "策略四"

FACTOR_BINDINGS = (
    bind_factor(
        "factor4",
        label="因子4(策略四配置)",
        role="both",
        window=10,
        filter_desc="占位：window=10，待实现",
    ),
)
