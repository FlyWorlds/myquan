"""策略十五 · 因子1 减磨损：F1 + 梯度 F22/F23/F24 + 震荡市 F25(30m)。"""

from __future__ import annotations

from strategy.core.protocols import bind_factor
from strategy.m30_chop import (
    DEFAULT_RECLAIM_BAND,
    DEFAULT_RECLAIM_HORIZON,
    DEFAULT_RECLAIM_PREMIUM_MAX,
    DEFAULT_STOP_CONFIRM_BARS,
    DEFAULT_TRAIL_ARM_PCT,
    DEFAULT_TRAIL_GIVEBACK_PCT,
)
from strategy.open_break import (
    DEFAULT_BAN_DOUBLE_YANG,
    DEFAULT_BAN_SINGLE_YANG,
    DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
    DEFAULT_DOUBLE_YANG_COMBINED_MODE,
    DEFAULT_PCT,
)
from strategy.strategies.strategy1.bindings import strategy1_factor_filter

STRATEGY_ID = "strategy15"
STRATEGY_NAME = "策略十五·连板减磨损"

FACTOR_BINDINGS = (
    bind_factor(
        "factor1",
        label="开盘突破建仓/止损",
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
        filter_desc="建仓以因子1为准：前日阴/小阳 + 禁双阳跨日≥5%",
    ),
    bind_factor(
        "factor22",
        label="止损后收盘动量接回",
        role="entry",
        bounce_pct=0.01,
        candle="any",
        mode="close",
        filter_desc="无 30m 时日线接回；震荡且启用 F25 时优先 30m 回补",
        enabled=True,
    ),
    bind_factor(
        "factor23",
        label="最高连板止盈",
        role="exit",
        filter_desc="最高板≤2 早止盈；3～4 板 10% 减半；≥5 放宽",
        enabled=True,
    ),
    bind_factor(
        "factor24",
        label="连板梯度情绪",
        role="filter",
        filter_desc="低/中梯度开 F22+F25；高梯度关接回；并微调止盈目标",
        enabled=True,
    ),
    bind_factor(
        "factor25",
        label="30m震荡减磨损",
        role="both",
        stop_confirm_bars=DEFAULT_STOP_CONFIRM_BARS,
        trail_arm_pct=DEFAULT_TRAIL_ARM_PCT,
        trail_giveback_pct=DEFAULT_TRAIL_GIVEBACK_PCT,
        reclaim_band=DEFAULT_RECLAIM_BAND,
        reclaim_premium_max=DEFAULT_RECLAIM_PREMIUM_MAX,
        reclaim_horizon=DEFAULT_RECLAIM_HORIZON,
        filter_desc="确认止损+动态半仓+卖飞回补；完整路径见 30m 回测",
        enabled=True,
    ),
)

__all__ = ["STRATEGY_ID", "STRATEGY_NAME", "FACTOR_BINDINGS"]
