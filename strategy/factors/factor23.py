"""因子23：市场最高连板数 → 止盈形态（早止盈 / 10%减半 / 放宽）。"""

from __future__ import annotations

from typing import Any

from strategy.core.factor_registry import register_factor
from strategy.core.protocols import FactorSpec
from strategy.ladder_tp import factor23_tp_from_max_height

FACTOR_ID = "factor23"
FACTOR_NAME = "因子23-最高连板止盈"


def _rules() -> str:
    return (
        "因子23-最高连板止盈\n"
        "  · 输入：当日或 T-1 市场最高连板数 mkt_max_height（与策略三同源）\n"
        "  · ≤2 板：震荡弱 → 约 7% 减半止盈\n"
        "  · 3～4 板：常规 → 10% 减半止盈\n"
        "  · ≥5 板：高潮 → 约 15% 减半止盈（让趋势多跑）\n"
        "  · 叠在因子1 持仓上；研究默认，非投资建议"
    )


def signal(**kw: Any) -> dict[str, Any]:
    h = kw.get("mkt_max_height", kw.get("max_height"))
    try:
        height = int(h) if h is not None else 0
    except (TypeError, ValueError):
        height = 0
    out = factor23_tp_from_max_height(height)
    return {"kind": "max_height_tp", "max_height": height, **out}


SPEC = FactorSpec(
    id=FACTOR_ID,
    name=FACTOR_NAME,
    description="市场最高连板数制订止盈：弱板早止盈、3～4 板 10% 减半、高潮放宽",
    rules_text=_rules(),
    implemented=True,
    signal=signal,
    meta={"kind": "max_height_tp", "category": "take_profit", "status": "research"},
)

register_factor(SPEC, replace=True)

__all__ = ["FACTOR_ID", "FACTOR_NAME", "SPEC", "signal"]
