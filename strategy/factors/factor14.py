"""因子14：题材共振 — 当日同题材涨停同伴数（theme_lu_count）。"""

from __future__ import annotations

from strategy.core.factor_registry import register_factor
from strategy.core.protocols import FactorSpec

FACTOR_ID = "factor14"
FACTOR_NAME = "因子14-题材共振"


def _rules() -> str:
    return """
因子14·题材共振（theme_lu_count）
  · 数据源：通达信概念成分（离线 tdx_members_index.json）
  · 统计：**当日**与本股共享概念且收盘涨停的同伴数量
  · 入池：theme_lu_count ≥ 3（同题材至少 3 只当日涨停，题材共振）
  · 用途：策略八选股排序；越高表示题材越热
  · 联动：未涨停但 theme_lu_count≥3 → 题材联动候选（当日因子1 ±阈值）
研究用途，非投资建议。
""".strip()


SPEC = FactorSpec(
    id=FACTOR_ID,
    name=FACTOR_NAME,
    description="当日同题材涨停同伴数；≥3 为题材共振，用于策略八联动选股",
    rules_text=_rules(),
    implemented=True,
    meta={
        "kind": "theme_resonance",
        "min_theme_lu": 3,
        "concept_source": "tdx_members_index",
        "strategy": "strategy8",
    },
)

register_factor(SPEC)
