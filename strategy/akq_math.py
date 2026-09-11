"""收益率 / 波动 / 盯市盈亏：一律走 akquant 向量原语。

盯盘与因子禁止再手写 ``(last/prev-1)``、对数收益标准差。
akquant 已有口径：

- ``vec_returns`` / ``vec_log_returns``：相对前值（昨收涨幅）
- ``TradePnL.unrealized_pnl``：``(现价 - 开仓均价) × 股数``
- 回测权益日变化：今买相对买入价，昨仓相对昨收（日初已按昨收盯市）

A 股券商「今日盈亏」与上述权益日变化相同，本模块 ``session_day_pnl`` 是唯一入口。
"""

from __future__ import annotations

import math
from typing import Any, Iterable

import numpy as np
from akquant import vec_log_returns, vec_returns, vec_rolling_std


def _finite_pos(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x) or x <= 0:
        return None
    return x


def simple_return(curr: Any, prev: Any) -> float | None:
    """akquant ``vec_returns`` 两点：(curr - prev) / prev。"""
    a = _finite_pos(prev)
    try:
        b = float(curr)
    except (TypeError, ValueError):
        return None
    if a is None or not math.isfinite(b):
        return None
    out = vec_returns(np.asarray([a, b], dtype=np.float64))
    r = float(out[1])
    if not math.isfinite(r):
        return None
    return r


def price_chg_pct(curr: Any, prev: Any) -> float | None:
    """涨幅%：现价相对昨收/开盘等前值，内部 ``vec_returns × 100``。"""
    r = simple_return(curr, prev)
    return None if r is None else r * 100.0


def mark_unrealized(
    mark: Any,
    cost: Any,
    qty: int,
) -> tuple[float | None, float | None]:
    """对齐 akquant ``TradePnL.unrealized_pnl``：相对开仓均价。"""
    if int(qty) <= 0:
        return None, None
    c = _finite_pos(cost)
    try:
        m = float(mark)
    except (TypeError, ValueError):
        return None, None
    if c is None or not math.isfinite(m):
        return None, None
    pnl = (m - c) * int(qty)
    pct = simple_return(m, c)
    return (
        round(pnl, 2),
        None if pct is None else round(pct * 100.0, 2),
    )


def session_day_pnl(
    *,
    mark: float,
    qty: int,
    cost: float | None = None,
    prev_close: float | None = None,
    bought_today: bool = False,
    fallback: float | None = None,
) -> tuple[float | None, float | None, float | None]:
    """今日盈亏（权益相对日初）。

    - 今买：日初无该仓 → 相对买入价
    - 昨仓：日初已按昨收盯市 → 相对昨收（``vec_returns``）
    """
    if int(qty) <= 0:
        return None, None, None
    try:
        last = float(mark)
    except (TypeError, ValueError):
        return None, None, None
    if not math.isfinite(last):
        return None, None, None
    if bought_today:
        base = _finite_pos(cost) or _finite_pos(fallback)
    else:
        base = _finite_pos(prev_close) or _finite_pos(fallback)
    if base is None:
        return None, None, None
    pnl = (last - base) * int(qty)
    notional = base * int(qty)
    pct = simple_return(last, base)
    return (
        round(pnl, 2),
        None if pct is None else round(pct * 100.0, 2),
        round(notional, 2),
    )


def log_return_sample_std(
    closes: Iterable[Any],
    *,
    window: int = 20,
) -> float | None:
    """近 window 根日对数收益样本标准差（不年化）。``vec_log_returns`` + ``vec_rolling_std``。"""
    vals: list[float] = []
    for x in closes or []:
        v = _finite_pos(x)
        if v is not None:
            vals.append(v)
    w = max(2, int(window))
    if len(vals) < w + 1:
        return None
    arr = np.asarray(vals[-(w + 1) :], dtype=np.float64)
    rets = vec_log_returns(arr)
    finite = rets[np.isfinite(rets)]
    if finite.size < w:
        return None
    stds = vec_rolling_std(np.asarray(finite, dtype=np.float64), w)
    last = float(stds[-1])
    if not math.isfinite(last):
        return None
    return last
