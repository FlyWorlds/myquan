"""策略绑定可复用过滤器。

只承载无状态、无策略编号的基础规则适配。具体策略通过各自 bindings 显式绑定，
避免 strategyN 直接导入另一个 strategyM。
"""

from __future__ import annotations

from strategy.open_break import (
    DEFAULT_BAN_DOUBLE_YANG,
    DEFAULT_BAN_SINGLE_YANG,
    DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT,
    DEFAULT_DOUBLE_YANG_COMBINED_MODE,
    DEFAULT_PCT,
    entry_filters_ok,
)


def open_break_entry_filter(
    prev_open: float | None = None,
    prev_close: float | None = None,
    prev2_open: float | None = None,
    prev2_close: float | None = None,
    **params: object,
) -> bool:
    """开盘突破类策略的通用前日形态过滤适配器。"""
    mode = str(params.get("prev_entry_mode") or "yin_or_small_yang")
    pct = float(params.get("prev_small_yang_pct") or params.get("entry_pct") or DEFAULT_PCT)
    ban_double = bool(params.get("ban_double_yang", DEFAULT_BAN_DOUBLE_YANG))
    ban_single = bool(params.get("ban_single_yang", DEFAULT_BAN_SINGLE_YANG))
    yang_min = float(params.get("yang_min_pct") or 0.0)
    sec = params.get("double_yang_second_min_pct")
    comb = params.get(
        "double_yang_combined_min_pct", DEFAULT_DOUBLE_YANG_COMBINED_MIN_PCT
    )
    comb_mode = str(
        params.get("double_yang_combined_mode") or DEFAULT_DOUBLE_YANG_COMBINED_MODE
    )
    single_min = params.get("single_yang_min_pct")
    return entry_filters_ok(
        prev_open,
        prev_close,
        prev2_open,
        prev2_close,
        entry_pct=pct,
        prev_entry_mode=mode,
        ban_double_yang=ban_double,
        ban_single_yang=ban_single,
        yang_min_pct=yang_min,
        double_yang_second_min_pct=float(sec) if sec is not None else None,
        double_yang_combined_min_pct=float(comb) if comb is not None else None,
        double_yang_combined_mode=comb_mode,
        single_yang_min_pct=float(single_min) if single_min is not None else None,
    )
