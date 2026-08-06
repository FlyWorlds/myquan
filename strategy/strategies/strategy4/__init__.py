"""策略四：策略层(bindings) + 决策层(decision)；回测入口骨架。"""

from __future__ import annotations

from strategy.core.protocols import StrategySpec
from strategy.core.strategy_registry import register_strategy
from strategy.strategies._common import compose_rules, not_implemented_runner
from strategy.strategies.strategy4.bindings import FACTOR_BINDINGS, STRATEGY_ID, STRATEGY_NAME
from strategy.strategies.strategy4.decision import Strategy4Decision, create_decision_engine


def _print_rules() -> str:
    return compose_rules(STRATEGY_NAME, bindings=FACTOR_BINDINGS)


register_strategy(
    StrategySpec(
        id=STRATEGY_ID,
        name=STRATEGY_NAME,
        description="骨架：挂 factor3 + 策略侧参数/过滤器",
        factor_bindings=FACTOR_BINDINGS,
        run=not_implemented_runner(STRATEGY_ID),
        default_config=None,
        strategy_cls=None,
        print_rules=_print_rules,
        decision_factory=create_decision_engine,
        aliases=("s4",),
        implemented=False,
        meta={"default": False},
    )
)

__all__ = [
    "STRATEGY_ID",
    "STRATEGY_NAME",
    "FACTOR_BINDINGS",
    "Strategy4Decision",
    "create_decision_engine",
]
