"""因子14：MACD 择时（教科书买图标准）。"""

from __future__ import annotations

from strategy.core.factor_registry import register_factor
from strategy.core.protocols import FactorSpec
from strategy.macd_timing import (
    DEFAULT_FAST,
    DEFAULT_MODE,
    DEFAULT_SIGNAL,
    DEFAULT_SLOW,
    compute_macd,
    macd_rules_text,
    macd_signals,
    strategy_signal,
)

FACTOR_ID = "factor14"
FACTOR_NAME = "因子14·MACD"


SPEC = FactorSpec(
    id=FACTOR_ID,
    name=FACTOR_NAME,
    description=(
        "MACD 买图：默认放宽（金叉|即将|快要|金叉趋势 买；"
        "死叉|即将|快要|死叉趋势 卖）；收盘确认次日开盘"
    ),
    rules_text=macd_rules_text(),
    implemented=True,
    signal=strategy_signal,
    meta={
        "kind": "macd_timing",
        "standalone": True,
        "default_fast": DEFAULT_FAST,
        "default_slow": DEFAULT_SLOW,
        "default_signal": DEFAULT_SIGNAL,
        "default_mode": DEFAULT_MODE,
        "compute": "strategy.macd_timing.compute_macd",
        "signals": "strategy.macd_timing.macd_signals",
    },
)

register_factor(SPEC, replace=True)

__all__ = [
    "FACTOR_ID",
    "FACTOR_NAME",
    "SPEC",
    "compute_macd",
    "macd_signals",
    "macd_rules_text",
    "strategy_signal",
]
