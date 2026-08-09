"""策略三：策略层(bindings) + 决策层(decision)；回测入口骨架。"""

from __future__ import annotations

from strategy.core.protocols import StrategySpec
from strategy.core.strategy_registry import register_strategy
from strategy.strategies._common import compose_rules, not_implemented_runner
from strategy.strategies.strategy3.bindings import FACTOR_BINDINGS, STRATEGY_ID, STRATEGY_NAME
from strategy.strategies.strategy3.decision import Strategy3Decision, create_decision_engine


def _print_rules() -> str:
    return compose_rules(STRATEGY_NAME, bindings=FACTOR_BINDINGS)


register_strategy(
    StrategySpec(
        id=STRATEGY_ID,
        name=STRATEGY_NAME,
        description="骨架：挂 factor2 回撤补仓（档位参数可与策略二不同）",
        factor_bindings=FACTOR_BINDINGS,
        run=not_implemented_runner(STRATEGY_ID),
        default_config=None,
        strategy_cls=None,
        print_rules=_print_rules,
        decision_factory=create_decision_engine,
        aliases=("s3",),
        implemented=False,
        meta={"default": False},
    )
)

__all__ = [
    "STRATEGY_ID",
    "STRATEGY_NAME",
    "FACTOR_BINDINGS",
    "Strategy3Decision",
    "create_decision_engine",
]
