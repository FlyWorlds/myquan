"""日线阴阳策略 — 规则与说明（与 OpenBreak3 无关）。"""

from __future__ import annotations

STRATEGY_RULES = """
================================================================================
  日线阴阳策略（YinYang）— 简化日 K 形态
================================================================================

【买入】
  空仓 + 当日收阳（收盘 > 开盘）→ 按收盘价附近建仓，目标仓位约 95%。

【卖出】
  有仓 + 当日收阴（收盘 < 开盘）→ 全部卖出。

【说明】
  · 仅看当根日 K 阴阳，无 945、无开盘±pct、无前日过滤
  · T+1：A 股买入当日不可卖（由 akquant t_plus_one 控制）
  · 与 OpenBreak3 完全独立，不共享 open_break 模块
================================================================================
"""


def is_yang(open_px: float, close_px: float) -> bool:
    return float(close_px) > float(open_px)


def is_yin(open_px: float, close_px: float) -> bool:
    return float(close_px) < float(open_px)


def bar_shape(open_px: float, close_px: float) -> str:
    if is_yang(open_px, close_px):
        return "阳"
    if is_yin(open_px, close_px):
        return "阴"
    return "十字"
