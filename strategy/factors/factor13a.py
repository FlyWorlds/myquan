"""因子13A · 策略1契合选股（质量带 walk-forward）。

真源：``strategy/factor13_fit.py``。与因子13B（熊盾）拆分注册，见 ``docs/FACTOR13.md``。
"""

from __future__ import annotations

from typing import Any

from strategy.core.factor_registry import register_factor
from strategy.core.protocols import FactorSpec
from strategy.factor13_fit import (
    DEFAULT_PARAMS,
    factor13_rules_text,
    factor13_signal,
    load_best_rule,
)

FACTOR_ID = "factor13a"
FACTOR_NAME = "因子13A·质量带契合选股"


def _rules() -> str:
    return factor13_rules_text(load_best_rule())


SPEC = FactorSpec(
    id=FACTOR_ID,
    name=FACTOR_NAME,
    description=(
        "策略1开盘突破质量带：上年夏普适中、回撤甜区、dd_ratio 过滤；"
        "按 score_quality / excess 等截面排序取 TopK"
    ),
    rules_text=_rules(),
    implemented=True,
    signal=factor13_signal,
    meta={
        "kind": "strategy_fit_quality_band",
        "standalone": True,
        "default_params": dict(DEFAULT_PARAMS),
        "timing": "year_t_quality_band_hold_year_t_plus_1",
        "research_only": True,
        "best_rule": load_best_rule(),
        "docs": "docs/FACTOR13.md#3-质量带a-线",
        "legacy_id": "factor13",
    },
)

register_factor(SPEC, replace=True)


def signal(**kwargs: Any) -> dict[str, Any]:
    return factor13_signal(**kwargs)
