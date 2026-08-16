"""策略八：行业 ETF 普通动量 + 改进残差动量月频轮动。"""

from __future__ import annotations

from typing import Any

from strategy.core.protocols import StrategySpec
from strategy.core.strategy_registry import register_strategy
from strategy.industry_residual_momentum import (
    DEFAULT_PARAMS,
    run_industry_residual_momentum,
)
from strategy.strategies._common import compose_rules
from strategy.strategies.strategy8.bindings import (
    FACTOR_BINDINGS,
    STRATEGY_ID,
    STRATEGY_NAME,
)
from strategy.strategies.strategy8.decision import (
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


register_strategy(
    StrategySpec(
        id=STRATEGY_ID,
        name=STRATEGY_NAME,
        description=(
            "15只行业ETF月频Top3：12月普通动量与100月PCA六因子"
            "改进残差动量各占50%，月末信号次日开盘执行"
        ),
        factor_bindings=FACTOR_BINDINGS,
        run=run_strategy8,
        default_config=dict(DEFAULT_PARAMS),
        print_rules=_print_rules,
        decision_factory=create_decision_engine,
        aliases=(
            "s8",
            "factor7",
            "industry_residual_momentum",
            "行业ETF双动量",
        ),
        implemented=True,
        meta={
            "default": False,
            "standalone_factor": "factor7",
            "mode": "monthly_etf_rotation",
            "research_only": True,
        },
    ),
    replace=True,
)

__all__ = [
    "STRATEGY_ID",
    "STRATEGY_NAME",
    "FACTOR_BINDINGS",
    "Strategy8Decision",
    "create_decision_engine",
    "run_strategy8",
    "run_industry_residual_momentum",
]

