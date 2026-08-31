"""因子18：低开跌停情绪（中证1000 低开开盘跌停家数）。

口径与 strategy9.sentiment_phase 一致；本模块不在 import 时加载策略包，避免循环依赖。
"""

from __future__ import annotations

from typing import Any

from strategy.core.factor_registry import register_factor
from strategy.core.protocols import FactorSpec

FACTOR_ID = "factor18"
FACTOR_NAME = "因子18-低开跌停情绪"

# 与 strategy.strategies.strategy9.sentiment_phase 保持一致
LD_OPEN_CALM_MAX = 0
LD_OPEN_PANIC_MIN = 4


def _rules() -> str:
    return f"""
因子18-低开跌停情绪
  · 宇宙：中证1000（剔 ST / 北交）
  · 低开开盘即跌停：开盘 < 昨收 且 开盘价在跌停价容差内
  · 情绪阶段：平静≤{LD_OPEN_CALM_MAX} · 正常{LD_OPEN_CALM_MAX + 1}～{LD_OPEN_PANIC_MIN - 1} · 恐慌≥{LD_OPEN_PANIC_MIN}
  · 研判（研究）：恐慌偏多→预判当日收跌；平静→预判收涨
  · 用途：大盘情绪择时；策略十二用家数≥1 压力日选股；CLI 对照见 run_strategy9_emotion
研究用途，非投资建议。
""".strip()


def factor18_signal(*, ld_open: int | None = None, **_: Any) -> dict[str, Any]:
    from strategy.strategies.strategy9.sentiment_phase import classify_ld_open_phase

    return classify_ld_open_phase(ld_open)


SPEC = FactorSpec(
    id=FACTOR_ID,
    name=FACTOR_NAME,
    description=(
        f"中证1000 低开开盘跌停家数：平静≤{LD_OPEN_CALM_MAX} / "
        f"恐慌≥{LD_OPEN_PANIC_MIN}；策略十二作压力日择时"
    ),
    rules_text=_rules(),
    implemented=True,
    signal=factor18_signal,
    meta={
        "kind": "market_emotion",
        "category": "sentiment",
        "research_only": True,
        "universe": "zz1000",
        "calm_max": LD_OPEN_CALM_MAX,
        "panic_min": LD_OPEN_PANIC_MIN,
        "legacy_strategy": "strategy9",
        "combo_strategy": "strategy12",
    },
)

register_factor(SPEC, replace=True)

__all__ = ["FACTOR_ID", "FACTOR_NAME", "SPEC", "factor18_signal"]
