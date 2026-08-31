"""因子20：跌停次日开板。

T-1 收盘跌停已知；T 开盘是否封死开盘可观测。不依赖单票（凯盛/天通）。
"""

from __future__ import annotations

from typing import Any

from strategy.core.factor_registry import register_factor
from strategy.core.protocols import FactorSpec
from strategy.factors.factor18 import LD_OPEN_PANIC_MIN

FACTOR_ID = "factor20"
FACTOR_NAME = "因子20-跌停次日开板"


def _rules() -> str:
    return f"""
因子20-跌停次日开板
  · 选股：昨日收盘跌停（收盘价在跌停价容差内）
  · 今日：开盘未封跌停（可买）
  · 择时：因子18 恐慌日（家数≥{LD_OPEN_PANIC_MIN}）空仓，避免趋势日接飞刀
  · 排序：今开相对昨收越低越优先；每日最多 3 只
  · 执行：开盘买入；T+1 收盘清仓
研究用途，非投资建议。
""".strip()


def factor20_signal(
    *,
    yest_close_limit_down: bool | None = None,
    today_limit_down_open: bool | None = None,
    ld_open: int | None = None,
    gap: float | None = None,
    open_px: float | None = None,
    **_: Any,
) -> dict[str, Any]:
    yest = bool(yest_close_limit_down)
    opened = not bool(today_limit_down_open)
    panic = ld_open is not None and int(ld_open) >= LD_OPEN_PANIC_MIN
    allow = bool(yest and opened and not panic)
    buy = float(open_px) if open_px is not None and float(open_px) > 0 else 0.0
    return {
        "yest_ld": yest,
        "opened": opened,
        "panic": panic,
        "allow": allow,
        "buy": buy,
        "rank_score": (-float(gap)) if (allow and gap is not None) else None,
    }


SPEC = FactorSpec(
    id=FACTOR_ID,
    name=FACTOR_NAME,
    description=(
        "昨日收盘跌停、今日开盘未封死；因子18 恐慌日空仓；开盘买、T+1 收盘清"
    ),
    rules_text=_rules(),
    implemented=True,
    signal=factor20_signal,
    meta={
        "kind": "limit_down_next",
        "category": "reversal",
        "research_only": True,
        "timing": "t1_close_ld_t_open_observable",
        "upstream": ["factor18"],
        "panic_skip": LD_OPEN_PANIC_MIN,
    },
)

register_factor(SPEC, replace=True)

__all__ = ["FACTOR_ID", "FACTOR_NAME", "SPEC", "factor20_signal"]
