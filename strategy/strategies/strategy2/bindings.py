"""策略二 · 因子绑定（同因子不同参数，演示开闭扩展）。"""

from __future__ import annotations

from strategy.core.protocols import bind_factor
from strategy.dd_alert import (
    DEFAULT_AVG_YEARLY_MAX_DD,
    DEFAULT_HIST_MAX_DD,
    default_thresholds,
)
from strategy.open_break import prev_day_allows_entry

STRATEGY_ID = "strategy2"
STRATEGY_NAME = "策略二"

_TH = default_thresholds()


def strict_yin_filter(
    prev_open: float | None = None,
    prev_close: float | None = None,
    prev2_open: float | None = None,
    prev2_close: float | None = None,
    **params: object,
) -> bool:
    """仅前日阴线可买（与策略一阴/小阳不同）。"""
    del prev2_open, prev2_close
    if prev_open is None or prev_close is None:
        return False
    return prev_day_allows_entry(
        float(prev_open),
        float(prev_close),
        prev_small_yang_pct=float(params.get("prev_small_yang_pct") or 0.025),
        prev_entry_mode="yin_only",
    )


FACTOR_BINDINGS = (
    bind_factor(
        "factor1",
        label="开盘突破(严过滤)",
        role="both",
        entry_pct=0.03,
        stop_pct=0.03,
        prev_small_yang_pct=0.03,
        prev_entry_mode="yin_only",
        filter=strict_yin_filter,
        filter_desc="仅前日阴线可买（yin_only）；阈值±3%",
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
        enabled=True,
    ),
)
