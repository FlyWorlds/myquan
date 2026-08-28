"""因子14：竞价一字联动选股。"""

from __future__ import annotations

from typing import Any

from strategy.auction_yizi_linkage import (
    DEFAULT_PARAMS,
    factor14_rules_text,
    factor14_signal,
)
from strategy.core.factor_registry import register_factor
from strategy.core.protocols import FactorSpec

FACTOR_ID = "factor14"
FACTOR_NAME = "因子14·竞价一字联动选股"


SPEC = FactorSpec(
    id=FACTOR_ID,
    name=FACTOR_NAME,
    description=(
        "识别当日竞价/开盘一字龙头，在同题材内选高开联动标的 TopK；"
        "T 开盘等权持有 hold_days 日"
    ),
    rules_text=factor14_rules_text(),
    implemented=True,
    signal=factor14_signal,
    meta={
        "kind": "auction_yizi_concept_linkage",
        "standalone": True,
        "default_params": dict(DEFAULT_PARAMS),
        "timing": "open_pick_same_day_open_entry",
        "research_only": True,
        "requires": ["skill-auction-yizi-linkage", "skill-b6-limitup-pool"],
    },
)

register_factor(SPEC, replace=True)


def signal(**kwargs: Any) -> dict[str, Any]:
    return factor14_signal(**kwargs)
