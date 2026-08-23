"""策略五：因子11 两段近高选股，Top5 等权持有。"""

from __future__ import annotations

from typing import Any

from strategy.core.protocols import StrategySpec
from strategy.core.strategy_registry import register_strategy
from strategy.near_high_hold import DEFAULT_PARAMS, run_near_high_hold
from strategy.strategies._common import compose_rules
from strategy.strategies.strategy5.bindings import (
    FACTOR_BINDINGS,
    STRATEGY_ID,
    STRATEGY_NAME,
)
from strategy.strategies.strategy5.decision import (
    Strategy5Decision,
    Strategy10Decision,
    create_decision_engine,
)


def _print_rules() -> str:
    return compose_rules(STRATEGY_NAME, bindings=FACTOR_BINDINGS)


def run_strategy5(cfg: Any = None, **kwargs: Any):
    """近高 Top5 等权持有。cfg 可传 dict 覆盖参数。研究回测，不构成投资建议。"""
    overrides: dict[str, Any] = dict(DEFAULT_PARAMS)
    if isinstance(cfg, dict):
        overrides.update(cfg)
    overrides.update(kwargs)
    return run_near_high_hold(**overrides)


run_strategy10 = run_strategy5


register_strategy(
    StrategySpec(
        id=STRATEGY_ID,
        name=STRATEGY_NAME,
        description=(
            "因子11：周频3日动量 Top20 内再取贴近5日高点 Top5，"
            "下一周等权持有；一字涨停开盘不可买入"
        ),
        factor_bindings=FACTOR_BINDINGS,
        run=run_strategy5,
        default_config=dict(DEFAULT_PARAMS),
        print_rules=_print_rules,
        decision_factory=create_decision_engine,
        aliases=(
            "s5",
            "s10",
            "strategy10",
            "factor11",
            "near_high",
            "近高持有",
            "策略五",
            "策略十",
        ),
        implemented=True,
        meta={
            "default": False,
            "standalone_factor": "factor11",
            "mode": "weekly_equal_weight_hold",
            "research_only": True,
        },
    ),
    replace=True,
)

__all__ = [
    "STRATEGY_ID",
    "STRATEGY_NAME",
    "FACTOR_BINDINGS",
    "Strategy5Decision",
    "Strategy10Decision",
    "create_decision_engine",
    "run_strategy5",
    "run_strategy10",
    "run_near_high_hold",
]
