"""因子3：占位（开闭扩展点）。"""

from __future__ import annotations

from strategy.core.factor_registry import register_factor
from strategy.core.protocols import FactorSpec

FACTOR_ID = "factor3"
FACTOR_NAME = "因子3"

_RULES = """
================================================================================
  因子3 — 占位（未实现）
================================================================================
  预留给第三套可插拔因子。可与因子1/2任意组合挂到策略上。
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

register_factor(SPEC)
