"""策略八 · 题材联动 + 因子14 + 因子1。"""

from __future__ import annotations

from strategy.core.protocols import bind_factor
from strategy.open_break import DEFAULT_PCT

STRATEGY_ID = "strategy8"
STRATEGY_NAME = "策略八·题材联动"

FACTOR_BINDINGS = (
    bind_factor(
        "factor14",
        label="题材共振（选股）",
        role="filter",
        filter_desc="**当日**涨停池 → 同题材同伴数 theme_lu_count≥3",
        enabled=True,
    ),
    bind_factor(
        "factor1",
        label="开盘突破（当日执行）",
        role="both",
        entry_pct=DEFAULT_PCT,
        stop_pct=DEFAULT_PCT,
        filter_desc=(
            "热题材内联动票（默认非当日涨停龙头）；"
            "**当日**开盘 ±阈值触达即买；T-1 情绪门槛"
        ),
        enabled=True,
    ),
)
