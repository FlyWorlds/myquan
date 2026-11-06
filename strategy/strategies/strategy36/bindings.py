"""策略三十六·科技成长空仓避险 · 因子绑定 (创业板/科创板/深成指及科技池择时与避险)。"""

from __future__ import annotations

from strategy.core.protocols import bind_factor
from strategy.dd_alert import (
    DEFAULT_AVG_YEARLY_MAX_DD,
    DEFAULT_HIST_MAX_DD,
    default_thresholds,
)
from strategy.factors.factor36 import (
    DEFAULT_REBOUND_MA,
    DEFAULT_TECH_BREADTH_PANIC,
    DEFAULT_TECH_EXIT_BREADTH,
    DEFAULT_TECH_EXTREME_PANIC,
    DEFAULT_TECH_NEW_LOW_PANIC,
    DEFAULT_TREND_MA,
)

STRATEGY_ID = "strategy36"
STRATEGY_NAME = "策略三十六·科技成长空仓避险"

_TH = default_thresholds()

FACTOR_BINDINGS = (
    bind_factor(
        "factor36",
        label="科技成长空仓因子",
        role="timing",
        trend_ma=DEFAULT_TREND_MA,
        rebound_ma=DEFAULT_REBOUND_MA,
        tech_breadth_panic=DEFAULT_TECH_BREADTH_PANIC,
        tech_extreme_panic=DEFAULT_TECH_EXTREME_PANIC,
        tech_new_low_panic=DEFAULT_TECH_NEW_LOW_PANIC,
        tech_exit_breadth=DEFAULT_TECH_EXIT_BREADTH,
        filter_desc=(
            f"创业板/深成指/科创50跌破 MA{DEFAULT_TREND_MA} 且科技池广度 < {DEFAULT_TECH_BREADTH_PANIC*100:.0f}% 或新低 > {DEFAULT_TECH_NEW_LOW_PANIC*100:.0f}% 强力空仓；"
            f"科技广度 < {DEFAULT_TECH_EXTREME_PANIC*100:.0f}% 极端熔断；突破 MA{DEFAULT_REBOUND_MA} 且广度 > {DEFAULT_TECH_EXIT_BREADTH*100:.0f}% 解除空仓"
        ),
        enabled=True,
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
            f"(年均值{_TH.avg_yearly_max_dd*100:.0f}% / 历史最大{_TH.hist_max_dd*100:.0f}%)"
        ),
        enabled=True,
    ),
)

__all__ = ["STRATEGY_ID", "STRATEGY_NAME", "FACTOR_BINDINGS"]
