"""策略一 · 因子绑定与策略侧过滤器。"""

from __future__ import annotations

from strategy.core.protocols import bind_factor
from strategy.open_break import DEFAULT_PCT, entry_filters_ok

STRATEGY_ID = "strategy1"
STRATEGY_NAME = "策略一"


def strategy1_factor_filter(
    prev_open: float | None = None,
    prev_close: float | None = None,
    prev2_open: float | None = None,
    prev2_close: float | None = None,
    **params: object,
) -> bool:
    mode = str(params.get("prev_entry_mode") or "yin_or_small_yang")
    pct = float(params.get("prev_small_yang_pct") or params.get("entry_pct") or DEFAULT_PCT)
    return entry_filters_ok(
        prev_open,
        prev_close,
        prev2_open,
        prev2_close,
        entry_pct=pct,
        prev_entry_mode=mode,
    )


FACTOR_BINDINGS = (
    bind_factor(
        "factor1",
        label="开盘突破主因子",
        role="both",
        entry_pct=DEFAULT_PCT,
        stop_pct=DEFAULT_PCT,
        prev_small_yang_pct=DEFAULT_PCT,
        prev_entry_mode="yin_or_small_yang",
        filter=strategy1_factor_filter,
        filter_desc="前日阴/小阳 + 禁前面双阳",
    ),
)
