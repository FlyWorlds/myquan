"""因子15：题材晋级低开 — 晋级日相对昨收低开带 [-4.5%, -0.3%]。"""

from __future__ import annotations

from strategy.core.factor_registry import register_factor
from strategy.core.protocols import FactorSpec

FACTOR_ID = "factor15"
FACTOR_NAME = "因子15-题材晋级低开"

GAP_MIN = -0.045
GAP_MAX = -0.003


def gap_in_band(gap_pct: float, *, lo: float = GAP_MIN, hi: float = GAP_MAX) -> bool:
    """gap_pct 为百分数（如 -2.5 表示 -2.5%）。"""
    g = float(gap_pct) / 100.0
    return lo <= g <= hi


def gap_quality_score(gap_pct: float) -> float:
    """低开带内得分越高（用于排序）。"""
    g = float(gap_pct) / 100.0
    if GAP_MIN <= g <= GAP_MAX:
        return 3.0 + max(0.0, (-g - 0.003) * 20.0)
    if -0.01 <= g <= 0.0:
        return 1.0
    return 0.0


def _rules() -> str:
    return f"""
因子15·题材晋级低开
  · 晋级日开盘相对昨收 gap ∈ [{GAP_MIN*100:.1f}%, {GAP_MAX*100:.1f}%]
  · 过滤高开追高与深跌抄底；与策略三首板 gap 带同源
  · 策略八可选：CLI `--gap-filter` 启用；默认关闭，直接因子1 ±阈值
研究用途，非投资建议。
""".strip()


SPEC = FactorSpec(
    id=FACTOR_ID,
    name=FACTOR_NAME,
    description="晋级日低开带过滤/打分；策略八默认关闭，需 --gap-filter 启用",
    rules_text=_rules(),
    implemented=True,
    meta={
        "kind": "theme_promo_gap",
        "gap_min": GAP_MIN,
        "gap_max": GAP_MAX,
        "strategy": "strategy8",
    },
)

register_factor(SPEC)
