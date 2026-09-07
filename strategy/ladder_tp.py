"""连板最高板 / 梯度 → 止盈目标与因子22 门控。

研究默认，非投资建议。缺行情时按震荡档：10% 减半 + 允许因子22。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LadderTpPolicy:
    regime: str  # chop | normal | hot
    max_height: int
    ladder_score: int
    lianban: int
    tp_pct: float
    reduce_ratio: float
    use_factor22: bool
    tp_style: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "regime": self.regime,
            "max_height": self.max_height,
            "ladder_score": self.ladder_score,
            "lianban": self.lianban,
            "tp_pct": self.tp_pct,
            "reduce_ratio": self.reduce_ratio,
            "use_factor22": self.use_factor22,
            "tp_style": self.tp_style,
            "reason": self.reason,
        }


def factor23_tp_from_max_height(max_height: int | None) -> dict[str, Any]:
    """因子23：用市场最高连板数定止盈形态。"""
    h = int(max_height or 0)
    if h <= 2:
        return {
            "tp_style": "half_early",
            "tp_pct": 0.07,
            "reduce_ratio": 0.5,
            "label": "弱最高板·早止盈",
        }
    if h <= 4:
        return {
            "tp_style": "half_std",
            "tp_pct": 0.10,
            "reduce_ratio": 0.5,
            "label": "常规最高板·10%减半",
        }
    return {
        "tp_style": "half_wide",
        "tp_pct": 0.15,
        "reduce_ratio": 0.5,
        "label": "高潮最高板·放宽止盈",
    }


def factor24_from_ladder(
    *,
    ladder_score: int | None,
    lianban: int | None,
) -> dict[str, Any]:
    """因子24：用连板梯度定止盈目标，并决定是否启用因子22。

    震荡（低梯度）开因子22 补因子1 卖飞；高潮梯度关因子22，避免追高磨损。
    """
    score = int(ladder_score or 0)
    lb = int(lianban or 0)
    if score < 8 or lb < 2:
        return {
            "regime": "chop",
            "use_factor22": True,
            "tp_pct_cap": 0.08,
            "label": "低梯度震荡·开F22·止盈收紧",
        }
    if score <= 20:
        return {
            "regime": "normal",
            "use_factor22": True,
            "tp_pct_cap": None,
            "label": "中梯度·开F22·沿用最高板止盈",
        }
    return {
        "regime": "hot",
        "use_factor22": False,
        "tp_pct_floor": 0.12,
        "label": "高梯度高潮·关F22·止盈上移",
    }


def resolve_ladder_tp_policy(
    *,
    max_height: int | None = None,
    ladder_score: int | None = None,
    lianban: int | None = None,
) -> LadderTpPolicy:
    h = int(max_height or 0)
    score = int(ladder_score or 0)
    lb = int(lianban or 0)
    f23 = factor23_tp_from_max_height(h)
    f24 = factor24_from_ladder(ladder_score=score, lianban=lb)
    tp = float(f23["tp_pct"])
    cap = f24.get("tp_pct_cap")
    floor = f24.get("tp_pct_floor")
    if cap is not None:
        tp = min(tp, float(cap))
    if floor is not None:
        tp = max(tp, float(floor))
    reason = f"{f23['label']}；{f24['label']}"
    return LadderTpPolicy(
        regime=str(f24["regime"]),
        max_height=h,
        ladder_score=score,
        lianban=lb,
        tp_pct=float(tp),
        reduce_ratio=float(f23["reduce_ratio"]),
        use_factor22=bool(f24["use_factor22"]),
        tp_style=str(f23["tp_style"]),
        reason=reason,
    )


__all__ = [
    "LadderTpPolicy",
    "factor23_tp_from_max_height",
    "factor24_from_ladder",
    "resolve_ladder_tp_policy",
]
