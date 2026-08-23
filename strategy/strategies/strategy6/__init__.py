"""策略六：因子12 反转池近高，Top5 等权持有（研究候选，非默认）。"""

from __future__ import annotations

from typing import Any

from strategy.core.protocols import StrategySpec
from strategy.core.strategy_registry import register_strategy
from strategy.factor12_combo import DEFAULT_PARAMS, run_factor12_hold
from strategy.strategies._common import compose_rules
from strategy.strategies.strategy6.bindings import (
    FACTOR_BINDINGS,
    STRATEGY_ID,
    STRATEGY_NAME,
)
from strategy.strategies.strategy6.decision import (
    Strategy6Decision,
    create_decision_engine,
)


def _print_rules() -> str:
    return compose_rules(STRATEGY_NAME, bindings=FACTOR_BINDINGS)


def run_strategy6(cfg: Any = None, **kwargs: Any):
    """反转池近高 Top5 等权持有。研究回测，不构成投资建议。"""
    overrides: dict[str, Any] = dict(DEFAULT_PARAMS)
    if isinstance(cfg, dict):
        overrides.update(cfg)
    overrides.update(kwargs)
    return run_factor12_hold(**overrides)


register_strategy(
    StrategySpec(
        id=STRATEGY_ID,
        name=STRATEGY_NAME,
        description=(
            "因子12：周频20日反转 Top20 内再取贴近5日高点 Top5，"
            "下一周等权持有；研究候选，2024–2025 未确认"
        ),
        factor_bindings=FACTOR_BINDINGS,
        run=run_strategy6,
        default_config=dict(DEFAULT_PARAMS),
        print_rules=_print_rules,
        decision_factory=create_decision_engine,
        aliases=("s6", "factor12", "rev_near", "策略六"),
        implemented=True,
        meta={
            "default": False,
            "standalone_factor": "factor12",
            "mode": "weekly_equal_weight_hold",
            "research_only": True,
            "replaces_strategy5": False,
        },
    ),
    replace=True,
)

__all__ = [
    "STRATEGY_ID",
    "STRATEGY_NAME",
    "FACTOR_BINDINGS",
    "Strategy6Decision",
    "create_decision_engine",
    "run_strategy6",
    "run_factor12_hold",
]
