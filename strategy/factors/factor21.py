"""因子21：涨停次日低开。

T-1 收盘涨停已知；T 低开且未封涨停开盘可观测。买的是强势股回档，不是跌停飞刀。
"""

from __future__ import annotations

from typing import Any

from strategy.core.factor_registry import register_factor
from strategy.core.protocols import FactorSpec
from strategy.factors.factor15 import GAP_MAX, GAP_MIN
from strategy.factors.factor18 import LD_OPEN_PANIC_MIN

FACTOR_ID = "factor21"
FACTOR_NAME = "因子21-涨停次日低开"
REQUIRE_YEST_OPENED = True
SKIP_YEST_IDX_RET = -0.02


def _rules() -> str:
    return f"""
因子21-涨停次日低开
  · 选股：昨日收盘涨停，且盘中曾开板（剔一字锁定/未触及涨停价）
  · 今日：gap ∈ [{GAP_MIN:.1%}, {GAP_MAX:.1%}] 且开盘未封涨停
  · 择时：因子18 恐慌日（家数≥{LD_OPEN_PANIC_MIN}）空仓；上证昨收≤{SKIP_YEST_IDX_RET:.0%} 空仓
  · 排序：低开越深（带内）越优先；每日最多 3 只
  · 执行：开盘买入；T+1 收盘清仓
研究用途，非投资建议。
""".strip()


def factor21_signal(
    *,
    yest_close_limit_up: bool | None = None,
    today_limit_up_open: bool | None = None,
    ld_open: int | None = None,
    gap: float | None = None,
    open_px: float | None = None,
    yest_opened: bool | None = None,
    yest_idx_ret: float | None = None,
    **_: Any,
) -> dict[str, Any]:
    yest = bool(yest_close_limit_up)
    not_sealed = not bool(today_limit_up_open)
    panic = ld_open is not None and int(ld_open) >= LD_OPEN_PANIC_MIN
    gap_ok = gap is not None and GAP_MIN - 1e-12 <= float(gap) <= GAP_MAX + 1e-12
    if REQUIRE_YEST_OPENED:
        opened_ok = True if yest_opened is None else bool(yest_opened)
    else:
        opened_ok = True
    idx_ok = True
    if SKIP_YEST_IDX_RET is not None and yest_idx_ret is not None:
        idx_ok = float(yest_idx_ret) > float(SKIP_YEST_IDX_RET)
    allow = bool(yest and not_sealed and (not panic) and gap_ok and opened_ok and idx_ok)
    buy = float(open_px) if open_px is not None and float(open_px) > 0 else 0.0
    return {
        "yest_lu": yest,
        "opened": not_sealed,
        "opened_ok": opened_ok,
        "idx_ok": idx_ok,
        "panic": panic,
        "gap_ok": gap_ok,
        "allow": allow,
        "buy": buy,
        "rank_score": (-float(gap)) if (allow and gap is not None) else None,
    }


SPEC = FactorSpec(
    id=FACTOR_ID,
    name=FACTOR_NAME,
    description=(
        f"昨收涨停且曾开板、今日低开 {GAP_MIN:.1%}～{GAP_MAX:.1%} 且未封涨停；"
        f"恐慌日或上证昨收≤{SKIP_YEST_IDX_RET:.0%} 空仓；开盘买、T+1 收盘清"
    ),
    rules_text=_rules(),
    implemented=True,
    signal=factor21_signal,
    meta={
        "kind": "limit_up_next_gap",
        "category": "reversal",
        "research_only": True,
        "timing": "t1_close_lu_t_open_gap",
        "upstream": ["factor18", "factor15"],
        "gap_min": GAP_MIN,
        "gap_max": GAP_MAX,
        "panic_skip": LD_OPEN_PANIC_MIN,
        "require_yest_opened": REQUIRE_YEST_OPENED,
        "skip_yest_idx_ret": SKIP_YEST_IDX_RET,
    },
)

register_factor(SPEC, replace=True)

__all__ = [
    "FACTOR_ID",
    "FACTOR_NAME",
    "SPEC",
    "factor21_signal",
    "REQUIRE_YEST_OPENED",
    "SKIP_YEST_IDX_RET",
]
