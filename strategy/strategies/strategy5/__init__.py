"""策略五：单因子4·动量。"""

from __future__ import annotations

from typing import Any

from strategy.config import KAICHENG, BacktestConfig
from strategy.core.protocols import StrategySpec
from strategy.core.strategy_registry import register_strategy
from strategy.strategies._common import compose_rules
from strategy.strategies.strategy5.bindings import FACTOR_BINDINGS, STRATEGY_ID, STRATEGY_NAME
from strategy.strategies.strategy5.decision import Strategy5Decision, create_decision_engine


def _print_rules() -> str:
    return compose_rules(STRATEGY_NAME, bindings=FACTOR_BINDINGS)


def _run(cfg: BacktestConfig | None = None, **kwargs: Any):
    from strategy.runner import run_momentum

    return run_momentum(cfg or KAICHENG, **kwargs)


register_strategy(
    StrategySpec(
        id=STRATEGY_ID,
        name=STRATEGY_NAME,
        description="独立因子4：动量（收盘确认/次日开盘，T+1）",
        factor_bindings=FACTOR_BINDINGS,
        run=_run,
        default_config=KAICHENG,
        strategy_cls=None,
        print_rules=_print_rules,
        decision_factory=create_decision_engine,
        aliases=("s5", "momentum", "factor4"),
        implemented=True,
        meta={"default": False, "standalone_factor": "factor4"},
    ),
    replace=True,
)

__all__ = [
    "STRATEGY_ID",
    "STRATEGY_NAME",
    "FACTOR_BINDINGS",
    "Strategy5Decision",
    "create_decision_engine",
]
