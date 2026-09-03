"""因子22：收盘动量（止损后自最低点收盘确认再买）。

叠在因子1 上：当日止损清仓后，若收盘站上 ``low×(1+bounce_pct)`` 则同日再买。
默认 bounce_pct=1%；可选收阳/收阴过滤。研究对照见
``backtest/tiantong_stop_rebuy_2026/``。
"""

from __future__ import annotations

from typing import Any

from strategy.close_momentum import (
    DEFAULT_BOUNCE_PCT,
    DEFAULT_CANDLE,
    DEFAULT_MODE,
    rebuy_signal,
    rules_text,
)
from strategy.core.factor_registry import register_factor
from strategy.core.protocols import FactorSpec

FACTOR_ID = "factor22"
FACTOR_NAME = "因子22-收盘动量"


def _rules() -> str:
    return rules_text(
        bounce_pct=DEFAULT_BOUNCE_PCT,
        candle=DEFAULT_CANDLE,
        mode=DEFAULT_MODE,
    )


def signal(**kw: Any) -> dict[str, Any]:
    """返回是否同日再买。

    期望关键字：open / high / low / close；可选 bounce_pct / candle / mode。
    """
    out = rebuy_signal(
        open_px=float(kw.get("open") or kw.get("open_px") or 0),
        high_px=float(kw.get("high") or kw.get("high_px") or 0),
        low_px=float(kw.get("low") or kw.get("low_px") or 0),
        close_px=float(kw.get("close") or kw.get("close_px") or 0),
        bounce_pct=float(kw.get("bounce_pct", DEFAULT_BOUNCE_PCT)),
        candle=str(kw.get("candle", DEFAULT_CANDLE)),  # type: ignore[arg-type]
        mode=str(kw.get("mode", DEFAULT_MODE)),  # type: ignore[arg-type]
        tick_ceil=kw.get("tick_ceil"),
    )
    return {
        "rebuy": bool(out.get("ok")),
        "reason": out.get("reason"),
        "thr": out.get("thr"),
        "fill_px": out.get("fill_px"),
        "kind": "close_momentum",
    }


SPEC = FactorSpec(
    id=FACTOR_ID,
    name=FACTOR_NAME,
    description=(
        "收盘动量：因子1 止损后，收盘≥当日最低价×(1+pct) 则同日再买；"
        "默认 pct=1%，可选收阳/收阴；已挂策略一"
    ),
    rules_text=_rules(),
    implemented=True,
    signal=signal,
    meta={
        "kind": "close_momentum",
        "category": "momentum",
        "overlay": "factor1_stop_rebuy",
        "default_bounce_pct": DEFAULT_BOUNCE_PCT,
        "default_candle": DEFAULT_CANDLE,
        "default_mode": DEFAULT_MODE,
        "status": "research",
        "backtest": "backtest/tiantong_stop_rebuy_2026/",
    },
)

register_factor(SPEC, replace=True)

__all__ = ["FACTOR_ID", "FACTOR_NAME", "SPEC", "signal"]
