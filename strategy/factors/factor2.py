"""因子2：占位（开闭扩展点）。

尚未实现交易/盯盘逻辑。任意策略可通过 factor_ids 引用本 id；
实现时只需在本文件补齐 levels/filters_ok/signal/replay 并保持 id=factor2。
"""

from __future__ import annotations

from strategy.core.factor_registry import register_factor
from strategy.core.protocols import FactorSpec

FACTOR_ID = "factor2"
FACTOR_NAME = "因子2"

_RULES = """
================================================================================
  因子2 — 占位（未实现）
================================================================================
  预留给第二套可插拔因子。策略可通过 factor_ids 挂载本因子，
  也可与因子1组合使用。实现后请更新本说明与回调函数。
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
