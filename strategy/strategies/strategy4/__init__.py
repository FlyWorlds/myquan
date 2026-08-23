"""策略四：因子1 开盘突破 + 因子4 牛市放宽止损 + 20%昨高止盈 + 因子10 周频动量选股。"""

from __future__ import annotations

from typing import Any

from strategy.core.protocols import StrategySpec
from strategy.core.strategy_registry import register_strategy
from strategy.strategies._common import compose_rules
from strategy.strategies.strategy4.bindings import FACTOR_BINDINGS, STRATEGY_ID, STRATEGY_NAME
from strategy.strategies.strategy4.decision import (
    Strategy4Decision,
    Strategy9Decision,
    create_decision_engine,
)


def _print_rules() -> str:
    return compose_rules(STRATEGY_NAME, bindings=FACTOR_BINDINGS)


def run_strategy4(cfg: Any = None, **kwargs: Any):
    """默认跑 26 只观察池的策略四组合；cfg 为 BacktestConfig 时只跑单票。"""
    from strategy.config import BacktestConfig
    from strategy.runner import run_open_break
    from strategy.strategies.strategy4.portfolio import apply_s9_overlay, run_strategy4_portfolio

    if isinstance(cfg, BacktestConfig):
        cfg = apply_s9_overlay(cfg)
        return run_open_break(cfg, **kwargs)

    return run_strategy4_portfolio(verbose=bool(kwargs.get("verbose", True)))


run_strategy9 = run_strategy4


def _bind() -> StrategySpec:
    from strategy.backtest import OpenBreak3Strategy

    return StrategySpec(
        id=STRATEGY_ID,
        name=STRATEGY_NAME,
        description=(
            "策略四：因子1 开盘突破 + 因子4 牛市放宽止损 + "
            "20%昨高次日开盘全清 + 因子10 周频20日动量 Top5"
        ),
        factor_bindings=FACTOR_BINDINGS,
        run=run_strategy4,
        default_config=None,
        strategy_cls=OpenBreak3Strategy,
        print_rules=_print_rules,
        decision_factory=create_decision_engine,
        aliases=("s4", "s9", "strategy9", "策略四", "策略九"),
        implemented=True,
        meta={
            "default": False,
            "factors": ("factor1", "factor4", "factor10"),
            "take_profit": "prev_high_20",
            "selection": "weekly_px_mom_top5",
        },
    )


register_strategy(_bind())

__all__ = [
    "STRATEGY_ID",
    "STRATEGY_NAME",
    "FACTOR_BINDINGS",
    "Strategy4Decision",
    "Strategy9Decision",
    "create_decision_engine",
    "run_strategy4",
    "run_strategy9",
]
