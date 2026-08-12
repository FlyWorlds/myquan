"""因子4：占位（开闭扩展点）。"""

from __future__ import annotations

from strategy.core.factor_registry import register_factor
from strategy.core.protocols import FactorSpec

FACTOR_ID = "factor4"
FACTOR_NAME = "因子4"

_RULES = """
================================================================================
  因子4 — 占位（未实现）
================================================================================
  预留给第四套可插拔因子。可与因子1/2/3任意组合挂到策略上。
================================================================================
""".strip()

SPEC = FactorSpec(
    id=FACTOR_ID,
    name=FACTOR_NAME,
    description="占位因子：待实现",
    rules_text=_RULES,
    implemented=False,
    meta={"kind": "placeholder"},
)

register_factor(SPEC, replace=True)
