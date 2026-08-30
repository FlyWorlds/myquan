"""策略三：首板晋级 — 昨日首板 → 次日因子1 开盘突破。"""

from __future__ import annotations

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


def run_strategy3(
    *,
    start: str = "20200101",
    end: str | None = None,
    entry_pcts: tuple[float, ...] | None = None,
    entry_pct: float | None = None,
    initial_cash: float = 1_000_000.0,
    max_positions: int = 10,
    mkt_lu_min: int | None = None,
    mkt_lu_max: int | None = None,
    mkt_lianban_min: int | None = 2,
    mkt_max_height_min: int | None = 2,
    mkt_max_height_max: int | None = 5,
    rebuild_signals: bool = False,
    **_: Any,
) -> dict[str, Any]:
    """首板晋级组合回测。默认同时跑 2.5% 与 3% 阈值。"""
    from strategy.strategies.strategy3.first_board import (
        run_first_board_promotion_backtest,
    )

    if entry_pcts is None:
        if entry_pct is not None:
            entry_pcts = (float(entry_pct),)
        else:
            entry_pcts = (0.025, 0.03)
    return run_first_board_promotion_backtest(
        start=start,
        end=end,
        entry_pcts=tuple(float(x) for x in entry_pcts),
        initial_cash=initial_cash,
        max_positions=max_positions,
        mkt_lu_min=mkt_lu_min,
        mkt_lu_max=mkt_lu_max,
        mkt_lianban_min=mkt_lianban_min,
        mkt_max_height_min=mkt_max_height_min,
        mkt_max_height_max=mkt_max_height_max,
        rebuild_signals=rebuild_signals,
    )


def _bind() -> StrategySpec:
    return StrategySpec(
        id=STRATEGY_ID,
        name=STRATEGY_NAME,
        description=(
            "盯盘：中证1000昨日涨停池，T-1 连板梯度门槛 + 涨停家数冰点/正常/高潮展示，"
            "晋级日因子1 ±阈值（不过阴/小阳过门）；"
            "回测：首板+gap/量比+情绪，见 backtest/strategy3_first_board"
        ),
        factor_bindings=FACTOR_BINDINGS,
        run=run_strategy3,
        default_config={
            "start": "20200101",
            "entry_pcts": (0.025, 0.03),
            "max_positions": 5,
        },
        print_rules=_print_rules,
        aliases=(
            "s3",
            "first_board",
            "首板晋级",
            "策略三",
        ),
        implemented=True,
        meta={
            "factors": ("factor1",),
            "execution": "first_board_promotion",
            "universe": "csi1000_first_limit_up",
        },
    )


register_strategy(_bind())

__all__ = [
    "STRATEGY_ID",
    "STRATEGY_NAME",
    "FACTOR_BINDINGS",
    "run_strategy3",
]
