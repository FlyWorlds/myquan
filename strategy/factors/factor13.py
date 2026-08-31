"""因子13 · 兼容别名（→ factor13a 质量带）。

新代码请使用 ``factor13a``（质量带）或 ``factor13b``（熊盾）。双轨说明见 ``docs/FACTOR13.md``。
"""

from __future__ import annotations

from typing import Any

from strategy.core.factor_registry import register_factor
from strategy.core.protocols import FactorSpec
from strategy.factor13_fit import factor13_signal, load_best_rule
from strategy.factors.factor13a import FACTOR_NAME as NAME_A
from strategy.factors.factor13a import _rules

FACTOR_ID = "factor13"
FACTOR_NAME = "因子13·契合选股（别名→13A）"


SPEC = FactorSpec(
    id=FACTOR_ID,
    name=FACTOR_NAME,
    description=f"兼容别名，等同 {NAME_A}。熊盾请用 factor13b。",
    rules_text=_rules(),
    implemented=True,
    signal=factor13_signal,
    meta={
        "alias_of": "factor13a",
        "bear_shield_id": "factor13b",
        "best_rule": load_best_rule(),
        "docs": "docs/FACTOR13.md",
    },
)

register_factor(SPEC, replace=True)


def signal(**kwargs: Any) -> dict[str, Any]:
    return factor13_signal(**kwargs)
