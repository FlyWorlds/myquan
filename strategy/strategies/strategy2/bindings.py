"""策略二 · 因子绑定（同因子不同参数，演示开闭扩展）。"""

from __future__ import annotations

from strategy.core.protocols import bind_factor
from strategy.dd_topup import DEFAULT_ADD_PCT, DEFAULT_LEVELS, filter_desc as factor2_filter_desc
from strategy.open_break import prev_day_allows_entry

STRATEGY_ID = "strategy2"
STRATEGY_NAME = "策略二"


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
        label="回撤阶梯补仓",
        role="custom",
        add_pct=DEFAULT_ADD_PCT,
        levels=DEFAULT_LEVELS,
        filter_desc=factor2_filter_desc(DEFAULT_ADD_PCT, DEFAULT_LEVELS),
        enabled=True,
    ),
)
