"""因子10：策略1 价格选股（周频冻结近高 / 趋势 / 动量）。

T 日收盘计算，本周收盘排名，下一周开仓可用。研究 overlay，默认不改援军战法绑定。
"""

from __future__ import annotations

from strategy.core.factor_registry import register_factor
from strategy.core.protocols import FactorSpec
from strategy.s1_price_select import (
    DEFAULT_PARAMS,
    compute_price_select,
    price_select_rules_text,
)

FACTOR_ID = "factor10"
FACTOR_NAME = "因子10·价格选股"


def _rules() -> str:
    return price_select_rules_text(DEFAULT_PARAMS)


SPEC = FactorSpec(
    id=FACTOR_ID,
    name=FACTOR_NAME,
    description="价格选股：近高/趋势/动量，周频 TopK 作为因子1 开仓名单",
    rules_text=_rules(),
    implemented=True,
    meta={
        "kind": "s1_price_select",
        "params": dict(DEFAULT_PARAMS),
        "timing": "week_end_close_exec_next_week",
        "compute": compute_price_select,
    },
)

register_factor(SPEC)

__all__ = ["FACTOR_ID", "FACTOR_NAME", "SPEC"]
