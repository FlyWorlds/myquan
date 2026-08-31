"""策略十二 · 情绪门控开盘突破：因子18 恐慌禁开仓 + 因子1 执行 + 因子2 预警。"""

from __future__ import annotations

from strategy.core.protocols import bind_factor
from strategy.dd_alert import DEFAULT_AVG_YEARLY_MAX_DD, DEFAULT_HIST_MAX_DD, default_thresholds
from strategy.open_break import DEFAULT_PCT
from strategy.strategies.strategy1.bindings import strategy1_factor_filter

STRATEGY_ID = "strategy12"
STRATEGY_NAME = "策略十二·情绪门控开盘突破"

_TH = default_thresholds()

FACTOR_BINDINGS = (
    bind_factor(
        "factor18",
        label="低开跌停情绪门控",
        role="filter",
        filter_desc="中证1000 低开开盘跌停≥4（恐慌）→ 当日禁止新开仓；已有仓仍按因子1 止损",
    ),
    bind_factor(
        "factor1",
        label="开盘突破（执行）",
        role="both",
        entry_pct=DEFAULT_PCT,
        stop_pct=DEFAULT_PCT,
        prev_small_yang_pct=DEFAULT_PCT,
        prev_entry_mode="yin_or_small_yang",
        filter=strategy1_factor_filter,
        filter_desc="同策略一：前日阴/小阳 + 禁双阳跨日≥5%；恐慌日不新开",
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
            f"加仓≥{_TH.add_alert_dd*100:.0f}% / 减仓≤{_TH.reduce_alert_dd*100:.0f}%；"
            "回测不注资"
        ),
    ),
)

__all__ = ["STRATEGY_ID", "STRATEGY_NAME", "FACTOR_BINDINGS"]
