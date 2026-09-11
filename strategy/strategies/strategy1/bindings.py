"""援军战法（strategy1）· 因子绑定与策略侧过滤器。"""

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

STRATEGY_ID = "strategy1"
STRATEGY_NAME = "援军战法"

_TH = default_thresholds()


# 兼容旧导入名；实现位于无策略编号的基础过滤层。
strategy1_factor_filter = open_break_entry_filter


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
        filter=strategy1_factor_filter,
        filter_desc="买=开盘阈值；卖=硬保护2.5% / 中赚3–10%回落一半与0.5×20日日频σ谁先到走谁 / 阶梯10%·15% / 未到3%次日峰值回落2.5%",
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
        "factor13a",
        label="质量带合格池",
        role="universe",
        filter_desc="沪深300+500+1000+1500 主板；夏普/回撤甜区 walk-forward；初选≤40",
        enabled=True,
    ),
    bind_factor(
        "factor16",
        label="龙头排序",
        role="entry",
        filter_desc="f13_pass → OOS 闭环盈亏比/利润因子排序 → Top10 定盘池",
        enabled=True,
    ),
    bind_factor(
        "factor22",
        label="收盘动量",
        role="entry",
        bounce_pct=0.01,
        candle="any",
        mode="close",
        filter_desc="因子26 止损后：收盘≥当日最低价×(1+1%) 同日再买；默认 1%、不限阴阳",
        enabled=True,
    ),
)
