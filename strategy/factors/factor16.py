"""因子16：概念龙头评分（因子13质量带 + 因子1 OOS + 缠论笔对照）。"""

from __future__ import annotations

from typing import Any

from strategy.core.factor_registry import register_factor
from strategy.core.protocols import FactorSpec
from strategy.factor16_leader_score import (
    DEFAULT_PARAMS,
    FACTOR_ID,
    FACTOR_NAME,
    factor16_rules_text,
    factor16_signal,
)

SPEC = FactorSpec(
    id=FACTOR_ID,
    name=FACTOR_NAME,
    description=(
        "概念/股票池内龙头排序：FIT 窗因子13A score_quality + f13_pass；"
        "OOS 窗因子1 盈亏比/胜率/超额/回撤；缠论笔作对照列"
    ),
    rules_text=factor16_rules_text(),
    implemented=True,
    signal=factor16_signal,
    meta={
        "kind": "concept_leader_f13_f1_chan",
        "standalone": True,
        "default_params": dict(DEFAULT_PARAMS),
        "timing": "fit_score_oos_display",
        "research_only": True,
        "upstream": ["factor13a", "factor13b", "factor1", "factor17"],
        "docs": "docs/FACTOR16.md",
        "sectors_api": "sectors/leader_score.py",
    },
)

register_factor(SPEC, replace=True)


def signal(**kwargs: Any) -> dict[str, Any]:
    return factor16_signal(**kwargs)
