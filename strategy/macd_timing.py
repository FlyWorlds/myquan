"""因子14 · MACD 择时（买图标准 + 放宽版）。

默认参数 MACD(12, 26, 9)：
  · DIF = EMA(close, 12) − EMA(close, 26)
  · DEA = EMA(DIF, 9)
  · HIST = 2 × (DIF − DEA)

严格买图：
  1. 金叉/死叉：DIF 上穿/下穿 DEA
  2. 零轴过滤：零轴下金叉买 / 零轴上死叉卖
  3. 柱翻红/绿

放宽买图（mode=relaxed / relaxed_8179）：
  · 金叉 / 死叉（经典）
  · 即将金叉/死叉：未交叉但缺口收窄、方向相向，缺口 < near_gap×收盘价
  · 快要金叉/死叉：缺口更小 < almost_gap×收盘价，且 DIF 朝交叉方向走
  · 金叉趋势：已在 DIF>DEA，柱重新放大（回抽后再起）
  · 死叉趋势：已在 DIF<DEA，柱再向下放大

执行：收盘确认 → 次日开盘；默认 T+1。
研究用途，不构成投资建议。
"""

from __future__ import annotations

from typing import Any, Literal

import pandas as pd

Mode = Literal[
    "cross",
    "zero_cross",
    "hist_flip",
    "zero_hist",
    "relaxed",
    "relaxed_zero",
]

DEFAULT_FAST = 12
DEFAULT_SLOW = 26
DEFAULT_SIGNAL = 9
DEFAULT_MODE: Mode = "relaxed"
# 缺口相对收盘价：即将 / 快要（ETF 价约 1～2，0.15%/0.08% 约等于柱很贴近）
DEFAULT_NEAR_GAP = 0.0015
DEFAULT_ALMOST_GAP = 0.0008


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
    return (a.shift(1) <= b.shift(1)) & (a > b)


def _cross_down(a: pd.Series, b: pd.Series) -> pd.Series:
    return (a.shift(1) >= b.shift(1)) & (a < b)


def _relaxed_components(
    close: pd.Series,
    dif: pd.Series,
    dea: pd.Series,
    hist: pd.Series,
    *,
    near_gap: float = DEFAULT_NEAR_GAP,
    almost_gap: float = DEFAULT_ALMOST_GAP,
) -> dict[str, pd.Series]:
    """拆解放宽买图子条件，便于回测标注。"""
    c = close.astype(float).replace(0, pd.NA)
    gap = dif - dea
    gap_prev = gap.shift(1)
    abs_gap_pct = gap.abs() / c
    dif_up = dif > dif.shift(1)
    dif_dn = dif < dif.shift(1)
    dea_up = dea > dea.shift(1)
    dea_dn = dea < dea.shift(1)
    narrowing_up = gap > gap_prev  # 负缺口变大（向 0 靠）
    narrowing_dn = gap < gap_prev  # 正缺口变小（向 0 靠）

    golden = _cross_up(dif, dea)
    death = _cross_down(dif, dea)

    # 即将：未交叉 + 缺口收窄 + 方向相向 + 缺口已不太大
    near_golden = (
        (gap < 0)
        & narrowing_up
        & dif_up
        & (~dea_up)  # DEA 走平或下行
        & (abs_gap_pct < near_gap)
    )
    near_death = (
        (gap > 0)
        & narrowing_dn
        & dif_dn
        & (~dea_dn)
        & (abs_gap_pct < near_gap)
    )

    # 快要：缺口更近 + DIF 朝交叉方向
    almost_golden = (gap < 0) & dif_up & (abs_gap_pct < almost_gap)
    almost_death = (gap > 0) & dif_dn & (abs_gap_pct < almost_gap)

    # 金叉趋势：已多头排列，柱由缩转放（回抽后再起），避免每日连发
    hist_prev = hist.shift(1)
    hist_prev2 = hist.shift(2)
    golden_trend = (
        (gap > 0)
        & (hist > 0)
        & dif_up
        & (hist > hist_prev)
        & (hist_prev <= hist_prev2)  # 柱重新抬头
    )
    death_trend = (
        (gap < 0)
        & (hist < 0)
        & dif_dn
        & (hist < hist_prev)
        & (hist_prev >= hist_prev2)
    )

    buy = golden | near_golden | almost_golden | golden_trend
    sell = death | near_death | almost_death | death_trend
    return {
        "golden": golden,
        "death": death,
        "near_golden": near_golden,
        "near_death": near_death,
        "almost_golden": almost_golden,
        "almost_death": almost_death,
        "golden_trend": golden_trend,
        "death_trend": death_trend,
        "buy": buy,
        "sell": sell,
        "below_zero": (dif < 0) & (dea < 0),
        "above_zero": (dif > 0) & (dea > 0),
    }


def macd_signals(
    close: pd.Series,
    *,
    fast: int = DEFAULT_FAST,
    slow: int = DEFAULT_SLOW,
    signal: int = DEFAULT_SIGNAL,
    mode: Mode = DEFAULT_MODE,
    near_gap: float = DEFAULT_NEAR_GAP,
    almost_gap: float = DEFAULT_ALMOST_GAP,
) -> pd.DataFrame:
    """按买图标准生成当日收盘确认的 buy/sell 布尔列。"""
    macd = compute_macd(close, fast=fast, slow=slow, signal=signal)
    dif, dea, hist = macd["dif"], macd["dea"], macd["hist"]
    parts = _relaxed_components(
        close, dif, dea, hist, near_gap=near_gap, almost_gap=almost_gap
    )
    golden, death = parts["golden"], parts["death"]
    hist_up = _cross_up(hist, pd.Series(0.0, index=hist.index))
    hist_dn = _cross_down(hist, pd.Series(0.0, index=hist.index))
    below_zero, above_zero = parts["below_zero"], parts["above_zero"]

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
    elif mode == "relaxed":
        buy, sell = parts["buy"], parts["sell"]
    elif mode == "relaxed_zero":
        # 放宽信号仍要求买侧偏零轴下、卖侧偏零轴上（趋势类用 gap 符号即可）
        buy = (
            (golden & below_zero)
            | (parts["near_golden"] & below_zero)
            | (parts["almost_golden"] & below_zero)
            | (parts["golden_trend"] & (dif > 0))
        )
        sell = (
            (death & above_zero)
            | (parts["near_death"] & above_zero)
            | (parts["almost_death"] & above_zero)
            | (parts["death_trend"] & (dif < 0))
        )
    else:
        raise ValueError(f"unknown MACD mode: {mode}")

    out = macd.copy()
    out["buy"] = buy.fillna(False).astype(bool)
    out["sell"] = sell.fillna(False).astype(bool)
    for k in (
        "golden",
        "death",
        "near_golden",
        "near_death",
        "almost_golden",
        "almost_death",
        "golden_trend",
        "death_trend",
    ):
        out[k] = parts[k].fillna(False).astype(bool)
    return out


def macd_rules_text(
    *,
    fast: int = DEFAULT_FAST,
    slow: int = DEFAULT_SLOW,
    signal: int = DEFAULT_SIGNAL,
    mode: Mode = DEFAULT_MODE,
    near_gap: float = DEFAULT_NEAR_GAP,
    almost_gap: float = DEFAULT_ALMOST_GAP,
) -> str:
    mode_desc = {
        "cross": "纯金叉买 / 死叉卖",
        "zero_cross": "零轴下金叉买 / 零轴上死叉卖（教科书）",
        "hist_flip": "柱翻红买 / 柱翻绿卖",
        "zero_hist": "零轴下柱翻红买 / 零轴上柱翻绿卖",
        "relaxed": (
            "放宽：金叉|即将金叉|快要金叉|金叉趋势 买；"
            "死叉|即将死叉|快要死叉|死叉趋势 卖"
        ),
        "relaxed_zero": "放宽 + 零轴偏向过滤",
    }
    return "\n".join(
        [
            "================================================================================",
            "  因子14 — MACD 择时（买图 / 放宽）",
            "================================================================================",
            f"  · 参数 MACD({fast},{slow},{signal})",
            f"  · 模式: {mode} — {mode_desc.get(mode, mode)}",
            f"  · 即将缺口阈值: |DIF-DEA|/收盘 < {near_gap*100:.2f}%",
            f"  · 快要缺口阈值: |DIF-DEA|/收盘 < {almost_gap*100:.2f}%",
            "  · 即将=缺口收窄+方向相向；快要=缺口更近+DIF朝交叉",
            "  · 金叉趋势=已多头且柱由缩转放；死叉趋势=已空头且柱再放大",
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
    prev2_hist: float | None = None,
    mode: Mode = DEFAULT_MODE,
    near_gap: float = DEFAULT_NEAR_GAP,
    almost_gap: float = DEFAULT_ALMOST_GAP,
    **_: Any,
) -> dict[str, Any]:
    """单 bar 决策辅助；完整序列请用 macd_signals。"""
    if dif is None or dea is None or prev_dif is None or prev_dea is None:
        return {"action": "hold", "reason": "MACD 不足"}
    if close is None or float(close) == 0:
        return {"action": "hold", "reason": "无收盘价"}

    px = float(close)
    gap = float(dif) - float(dea)
    gap_prev = float(prev_dif) - float(prev_dea)
    abs_gap_pct = abs(gap) / px
    golden = prev_dif <= prev_dea and dif > dea
    death = prev_dif >= prev_dea and dif < dea
    hist_v = 0.0 if hist is None else float(hist)
    prev_h = 0.0 if prev_hist is None else float(prev_hist)
    prev2_h = prev_h if prev2_hist is None else float(prev2_hist)
    hist_up = prev_h <= 0 and hist_v > 0
    hist_dn = prev_h >= 0 and hist_v < 0
    below = dif < 0 and dea < 0
    above = dif > 0 and dea > 0
    dif_up = dif > prev_dif
    dif_dn = dif < prev_dif
    dea_up = dea > prev_dea
    dea_dn = dea < prev_dea

    near_golden = (
        gap < 0
        and gap > gap_prev
        and dif_up
        and not dea_up
        and abs_gap_pct < near_gap
    )
    near_death = (
        gap > 0
        and gap < gap_prev
        and dif_dn
        and not dea_dn
        and abs_gap_pct < near_gap
    )
    almost_golden = gap < 0 and dif_up and abs_gap_pct < almost_gap
    almost_death = gap > 0 and dif_dn and abs_gap_pct < almost_gap
    golden_trend = (
        gap > 0 and hist_v > 0 and dif_up and hist_v > prev_h and prev_h <= prev2_h
    )
    death_trend = (
        gap < 0 and hist_v < 0 and dif_dn and hist_v < prev_h and prev_h >= prev2_h
    )

    buy = sell = False
    reason = "无信号"
    if mode == "cross":
        buy, sell = golden, death
    elif mode == "zero_cross":
        buy, sell = golden and below, death and above
    elif mode == "hist_flip":
        buy, sell = hist_up, hist_dn
    elif mode == "zero_hist":
        buy, sell = hist_up and dea < 0, hist_dn and dea > 0
    elif mode == "relaxed":
        if golden:
            buy, reason = True, "金叉"
        elif near_golden:
            buy, reason = True, "即将金叉"
        elif almost_golden:
            buy, reason = True, "快要金叉"
        elif golden_trend:
            buy, reason = True, "金叉趋势"
        if death:
            sell, reason = True, "死叉"
        elif near_death:
            sell, reason = True, "即将死叉"
        elif almost_death:
            sell, reason = True, "快要死叉"
        elif death_trend:
            sell, reason = True, "死叉趋势"
    elif mode == "relaxed_zero":
        buy = (
            (golden and below)
            or (near_golden and below)
            or (almost_golden and below)
            or (golden_trend and dif > 0)
        )
        sell = (
            (death and above)
            or (near_death and above)
            or (almost_death and above)
            or (death_trend and dif < 0)
        )
        reason = "relaxed_zero"
    else:
        return {"action": "hold", "reason": f"未知模式{mode}"}

    # 同日冲突：持仓场景优先卖；空仓优先买 —— 由上层决定；这里同时给出
    if buy and not sell:
        return {"action": "buy", "reason": reason, "dif": dif, "dea": dea}
    if sell and not buy:
        return {"action": "sell", "reason": reason, "dif": dif, "dea": dea}
    if buy and sell:
        return {
            "action": "conflict",
            "reason": f"买卖同现:{reason}",
            "dif": dif,
            "dea": dea,
        }
    return {"action": "hold", "reason": "无交叉/放宽触发", "dif": dif, "dea": dea}


__all__ = [
    "DEFAULT_FAST",
    "DEFAULT_SLOW",
    "DEFAULT_SIGNAL",
    "DEFAULT_MODE",
    "DEFAULT_NEAR_GAP",
    "DEFAULT_ALMOST_GAP",
    "Mode",
    "ema",
    "compute_macd",
    "macd_signals",
    "macd_rules_text",
    "strategy_signal",
]
