"""因子4：牛市持股 regime（修复因子1在趋势市跑输平权持有）。

叠在因子1上时：
  · 牛市 regime 内持仓 → 暂停止损（持股不动）
  · 可选牛市空仓 → 开盘建仓持股
  · 非牛市 → 因子1 原逻辑
"""

from __future__ import annotations

from typing import Any

from strategy.bull_regime import (
    DEFAULT_BULL_KIND,
    DEFAULT_BULL_PARAMS,
    bull_rules_text,
    build_bull_regime,
)
from strategy.core.factor_registry import register_factor
from strategy.core.protocols import FactorSpec

FACTOR_ID = "factor4"
FACTOR_NAME = "因子4"


def _rules() -> str:
    return bull_rules_text(DEFAULT_BULL_KIND, DEFAULT_BULL_PARAMS)


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


SPEC = FactorSpec(
    id=FACTOR_ID,
    name=FACTOR_NAME,
    description="牛市持股：趋势 regime 内暂停止损；可选空仓开盘建仓",
    rules_text=_rules(),
    implemented=True,
    signal=lambda **kw: {"bull": is_bull_regime(kw.get("bull_exec"))},
    meta={
        "kind": "bull_hold",
        "default_kind": DEFAULT_BULL_KIND,
        "default_params": dict(DEFAULT_BULL_PARAMS),
        "overlay": "factor1_stop_suppress",
    },
)

register_factor(SPEC, replace=True)

__all__ = [
    "FACTOR_ID",
    "FACTOR_NAME",
    "SPEC",
    "is_bull_regime",
    "build_bull_regime",
]
