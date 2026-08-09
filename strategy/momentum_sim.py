"""动量因子快速向量化仿真（用于挖参；口径贴近次日开盘/T+1/费率）。"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from strategy.momentum import build_momentum_signals


def simulate_momentum(
    daily: pd.DataFrame,
    *,
    kind: str,
    params: dict[str, Any] | None = None,
    initial_cash: float = 100_000.0,
    target_pct: float = 0.95,
    commission_rate: float = 0.0000854,
    stamp_tax_rate: float = 0.001,
    slippage_value: float = 0.001,
    lot_size: int = 100,
) -> dict[str, float]:
    """次日开盘调仓仿真。返回收益/回撤/夏普等。"""
    df = build_momentum_signals(daily, kind=kind, params=params)
    opens = df["open"].astype(float).to_numpy()
    closes = df["close"].astype(float).to_numpy()
    exec_tgt = df["mom_exec"].to_numpy(dtype=float)

    cash = float(initial_cash)
    shares = 0
    equity_curve: list[float] = []
    buy_day = -999
    peak = initial_cash
    max_dd = 0.0

    for i in range(len(df)):
        tgt = exec_tgt[i]
        if np.isnan(tgt):
            tgt = 0.0
        want_long = tgt >= 0.5
        o = opens[i]
        c = closes[i]
        if o <= 0 or c <= 0:
            equity_curve.append(cash + shares * max(c, 0))
            continue

        # 卖：非买入日即可（T+1）
        if shares > 0 and not want_long and i > buy_day:
            px = o * (1.0 - slippage_value)
            proceeds = shares * px
            fee = proceeds * (commission_rate + stamp_tax_rate)
            cash += proceeds - fee
            shares = 0

        # 买
        if shares <= 0 and want_long:
            px = o * (1.0 + slippage_value)
            budget = cash * target_pct
            qty = int(budget // (px * lot_size)) * lot_size
            if qty > 0:
                cost = qty * px
                fee = cost * commission_rate
                if cost + fee <= cash:
                    cash -= cost + fee
                    shares = qty
                    buy_day = i

        eq = cash + shares * c
        equity_curve.append(eq)
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd

    eq = np.asarray(equity_curve, dtype=float)
    if len(eq) < 3:
        return {
            "total_return": 0.0,
            "max_dd": 0.0,
            "sharpe": 0.0,
            "trades": 0.0,
            "end_equity": float(initial_cash),
        }
    rets = np.diff(eq) / np.where(eq[:-1] == 0, np.nan, eq[:-1])
    rets = rets[np.isfinite(rets)]
    if len(rets) == 0 or np.std(rets) < 1e-12:
        sharpe = 0.0
    else:
        sharpe = float(np.mean(rets) / np.std(rets) * np.sqrt(252))
    total_return = float(eq[-1] / initial_cash - 1.0)
    # 粗估交易次数：持仓 0→正 次数
    flips = 0
    prev = 0
    pos = 0
    for i in range(len(df)):
        t = exec_tgt[i]
        if np.isnan(t):
            t = 0.0
        cur = 1 if t >= 0.5 else 0
        if prev == 0 and cur == 1:
            flips += 1
        prev = cur
        pos = cur
    return {
        "total_return": total_return,
        "max_dd": float(max_dd),
        "sharpe": sharpe,
        "trades": float(flips),
        "end_equity": float(eq[-1]),
    }


__all__ = ["simulate_momentum"]
