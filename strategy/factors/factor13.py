"""因子13：策略一·因子1 契合选股（质量带 Walk-Forward）。"""

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

FACTOR_ID = "factor13"
FACTOR_NAME = "因子13·策略1质量带选股"


def _rules() -> str:
    return factor13_rules_text(load_best_rule())


SPEC = FactorSpec(
    id=FACTOR_ID,
    name=FACTOR_NAME,
    description=(
        "上年开盘突破：夏普适中、回撤约20–30%、策略回撤≤约持有一半，"
        "按 score_quality 取 Top10（不足放宽补齐）；支持年频/季频滚动"
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
    },
)

register_factor(SPEC, replace=True)


def signal(**kwargs: Any) -> dict[str, Any]:
    return factor13_signal(**kwargs)
