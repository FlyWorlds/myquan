"""策略八：行业 ETF 普通动量 + 改进残差动量月频轮动。"""

from __future__ import annotations

from typing import Any

from strategy.industry_residual_momentum import (
    DEFAULT_PARAMS,
    run_industry_residual_momentum,
)
from strategy.strategies._common import compose_rules
from strategy.strategies._unreg_s8.bindings import (
    FACTOR_BINDINGS,
    STRATEGY_ID,
    STRATEGY_NAME,
)
from strategy.strategies._unreg_s8.decision import (
    Strategy8Decision,
    create_decision_engine,
)


def _print_rules() -> str:
    return compose_rules(STRATEGY_NAME, bindings=FACTOR_BINDINGS)


def run_strategy8(cfg: Any = None, **kwargs: Any):
    overrides = dict(DEFAULT_PARAMS)
    if isinstance(cfg, dict):
        overrides.update(cfg)
    overrides.update(kwargs)
    return run_industry_residual_momentum(**overrides)


__all__ = [
    "STRATEGY_ID",
    "STRATEGY_NAME",
    "FACTOR_BINDINGS",
    "Strategy8Decision",
    "create_decision_engine",
    "run_strategy8",
    "run_industry_residual_momentum",
]

