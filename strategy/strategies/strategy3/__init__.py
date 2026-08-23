"""策略三：因子5事件建仓、单主题一只、固定持有五日的五槽位策略。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from strategy.core.protocols import StrategySpec
from strategy.core.strategy_registry import register_strategy
from strategy.strategies._common import compose_rules
from strategy.strategies.strategy3.bindings import (
    FACTOR_BINDINGS,
    STRATEGY_ID,
    STRATEGY_NAME,
)


def _print_rules() -> str:
    return compose_rules(STRATEGY_NAME, bindings=FACTOR_BINDINGS)


def refresh_strategy3_factor5(
    *,
    asof: str | None = None,
    posts_path: str | Path | None = None,
    output: str | Path | None = None,
) -> dict[str, Any]:
    """刷新当天因子5候选池；没有合格新帖时输出为空池。"""
    from strategy.backtest_factor5_serenity import _zz500_1000_mainboard_codes
    from strategy.serenity_factor5 import DEFAULT_OUTPUT, write_snapshot

    snapshot = write_snapshot(
        output or DEFAULT_OUTPUT,
        posts_path=posts_path,
        asof=asof,
        lookback_days=0,
        eligible_codes=_zz500_1000_mainboard_codes(),
    )
    return {
        "strategy_id": STRATEGY_ID,
        "factor_id": "factor5",
        "snapshot": str(snapshot),
        "event_driven": True,
        "max_positions": 5,
    }


def run_strategy3(
    *,
    start: str = "20260101",
    end: str = "20260815",
    max_themes: int = 3,
    max_positions: int = 5,
    max_per_theme: int = 1,
    hold_days: int = 5,
    initial_cash: float = 1_000_000.0,
    posts_path: str | Path | None = None,
) -> dict[str, Any]:
    """运行因子5事件回测。

    因子5事件候选在下一交易日开盘填充最多五个空槽；每主题最多一只，
    持有五个交易日后开盘退出。新事件同主题替换旧票，不同主题满仓时替换
    最早入池持仓；无候选时保留现金。
    """
    from strategy.backtest_factor5_serenity import run_backtest
    from strategy.serenity_factor5 import DEFAULT_POSTS

    return run_backtest(
        start=start,
        end=end,
        max_themes=max_themes,
        max_positions=max_positions,
        max_per_theme=max_per_theme,
        hold_days=hold_days,
        use_factor1_stop=False,
        initial_cash=initial_cash,
        posts_path=posts_path or DEFAULT_POSTS,
    )


refresh_strategy7_factor5 = refresh_strategy3_factor5
run_strategy7 = run_strategy3


def _bind() -> StrategySpec:
    return StrategySpec(
        id=STRATEGY_ID,
        name=STRATEGY_NAME,
        description=(
            "因子5事件候选填充最多五个仓位；单主题最多一只、固定持有五日；"
            "新事件可替换同主题旧票或满仓时最早入池持仓。"
        ),
        factor_bindings=FACTOR_BINDINGS,
        run=run_strategy3,
        default_config={
            "start": "20260101",
            "max_themes": 3,
            "max_positions": 5,
            "max_per_theme": 1,
            "hold_days": 5,
        },
        print_rules=_print_rules,
        aliases=(
            "s3",
            "s7",
            "strategy7",
            "factor5_serenity",
            "策略三",
            "策略七",
        ),
        implemented=True,
        meta={
            "factors": ("factor5",),
            "execution": "event_driven_slots_fixed_hold",
            "source_skill": "serenity-research-model",
        },
    )


register_strategy(_bind())

__all__ = [
    "STRATEGY_ID",
    "STRATEGY_NAME",
    "FACTOR_BINDINGS",
    "refresh_strategy3_factor5",
    "refresh_strategy7_factor5",
    "run_strategy3",
    "run_strategy7",
]
