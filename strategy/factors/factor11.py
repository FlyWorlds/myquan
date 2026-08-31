"""因子11：两段近高选股（3 日动量 Top20 → 贴近 5 日高点 Top5，周频冻结）。"""

from __future__ import annotations

from typing import Any

from strategy.core.factor_registry import register_factor
from strategy.core.protocols import FactorSpec
from strategy.near_high_hold import (
    DEFAULT_PARAMS,
    factor11_signal,
    near_high_rules_text,
)

FACTOR_ID = "factor11"
FACTOR_NAME = "因子11-两段近高选股"


SPEC = FactorSpec(
    id=FACTOR_ID,
    name=FACTOR_NAME,
    description=(
        "周频两段选股：3日动量 Top20 内再取贴近5日高点 Top5；"
        "本周收盘排名，下一周持有；一字涨停开盘不可买入"
    ),
    rules_text=near_high_rules_text(),
    implemented=True,
    signal=factor11_signal,
    meta={
        "kind": "two_stage_near_high",
        "standalone": True,
        "default_params": dict(DEFAULT_PARAMS),
        "timing": "week_end_close_hold_next_week",
        "research_only": True,
    },
)

register_factor(SPEC, replace=True)


def signal(**kwargs: Any) -> dict[str, Any]:
    return factor11_signal(**kwargs)
