"""策略四 · 因子1 开盘突破 + 因子4 牛市放宽止损 + 20% 昨高止盈 + 因子10 周频动量选股。"""

from __future__ import annotations

from strategy.binding_filters import open_break_entry_filter
from strategy.core.protocols import bind_factor
from strategy.open_break import (
    DEFAULT_BAN_DOUBLE_YANG,
    DEFAULT_BAN_SINGLE_YANG,
    DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
    DEFAULT_DOUBLE_YANG_COMBINED_MODE,
    DEFAULT_PCT,
)
STRATEGY_ID = "strategy4"
STRATEGY_NAME = "策略四·F4止盈动量"

TAKE_PROFIT_LEVELS = (0.20,)
TAKE_PROFIT_REDUCE = 1.0
TAKE_PROFIT_TRIGGER = "prev_high"
MOM_TOP_K = 5
MOM_VALUE_COL = "px_mom"

FACTOR_BINDINGS = (
    bind_factor(
        "factor1",
        label="开盘突破主因子",
        role="both",
        entry_pct=DEFAULT_PCT,
        stop_pct=DEFAULT_PCT,
        prev_small_yang_pct=DEFAULT_PCT,
        prev_entry_mode="yin_or_small_yang",
        ban_double_yang=DEFAULT_BAN_DOUBLE_YANG,
        ban_single_yang=DEFAULT_BAN_SINGLE_YANG,
        double_yang_combined_min_pct=DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
        double_yang_combined_mode=DEFAULT_DOUBLE_YANG_COMBINED_MODE,
        filter=open_break_entry_filter,
        filter_desc="前日阴/小阳 + 禁双阳跨日≥5%",
    ),
    bind_factor(
        "factor4",
        label="牛市止损放宽",
        role="custom",
        factor4_kind="roc_ma",
        factor4_stop_widen_mult=2.0,
        filter_desc="个股套用 resolve_factor4_repair；牛市内放宽止损",
    ),
    bind_factor(
        "factor10",
        label="周频20日动量选股",
        role="entry",
        top_k=MOM_TOP_K,
        value_col=MOM_VALUE_COL,
        take_profit_levels=TAKE_PROFIT_LEVELS,
        take_profit_trigger=TAKE_PROFIT_TRIGGER,
        filter_desc=(
            f"本周最后交易日 {MOM_VALUE_COL} Top{MOM_TOP_K} → 下一周才允许开仓；"
            f"止盈 {TAKE_PROFIT_LEVELS[0]*100:.0f}% {TAKE_PROFIT_TRIGGER} 全清"
        ),
    ),
)
