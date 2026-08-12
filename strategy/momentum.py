"""因子3 · 动量：时序动量信号（单票）。

灵感（截面 Alpha 的时序化用法，非照搬 IC）：
  · roc         — N 日收益率动量（经典 TSMOM）
  · ma          — 收盘站上均线
  · dual_ma     — 双均线金叉/死叉
  · alpha022    — sma((c-mean(c,6))/mean(c,6), k) 偏离动量
  · up_ratio    — 近 N 日上涨日占比（Alpha191_190 思路）
  · breakout    — N 日高点突破买 / 低点跌破卖
  · dist_hl     — 距 N 日高低点的时间距离差（近低点→偏多）

交易约定（无未来函数）：
  · 当日收盘算因子 → 生成目标仓位信号
  · 次日开盘执行（T+1：买入当日不可卖）
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

MOMENTUM_KINDS = (
    "roc",
    "ma",
    "dual_ma",
    "alpha022",
    "up_ratio",
    "breakout",
    "dist_hl",
    "roc_ma",
    "dist_ma",
    "dual_dist",
)

# 凯盛挖参默认：N日高低点时间距离动量（可解释；非 Alpha191 黑盒）
DEFAULT_KIND = "dist_hl"
DEFAULT_PARAMS: dict[str, Any] = {
    "n": 120,
    "enter": 1.0,
    "exit": 0.0,
    "fast": 10,
    "slow": 30,
    "k": 12,
    "thresh": 0.55,
    "exit_thresh": 0.45,
}


def _sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(int(n), min_periods=int(n)).mean()


def compute_momentum_raw(
    daily: pd.DataFrame,
    *,
    kind: str,
    params: dict[str, Any] | None = None,
) -> pd.Series:
    """返回与 daily 对齐的原始因子值（越大越偏多）。"""
    p = {**DEFAULT_PARAMS, **(params or {})}
    kind = str(kind or DEFAULT_KIND).lower()
    c = daily["close"].astype(float)
    h = daily["high"].astype(float) if "high" in daily.columns else c
    low = daily["low"].astype(float) if "low" in daily.columns else c
    ret1 = c / c.shift(1) - 1.0

    if kind == "roc":
        n = int(p["n"])
        return c / c.shift(n) - 1.0

    if kind == "ma":
        n = int(p["n"])
        ma = _sma(c, n)
        return (c - ma) / ma.replace(0, np.nan)

    if kind == "dual_ma":
        fast = int(p["fast"])
        slow = int(p["slow"])
        return _sma(c, fast) - _sma(c, slow)

    if kind == "alpha022":
        # sma(((close - mean(close, 6)) / mean(close, 6)), k, 1) ≈ SMA of pct deviation
        m = int(p.get("m", 6))
        k = int(p["k"])
        base = _sma(c, m)
        dev = (c - base) / base.replace(0, np.nan)
        return _sma(dev, k)

    if kind == "up_ratio":
        n = int(p["n"])
        up = (ret1 > 0).astype(float)
        return up.rolling(n, min_periods=n).mean()

    if kind == "breakout":
        n = int(p["n"])
        # 相对前高/前低的位置：正=突破前高一侧
        hh = h.shift(1).rolling(n, min_periods=n).max()
        ll = low.shift(1).rolling(n, min_periods=n).min()
        mid = (hh + ll) / 2.0
        span = (hh - ll).replace(0, np.nan)
        return (c - mid) / span

    if kind == "dist_hl":
        n = int(p["n"])
        dist_high = pd.Series(np.nan, index=c.index, dtype=float)
        dist_low = pd.Series(np.nan, index=c.index, dtype=float)
        hv = h.to_numpy()
        lv = low.to_numpy()
        for i in range(n - 1, len(c)):
            sl_h = hv[i - n + 1 : i + 1]
            sl_l = lv[i - n + 1 : i + 1]
            dist_high.iloc[i] = (n - 1) - int(np.argmax(sl_h))
            dist_low.iloc[i] = (n - 1) - int(np.argmin(sl_l))
        # 低点更近 → 正；高点更近 → 负
        return dist_high - dist_low

    if kind == "roc_ma":
        n = int(p["n"])
        ma_n = int(p.get("ma_n", 60))
        roc = c / c.shift(n) - 1.0
        ma = _sma(c, ma_n)
        # 正动量且站上均线 → 正；否则负
        score = roc.where(c > ma, -abs(roc))
        return score

    if kind == "dist_ma":
        n = int(p["n"])
        ma_n = int(p.get("ma_n", 60))
        base = compute_momentum_raw(daily, kind="dist_hl", params={"n": n})
        ma = _sma(c, ma_n)
        return base.where(c > ma, -abs(base.fillna(0)))

    if kind == "dual_dist":
        # 双均线方向 × 高低点时间距离（同号加强）
        fast = int(p.get("fast", 10))
        slow = int(p.get("slow", 30))
        n = int(p.get("n", 60))
        dual = compute_momentum_raw(
            daily, kind="dual_ma", params={"fast": fast, "slow": slow}
        )
        dist = compute_momentum_raw(daily, kind="dist_hl", params={"n": n})
        return np.sign(dual.fillna(0)) * dist.abs().fillna(0) * np.sign(dist.fillna(0))

    raise ValueError(f"unknown momentum kind: {kind}")


def raw_to_target(
    raw: pd.Series,
    *,
    kind: str,
    params: dict[str, Any] | None = None,
) -> pd.Series:
    """原始因子 → 目标仓位 {0, 1}。带滞回，减少抖动。"""
    p = {**DEFAULT_PARAMS, **(params or {})}
    kind = str(kind or DEFAULT_KIND).lower()
    out = pd.Series(np.nan, index=raw.index, dtype=float)

    if kind == "up_ratio":
        enter = float(p["thresh"])
        exit_ = float(p.get("exit_thresh", enter - 0.1))
        state = 0.0
        for i, v in enumerate(raw.to_numpy()):
            if np.isnan(v):
                out.iloc[i] = state
                continue
            if state <= 0 and v >= enter:
                state = 1.0
            elif state >= 1 and v <= exit_:
                state = 0.0
            out.iloc[i] = state
        return out

    if kind == "breakout":
        # >0 偏多，<0 偏空；用小死区
        dead = float(p.get("deadband", 0.05))
        state = 0.0
        for i, v in enumerate(raw.to_numpy()):
            if np.isnan(v):
                out.iloc[i] = state
                continue
            if state <= 0 and v > dead:
                state = 1.0
            elif state >= 1 and v < -dead:
                state = 0.0
            out.iloc[i] = state
        return out

    if kind in ("dist_hl", "dist_ma", "dual_dist"):
        # 低点更近(raw>0)做多；高点更近做空
        enter = float(p.get("enter", 1.0))
        exit_ = float(p.get("exit", 0.0))
        state = 0.0
        for i, v in enumerate(raw.to_numpy()):
            if np.isnan(v):
                out.iloc[i] = state
                continue
            if state <= 0 and v >= enter:
                state = 1.0
            elif state >= 1 and v <= exit_:
                state = 0.0
            out.iloc[i] = state
        return out

    # roc / ma / dual_ma / alpha022 / roc_ma：零轴穿越 + 可选缓冲
    buf = float(p.get("buffer", 0.0))
    state = 0.0
    for i, v in enumerate(raw.to_numpy()):
        if np.isnan(v):
            out.iloc[i] = state
            continue
        if state <= 0 and v > buf:
            state = 1.0
        elif state >= 1 and v < -buf:
            state = 0.0
        out.iloc[i] = state
    return out


def build_momentum_signals(
    daily: pd.DataFrame,
    *,
    kind: str = DEFAULT_KIND,
    params: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """在日线上附加 mom_raw / mom_target；target 为收盘确认仓位。"""
    out = daily.copy()
    raw = compute_momentum_raw(out, kind=kind, params=params)
    tgt = raw_to_target(raw, kind=kind, params=params)
    out["mom_raw"] = raw
    out["mom_target"] = tgt
    # 次日执行：把今日目标平移到明日
    out["mom_exec"] = tgt.shift(1)
    return out


def momentum_rules_text(kind: str, params: dict[str, Any] | None = None) -> str:
    p = {**DEFAULT_PARAMS, **(params or {})}
    kind = str(kind or DEFAULT_KIND).lower()
    return f"""
================================================================================
  因子3 — 动量因子（独立，单票时序）
================================================================================
【定位】
  · 独立交易因子：不叠因子1开盘突破
  · 动量：价格延续性；收盘确认，次日开盘调仓；T+1
【形态】kind={kind}  params={p}
【执行】
  · 信号日收盘算因子 → mom_target ∈ {{0,1}}
  · 下一交易日开盘按 target_pct 开/平仓
  · 不做涨跌预测措辞；仅规则化仓位
================================================================================
""".strip()


__all__ = [
    "MOMENTUM_KINDS",
    "DEFAULT_KIND",
    "DEFAULT_PARAMS",
    "compute_momentum_raw",
    "raw_to_target",
    "build_momentum_signals",
    "momentum_rules_text",
]
