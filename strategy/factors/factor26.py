"""因子26：浮盈回落一半止盈（买同开盘突破，卖=持仓最高浮盈回落一半）。"""

from __future__ import annotations

from typing import Any

from strategy.core.factor_registry import register_factor
from strategy.core.protocols import FactorSpec
from strategy.open_break import entry_filters_ok
from strategy.pullback_wave_stop import (
    DEFAULT_ENTRY_PCT,
    DEFAULT_GIVEBACK_RATIO,
    DEFAULT_PULLBACK_PCT,
    STRATEGY_RULES,
    replay_last_factor_triggers,
    rules_text,
    strategy_levels,
    strategy_signal,
)

FACTOR_ID = "factor26"
FACTOR_NAME = "因子26-浮盈回落一半止盈"


def _rules() -> str:
    return STRATEGY_RULES.strip()


def levels(open_px: float, **kw: Any) -> dict[str, Any]:
    return strategy_levels(open_px, **kw)


def signal(**kw: Any) -> dict[str, Any]:
    return strategy_signal(**kw)


SPEC = FactorSpec(
    id=FACTOR_ID,
    name=FACTOR_NAME,
    description=(
        "浮盈回落一半止盈：买=开盘突破或攻击波；"
        "卖=持仓最高相对成本浮盈回落一半（未浮盈成本硬保护）；"
        "成交触达按 1 分钟顺序（同根 K 先判后更新高低）；选股/回撤用日线；池回测近 7 日 1m；"
        f"默认 entry ±{DEFAULT_ENTRY_PCT*100:.1f}% / giveback {DEFAULT_GIVEBACK_RATIO*100:.0f}%"
    ),
    rules_text=_rules(),
    implemented=True,
    levels=levels,
    filters_ok=entry_filters_ok,
    signal=signal,
    replay=replay_last_factor_triggers,
    meta={
        "kind": "half_gain_take_profit",
        "category": "execution",
        "default_entry_pct": DEFAULT_ENTRY_PCT,
        "default_pullback_pct": DEFAULT_PULLBACK_PCT,
        "default_giveback_ratio": DEFAULT_GIVEBACK_RATIO,
        "replaces": "factor1_stop",
        "status": "production_watch",
        "buy_modes": ("open_break", "attack_wave"),
        "exit": "half_gain",
    },
)

register_factor(SPEC, replace=True)

__all__ = ["FACTOR_ID", "FACTOR_NAME", "SPEC", "rules_text"]
