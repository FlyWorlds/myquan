"""因子1 叠加：双均线死叉 / 即将死叉分批止盈信号。

约定（无未来函数）：
  · 当日收盘算 fast/slow MA → 判定 near_death / death
  · 次日开盘执行减仓（exec 映射挂到执行日）
  · 默认不替换仅止损基线；由 BacktestConfig.ma_tp_enabled 显式开启

即将死叉：仍多头（fast≥slow），但缺口收窄且 gap_pct ≤ near_gap。
死叉：缺口由非负翻负（sign change）。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

DEFAULT_FAST = 5
DEFAULT_SLOW = 20  # 对照回测：5/20 相对仅止损损耗显著小于 5/10
DEFAULT_NEAR_GAP = 0.008  # 0.8%
DEFAULT_NEAR_REDUCE = 0.40
DEFAULT_DEATH_REDUCE = 1.0  # 余仓全清
DEFAULT_MIN_PROFIT = 0.03  # 浮盈≥3% 才允许均线止盈
DEFAULT_MIN_HOLD_BARS = 1


def _sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(int(n), min_periods=int(n)).mean()


def _day_key(ts) -> str:
    t = pd.Timestamp(ts)
    if t.tzinfo is not None:
        t = t.tz_localize(None)
    return t.strftime("%Y-%m-%d")


def compute_ma_cross_frame(
    daily: pd.DataFrame,
    *,
    fast: int = DEFAULT_FAST,
    slow: int = DEFAULT_SLOW,
    near_gap: float = DEFAULT_NEAR_GAP,
) -> pd.DataFrame:
    """在日线上附加 ma_fast / ma_slow / ma_gap_pct / ma_signal。

    ma_signal ∈ {\"\", \"near\", \"death\"}，按**当日收盘**确认。
    """
    if daily is None or getattr(daily, "empty", True):
        return pd.DataFrame()
    if "close" not in daily.columns or "date" not in daily.columns:
        raise ValueError("daily must contain date and close")
    fast_n = int(fast)
    slow_n = int(slow)
    if fast_n < 1 or slow_n <= fast_n:
        raise ValueError(f"need 1 <= fast < slow, got fast={fast_n} slow={slow_n}")
    near = max(0.0, float(near_gap))

    out = daily.copy()
    c = out["close"].astype(float)
    ma_f = _sma(c, fast_n)
    ma_s = _sma(c, slow_n)
    gap = (ma_f - ma_s) / ma_s.replace(0.0, np.nan)
    gap_prev = gap.shift(1)

    death = (gap_prev >= 0.0) & (gap < 0.0)
    # 即将死叉：仍≥0，缺口收窄，且绝对缺口 ≤ near_gap
    near_mask = (
        (gap >= 0.0)
        & gap_prev.notna()
        & (gap < gap_prev)
        & (gap <= near)
        & (~death)
    )

    signal = pd.Series("", index=out.index, dtype=object)
    signal = signal.mask(near_mask.fillna(False), "near")
    signal = signal.mask(death.fillna(False), "death")

    out["ma_fast"] = ma_f
    out["ma_slow"] = ma_s
    out["ma_gap_pct"] = gap
    out["ma_signal"] = signal
    return out


def ma_tp_exec_by_date(
    daily: pd.DataFrame,
    *,
    fast: int = DEFAULT_FAST,
    slow: int = DEFAULT_SLOW,
    near_gap: float = DEFAULT_NEAR_GAP,
) -> dict[str, str]:
    """收盘信号 → 次日执行日映射。

    返回 {exec_date: \"near\"|\"death\"}。同日若既有 near 又有 death（不应发生），
    death 优先。
    """
    frame = compute_ma_cross_frame(
        daily, fast=fast, slow=slow, near_gap=near_gap
    )
    if frame.empty:
        return {}
    dates = [_day_key(x) for x in frame["date"].tolist()]
    signals = [str(x or "") for x in frame["ma_signal"].tolist()]
    out: dict[str, str] = {}
    for i, sig in enumerate(signals):
        if sig not in ("near", "death"):
            continue
        if i + 1 >= len(dates):
            continue
        exec_day = dates[i + 1]
        prev = out.get(exec_day, "")
        if prev == "death":
            continue
        if sig == "death" or prev != "death":
            out[exec_day] = sig
    return out


def recommended_params() -> dict[str, Any]:
    """研究默认推荐（5/20；近死叉减 40%；死叉清余）。

    凯盛/天通 2020+ 对照：相对仅止损全样本约保留 92–94% 收益，
    凯盛样本外几乎持平；短均线 5/10 会明显砍趋势，不推荐默认。
    """
    return {
        "ma_tp_enabled": True,
        "ma_tp_fast": DEFAULT_FAST,
        "ma_tp_slow": DEFAULT_SLOW,
        "ma_tp_near_gap": DEFAULT_NEAR_GAP,
        "ma_tp_near_reduce": DEFAULT_NEAR_REDUCE,
        "ma_tp_death_reduce": DEFAULT_DEATH_REDUCE,
        "ma_tp_min_profit": DEFAULT_MIN_PROFIT,
        "ma_tp_min_hold_bars": DEFAULT_MIN_HOLD_BARS,
        "ma_tp_lock_pct": 0.0,  # 近死叉后抬止损到成本
    }


def rules_text(
    *,
    fast: int = DEFAULT_FAST,
    slow: int = DEFAULT_SLOW,
    near_gap: float = DEFAULT_NEAR_GAP,
    near_reduce: float = DEFAULT_NEAR_REDUCE,
    death_reduce: float = DEFAULT_DEATH_REDUCE,
    min_profit: float = DEFAULT_MIN_PROFIT,
    min_hold_bars: int = DEFAULT_MIN_HOLD_BARS,
    lock_pct: float | None = 0.0,
) -> str:
    lock = (
        f"近死叉后抬止损至成本+{float(lock_pct)*100:.0f}%"
        if lock_pct is not None
        else "不抬止损"
    )
    death_txt = (
        "余仓全清"
        if float(death_reduce) >= 1.0 - 1e-12
        else f"再减初始仓×{float(death_reduce)*100:.0f}%"
    )
    return (
        f"双均线{int(fast)}/{int(slow)}：收盘确认→次日开盘执行；"
        f"即将死叉(gap≤{float(near_gap)*100:.1f}%且收窄)减初始仓"
        f"{float(near_reduce)*100:.0f}%；死叉{death_txt}；"
        f"浮盈≥{float(min_profit)*100:.0f}%且持有≥{int(min_hold_bars)}日才触发；"
        f"{lock}"
    )


__all__ = [
    "DEFAULT_FAST",
    "DEFAULT_SLOW",
    "DEFAULT_NEAR_GAP",
    "DEFAULT_NEAR_REDUCE",
    "DEFAULT_DEATH_REDUCE",
    "DEFAULT_MIN_PROFIT",
    "DEFAULT_MIN_HOLD_BARS",
    "compute_ma_cross_frame",
    "ma_tp_exec_by_date",
    "recommended_params",
    "rules_text",
]
