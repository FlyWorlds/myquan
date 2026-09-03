"""策略十五：因子1 减磨损（连板最高板止盈 + 梯度门控因子22）。"""

from __future__ import annotations

from typing import Any

from strategy.core.protocols import StrategySpec
from strategy.core.strategy_registry import register_strategy
from strategy.strategies._common import compose_rules
from strategy.strategies.strategy15.bindings import (
    FACTOR_BINDINGS,
    STRATEGY_ID,
    STRATEGY_NAME,
)
from strategy.strategies.strategy15.decision import Strategy15Decision, create_decision_engine


def _print_rules() -> str:
    return compose_rules(STRATEGY_NAME, bindings=FACTOR_BINDINGS)


def run_strategy15(cfg: Any = None, **kwargs: Any):
    """回测底层仍走因子1 开盘突破；止盈/F22 门控见决策层与盯盘。"""
    from strategy.strategies.strategy1 import run_strategy1

    return run_strategy1(cfg, **kwargs)


register_strategy(
    StrategySpec(
        id=STRATEGY_ID,
        name=STRATEGY_NAME,
        description=(
            "减磨损：因子1 建仓/止损；因子23 按最高连板定止盈；"
            "因子24 按连板梯度定止盈目标并决定是否用因子22 接回"
        ),
        factor_bindings=FACTOR_BINDINGS,
        run=run_strategy15,
        default_config=None,
        strategy_cls=None,
        print_rules=_print_rules,
        decision_factory=create_decision_engine,
        aliases=("s15", "连板减磨损", "ladder_tp"),
        implemented=True,
        meta={"default": False, "mode": "watch_overlay", "watch_tab": True},
    ),
    replace=True,
)

__all__ = [
    "STRATEGY_ID",
    "STRATEGY_NAME",
    "FACTOR_BINDINGS",
    "Strategy15Decision",
    "create_decision_engine",
    "run_strategy15",
]
