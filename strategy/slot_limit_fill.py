"""三槽限价补仓：按 1 分钟 K 判断挂单价是否成交。

槽满触买只锁定开盘突破价；腾槽后须某根 1m 的最低价打到/低于挂单价才成交。
空槽时新突破：该根最高价打到买点即可按买点成交。

盯盘与 ``pool_1m`` 共用，避免两边成交纪律分叉。

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
) -> dict[str, Any] | None:
    """按时间顺序扫 1m，返回第一笔可成交。

    ``require_pullback=True``：槽满后挂单，须 ``low≤挂单价``。
    ``require_pullback=False``：空槽新突破，须 ``high≥挂单价``，成交价=挂单价。
    """
    lp = float(limit_px)
    if lp <= 0:
        return None
    if bars is None or getattr(bars, "empty", True):
        return None
    df = bars
    if "ts" in df.columns:
        df = df.sort_values("ts")
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
        if require_pullback:
            fill_px = limit_buy_fill_from_bar(lp, bar_open=o, bar_low=lo)
            if fill_px is None:
                continue
        else:
            if h + 1e-12 < lp:
                continue
            fill_px = lp
        return {
            "fill_px": float(fill_px),
            "fill_ts": bar_ts_str(ts),
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
    """同一分钟多票可成交：先比 1m 成交时间，再比触买时间，再比代码。"""
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
