"""因子17：大盘低开 — 指数 gap / 实体阳家数 / 次日表现。"""

from __future__ import annotations

from typing import Any

from strategy.core.factor_registry import register_factor
from strategy.core.protocols import FactorSpec
from strategy.factor17_market_low_open import (
    DEFAULT_PARAMS,
    FACTOR_ID,
    FACTOR_NAME,
    factor17_rules_text,
    factor17_signal,
)

SPEC = FactorSpec(
    id=FACTOR_ID,
    name=FACTOR_NAME,
    description=(
        "上证指数低开幅度分桶；统计当日收盘、次日开收、实体阳家数比例（close>open）；"
        "低开日买卖情景历史胜率/均收益"
    ),
    rules_text=factor17_rules_text(),
    implemented=True,
    signal=factor17_signal,
    meta={
        "kind": "market_low_open_regime",
        "standalone": True,
        "default_params": dict(DEFAULT_PARAMS),
        "index": "sh000001",
        "yang_definition": "close_gt_open",
        "research_only": True,
        "docs": "docs/FACTOR17.md",
        "cli": "python -m strategy.run_factor17_market_low_open",
    },
)

register_factor(SPEC, replace=True)


def signal(**kwargs: Any) -> dict[str, Any]:
    return factor17_signal(**kwargs)
