"""中证1000 涨停家数（mkt_lu）情绪阶段：冰点 / 正常 / 高潮。"""

from __future__ import annotations

from typing import Any

# 基于 mkt_sentiment_zz1000 历史分位（2020→，约三分位）
MKT_LU_ICE_MAX = 6
MKT_LU_CLIMAX_MIN = 15

_PHASE_META: dict[str, dict[str, str]] = {
    "ice": {
        "label": "冰点",
        "hint": "涨停稀少，短线偏冷；晋级成功率通常偏低",
    },
    "normal": {
        "label": "正常",
        "hint": "涨停家数处于常见区间，情绪相对均衡",
    },
    "climax": {
        "label": "高潮",
        "hint": "涨停偏多，情绪偏热；注意分化与退潮风险",
    },
}


def classify_mkt_lu_phase(lu: int | None) -> dict[str, Any]:
    """按 T-1 涨停家数划分情绪阶段（中证1000 宇宙）。"""
    if lu is None:
        return {
            "luPhase": None,
            "luPhaseLabel": "—",
            "luPhaseHint": "无数据",
            "luPhaseRanges": _phase_ranges_text(),
        }
    n = int(lu)
    if n <= MKT_LU_ICE_MAX:
        key = "ice"
    elif n >= MKT_LU_CLIMAX_MIN:
        key = "climax"
    else:
        key = "normal"
    meta = _PHASE_META[key]
    return {
        "luPhase": key,
        "luPhaseLabel": meta["label"],
        "luPhaseHint": meta["hint"],
        "luPhaseRanges": _phase_ranges_text(),
    }


def _phase_ranges_text() -> str:
    return f"冰点≤{MKT_LU_ICE_MAX} · 正常{MKT_LU_ICE_MAX + 1}～{MKT_LU_CLIMAX_MIN - 1} · 高潮≥{MKT_LU_CLIMAX_MIN}"
