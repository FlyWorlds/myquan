"""策略四：暂不挂因子。"""

from __future__ import annotations

from strategy.core.protocols import StrategySpec
from strategy.core.strategy_registry import register_strategy
from strategy.strategies._common import compose_rules, not_implemented_runner
from strategy.strategies.strategy4.bindings import FACTOR_BINDINGS, STRATEGY_ID, STRATEGY_NAME
from strategy.strategies.strategy4.decision import Strategy4Decision, create_decision_engine


def _print_rules() -> str:
    return (
        compose_rules(STRATEGY_NAME, bindings=FACTOR_BINDINGS)
        + "\n【策略四】当前不挂因子，仅占位。\n"
    )


register_strategy(
    StrategySpec(
        id=STRATEGY_ID,
        name=STRATEGY_NAME,
        description="占位：当前不挂因子",
        factor_bindings=FACTOR_BINDINGS,
        run=not_implemented_runner(STRATEGY_ID),
        default_config=None,
        strategy_cls=None,
        print_rules=_print_rules,
        decision_factory=create_decision_engine,
        aliases=("s4",),
        implemented=False,
        meta={"default": False},
    ),
    replace=True,
)

__all__ = [
    "STRATEGY_ID",
    "STRATEGY_NAME",
    "FACTOR_BINDINGS",
    "Strategy4Decision",
    "create_decision_engine",
]
