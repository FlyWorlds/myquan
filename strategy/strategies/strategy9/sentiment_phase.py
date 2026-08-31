"""中证1000 低开跌停开盘家数（mkt_ld_open）情绪阶段：平静 / 正常 / 恐慌。"""

from __future__ import annotations

from typing import Any

# 基于 mkt_ld_open_zz1000 历史分位（2020→，中证1000 全宇宙）
LD_OPEN_CALM_MAX = 0
LD_OPEN_PANIC_MIN = 4

_PHASE_META: dict[str, dict[str, str]] = {
    "calm": {
        "label": "平静",
        "hint": "当日无低开跌停开盘，恐慌有限；大盘收涨概率略高",
    },
    "normal": {
        "label": "正常",
        "hint": "家数处于常见区间，情绪中性",
    },
    "panic": {
        "label": "恐慌",
        "hint": "低开跌停偏多，恐慌扩散；大盘当日收跌概率偏高",
    },
}


def classify_ld_open_phase(ld_open: int | None) -> dict[str, Any]:
    """按当日低开跌停开盘家数划分情绪阶段（中证1000 宇宙）。"""
    if ld_open is None:
        return {
            "ldPhase": None,
            "ldPhaseLabel": "—",
            "ldPhaseHint": "无数据",
            "ldPhaseRanges": _phase_ranges_text(),
        }
    n = int(ld_open)
    if n <= LD_OPEN_CALM_MAX:
        key = "calm"
    elif n >= LD_OPEN_PANIC_MIN:
        key = "panic"
    else:
        key = "normal"
    meta = _PHASE_META[key]
    return {
        "ldPhase": key,
        "ldPhaseLabel": meta["label"],
        "ldPhaseHint": meta["hint"],
        "ldPhaseRanges": _phase_ranges_text(),
    }


def _phase_ranges_text() -> str:
    return (
        f"平静≤{LD_OPEN_CALM_MAX} · 正常{LD_OPEN_CALM_MAX + 1}～{LD_OPEN_PANIC_MIN - 1} · "
        f"恐慌≥{LD_OPEN_PANIC_MIN}"
    )
