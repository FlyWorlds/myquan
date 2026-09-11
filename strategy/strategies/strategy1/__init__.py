"""援军战法（strategy1）：因子26 多层止盈 + 因子2 回撤预警 + 因子22 收盘动量再买。

生产默认策略是 strategy16。本模块是援军战法绑定，不作为盯盘默认。
"""

from __future__ import annotations

from typing import Any, Sequence

from strategy.core.protocols import StrategySpec
from strategy.core.strategy_registry import register_strategy
from strategy.strategies._common import compose_rules
from strategy.strategies.strategy1.bindings import (
    FACTOR_BINDINGS,
    STRATEGY_ID,
    STRATEGY_NAME,
    strategy1_factor_filter,
)
from strategy.strategies.strategy1.decision import Strategy1Decision, create_decision_engine


def _print_rules() -> str:
    return compose_rules(STRATEGY_NAME, bindings=FACTOR_BINDINGS)


def run_strategy1(
    cfg: Any = None,
    *,
    show_report: bool = False,
    verbose: bool = True,
    force_daily_refresh: bool = False,
    apply_factor2_overlay: bool = False,
    factor2_add_pct: float | None = None,
    factor2_add_pcts: Sequence[float] | None = None,
    factor2_levels: Sequence[float] | None = None,
    factor2_max_inject_pct: float | None = None,
) -> tuple[Any, Any]:
    """援军战法回测：因子26 多层止盈；因子2 默认只挂预警阈值（不注资）。"""
    from strategy.strategies._factor26_runner import run_factor26_strategy

    return run_factor26_strategy(
        cfg,
        bindings=FACTOR_BINDINGS,
        strategy_name=STRATEGY_NAME,
        show_report=show_report,
        verbose=verbose,
        force_daily_refresh=force_daily_refresh,
        apply_factor2_overlay=apply_factor2_overlay,
        factor2_add_pct=factor2_add_pct,
        factor2_add_pcts=factor2_add_pcts,
        factor2_levels=factor2_levels,
        factor2_max_inject_pct=factor2_max_inject_pct,
    )


def _bind() -> StrategySpec:
    from strategy.backtest import OpenBreak3Strategy
    from strategy.config import KAICHENG

    return StrategySpec(
        id=STRATEGY_ID,
        name=STRATEGY_NAME,
        description=(
            "援军战法：因子26 开盘阈值买/多层止盈"
            " + 因子2 回撤加减仓预警（回测不注资）"
            " + 因子22 收盘动量再买"
            " + 因子13A 质量带合格池 + 因子16 龙头排序（定盘池，研究）"
        ),
        factor_bindings=FACTOR_BINDINGS,
        run=run_strategy1,
        default_config=KAICHENG,
        strategy_cls=OpenBreak3Strategy,
        print_rules=_print_rules,
        decision_factory=create_decision_engine,
        aliases=("open_break3", "s1", "策略一", "援军战法"),
        implemented=True,
        meta={
            "default": False,
            "legacy_id": "open_break3",
            "factors": ("factor26", "factor2", "factor13a", "factor16", "factor22"),
            "pool_chain": "factor13a_quality_band → factor16_pl_ratio_rank",
            "pool_size": 10,
            "stop_anchor": "day_high",
            "factor2_overlay": False,
            "factor2_alert_only": True,
        },
    )


register_strategy(_bind())


def _apply_factor2_overlay(result: Any, **kwargs: Any):
    """兼容旧导入：委托共享执行器。"""
    from strategy.strategies._factor26_runner import apply_factor2_overlay

    kwargs.setdefault("bindings", FACTOR_BINDINGS)
    kwargs.setdefault("strategy_name", STRATEGY_NAME)
    return apply_factor2_overlay(result, **kwargs)


__all__ = [
    "STRATEGY_ID",
    "STRATEGY_NAME",
    "FACTOR_BINDINGS",
    "strategy1_factor_filter",
    "Strategy1Decision",
    "create_decision_engine",
    "run_strategy1",
    "_apply_factor2_overlay",
]
