"""超跌反弹形态 — 规则定义（与 OpenBreak3 / yin_yang 无关）。"""

from __future__ import annotations

STRATEGY_RULES = """
================================================================================
  超跌反弹形态统计（Oversold Bounce）
================================================================================

【信号日 T 需同时满足】
  1. 盘中超跌 > 5%：最低价相对昨收跌幅 <= -5%（收盘可已收回，如锤头线）
  2. 低开：开盘价 < 昨收
  3. 小阴线：收盘 < 开盘
  4. 实体跌幅 < 1%：(开盘 - 收盘) / 开盘 × 100% < 1%
  5. 带下引线：最低价 < min(开盘, 收盘)

【统计次日 T+1】
  · 开盘相对 T 日收盘的涨跌幅
  · 最高相对 T 日收盘的涨跌幅
  · 收盘相对 T 日收盘的涨跌幅
  · 以及 T+1 绝对 OHLC

【用途】
  历史样本统计，非自动交易回测；用于观察该形态后次日表现。
================================================================================
"""

# 默认阈值
MIN_DAY_DROP_PCT = 5.0       # 盘中最低价相对昨收须 <= -5%
MAX_BODY_DROP_PCT = 1.0      # 实体跌幅 < 1%（默认）
MAX_BODY_ABS = 1.0           # 可选：实体绝对值 < 1 元（body_mode=abs）


def day_change_pct(close: float, prev_close: float) -> float:
    """相对昨收的当日涨跌幅 %。"""
    if prev_close <= 0:
        return float("nan")
    return (float(close) / float(prev_close) - 1.0) * 100.0


def low_drop_pct(low_px: float, prev_close: float) -> float:
    """盘中最低价相对昨收跌幅 %。"""
    if prev_close <= 0:
        return float("nan")
    return (float(low_px) / float(prev_close) - 1.0) * 100.0


def body_drop_pct(open_px: float, close_px: float) -> float:
    """阴线实体跌幅 % = (open-close)/open。"""
    open_px = float(open_px)
    if open_px <= 0:
        return float("nan")
    return max(0.0, (open_px - float(close_px)) / open_px * 100.0)


def lower_shadow(open_px: float, close_px: float, low_px: float) -> float:
    """下引线长度。"""
    return float(min(open_px, close_px)) - float(low_px)


def body_abs(open_px: float, close_px: float) -> float:
    """阴线实体绝对值（元）。"""
    return max(0.0, float(open_px) - float(close_px))


def match_oversold_hammer_yin(
    *,
    open_px: float,
    high_px: float,
    low_px: float,
    close_px: float,
    prev_close: float,
    min_day_drop_pct: float = MIN_DAY_DROP_PCT,
    max_body_drop_pct: float = MAX_BODY_DROP_PCT,
    max_body_abs: float = MAX_BODY_ABS,
    body_mode: str = "pct",
) -> bool:
    """是否满足：超跌 + 低开 + 带下引线小阴。

    body_mode:
      - pct: (open-close)/open*100 < max_body_drop_pct（默认 1%）
      - abs: 实体绝对值 < max_body_abs
    """
    _ = high_px
    if prev_close <= 0 or open_px <= 0:
        return False
    if low_drop_pct(low_px, prev_close) > -min_day_drop_pct:
        return False
    if open_px + 1e-12 >= prev_close:
        return False
    if close_px + 1e-12 >= open_px:
        return False
    if body_mode == "pct":
        if body_drop_pct(open_px, close_px) + 1e-12 >= max_body_drop_pct:
            return False
    elif body_abs(open_px, close_px) + 1e-12 >= max_body_abs:
        return False
    if lower_shadow(open_px, close_px, low_px) <= 1e-12:
        return False
    return True
