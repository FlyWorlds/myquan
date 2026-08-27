"""缠论笔算盈亏比（strategy11）· 因子绑定。

交易真源仍是因子1（开盘突破）；本策略的研究产出是日线笔归因盈亏比、
让利与防守，不改变因子1 下单规则。
"""

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

STRATEGY_ID = "strategy11"
STRATEGY_NAME = "缠论笔算盈亏比"

FACTOR_BINDINGS = (
    bind_factor(
        "factor1",
        label="开盘突破（笔归因记账）",
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
        filter_desc="前日阴/小阳 + 禁双阳跨日≥5%；卖点跨笔时差价记入买入笔",
    ),
)

__all__ = [
    "STRATEGY_ID",
    "STRATEGY_NAME",
    "FACTOR_BINDINGS",
    "strategy1_factor_filter",
]
