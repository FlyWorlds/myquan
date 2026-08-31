"""因子19：压力日低开（开盘可观测 gap + 因子18 家数）。"""

from __future__ import annotations

from typing import Any

from strategy.core.factor_registry import register_factor
from strategy.core.protocols import FactorSpec
from strategy.factors.factor18 import LD_OPEN_CALM_MAX

FACTOR_ID = "factor19"
FACTOR_NAME = "因子19-低开反包"

GAP_MIN = -0.08
GAP_MAX = -0.005
STRESS_MIN_LD = LD_OPEN_CALM_MAX + 1  # ≥1：正常+恐慌


def _rules() -> str:
    return f"""
因子19-低开反包
  · 择时：因子18 中证1000 低开开盘跌停家数 ≥ {STRESS_MIN_LD}（开盘可观测）
  · 个股：gap=开盘/昨收-1 ∈ [{GAP_MIN:.1%}, {GAP_MAX:.1%}]，非跌停开盘
  · 排序：gap 越负越优先；每日最多 3 只
  · 执行：开盘价买入（不追涨）；T+1 收盘清仓（A 股 T+1 无法当日卖）
研究用途，非投资建议。
""".strip()


def factor19_signal(
    *,
    ld_open: int | None = None,
    gap: float | None = None,
    open_px: float | None = None,
    **_: Any,
) -> dict[str, Any]:
    stress = ld_open is not None and int(ld_open) >= STRESS_MIN_LD
    gap_ok = gap is not None and GAP_MIN - 1e-12 <= float(gap) <= GAP_MAX + 1e-12
    buy = float(open_px) if open_px is not None and float(open_px) > 0 else 0.0
    allow = bool(stress and gap_ok)
    return {
        "stress": stress,
        "gap_ok": gap_ok,
        "allow": allow,
        "buy": buy,
        "rank_score": (-float(gap)) if gap_ok else None,
    }


SPEC = FactorSpec(
    id=FACTOR_ID,
    name=FACTOR_NAME,
    description=(
        f"压力日（因子18 家数≥{STRESS_MIN_LD}）低开 {GAP_MIN:.1%}～{GAP_MAX:.1%}，"
        "开盘买入、T+1 收盘清仓"
    ),
    rules_text=_rules(),
    implemented=True,
    signal=factor19_signal,
    meta={
        "kind": "gap_reclaim",
        "category": "reversal",
        "research_only": True,
        "timing": "open_observable_ld_and_gap",
        "upstream": ["factor18"],
        "gap_min": GAP_MIN,
        "gap_max": GAP_MAX,
        "stress_min_ld": STRESS_MIN_LD,
    },
)

register_factor(SPEC, replace=True)

__all__ = [
    "FACTOR_ID",
    "FACTOR_NAME",
    "GAP_MIN",
    "GAP_MAX",
    "STRESS_MIN_LD",
    "SPEC",
    "factor19_signal",
]
