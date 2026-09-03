"""因子22 · 收盘动量：因子1 止损后，收盘确认自当日最低点反弹再买。

研究用途，非投资建议。默认叠在因子1 上：当日止损清仓后，若收盘价已站上
``low × (1 + bounce_pct)``，则按阈值价同日再买（T+1）。

仅在 2026 天通（±3%）日线上做过对照；路径敏感，未绑默认策略。
"""

from __future__ import annotations

from typing import Any, Literal

CandleFilter = Literal["any", "yang", "yin"]
ConfirmMode = Literal["close", "intraday"]

DEFAULT_BOUNCE_PCT = 0.01
DEFAULT_CANDLE: CandleFilter = "any"
DEFAULT_MODE: ConfirmMode = "close"


def bounce_threshold(low: float, bounce_pct: float = DEFAULT_BOUNCE_PCT) -> float:
    return float(low) * (1.0 + float(bounce_pct))


def candle_ok(
    open_px: float,
    close_px: float,
    candle: CandleFilter = DEFAULT_CANDLE,
) -> bool:
    o, c = float(open_px), float(close_px)
    if candle == "yang":
        return c > o + 1e-12
    if candle == "yin":
        return c < o - 1e-12
    return True


def rebuy_signal(
    *,
    open_px: float,
    high_px: float,
    low_px: float,
    close_px: float,
    bounce_pct: float = DEFAULT_BOUNCE_PCT,
    candle: CandleFilter = DEFAULT_CANDLE,
    mode: ConfirmMode = DEFAULT_MODE,
    tick_ceil: Any | None = None,
) -> dict[str, Any]:
    """止损后同日再买判定。

    Parameters
    ----------
    mode:
      ``close`` — 收盘 ≥ low×(1+pct) 才买（收盘确认）
      ``intraday`` — 最高价曾 ≥ low×(1+pct)（日线易高估，研究对照用）
    tick_ceil:
      可选 ``(price, tick) -> price``；默认原样返回阈值。
    """
    low = float(low_px)
    if low <= 0:
        return {"ok": False, "reason": "bad_low", "thr": None, "fill_px": None}

    if not candle_ok(open_px, close_px, candle):
        return {
            "ok": False,
            "reason": f"candle!={candle}",
            "thr": None,
            "fill_px": None,
        }

    thr = bounce_threshold(low, bounce_pct)
    if tick_ceil is not None:
        thr = float(tick_ceil(thr))

    if mode == "close":
        hit = float(close_px) + 1e-12 >= thr
        reason = f"close>=low*(1+{float(bounce_pct):.1%})"
    else:
        hit = float(high_px) + 1e-12 >= thr
        reason = f"high>=low*(1+{float(bounce_pct):.1%})"

    if candle != "any":
        reason += f"&{candle}"

    if not hit:
        return {"ok": False, "reason": "miss_thr", "thr": thr, "fill_px": None}

    return {"ok": True, "reason": reason, "thr": thr, "fill_px": thr}


def rules_text(
    *,
    bounce_pct: float = DEFAULT_BOUNCE_PCT,
    candle: CandleFilter = DEFAULT_CANDLE,
    mode: ConfirmMode = DEFAULT_MODE,
) -> str:
    mode_cn = "收盘确认" if mode == "close" else "盘中触价（日线易高估）"
    candle_cn = {"any": "不限阴阳", "yang": "须收阳", "yin": "须收阴"}[candle]
    return (
        f"因子22-收盘动量\n"
        f"  · 前置：因子1（或同源开盘突破）当日已止损清仓\n"
        f"  · 再买：{mode_cn}，门槛 = 当日最低价 × (1+{float(bounce_pct):.1%})\n"
        f"  · 阴阳：{candle_cn}\n"
        f"  · 成交：按门槛价（收盘确认时实盘更贴近收盘价）\n"
        f"  · 默认绑策略一；研究对照见 backtest/tiantong_stop_rebuy_2026/\n"
        f"  · 对照：backtest/tiantong_stop_rebuy_2026/"
    )


__all__ = [
    "DEFAULT_BOUNCE_PCT",
    "DEFAULT_CANDLE",
    "DEFAULT_MODE",
    "bounce_threshold",
    "candle_ok",
    "rebuy_signal",
    "rules_text",
]
