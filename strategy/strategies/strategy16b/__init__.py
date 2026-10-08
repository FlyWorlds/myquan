"""策略十六B·条件选股：复刻策略16，盯盘页提供可配置全A选股。"""

from __future__ import annotations

from typing import Any

from strategy.core.protocols import StrategySpec
from strategy.core.strategy_registry import register_strategy
from strategy.strategies._common import compose_rules
from strategy.strategies.strategy16b.bindings import (
    FACTOR_BINDINGS,
    STRATEGY_ID,
    STRATEGY_NAME,
)
from strategy.strategies.strategy16b.decision import (
    Strategy16BDecision,
    create_decision_engine,
)


def _print_rules() -> str:
    return compose_rules(STRATEGY_NAME, bindings=FACTOR_BINDINGS)


def run_strategy16b(cfg: Any = None, **kwargs: Any):
    """买卖内核与策略16相同；选股池由16B页面参数动态生成。"""
    from strategy.strategies._factor26_runner import run_factor26_strategy

    return run_factor26_strategy(
        cfg,
        bindings=FACTOR_BINDINGS,
        strategy_name=STRATEGY_NAME,
        **kwargs,
    )


register_strategy(
    StrategySpec(
        id=STRATEGY_ID,
        name=STRATEGY_NAME,
        description=(
            "策略16B复刻策略16的因子27核心龙头池与因子26买卖内核；"
            "区别是盯盘页面可动态配置回看月份、价格上限、板块/ST过滤等条件，"
            "再从全A概念成分重新生成候选池。"
        ),
        factor_bindings=FACTOR_BINDINGS,
        run=run_strategy16b,
        default_config=None,
        strategy_cls=None,
        print_rules=_print_rules,
        decision_factory=create_decision_engine,
        aliases=("s16b", "策略十六B", "条件选股", "core_leader_custom"),
        implemented=True,
        meta={
            "default": False,
            "mode": "watch_overlay",
            "watch_tab": True,
            "universe": "factor27",
            "horizon": "rolling_3m",
            "factors": ("factor26", "factor2", "factor27", "factor22"),
            "custom_select_ui": True,
            "tab_order": 16.1,
        },
    ),
    replace=True,
)

__all__ = [
    "STRATEGY_ID",
    "STRATEGY_NAME",
    "FACTOR_BINDINGS",
    "Strategy16BDecision",
    "create_decision_engine",
    "run_strategy16b",
]
