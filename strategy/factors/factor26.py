"""因子26：回落波阈值止损（买同开盘突破，止损=分时最高回落）。"""

from __future__ import annotations

from typing import Any

from strategy.core.factor_registry import register_factor
from strategy.core.protocols import FactorSpec
from strategy.open_break import entry_filters_ok
from strategy.pullback_wave_stop import (
    DEFAULT_ENTRY_PCT,
    DEFAULT_PULLBACK_PCT,
    STRATEGY_RULES,
    replay_last_factor_triggers,
    rules_text,
    strategy_levels,
    strategy_signal,
)

FACTOR_ID = "factor26"
FACTOR_NAME = "因子26-回落波阈值止损"


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
        "回落波阈值止损：买=开盘突破或攻击波；卖=分时最高回落；"
        "成交触达按 1 分钟顺序；选股/回撤用日线；池回测近 7 日 1m；默认 ±2.5%"
    ),
    rules_text=_rules(),
    implemented=True,
    levels=levels,
    filters_ok=entry_filters_ok,
    signal=signal,
    replay=replay_last_factor_triggers,
    meta={
        "kind": "pullback_wave_stop",
        "category": "execution",
        "default_entry_pct": DEFAULT_ENTRY_PCT,
        "default_pullback_pct": DEFAULT_PULLBACK_PCT,
        "replaces": "factor1_stop",
        "status": "production_watch",
        "buy_modes": ("open_break", "attack_wave"),
    },
)

register_factor(SPEC, replace=True)

__all__ = ["FACTOR_ID", "FACTOR_NAME", "SPEC", "rules_text"]
