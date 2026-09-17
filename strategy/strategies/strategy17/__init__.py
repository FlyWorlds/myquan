"""策略十七·紫阳真君：因子28 席位池 + 因子26/2 买卖（因子22 默认关）。"""

from __future__ import annotations

from typing import Any

from strategy.core.protocols import StrategySpec
from strategy.core.strategy_registry import register_strategy
from strategy.strategies._common import compose_rules
from strategy.strategies.strategy17.bindings import (
    FACTOR_BINDINGS,
    STRATEGY_ID,
    STRATEGY_NAME,
)
from strategy.strategies.strategy17.decision import Strategy17Decision, create_decision_engine


def _print_rules() -> str:
    return compose_rules(STRATEGY_NAME, bindings=FACTOR_BINDINGS)


def run_strategy17(cfg: Any = None, **kwargs: Any):
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
            "紫阳真君：国泰海通/国泰君安武汉紫阳东路近3个月龙虎榜成交池；"
            "买卖走因子26 多层止盈 + 因子2 预警；因子22 默认关；非默认交易池"
        ),
        factor_bindings=FACTOR_BINDINGS,
        run=run_strategy17,
        default_config=None,
        strategy_cls=None,
        print_rules=_print_rules,
        decision_factory=create_decision_engine,
        aliases=("s17", "紫阳真君", "ziyang"),
        implemented=True,
        meta={
            "default": False,
            "mode": "watch_overlay",
            "watch_tab": True,
            "universe": "factor28",
            "horizon": "rolling_3m",
            "factors": ("factor26", "factor2", "factor28", "factor22"),
            "seat": "国泰海通证券股份有限公司武汉紫阳东路证券营业部",
        },
    ),
    replace=True,
)

__all__ = [
    "STRATEGY_ID",
    "STRATEGY_NAME",
    "FACTOR_BINDINGS",
    "Strategy17Decision",
    "create_decision_engine",
    "run_strategy17",
]
