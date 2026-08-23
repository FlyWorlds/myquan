"""因子9 · 日线多空动能（追涨杀跌）。

T 日收盘用当日及以前的 OHLCV 计算 raw；exec = raw.shift(1)，
即 T 日开盘只能用到 T-1 收盘的动能，无未来函数。

多头动能：短/中期涨幅、站上均线、上涨日占比、连阳、相对前高突破、放量上涨。
空头动能：对称的下跌/跌破/连阴/放量下跌。
净动能 = 多头 − 空头；截面百分位用于选股。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

DEFAULT_PARAMS: dict[str, Any] = {
    "fast": 5,
    "slow": 20,
    "ma_n": 20,
    "up_n": 10,
    "vol_n": 20,
}


def _sma(s: pd.Series, n: int) -> pd.Series:
    n = int(n)
    return s.rolling(n, min_periods=n).mean()


def _streak(mask: pd.Series) -> pd.Series:
    """连续 True 的天数；False 处置 0。"""
    v = mask.fillna(False).astype(int).to_numpy()
    out = np.zeros(len(v), dtype=float)
    run = 0.0
    for i, flag in enumerate(v):
        if flag:
            run += 1.0
        else:
            run = 0.0
        out[i] = run
    return pd.Series(out, index=mask.index)


def compute_ls_energy(
    daily: pd.DataFrame,
    *,
    params: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """给单票日线附加多/空/净动能及次日可交易的 exec 列。"""
    p = {**DEFAULT_PARAMS, **(params or {})}
    out = daily.copy()
    c = out["close"].astype(float)
    h = out["high"].astype(float) if "high" in out.columns else c
    low = out["low"].astype(float) if "low" in out.columns else c
    vol = out["volume"].astype(float) if "volume" in out.columns else pd.Series(0.0, index=out.index)
    ret1 = c / c.shift(1) - 1.0
    up = ret1 > 0
    down = ret1 < 0

    fast = int(p["fast"])
    slow = int(p["slow"])
    ma_n = int(p["ma_n"])
    up_n = int(p["up_n"])
    vol_n = int(p["vol_n"])

    roc_fast = c / c.shift(fast) - 1.0
    roc_slow = c / c.shift(slow) - 1.0
    ma = _sma(c, ma_n)
    ma_gap = (c - ma) / ma.replace(0.0, np.nan)
    up_ratio = up.astype(float).rolling(up_n, min_periods=up_n).mean()
    down_ratio = down.astype(float).rolling(up_n, min_periods=up_n).mean()
    up_streak = _streak(up)
    down_streak = _streak(down)
    prior_high = h.rolling(slow, min_periods=slow).max().shift(1)
    prior_low = low.rolling(slow, min_periods=slow).min().shift(1)
    breakout = c / prior_high.replace(0.0, np.nan) - 1.0
    breakdown = prior_low / c.replace(0.0, np.nan) - 1.0
    vol_ma = _sma(vol, vol_n)
    vol_ratio = vol / vol_ma.replace(0.0, np.nan)
    vol_up = vol_ratio.where(up, 0.0)
    vol_down = vol_ratio.where(down, 0.0)

    # 跨股可比的原始量纲（不用个股滚动 z，避免把趋势压成均值回归）
    long_e = pd.concat(
        [
            roc_fast,
            roc_slow,
            ma_gap,
            up_ratio - 0.5,
            (up_streak / 10.0).clip(0.0, 1.0),
            breakout,
            (vol_up - 1.0).clip(-2.0, 2.0) * 0.05,
        ],
        axis=1,
    ).mean(axis=1)
    short_e = pd.concat(
        [
            -roc_fast,
            -roc_slow,
            -ma_gap,
            down_ratio - 0.5,
            (down_streak / 10.0).clip(0.0, 1.0),
            breakdown,
            (vol_down - 1.0).clip(-2.0, 2.0) * 0.05,
        ],
        axis=1,
    ).mean(axis=1)
    net = long_e - short_e

    out["ls_long"] = long_e
    out["ls_short"] = short_e
    out["ls_net"] = net
    out["ls_long_exec"] = long_e.shift(1)
    out["ls_short_exec"] = short_e.shift(1)
    out["ls_net_exec"] = net.shift(1)
    out["ls_roc_fast"] = roc_fast
    out["ls_roc_slow"] = roc_slow
    return out


def energy_by_date(daily: pd.DataFrame) -> dict[str, float]:
    """date(YYYY-MM-DD) -> 当日开盘可用的净动能 exec。"""
    if "ls_net_exec" not in daily.columns:
        daily = compute_ls_energy(daily)
    out: dict[str, float] = {}
    for _, row in daily.iterrows():
        d = row["date"]
        if hasattr(d, "strftime"):
            key = d.strftime("%Y-%m-%d")
        else:
            key = str(d)[:10]
        v = row.get("ls_net_exec")
        if pd.notna(v):
            out[key] = float(v)
    return out


def cross_section_rank(
    panel: pd.DataFrame,
    *,
    value_col: str = "ls_net_exec",
    date_col: str = "date",
    symbol_col: str = "symbol",
) -> pd.DataFrame:
    """按日截面百分位（0~1，越大越偏多）。"""
    out = panel.copy()
    out["_d"] = pd.to_datetime(out[date_col]).dt.tz_localize(None).dt.normalize()
    out["ls_cs_rank"] = out.groupby("_d")[value_col].rank(pct=True, method="average")
    return out.drop(columns=["_d"])


def topk_allowed_by_date(
    ranked: pd.DataFrame,
    *,
    k: int = 5,
    rank_col: str = "ls_cs_rank",
    date_col: str = "date",
    symbol_col: str = "symbol",
) -> dict[str, dict[str, bool]]:
    """symbol -> {date -> 是否进入当日截面 TopK}。"""
    df = ranked.copy()
    df["_d"] = pd.to_datetime(df[date_col]).dt.tz_localize(None).dt.strftime("%Y-%m-%d")
    k = max(1, int(k))
    allowed: dict[str, dict[str, bool]] = {}
    for day, g in df.groupby("_d"):
        g = g.dropna(subset=[rank_col])
        if g.empty:
            continue
        n = max(1, min(k, len(g)))
        picked = set(g.nlargest(n, rank_col)[symbol_col].astype(str))
        for sym in g[symbol_col].astype(str).unique():
            allowed.setdefault(str(sym), {})[str(day)] = str(sym) in picked
    return allowed


def build_market_regime(
    close_by_symbol: pd.DataFrame,
    *,
    ma_n: int = 60,
    roc_n: int = 20,
) -> pd.Series:
    """等权指数的牛/熊/震荡；返回次日生效的 regime（index=日期）。

    bull: 收盘站上均线且 roc>0
    bear: 收盘跌破均线且 roc<0
    sideways: 其余
    """
    ew = close_by_symbol.mean(axis=1).astype(float)
    ew = ew.sort_index()
    sma = _sma(ew, ma_n)
    roc = ew / ew.shift(int(roc_n)) - 1.0
    regime = pd.Series("sideways", index=ew.index, dtype=object)
    bull = (ew > sma) & (roc > 0)
    bear = (ew < sma) & (roc < 0)
    regime = regime.mask(bull, "bull").mask(bear, "bear")
    return regime.shift(1)


def regime_by_date(regime: pd.Series) -> dict[str, str]:
    out: dict[str, str] = {}
    for ts, val in regime.items():
        if pd.isna(val):
            continue
        if hasattr(ts, "strftime"):
            key = pd.Timestamp(ts).tz_localize(None).strftime("%Y-%m-%d")
        else:
            key = str(ts)[:10]
        out[key] = str(val)
    return out


def ls_energy_rules_text(params: dict[str, Any] | None = None) -> str:
    p = {**DEFAULT_PARAMS, **(params or {})}
    return f"""
================================================================================
  因子9 — 日线多空动能（追涨杀跌）
================================================================================
  · 频率：日线。T 日收盘计算，T+1 开盘可用（exec=shift(1)）。
  · 多头动能：ROC{p['fast']}/ROC{p['slow']}、收盘/MA{p['ma_n']}、
    {p['up_n']}日上涨占比、连阳、相对前{p['slow']}日高点突破、放量上涨。
  · 空头动能：对称的下跌、跌破均线、连阴、跌破前低、放量下跌。
    · 各分量按可跨股比较的原始量纲等权合成（不做个股滚动 z，以免把趋势压成反转）；
    净动能 = 多头 − 空头。
  · 选股：当日截面净动能百分位 TopK，只对入选标的允许因子1 开盘突破买入。
  · 用途：提高因子1 阈值交易的跟随度，减少逆势摩擦；不是收益承诺。
================================================================================
""".strip()


def panel_from_dailies(
    dailies: dict[str, pd.DataFrame],
    *,
    params: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """多票日线 → 带动能列的长表。"""
    frames: list[pd.DataFrame] = []
    for sym, daily in dailies.items():
        if daily is None or daily.empty:
            continue
        one = compute_ls_energy(daily, params=params)
        if "symbol" not in one.columns:
            one["symbol"] = sym
        frames.append(one)
    if not frames:
        return pd.DataFrame()
    panel = pd.concat(frames, ignore_index=True)
    return cross_section_rank(panel)


__all__ = [
    "DEFAULT_PARAMS",
    "build_market_regime",
    "compute_ls_energy",
    "cross_section_rank",
    "energy_by_date",
    "ls_energy_rules_text",
    "panel_from_dailies",
    "regime_by_date",
    "topk_allowed_by_date",
]
