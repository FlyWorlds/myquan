"""打板战法 — 规则（与 OpenBreak3 / yin_yang 无关）。"""

from __future__ import annotations

import math

STRATEGY_RULES = """
================================================================================
  打板战法（DaBan）— 涨停封板 · 连板持有
================================================================================

【买入 · 空仓】
  当日涨停封板 → 收盘价附近建仓（约 95% 仓位）。
  · 涨停价 = ceil(昨收 × (1 + 涨停幅度))，默认主板 10%
  · 封板：收盘 ≥ 涨停价 - 1tick，且收盘接近当日最高（默认 |收-高| ≤ 1tick）

【卖出 · 有仓 · T+1 起】优先级：
  ① 低开止损：开盘相对昨收低开 ≥ 阈值（默认 3%）→ 按开盘价卖
  ② 不连板：当日收盘未涨停 → 按收盘价全清
  ③ 连板：收盘继续涨停封板 → 继续持有

【说明】
  · 日线回测近似：买入价=涨停日收盘；无法排板/炸板精细撮合
  · A 股 T+1：买入当日不可卖
  · 与 OpenBreak3、yin_yang 完全独立
================================================================================
"""

TICK_SIZE = 0.01
DEFAULT_LIMIT_PCT = 0.10
DEFAULT_TARGET_PCT = 0.95
DEFAULT_GAP_DOWN_EXIT_PCT = 0.03
DEFAULT_SEAL_HIGH_TICKS = 1.0


def ceil_to_tick(px: float, tick: float = TICK_SIZE) -> float:
    if tick <= 0:
        return float(px)
    decimals = max(0, -int(round(math.log10(tick)))) if tick < 1 else 0
    return round(math.ceil((float(px) - 1e-12) / tick) * tick, decimals)


def limit_up_price(prev_close: float, limit_pct: float = DEFAULT_LIMIT_PCT) -> float:
    """涨停价（向上取整到分）。"""
    if prev_close <= 0:
        return float("nan")
    return ceil_to_tick(float(prev_close) * (1.0 + float(limit_pct)))


def is_limit_up_close(
    close_px: float,
    prev_close: float,
    *,
    limit_pct: float = DEFAULT_LIMIT_PCT,
    tick: float = TICK_SIZE,
) -> bool:
    """收盘涨停（允许 1tick 误差）。"""
    if prev_close <= 0:
        return False
    lu = limit_up_price(prev_close, limit_pct)
    return float(close_px) + tick * 0.5 + 1e-8 >= lu


def is_sealed_limit_up(
    open_px: float,
    high_px: float,
    low_px: float,
    close_px: float,
    prev_close: float,
    *,
    limit_pct: float = DEFAULT_LIMIT_PCT,
    tick: float = TICK_SIZE,
    seal_high_ticks: float = DEFAULT_SEAL_HIGH_TICKS,
) -> bool:
    """涨停封板：收盘涨停且收盘贴近最高价。"""
    _ = (open_px, low_px)
    if not is_limit_up_close(close_px, prev_close, limit_pct=limit_pct, tick=tick):
        return False
    return float(high_px) - float(close_px) <= tick * seal_high_ticks + 1e-8


def gap_down_pct(open_px: float, prev_close: float) -> float:
    """低开幅度（正数 %）= (昨收 - 开盘) / 昨收 × 100。"""
    if prev_close <= 0:
        return float("nan")
    return max(0.0, (float(prev_close) - float(open_px)) / float(prev_close) * 100.0)


def should_gap_down_exit(
    open_px: float,
    prev_close: float,
    *,
    gap_down_exit_pct: float = DEFAULT_GAP_DOWN_EXIT_PCT,
) -> bool:
    """低开超过阈值则开盘卖。"""
    g = gap_down_pct(open_px, prev_close)
    return g + 1e-12 >= gap_down_exit_pct * 100.0
