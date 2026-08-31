"""策略七 CLI 包装 · 绑定因子17（Web 不展示）。"""

from __future__ import annotations

from strategy.core.protocols import bind_factor

STRATEGY_ID = "strategy7"
STRATEGY_NAME = "策略七·缠论笔算盈亏比"

FACTOR_BINDINGS = (
    bind_factor(
        "factor17",
        label="缠论笔盈亏比",
        role="custom",
        filter_desc="评估因子：因子1 费用后盈亏按买入笔记账，不单独下单",
    ),
)

__all__ = ["STRATEGY_ID", "STRATEGY_NAME", "FACTOR_BINDINGS"]
