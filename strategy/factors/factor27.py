"""因子27：核心龙头选股（通达信概念活跃度偏高 → 概念内龙头，滚动近 3 个月冻结）。"""

from __future__ import annotations

from strategy.core.factor_registry import register_factor
from strategy.core.protocols import FactorSpec
from strategy.core_leader_universe import (
    DEFAULT_MAX_CONCEPTS,
    DEFAULT_PER_CONCEPT,
    DEFAULT_PRICE_MAX,
    DEFAULT_TARGET_POOL,
    DEFAULT_PICKS_PATH,
    build_quarter_pool,
    rolling_3m_window,
    load_picks,
    pick_codes,
)

FACTOR_ID = "factor27"
FACTOR_NAME = "因子27-核心龙头"


def _rules() -> str:
    return """
因子27·核心龙头（滚动近 3 个月冻结）
  · 数据：通达信概念现价成交额（活跃度）+ 概念成分行情
  · 偏高概念：成交额 ≥ 当日截面中位数，最多扫成交额 Top40
  · 每个概念至多 2 只：过滤后按涨跌幅、成交额取前 2；去重后凑满约 30 只
  · 过滤：非创业 / 非科创 / 非北交 / 非 ST / 现价 < 100
  · 周期：滚动近 3 个月（非自然季度 Q1/Q2/Q3）；CLI `python strategy/run_core_leader_pool.py`
  · 用途：策略十六宇宙；买卖不在本因子（复用因子26/2/22）
研究用途，非投资建议。
""".strip()


def signal(**kwargs):  # noqa: ANN003
    payload = load_picks()
    return {
        "label": payload.get("label") or rolling_3m_window()["label"],
        "window_start": payload.get("window_start"),
        "valid_until": payload.get("valid_until"),
        "n_picks": int(payload.get("n_picks") or 0),
        "codes": pick_codes(payload),
        "as_of": payload.get("as_of"),
        **kwargs,
    }


SPEC = FactorSpec(
    id=FACTOR_ID,
    name=FACTOR_NAME,
    description=(
        "通达信概念活跃度偏高（成交额≥中位数，最多扫题材 Top40）内取龙头；"
        f"每概念≤{DEFAULT_PER_CONCEPT}；池约{DEFAULT_TARGET_POOL}只；主板非ST非科创创业、现价<{DEFAULT_PRICE_MAX:.0f}；滚动近3个月冻结"
    ),
    rules_text=_rules(),
    implemented=True,
    signal=signal,
    meta={
        "kind": "core_leader_universe",
        "category": "sentiment",
        "max_concepts": DEFAULT_MAX_CONCEPTS,
        "per_concept": DEFAULT_PER_CONCEPT,
        "target_pool": DEFAULT_TARGET_POOL,
        "price_max": DEFAULT_PRICE_MAX,
        "horizon": "rolling_3m",
        "picks_path": str(DEFAULT_PICKS_PATH.as_posix()),
        "strategy": "strategy16",
        "docs": "docs/FACTOR27.md",
        "refresh": build_quarter_pool,
    },
)

register_factor(SPEC)
