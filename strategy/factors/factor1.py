"""因子1：开盘突破 ±pct（默认 ±2.5%）。

实现复用 strategy.open_break（回测与盯盘同源），本模块只做可插拔包装。
"""

from __future__ import annotations

from strategy.core.factor_registry import register_factor
from strategy.core.protocols import FactorSpec
from strategy.open_break import (
    DEFAULT_PCT,
    STRATEGY_RULES,
    entry_filters_ok,
    replay_last_factor_triggers,
    strategy_levels,
    strategy_signal,
)

FACTOR_ID = "factor1"
FACTOR_NAME = "因子1"


def _rules() -> str:
    return STRATEGY_RULES.strip()


SPEC = FactorSpec(
    id=FACTOR_ID,
    name=FACTOR_NAME,
    description="开盘突破：买=开盘+pct，卖=开盘-pct止损；前日阴/小阳+禁双阳跨日≥5%；T+1",
    rules_text=_rules(),
    implemented=True,
    levels=strategy_levels,
    filters_ok=entry_filters_ok,
    signal=strategy_signal,
    replay=replay_last_factor_triggers,
    meta={
        "default_pct": DEFAULT_PCT,
        "kind": "open_break",
        "legacy_name": "OpenBreak3",
    },
)

register_factor(SPEC)
