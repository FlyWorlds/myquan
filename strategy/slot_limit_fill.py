"""三槽限价补仓：按 1 分钟 K 判断挂单价是否成交。

规则（盯盘是生产真源；``pool_1m`` 必须同一套函数）：
  · 所有触买先入队（槽满旧信号、腾槽后新突破都进队列），再按队列补到满槽
  · 腾槽前触买：从 max(触买分钟, 腾槽分钟) 起扫 1m，须 ``low≤挂单价``
  · 腾槽后/空槽新突破：触买单根 ``high≥买点`` 可按买点成交
  · 触买当根没排上槽：之后再腾槽改回落到价
  · 成交时钟 = 第一根碰到挂单价的 1m；同分钟再按触买先后
  · 成交价：开盘已不高于挂单价用开盘，否则用挂单价

研究用途，非投资建议。
"""

from __future__ import annotations

from typing import Any

import pandas as pd

TICK_SIZE = 0.01


def bar_ts_str(ts: Any) -> str | None:
    if ts is None:
        return None
    try:
        t = pd.Timestamp(ts)
        if getattr(t, "tzinfo", None) is not None:
            t = t.tz_convert("Asia/Shanghai").tz_localize(None)
        return t.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:  # noqa: BLE001
        s = str(ts).strip()
        return s or None


def _ge_ts(left: Any, right: Any) -> bool:
    """left 不早于 right（缺一边则不过滤）。"""
    a, b = bar_ts_str(left), bar_ts_str(right)
    if not a or not b:
        return True
    return a >= b


def first_1m_buy_trigger_ts(
    bars: pd.DataFrame | None,
    *,
    limit_px: float,
) -> str | None:
    """触买分钟：第一根 1m ``high≥挂单价``（突破信号），不用更早的回落根。"""
    lp = float(limit_px)
    if lp <= 0 or bars is None or getattr(bars, "empty", True):
        return None
    df = bars
    if "ts" in df.columns:
        df = df.sort_values("ts")
    for _, row in df.iterrows():
        try:
            h = float(row["high"])
        except (TypeError, ValueError, KeyError):
            continue
        if h + 1e-12 >= lp:
            ts = row["ts"] if "ts" in df.columns else None
            return bar_ts_str(ts)
    return None


def slot_queue_window(
    *,
    trigger_ts: str | None,
    slot_freed_at: str | None,
    queued_while_full: bool,
) -> tuple[str | None, bool]:
    """(since_ts, require_pullback)。盯盘生产窗口，回测必须相同。"""
    trig = bar_ts_str(trigger_ts)
    freed = bar_ts_str(slot_freed_at)
    if queued_while_full:
        if trig and freed:
            return (trig if trig >= freed else freed), True
        return (freed or trig), True
    if freed and trig and freed > trig:
        return freed, True
    return trig, False


def eval_queue_fill_on_bar(
    limit_px: float,
    *,
    bar_open: float | None,
    bar_high: float | None,
    bar_low: float | None,
    require_pullback: bool,
    allow_breakout: bool,
) -> float | None:
    """单根 1m：回落成交或（允许时）突破当根成交。"""
    lp = float(limit_px)
    if lp <= 0:
        return None
    pb = limit_buy_fill_from_bar(lp, bar_open=bar_open, bar_low=bar_low)
    if pb is not None:
        return pb
    try:
        h = float(bar_high or 0)
    except (TypeError, ValueError):
        h = 0.0
    if (not require_pullback) and allow_breakout and h + 1e-12 >= lp:
        return float(lp)
    return None


def limit_buy_fill_from_bar(
    limit_px: float,
    *,
    bar_open: float | None,
    bar_low: float | None,
    tick: float = TICK_SIZE,
) -> float | None:
    """单根 1m：限价买能否成交，返回成交价。

    · 最低价未打到挂单价 → 不成交
    · 开盘已不高于挂单价 → 按开盘（更好价）
    · 否则盘中回落到挂单价 → 按挂单价
    """
    lp = float(limit_px)
    if lp <= 0:
        return None
    lo = float(bar_low or 0)
    if lo <= 0 or lo > lp + 1e-12:
        return None
    o = float(bar_open or 0)
    if o > 0 and o <= lp + 1e-12:
        return round(o, 4) if tick and tick > 0 else float(o)
    return float(lp)


def first_1m_limit_buy_fill(
    bars: pd.DataFrame | None,
    *,
    limit_px: float,
    since_ts: str | None = None,
    require_pullback: bool = True,
    trigger_ts: str | None = None,
    slot_freed_at: str | None = None,
    queued_while_full: bool | None = None,
) -> dict[str, Any] | None:
    """按时间顺序扫 1m，返回第一笔可成交。

    传入 ``queued_while_full`` 时按 ``slot_queue_window`` 算 since / 是否回落。
    空槽新突破只允许**触买单根**用最高价成交；没排上槽之后改回落。
    """
    lp = float(limit_px)
    if lp <= 0:
        return None
    if queued_while_full is not None:
        since_ts, require_pullback = slot_queue_window(
            trigger_ts=trigger_ts,
            slot_freed_at=slot_freed_at,
            queued_while_full=bool(queued_while_full),
        )
    if bars is None or getattr(bars, "empty", True):
        return None
    df = bars
    if "ts" in df.columns:
        df = df.sort_values("ts")
    trig = bar_ts_str(trigger_ts)
    for _, row in df.iterrows():
        ts = row["ts"] if "ts" in df.columns else None
        if since_ts and not _ge_ts(ts, since_ts):
            continue
        try:
            h = float(row["high"])
            lo = float(row["low"])
        except (TypeError, ValueError, KeyError):
            continue
        if h <= 0 or lo <= 0:
            continue
        try:
            o = float(row["open"]) if "open" in df.columns else 0.0
        except (TypeError, ValueError):
            o = 0.0
        bar_s = bar_ts_str(ts)
        allow_breakout = (not require_pullback) and (
            not trig or bar_s == trig
        )
        fill_px = eval_queue_fill_on_bar(
            lp,
            bar_open=o,
            bar_high=h,
            bar_low=lo,
            require_pullback=require_pullback,
            allow_breakout=allow_breakout,
        )
        if fill_px is None:
            continue
        return {
            "fill_px": float(fill_px),
            "fill_ts": bar_s,
            "bar_open": o,
            "bar_high": h,
            "bar_low": lo,
        }
    return None


def rank_1m_slot_fills(
    fills: list[dict[str, Any]],
    *,
    free: int,
    buys_left: int,
) -> list[dict[str, Any]]:
    """可成交单按 1m 成交时钟，再按队列（触买先后）、再按代码，补到满槽。"""
    ranked = [dict(x) for x in fills if x.get("fill_px") and float(x["fill_px"]) > 0]
    ranked.sort(
        key=lambda x: (
            str(x.get("fill_ts") or ""),
            str(x.get("trigger_ts") or ""),
            str(x.get("code") or ""),
        )
    )
    n = max(0, min(int(free), int(buys_left)))
    return ranked[:n]
