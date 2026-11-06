"""策略三十五·多维空仓避险 · 因子绑定 (大盘择时与全局空仓防守)。"""

from __future__ import annotations

from strategy.core.protocols import bind_factor
from strategy.dd_alert import (
    DEFAULT_AVG_YEARLY_MAX_DD,
    DEFAULT_HIST_MAX_DD,
    default_thresholds,
)
from strategy.factors.factor35 import (
    DEFAULT_BREADTH_PANIC,
    DEFAULT_EXIT_BREADTH,
    DEFAULT_EXTREME_PANIC,
    DEFAULT_NEW_LOW_PANIC,
    DEFAULT_REBOUND_MA,
    DEFAULT_TREND_MA,
)

STRATEGY_ID = "strategy35"
STRATEGY_NAME = "策略三十五·多维空仓避险"

_TH = default_thresholds()

FACTOR_BINDINGS = (
    bind_factor(
        "factor35",
        label="多维复合空仓因子",
        role="timing",
        trend_ma=DEFAULT_TREND_MA,
        rebound_ma=DEFAULT_REBOUND_MA,
        breadth_panic=DEFAULT_BREADTH_PANIC,
        extreme_panic=DEFAULT_EXTREME_PANIC,
        new_low_panic=DEFAULT_NEW_LOW_PANIC,
        exit_breadth=DEFAULT_EXIT_BREADTH,
        filter_desc=(
            f"大盘跌破 MA{DEFAULT_TREND_MA} 且全市场广度 < {DEFAULT_BREADTH_PANIC*100:.0f}% 或新低 > {DEFAULT_NEW_LOW_PANIC*100:.0f}% 强力空仓；"
            f"广度 < {DEFAULT_EXTREME_PANIC*100:.0f}% 极端熔断；突破 MA{DEFAULT_REBOUND_MA} 且广度 > {DEFAULT_EXIT_BREADTH*100:.0f}% 解除空仓"
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
