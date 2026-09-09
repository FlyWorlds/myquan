"""策略十六·核心龙头：因子27 季度宇宙 + 因子26/2/22 买卖（同策略一）。"""

from __future__ import annotations

from typing import Any

from strategy.core.protocols import StrategySpec
from strategy.core.strategy_registry import register_strategy
from strategy.strategies._common import compose_rules
from strategy.strategies.strategy16.bindings import (
    FACTOR_BINDINGS,
    STRATEGY_ID,
    STRATEGY_NAME,
)
from strategy.strategies.strategy16.decision import Strategy16Decision, create_decision_engine


def _print_rules() -> str:
    return compose_rules(STRATEGY_NAME, bindings=FACTOR_BINDINGS)


def run_strategy16(cfg: Any = None, **kwargs: Any):
    """买卖回测同策略一；宇宙请用季度 picks，不替换策略一定盘池。"""
    from strategy.strategies.strategy1 import run_strategy1

    return run_strategy1(cfg, **kwargs)


register_strategy(
    StrategySpec(
        id=STRATEGY_ID,
        name=STRATEGY_NAME,
        description=(
            "核心龙头：通达信活跃概念偏高、每概念≤3、池约20只、主板非ST非科创创业百元以下；"
            "滚动近3个月冻结选股；买卖同策略一（因子26 多层止盈 + 因子2 预警 + 因子22 再买）"
        ),
        factor_bindings=FACTOR_BINDINGS,
        run=run_strategy16,
        default_config=None,
        strategy_cls=None,
        print_rules=_print_rules,
        decision_factory=create_decision_engine,
        aliases=("s16", "核心龙头", "core_leader"),
        implemented=True,
        meta={
            "default": False,
            "mode": "watch_overlay",
            "watch_tab": True,
            "universe": "factor27",
            "horizon": "rolling_3m",
            "factors": ("factor26", "factor2", "factor27", "factor22"),
        },
    ),
    replace=True,
)

__all__ = [
    "STRATEGY_ID",
    "STRATEGY_NAME",
    "FACTOR_BINDINGS",
    "Strategy16Decision",
    "create_decision_engine",
    "run_strategy16",
]
