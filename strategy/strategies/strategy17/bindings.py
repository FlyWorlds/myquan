"""策略十七·紫阳真君 · 因子绑定（宇宙=因子28；买卖走因子26）。"""

from __future__ import annotations

from strategy.binding_filters import open_break_entry_filter
from strategy.core.protocols import bind_factor
from strategy.dd_alert import (
    DEFAULT_AVG_YEARLY_MAX_DD,
    DEFAULT_HIST_MAX_DD,
    default_thresholds,
)
from strategy.open_break import (
    DEFAULT_BAN_DOUBLE_YANG,
    DEFAULT_BAN_SINGLE_YANG,
    DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
    DEFAULT_DOUBLE_YANG_COMBINED_MODE,
    DEFAULT_PCT,
)

STRATEGY_ID = "strategy17"
STRATEGY_NAME = "策略十七·紫阳真君"

_TH = default_thresholds()

FACTOR_BINDINGS = (
    bind_factor(
        "factor26",
        label="多层止盈",
        role="both",
        entry_pct=DEFAULT_PCT,
        stop_pct=DEFAULT_PCT,
        pullback_pct=DEFAULT_PCT,
        giveback_ratio=0.5,
        prev_small_yang_pct=DEFAULT_PCT,
        prev_entry_mode="yin_or_small_yang",
        ban_double_yang=DEFAULT_BAN_DOUBLE_YANG,
        ban_single_yang=DEFAULT_BAN_SINGLE_YANG,
        double_yang_combined_min_pct=DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
        double_yang_combined_mode=DEFAULT_DOUBLE_YANG_COMBINED_MODE,
        filter=open_break_entry_filter,
        filter_desc="买=开盘阈值；卖=硬保护/中赚回落一半与波动回落谁先到走谁/阶梯止盈；同策略十六内核",
    ),
    bind_factor(
        "factor2",
        label="回撤加减仓预警",
        role="custom",
        hist_max_dd=DEFAULT_HIST_MAX_DD,
        avg_yearly_max_dd=DEFAULT_AVG_YEARLY_MAX_DD,
        add_alert_dd=_TH.add_alert_dd,
        reduce_alert_dd=_TH.reduce_alert_dd,
        overlay=False,
        filter_desc=(
            f"加仓≥{_TH.add_alert_dd*100:.0f}% / 减仓≤{_TH.reduce_alert_dd*100:.0f}% "
            f"(年均值{_TH.avg_yearly_max_dd*100:.0f}% / 历史最大{_TH.hist_max_dd*100:.0f}%)；"
            "回测不注资"
        ),
        enabled=True,
    ),
    bind_factor(
        "factor28",
        label="紫阳真君近3个月池",
        role="universe",
        filter_desc="国泰海通/国泰君安武汉紫阳东路近3个月龙虎榜成交并集（买或卖任一出现）",
        enabled=True,
    ),
    bind_factor(
        "factor22",
        label="收盘动量",
        role="entry",
        bounce_pct=0.01,
        candle="any",
        mode="close",
        filter_desc="研究对照；生产默认关闭",
        enabled=False,
    ),
)

__all__ = ["STRATEGY_ID", "STRATEGY_NAME", "FACTOR_BINDINGS"]
