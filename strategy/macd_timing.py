"""因子14 · MACD 择时（教科书买图标准）。

默认参数 MACD(12, 26, 9)：
  · DIF = EMA(close, 12) − EMA(close, 26)
  · DEA = EMA(DIF, 9)
  · HIST = 2 × (DIF − DEA)

买图标准（可组合）：
  1. 金叉/死叉：DIF 上穿 DEA 买入，下穿卖出
  2. 零轴过滤：仅「零轴下金叉」买、「零轴上死叉」卖（更贴近教科书）
  3. 柱翻红/绿：HIST 由负转正买、由正转负卖

执行：收盘确认信号 → 次日开盘成交（无未来函数）；默认 T+1。
研究用途，不构成投资建议。
"""

from __future__ import annotations

from typing import Any, Literal

import numpy as np
import pandas as pd

Mode = Literal["cross", "zero_cross", "hist_flip", "zero_hist"]

DEFAULT_FAST = 12
DEFAULT_SLOW = 26
DEFAULT_SIGNAL = 9
DEFAULT_MODE: Mode = "zero_cross"


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.astype(float).ewm(span=int(span), adjust=False).mean()


def compute_macd(
    close: pd.Series,
    *,
    fast: int = DEFAULT_FAST,
    slow: int = DEFAULT_SLOW,
    signal: int = DEFAULT_SIGNAL,
) -> pd.DataFrame:
    """返回对齐 close 索引的 DIF / DEA / HIST。"""
    c = close.astype(float)
    dif = ema(c, fast) - ema(c, slow)
    dea = ema(dif, signal)
    hist = 2.0 * (dif - dea)
    return pd.DataFrame({"dif": dif, "dea": dea, "hist": hist}, index=c.index)


def _cross_up(a: pd.Series, b: pd.Series) -> pd.Series:
    prev = a.shift(1) <= b.shift(1)
    now = a > b
    return prev & now


def _cross_down(a: pd.Series, b: pd.Series) -> pd.Series:
    prev = a.shift(1) >= b.shift(1)
    now = a < b
    return prev & now


def macd_signals(
    close: pd.Series,
    *,
    fast: int = DEFAULT_FAST,
    slow: int = DEFAULT_SLOW,
    signal: int = DEFAULT_SIGNAL,
    mode: Mode = DEFAULT_MODE,
) -> pd.DataFrame:
    """按买图标准生成当日收盘确认的 buy/sell 布尔列。

    mode:
      · cross      — 纯金叉买 / 死叉卖
      · zero_cross — 零轴下金叉买 / 零轴上死叉卖（默认教科书）
      · hist_flip  — 柱由负转正买 / 由正转负卖
      · zero_hist  — 零轴下柱翻红买 / 零轴上柱翻绿卖
    """
    macd = compute_macd(close, fast=fast, slow=slow, signal=signal)
    dif, dea, hist = macd["dif"], macd["dea"], macd["hist"]
    golden = _cross_up(dif, dea)
    death = _cross_down(dif, dea)
    hist_up = _cross_up(hist, pd.Series(0.0, index=hist.index))
    hist_dn = _cross_down(hist, pd.Series(0.0, index=hist.index))
    below_zero = (dif < 0) & (dea < 0)
    above_zero = (dif > 0) & (dea > 0)

    if mode == "cross":
        buy, sell = golden, death
    elif mode == "zero_cross":
        buy = golden & below_zero
        sell = death & above_zero
    elif mode == "hist_flip":
        buy, sell = hist_up, hist_dn
    elif mode == "zero_hist":
        buy = hist_up & (dea < 0)
        sell = hist_dn & (dea > 0)
    else:
        raise ValueError(f"unknown MACD mode: {mode}")

    out = macd.copy()
    out["buy"] = buy.fillna(False).astype(bool)
    out["sell"] = sell.fillna(False).astype(bool)
    out["golden"] = golden.fillna(False).astype(bool)
    out["death"] = death.fillna(False).astype(bool)
    return out


def macd_rules_text(
    *,
    fast: int = DEFAULT_FAST,
    slow: int = DEFAULT_SLOW,
    signal: int = DEFAULT_SIGNAL,
    mode: Mode = DEFAULT_MODE,
) -> str:
    mode_desc = {
        "cross": "纯金叉买 / 死叉卖",
        "zero_cross": "零轴下金叉买 / 零轴上死叉卖（教科书）",
        "hist_flip": "柱翻红买 / 柱翻绿卖",
        "zero_hist": "零轴下柱翻红买 / 零轴上柱翻绿卖",
    }
    return "\n".join(
        [
            "================================================================================",
            "  因子14 — MACD 择时（买图标准）",
            "================================================================================",
            f"  · 参数 MACD({fast},{slow},{signal})",
            f"  · 模式: {mode} — {mode_desc.get(mode, mode)}",
            "  · 收盘确认 → 次日开盘成交；默认 T+1",
            "  · 研究用途，不构成投资建议",
            "================================================================================",
        ]
    )


def strategy_signal(
    close: float | None = None,
    *,
    dif: float | None = None,
    dea: float | None = None,
    hist: float | None = None,
    prev_dif: float | None = None,
    prev_dea: float | None = None,
    prev_hist: float | None = None,
    mode: Mode = DEFAULT_MODE,
    **_: Any,
) -> dict[str, Any]:
    """单 bar 决策辅助（盯盘可调用）；完整序列请用 macd_signals。"""
    if dif is None or dea is None or prev_dif is None or prev_dea is None:
        return {"action": "hold", "reason": "MACD 不足"}
    golden = prev_dif <= prev_dea and dif > dea
    death = prev_dif >= prev_dea and dif < dea
    hist_v = 0.0 if hist is None else float(hist)
    prev_h = 0.0 if prev_hist is None else float(prev_hist)
    hist_up = prev_h <= 0 and hist_v > 0
    hist_dn = prev_h >= 0 and hist_v < 0
    below = dif < 0 and dea < 0
    above = dif > 0 and dea > 0

    buy = sell = False
    if mode == "cross":
        buy, sell = golden, death
    elif mode == "zero_cross":
        buy, sell = golden and below, death and above
    elif mode == "hist_flip":
        buy, sell = hist_up, hist_dn
    elif mode == "zero_hist":
        buy, sell = hist_up and dea < 0, hist_dn and dea > 0

    if buy:
        return {"action": "buy", "reason": f"MACD买图({mode})", "dif": dif, "dea": dea}
    if sell:
        return {"action": "sell", "reason": f"MACD卖图({mode})", "dif": dif, "dea": dea}
    return {"action": "hold", "reason": "无交叉", "dif": dif, "dea": dea}


__all__ = [
    "DEFAULT_FAST",
    "DEFAULT_SLOW",
    "DEFAULT_SIGNAL",
    "DEFAULT_MODE",
    "Mode",
    "ema",
    "compute_macd",
    "macd_signals",
    "macd_rules_text",
    "strategy_signal",
]
