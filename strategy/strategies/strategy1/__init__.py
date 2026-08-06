"""策略一（默认）：策略层(bindings) + 决策层(decision)。

默认：因子1 + ±2.5% + 阴/小阳 + 禁双阳跨日≥5%；执行层仍走 OpenBreak3Strategy / runner。
"""

from __future__ import annotations

from strategy.core.protocols import StrategySpec
from strategy.core.strategy_registry import register_strategy
from strategy.strategies._common import compose_rules
from strategy.strategies.strategy1.bindings import (
    FACTOR_BINDINGS,
    STRATEGY_ID,
    STRATEGY_NAME,
    strategy1_factor_filter,
)
from strategy.strategies.strategy1.decision import Strategy1Decision, create_decision_engine


def _print_rules() -> str:
    return compose_rules(STRATEGY_NAME, bindings=FACTOR_BINDINGS)


def _bind() -> StrategySpec:
    from strategy.backtest import OpenBreak3Strategy
    from strategy.config import KAICHENG
    from strategy.runner import run_open_break

    return StrategySpec(
        id=STRATEGY_ID,
        name=STRATEGY_NAME,
        description="默认策略：因子1 + 策略侧±2.5%/阴小阳过滤，仅止损全清",
        factor_bindings=FACTOR_BINDINGS,
        run=run_open_break,
        default_config=KAICHENG,
        strategy_cls=OpenBreak3Strategy,
        print_rules=_print_rules,
        decision_factory=create_decision_engine,
        aliases=("open_break3", "s1", "因子1策略"),
        implemented=True,
        meta={"default": True, "legacy_id": "open_break3"},
    )


register_strategy(_bind())

__all__ = [
    "STRATEGY_ID",
    "STRATEGY_NAME",
    "FACTOR_BINDINGS",
    "strategy1_factor_filter",
    "Strategy1Decision",
    "create_decision_engine",
]
