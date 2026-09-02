"""策略十三：因子13A 质量带 + 周动量 TopK 等权轮动（重叠留仓）。"""

from __future__ import annotations

from typing import Any

from strategy.core.protocols import StrategySpec
from strategy.core.strategy_registry import register_strategy
from strategy.s1_weekly_rotate import DEFAULT_PARAMS, run_s1_weekly_rotate, s1_weekly_rules_text
from strategy.strategies._common import compose_rules
from strategy.strategies.strategy13.bindings import (
    FACTOR_BINDINGS,
    STRATEGY_ID,
    STRATEGY_NAME,
)
from strategy.strategies.strategy13.decision import (
    Strategy13Decision,
    create_decision_engine,
)


def _print_rules() -> str:
    head = compose_rules(STRATEGY_NAME, bindings=FACTOR_BINDINGS)
    return head + "\n\n" + s1_weekly_rules_text()


def run_strategy13(cfg: Any = None, **kwargs: Any):
    """周频轮动回测。cfg 可传 dict 覆盖参数。研究用途，非投资建议。"""
    overrides: dict[str, Any] = dict(DEFAULT_PARAMS)
    if isinstance(cfg, dict):
        overrides.update(cfg)
    overrides.update(kwargs)
    return run_s1_weekly_rotate(**overrides)


register_strategy(
    StrategySpec(
        id=STRATEGY_ID,
        name=STRATEGY_NAME,
        description=(
            "策略1质量带宇宙内，周频近20日动量 Top20 等权；"
            "仍在名单的票留仓不强制换出；研究，非默认盯盘"
        ),
        factor_bindings=FACTOR_BINDINGS,
        run=run_strategy13,
        default_config=dict(DEFAULT_PARAMS),
        print_rules=_print_rules,
        decision_factory=create_decision_engine,
        aliases=("s13", "s1_weekly", "周频轮动", "策略十三"),
        implemented=True,
        meta={
            "default": False,
            "mode": "weekly_equal_weight_rotate",
            "research_only": True,
            "ref": "strategy1",
            "backtest_cli": "backtest/strategy13_weekly_rotate/run.py",
        },
    ),
    replace=True,
)

__all__ = [
    "STRATEGY_ID",
    "STRATEGY_NAME",
    "FACTOR_BINDINGS",
    "Strategy13Decision",
    "create_decision_engine",
    "run_strategy13",
    "run_s1_weekly_rotate",
]
