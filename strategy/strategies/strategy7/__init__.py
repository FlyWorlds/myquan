"""策略七：因子5事件建仓 + 因子1止损的五槽位主题策略。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from strategy.core.protocols import StrategySpec
from strategy.core.strategy_registry import register_strategy
from strategy.strategies._common import compose_rules
from strategy.strategies.strategy7.bindings import (
    FACTOR_BINDINGS,
    STRATEGY_ID,
    STRATEGY_NAME,
)


def _print_rules() -> str:
    return compose_rules(STRATEGY_NAME, bindings=FACTOR_BINDINGS)


def refresh_strategy7_factor5(
    *,
    asof: str | None = None,
    posts_path: str | Path | None = None,
    output: str | Path | None = None,
) -> dict[str, Any]:
    """刷新当天因子5候选池；没有合格新帖时输出为空池。"""
    from strategy.serenity_factor5 import DEFAULT_OUTPUT, write_snapshot

    snapshot = write_snapshot(
        output or DEFAULT_OUTPUT,
        posts_path=posts_path,
        asof=asof,
        lookback_days=0,
    )
    return {
        "strategy_id": STRATEGY_ID,
        "factor_id": "factor5",
        "snapshot": str(snapshot),
        "event_driven": True,
        "max_positions": 5,
    }


def run_strategy7(
    *,
    start: str = "20260101",
    end: str = "20260815",
    max_themes: int = 3,
    max_positions: int = 5,
    stop_pct: float = 0.025,
    initial_cash: float = 1_000_000.0,
    posts_path: str | Path | None = None,
) -> dict[str, Any]:
    """运行因子5事件回测。

    因子5事件候选在下一交易日开盘填充最多五个空槽；因子1仅负责盘中止损。
    无候选或空槽未能补足时保留现金，不设固定持有期限。
    """
    from strategy.backtest_factor5_serenity import run_backtest
    from strategy.serenity_factor5 import DEFAULT_POSTS

    return run_backtest(
        start=start,
        end=end,
        max_themes=max_themes,
        max_positions=max_positions,
        stop_pct=stop_pct,
        initial_cash=initial_cash,
        posts_path=posts_path or DEFAULT_POSTS,
    )


def _bind() -> StrategySpec:
    return StrategySpec(
        id=STRATEGY_ID,
        name=STRATEGY_NAME,
        description=(
            "因子5事件候选填充最多五个仓位，因子1仅止损卖出；"
            "每日补足空槽，候选不足时保持现金，不设固定持有期。"
        ),
        factor_bindings=FACTOR_BINDINGS,
        run=run_strategy7,
        default_config={
            "start": "20260101",
            "max_themes": 3,
            "max_positions": 5,
            "stop_pct": 0.025,
        },
        print_rules=_print_rules,
        aliases=("s7", "factor5_serenity", "策略七"),
        implemented=True,
        meta={
            "factors": ("factor5", "factor1"),
            "execution": "event_driven_slots_factor1_stop",
            "source_skill": "serenity-research-model",
        },
    )


register_strategy(_bind())

__all__ = [
    "STRATEGY_ID",
    "STRATEGY_NAME",
    "FACTOR_BINDINGS",
    "refresh_strategy7_factor5",
    "run_strategy7",
]
