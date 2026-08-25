"""因子 CF1：流动性门控反转。"""

from __future__ import annotations

from typing import Any

from strategy.cf1_liquidity_gated_reversal import (
    DEFAULT_PARAMS,
    FACTOR_ID,
    FACTOR_NAME,
    cf1_rules_text,
    cf1_signal,
    compute_cf1,
)
from strategy.core.factor_registry import register_factor
from strategy.core.protocols import FactorSpec

SPEC = FactorSpec(
    id=FACTOR_ID,
    name=FACTOR_NAME,
    description=(
        "短期反转为主、Amihud 非流动性软门控；"
        "低成交额分位剔除；涨跌停/一字剔除；可选趋势/波动门。"
        "T 收盘→T+1 开盘。研究因子。"
    ),
    rules_text=cf1_rules_text(),
    implemented=True,
    signal=cf1_signal,
    meta={
        "kind": "liquidity_gated_reversal",
        "standalone": True,
        "default_params": dict(DEFAULT_PARAMS),
        "timing": "close_t_trade_open_t1",
        "research_only": True,
        "aliases": ("CF1", "流动性门控反转"),
    },
)

register_factor(SPEC, replace=True)


def signal(**kwargs: Any) -> dict[str, Any]:
    return cf1_signal(**kwargs)


def compute(close, volume, **kwargs):
    return compute_cf1(close, volume, **kwargs)
