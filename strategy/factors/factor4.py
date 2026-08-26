"""因子4：行情三态 + 分档止盈（叠在因子1 上）。

以因子1 为基准：
  · 开盘±pct 买卖；触及阈值止损 → 始终全清
  · 牛市：+20/30/40% 分档减仓
  · 震荡：+10/15/20% 分档减仓
  · 下跌：+5/10/15% 分档减仓；余仓继续阈值止损
  · 可选兼容旧「牛市暂停止损 / 放宽止损 / 开盘建仓」
"""

from __future__ import annotations

from typing import Any

from strategy.bull_regime import (
    DEFAULT_BULL_KIND,
    DEFAULT_BULL_PARAMS,
    build_bull_regime,
    build_market_regime_series,
    bull_rules_text,
    factor4_rules_text,
    market_regime_by_date,
    resolve_factor4_tp_policy,
)
from strategy.core.factor_registry import register_factor
from strategy.core.protocols import FactorSpec

FACTOR_ID = "factor4"
FACTOR_NAME = "因子4·行情止盈"


def _rules() -> str:
    return factor4_rules_text(DEFAULT_BULL_PARAMS)


def is_bull_regime(
    bull_exec: float | None,
    *,
    min_raw: float | None = None,
    raw: float | None = None,
) -> bool:
    if bull_exec is None:
        return False
    if float(bull_exec) < 0.5:
        return False
    if min_raw is not None and raw is not None:
        return float(raw) >= float(min_raw)
    return True


def factor4_signal(**kwargs: Any) -> dict[str, Any]:
    """研究信号：返回当日 regime 与止盈政策摘要。"""
    regime = kwargs.get("regime") or kwargs.get("regime_exec")
    bull = kwargs.get("bull_exec")
    if bull is None and regime is not None:
        bull = 1.0 if str(regime) == "bull" else 0.0
    policy = resolve_factor4_tp_policy(kwargs.get("params"))
    return {
        "factor_id": FACTOR_ID,
        "bull": is_bull_regime(bull if bull is None else float(bull or 0.0)),
        "regime": None if regime is None else str(regime),
        "tp_policy": policy,
        "stop_policy": "threshold_full_exit",
    }


SPEC = FactorSpec(
    id=FACTOR_ID,
    name=FACTOR_NAME,
    description=(
        "叠因子1：牛20/30/40、震10/15/20、跌5/10/15 分档减仓；"
        "开盘阈值止损始终全清"
    ),
    rules_text=_rules(),
    implemented=True,
    signal=factor4_signal,
    meta={
        "kind": "regime_take_profit",
        "default_kind": DEFAULT_BULL_KIND,
        "default_params": dict(DEFAULT_BULL_PARAMS),
        "overlay": "factor1_regime_tp",
        "regimes": ("bull", "sideways", "bear"),
        "stop": "threshold_full_clear",
        "research_only": True,
    },
)

register_factor(SPEC, replace=True)

__all__ = [
    "FACTOR_ID",
    "FACTOR_NAME",
    "SPEC",
    "is_bull_regime",
    "factor4_signal",
    "build_bull_regime",
    "build_market_regime_series",
    "market_regime_by_date",
    "resolve_factor4_tp_policy",
    "bull_rules_text",
    "factor4_rules_text",
]
