"""策略十三 · 纯因子1 ETF：单票独立阈值，宇宙由 walk-forward 选票产出。"""

from __future__ import annotations

from strategy.core.protocols import bind_factor
from strategy.open_break import (
    DEFAULT_BAN_DOUBLE_YANG,
    DEFAULT_BAN_SINGLE_YANG,
    DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
    DEFAULT_DOUBLE_YANG_COMBINED_MODE,
    DEFAULT_PCT,
)
from strategy.strategies.strategy1.bindings import strategy1_factor_filter

STRATEGY_ID = "strategy13"
STRATEGY_NAME = "策略十三·因子1ETF"

FACTOR_BINDINGS = (
    bind_factor(
        "factor1",
        label="开盘突破（ETF）",
        role="both",
        entry_pct=DEFAULT_PCT,
        stop_pct=DEFAULT_PCT,
        prev_small_yang_pct=DEFAULT_PCT,
        prev_entry_mode="yin_or_small_yang",
        ban_double_yang=DEFAULT_BAN_DOUBLE_YANG,
        ban_single_yang=DEFAULT_BAN_SINGLE_YANG,
        double_yang_combined_min_pct=DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
        double_yang_combined_mode=DEFAULT_DOUBLE_YANG_COMBINED_MODE,
        filter=strategy1_factor_filter,
        filter_desc="前日阴/小阳 + 禁双阳；单票阈值见 etf_wf/top10_pool.json",
    ),
)

__all__ = ["STRATEGY_ID", "STRATEGY_NAME", "FACTOR_BINDINGS"]
