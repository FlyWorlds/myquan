"""因子12：20日反转池内再取贴近5日高点 Top5。研究候选，不替换因子11。"""

from __future__ import annotations

from typing import Any

from strategy.core.factor_registry import register_factor
from strategy.core.protocols import FactorSpec
from strategy.factor12_combo import (
    DEFAULT_PARAMS,
    factor12_rules_text,
    factor12_signal,
)

FACTOR_ID = "factor12"
FACTOR_NAME = "因子12-反转池近高"


SPEC = FactorSpec(
    id=FACTOR_ID,
    name=FACTOR_NAME,
    description=(
        "周频两段：20日涨幅最低 Top20 内再取贴近5日高点 Top5；"
        "研究候选，2024–2025 未确认，不替换因子11"
    ),
    rules_text=factor12_rules_text(),
    implemented=True,
    signal=factor12_signal,
    meta={
        "kind": "reversal_then_near_high",
        "standalone": True,
        "default_params": dict(DEFAULT_PARAMS),
        "timing": "week_end_close_hold_next_week",
        "research_only": True,
        "replaces_factor11": False,
    },
)

register_factor(SPEC, replace=True)


def signal(**kwargs: Any) -> dict[str, Any]:
    return factor12_signal(**kwargs)
