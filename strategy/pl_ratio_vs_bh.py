"""相对持股盈亏比（pl_ratio_vs_bh）。

口径（逐笔闭环，费用后策略收益 vs 同期买入持有）：
  · 盈利笔（策略收益 > 0）：落后 lag = max(0, 持股收益 − 策略收益)，越小越好
  · 亏损笔（策略收益 ≤ 0）：防守 def = max(0, 策略收益 − 持股收益)，越大越好
  · 汇总：pl_ratio_vs_bh = 亏损笔平均防守 / 盈利笔平均落后（越大越好）

持股收益：买入日收盘 → 卖出日收盘，close[sell] / close[buy] − 1。
"""

from __future__ import annotations

import numpy as np

TradePair = tuple[float, float]  # (strat_ret, bh_ret) 小数


def hold_return(close: np.ndarray, buy_i: int, sell_i: int) -> float:
    """同期买入持有收益率（买入日收→卖出日收）。"""
    c0 = float(close[int(buy_i)])
    c1 = float(close[int(sell_i)])
    if c0 <= 0:
        return float("nan")
    return c1 / c0 - 1.0


def pl_ratio_vs_bh_from_trades(
    strat_rets: list[float] | np.ndarray,
    bh_rets: list[float] | np.ndarray,
) -> dict[str, float]:
    """由逐笔 (策略收益, 持股收益) 计算相对持股盈亏比及分解项。"""
    empty = {
        "pl_ratio_vs_bh": np.nan,
        "mean_lag_pct": np.nan,
        "mean_def_pct": np.nan,
        "n_win_trades": 0,
        "n_loss_trades": 0,
    }
    if strat_rets is None or bh_rets is None:
        return empty
    pairs = [
        (float(r), float(h))
        for r, h in zip(strat_rets, bh_rets, strict=False)
        if r == r and h == h
    ]
    if not pairs:
        return empty

    lags: list[float] = []
    defs: list[float] = []
    n_win = 0
    n_loss = 0
    for r, h in pairs:
        if r > 0:
            n_win += 1
            lags.append(max(0.0, h - r))
        else:
            n_loss += 1
            defs.append(max(0.0, r - h))

    mean_lag = float(np.mean(lags)) if lags else float("nan")
    mean_def = float(np.mean(defs)) if defs else float("nan")

    if mean_lag == mean_lag and mean_lag > 1e-12:
        ratio = (mean_def / mean_lag) if mean_def == mean_def else 0.0
    elif lags and mean_lag == mean_lag and mean_lag <= 1e-12:
        ratio = float("inf")
    elif defs and mean_def == mean_def and mean_def > 0:
        ratio = float("inf")
    else:
        ratio = float("nan")

    if ratio == float("inf"):
        ratio_out = float("inf")
    elif ratio == ratio:
        ratio_out = float(ratio)
    else:
        ratio_out = float("nan")

    return {
        "pl_ratio_vs_bh": ratio_out,
        "mean_lag_pct": mean_lag * 100.0 if mean_lag == mean_lag else np.nan,
        "mean_def_pct": mean_def * 100.0 if mean_def == mean_def else np.nan,
        "n_win_trades": n_win,
        "n_loss_trades": n_loss,
    }


def pl_ratio_vs_bh_from_pairs(pairs: list[TradePair]) -> dict[str, float]:
    if not pairs:
        return pl_ratio_vs_bh_from_trades([], [])
    strat = [p[0] for p in pairs]
    bh = [p[1] for p in pairs]
    return pl_ratio_vs_bh_from_trades(strat, bh)
