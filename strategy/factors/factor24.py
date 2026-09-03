"""因子24：连板梯度情绪 → 止盈目标 + 是否启用因子22。"""

from __future__ import annotations

from typing import Any

from strategy.core.factor_registry import register_factor
from strategy.core.protocols import FactorSpec
from strategy.ladder_tp import factor24_from_ladder, resolve_ladder_tp_policy

FACTOR_ID = "factor24"
FACTOR_NAME = "因子24-连板梯度情绪"


def _rules() -> str:
    return (
        "因子24-连板梯度情绪\n"
        "  · 输入：mkt_ladder_score（连板≥2 的板数之和）、mkt_lianban\n"
        "  · 低梯度（score<8 或 连板家数<2）：震荡 → 开因子22，止盈目标收紧\n"
        "  · 中梯度（8～20）：开因子22，止盈沿用因子23\n"
        "  · 高梯度（>20）：高潮 → 关因子22（止损后不接回，减少追高磨损），止盈上移\n"
        "  · 与因子23 合成见 strategy.ladder_tp.resolve_ladder_tp_policy\n"
        "研究默认，非投资建议"
    )


def signal(**kw: Any) -> dict[str, Any]:
    try:
        score = int(kw.get("mkt_ladder_score", kw.get("ladder_score") or 0) or 0)
    except (TypeError, ValueError):
        score = 0
    try:
        lb = int(kw.get("mkt_lianban", kw.get("lianban") or 0) or 0)
    except (TypeError, ValueError):
        lb = 0
    try:
        height = int(kw.get("mkt_max_height", kw.get("max_height") or 0) or 0)
    except (TypeError, ValueError):
        height = 0
    f24 = factor24_from_ladder(ladder_score=score, lianban=lb)
    policy = resolve_ladder_tp_policy(
        max_height=height, ladder_score=score, lianban=lb
    )
    return {
        "kind": "ladder_emotion",
        "mkt_ladder_score": score,
        "mkt_lianban": lb,
        **f24,
        "policy": policy.as_dict(),
    }


SPEC = FactorSpec(
    id=FACTOR_ID,
    name=FACTOR_NAME,
    description="连板梯度定止盈目标，并决定震荡市是否用因子22 接回因子1 卖飞",
    rules_text=_rules(),
    implemented=True,
    signal=signal,
    meta={"kind": "ladder_emotion", "category": "sentiment", "status": "research"},
)

register_factor(SPEC, replace=True)

__all__ = ["FACTOR_ID", "FACTOR_NAME", "SPEC", "signal"]
