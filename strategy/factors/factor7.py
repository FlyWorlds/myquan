"""因子7：行业 ETF 普通动量 + 改进残差动量。"""

from __future__ import annotations

from typing import Any

from strategy.core.factor_registry import register_factor
from strategy.core.protocols import FactorSpec
from strategy.industry_residual_momentum import (
    DEFAULT_COMMON_UNIVERSE,
    DEFAULT_PARAMS,
    DEFAULT_UNIVERSE,
    factor7_signal,
    industry_residual_momentum_rules_text,
)

FACTOR_ID = "factor7"
FACTOR_NAME = "因子7·行业ETF双动量"

SPEC = FactorSpec(
    id=FACTOR_ID,
    name=FACTOR_NAME,
    description=(
        "15只行业ETF月频轮动：12月普通动量与100月PCA改进残差动量"
        "各按50%合成，月末选择Top3"
    ),
    rules_text=industry_residual_momentum_rules_text(),
    implemented=True,
    signal=factor7_signal,
    meta={
        "kind": "industry_etf_dual_momentum",
        "standalone": True,
        "universe": [code for code, _ in DEFAULT_UNIVERSE],
        "common_universe": [code for code, _ in DEFAULT_COMMON_UNIVERSE],
        "default_params": dict(DEFAULT_PARAMS),
        "research_only": True,
    },
)

register_factor(SPEC, replace=True)


def signal(**kwargs: Any) -> dict[str, Any]:
    return factor7_signal(**kwargs)

