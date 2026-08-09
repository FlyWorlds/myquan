"""策略三 · 挂因子2，阈值与策略一不同（演示只改 params）。"""

from __future__ import annotations

from strategy.core.protocols import bind_factor
from strategy.dd_alert import derive_thresholds

STRATEGY_ID = "strategy3"
STRATEGY_NAME = "策略三"

# 更高历史最大回撤假设 → 加仓线仍取整，但减仓线更保守（演示只改统计输入）
_TH = derive_thresholds(hist_max_dd=0.35, avg_yearly_max_dd=0.22)

FACTOR_BINDINGS = (
    bind_factor(
        "factor2",
        label="回撤加减仓预警(策略三)",
        role="custom",
        hist_max_dd=_TH.hist_max_dd,
        avg_yearly_max_dd=_TH.avg_yearly_max_dd,
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
)
