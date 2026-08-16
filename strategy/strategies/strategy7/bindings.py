"""策略七 · 因子绑定：因子1 + 因子4 牛市持股修复。"""

from __future__ import annotations

from strategy.config import FACTOR4_REPAIR_UNIFIED
from strategy.core.protocols import bind_factor
from strategy.strategies.strategy1.bindings import strategy1_factor_filter

STRATEGY_ID = "strategy7"
STRATEGY_NAME = "策略七"

_F4 = FACTOR4_REPAIR_UNIFIED

FACTOR_BINDINGS = (
    bind_factor(
        "factor1",
        label="开盘突破主因子",
        role="both",
        entry_pct=0.025,
        stop_pct=0.025,
        prev_small_yang_pct=0.025,
        prev_entry_mode="yin_or_small_yang",
        filter=strategy1_factor_filter,
        filter_desc="前日阴/小阳 + 禁双阳跨日≥5%",
    ),
    bind_factor(
        "factor4",
        label="牛市持股修复",
        role="custom",
        kind=str(_F4["factor4_kind"]),
        n=60,
        ma_n=60,
        suppress_stop_in_bull=True,
        stop_widen_mult=float(_F4.get("factor4_stop_widen_mult") or 0.0),
        bull_entry=False,
        filter_desc=(
            "牛市=roc_ma(N)且收盘>MA(N)；牛市内止损放宽2倍或暂停止损"
        ),
        enabled=True,
    ),
)
