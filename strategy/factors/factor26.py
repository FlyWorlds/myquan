"""因子26：浮盈多层止盈（买同开盘突破；卖=阶梯10/15 + 回吐一半 + 峰值回落3%半仓 + 隔夜下杀）。"""

from __future__ import annotations

from typing import Any

from strategy.core.factor_registry import register_factor
from strategy.core.protocols import FactorSpec
from strategy.open_break import entry_filters_ok
from strategy.pullback_wave_stop import (
    DEFAULT_ENTRY_PCT,
    DEFAULT_GIVEBACK_RATIO,
    DEFAULT_LADDER_FULL_PCT,
    DEFAULT_LADDER_HALF_PCT,
    DEFAULT_PEAK_PULLBACK_X,
    DEFAULT_PULLBACK_PCT,
    STRATEGY_RULES,
    replay_last_factor_triggers,
    rules_text,
    strategy_levels,
    strategy_signal,
)

FACTOR_ID = "factor26"
FACTOR_NAME = "因子26-多层止盈"


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
        "多层止盈：买=开盘突破或攻击波；"
        f"卖=阶梯{DEFAULT_LADDER_HALF_PCT*100:.0f}%半仓/"
        f"{DEFAULT_LADDER_FULL_PCT*100:.0f}%全清 + 浮盈回吐一半 + "
        f"峰值回落{DEFAULT_PEAK_PULLBACK_X*100:.0f}%半仓 + 昨亏/止盈标记次日开盘下杀1%；"
        "成交触达按 1 分钟顺序；选股/回撤用日线；池回测近 7 日 1m；"
        f"默认 entry ±{DEFAULT_ENTRY_PCT*100:.1f}% / giveback {DEFAULT_GIVEBACK_RATIO*100:.0f}%"
    ),
    rules_text=_rules(),
    implemented=True,
    levels=levels,
    filters_ok=entry_filters_ok,
    signal=signal,
    replay=replay_last_factor_triggers,
    meta={
        "kind": "multi_take_profit",
        "category": "execution",
        "default_entry_pct": DEFAULT_ENTRY_PCT,
        "default_pullback_pct": DEFAULT_PULLBACK_PCT,
        "default_giveback_ratio": DEFAULT_GIVEBACK_RATIO,
        "ladder_half_pct": DEFAULT_LADDER_HALF_PCT,
        "ladder_full_pct": DEFAULT_LADDER_FULL_PCT,
        "peak_pullback_x": DEFAULT_PEAK_PULLBACK_X,
        "replaces": "factor1_stop",
        "status": "production_watch",
        "buy_modes": ("open_break", "attack_wave"),
        "exit": "multi_tp",
    },
)

register_factor(SPEC, replace=True)

__all__ = ["FACTOR_ID", "FACTOR_NAME", "SPEC", "rules_text"]
