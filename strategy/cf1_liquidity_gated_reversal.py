"""CF1 · 流动性门控反转。

主机制：波动缩放的短期反转（过度反应拉伸）。
门控（可叠加）：
  1. Amihud 非流动性软门
  2. 成交额容量地板
  3. 涨跌停 / 一字板（T 收盘不可交易则剔除）
  4. 趋势门（默认定稿由验证集决定）
  5. 波动门（短/长波动比，默认定稿由验证集决定）

时点：T 收盘可观测；最早 T+1 开盘成交。无未来函数。
研究模拟，不构成投资建议。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

FACTOR_ID = "cf1"
FACTOR_NAME = "因子CF1-流动性门控反转"

# 冻结规格：发现集 2018–2022 分阶段扫描，验证集 2023–2024 在短名单中选定。
# 假设起点曾是 rev_n=5 / horizon=5；不得用 2025+ 测试集改这些默认值。
DEFAULT_PARAMS: dict[str, Any] = {
    "rev_n": 20,
    "amihud_n": 60,
    "adv_n": 60,
    "vol_n": 20,
    "vol_scale": True,
    "skip_days": 0,
    "gate_lo": 0.60,
    "adv_floor": 0.10,
    "gate_mode": "soft_illiquid",  # none | soft_illiquid | soft_liquid | hard_illiquid
    "limit_gate": True,
    "trend_gate": "below_ma",  # none | below_ma | above_ma | soft_below_ma
    "trend_n": 60,
    "vol_gate": "none",  # none | high | low | soft_high ；验证集未确认，默认关
    "vol_short": 20,
    "vol_long": 60,
    "vol_gate_lo": 0.50,
    "winsor_k": 5.0,
    "min_names": 30,
    "horizon": 10,
    "top_frac": 0.10,
}


def cf1_rules_text(params: dict[str, Any] | None = None) -> str:
    p = {**DEFAULT_PARAMS, **(params or {})}
    return f"""
================================================================================
CF1 · 流动性门控反转
================================================================================
宇宙：中证500 ∪ 中证1000 主板（当前成分缓存，有幸存者偏差）。
主信号：-{p['rev_n']} 日收益；vol_scale={p['vol_scale']} 时除以 {p['vol_n']} 日收益标准差。
skip_days={p['skip_days']}：跳过最近 skip 日再算反转（避免隔夜噪音）。
Amihud 门：{p['amihud_n']} 日 mean(|ret|/(close×volume)) 截面分位；
      gate_mode={p['gate_mode']}，gate_lo={p['gate_lo']}。
成交额门：{p['adv_n']} 日成交额截面分位 < {p['adv_floor']} 剔除。
涨跌停门：limit_gate={p['limit_gate']}，T 收盘触及涨停/跌停或一字板则剔除。
趋势门：trend_gate={p['trend_gate']}，均线 {p['trend_n']} 日。
波动门：vol_gate={p['vol_gate']}，短{p['vol_short']}/长{p['vol_long']} 波动比，lo={p['vol_gate_lo']}。
标准化：截面 MAD winsor k={p['winsor_k']} + z-score；有效股票 < {p['min_names']} 当日不计。
时点：T 收盘算分，T+1 开盘可交易。预测周期默认 {p['horizon']} 日。
研究模拟，不构成投资建议，不承诺收益。
================================================================================
""".strip()


def _xs_rank(df: pd.DataFrame) -> pd.DataFrame:
    return df.rank(axis=1, pct=True, method="average")


def mad_winsor_xs(df: pd.DataFrame, k: float = 5.0) -> pd.DataFrame:
    med = df.median(axis=1)
    mad = df.sub(med, axis=0).abs().median(axis=1)
    scale = 1.4826 * mad.replace(0, np.nan)
    lo = med - float(k) * scale
    hi = med + float(k) * scale
    return df.clip(lower=lo, upper=hi, axis=0)


def xs_zscore(df: pd.DataFrame) -> pd.DataFrame:
    mu = df.mean(axis=1)
    sd = df.std(axis=1, ddof=0).replace(0, np.nan)
    return df.sub(mu, axis=0).div(sd, axis=0)


def _soft_gate(rank: pd.DataFrame, lo: float) -> pd.DataFrame:
    lo = float(lo)
    span = max(1.0 - lo, 1e-9)
    return ((rank - lo) / span).clip(lower=0.0, upper=1.0)


def _limit_pct_row(columns: pd.Index) -> pd.Series:
    from holdingStocks.watch_config import limit_up_pct_of

    return pd.Series({c: float(limit_up_pct_of(str(c))) for c in columns}, dtype=float)


def limit_halt_mask(
    close: pd.DataFrame,
    high: pd.DataFrame | None = None,
    low: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """T 收盘涨停、跌停或一字板 → True（应剔除）。只用 T 及以前数据。"""
    from strategy.open_break import TICK_SIZE

    prev = close.shift(1)
    pct = _limit_pct_row(close.columns)
    tick = float(TICK_SIZE)
    decimals = max(0, -int(round(np.log10(tick)))) if tick < 1 else 0
    tol = max(tick * 0.51, 1e-8)
    raw_up = prev.mul(1.0 + pct, axis=1)
    raw_dn = prev.mul(1.0 - pct, axis=1)
    limit_up = np.round(np.ceil((raw_up - 1e-12) / tick) * tick, decimals)
    limit_dn = np.round(np.floor((raw_dn + 1e-12) / tick) * tick, decimals)
    at_up = close + 1e-12 >= limit_up - tol
    at_dn = close - 1e-12 <= limit_dn + tol
    one_word = pd.DataFrame(False, index=close.index, columns=close.columns)
    if high is not None and low is not None:
        h = high.reindex_like(close)
        l = low.reindex_like(close)
        one_word = (h - l) <= (tick + 1e-12)
        ret_ok = (close / prev - 1.0).abs() >= 0.02
        one_word = one_word & ret_ok
    return (at_up | at_dn | one_word).fillna(False)


def compute_cf1(
    close: pd.DataFrame,
    volume: pd.DataFrame,
    *,
    high: pd.DataFrame | None = None,
    low: pd.DataFrame | None = None,
    params: dict[str, Any] | None = None,
    standardize: bool = True,
) -> pd.DataFrame:
    """返回 [date × symbol] 因子值。高分 = 看多（超跌且流动性冲击大）。"""
    p = {**DEFAULT_PARAMS, **(params or {})}
    close = close.astype(float)
    volume = volume.reindex_like(close).astype(float)
    volume = volume.where(volume > 0.0)

    rev_n = max(int(p["rev_n"]), 1)
    skip = max(int(p.get("skip_days", 0) or 0), 0)
    amihud_n = max(int(p["amihud_n"]), 2)
    adv_n = max(int(p["adv_n"]), 1)
    vol_n = max(int(p.get("vol_n", 20) or 20), 5)
    gate_lo = float(p.get("gate_lo", 0.3) or 0.0)
    adv_floor = float(p.get("adv_floor", 0.1) or 0.0)
    gate_mode = str(p.get("gate_mode", "soft_illiquid") or "soft_illiquid")
    min_names = int(p.get("min_names", 30))

    ret1 = close / close.shift(1) - 1.0
    dollar = close * volume
    amihud_d = ret1.abs() / dollar
    amihud = amihud_d.rolling(amihud_n, min_periods=max(5, amihud_n // 2)).mean()
    adv = dollar.rolling(adv_n, min_periods=max(3, adv_n // 2)).mean()

    lookback = rev_n + skip
    rev_raw = -(close.shift(skip) / close.shift(lookback) - 1.0)
    if bool(p.get("vol_scale", True)):
        vol = ret1.rolling(vol_n, min_periods=max(5, vol_n // 2)).std()
        rev = rev_raw / vol.replace(0, np.nan)
    else:
        rev = rev_raw

    amihud_rank = _xs_rank(amihud)
    adv_rank = _xs_rank(adv)
    tradable = adv_rank >= adv_floor if adv_floor > 0 else adv_rank.notna()

    if gate_mode == "none":
        gated = rev
    elif gate_mode == "soft_liquid":
        gated = rev * _soft_gate(1.0 - amihud_rank, gate_lo)
    elif gate_mode == "hard_illiquid":
        gated = rev.where(amihud_rank >= gate_lo)
    else:
        gated = rev * _soft_gate(amihud_rank, gate_lo)

    out = gated.where(tradable)

    if bool(p.get("limit_gate", True)):
        blocked = limit_halt_mask(close, high=high, low=low)
        out = out.where(~blocked)

    trend_mode = str(p.get("trend_gate", "none") or "none")
    if trend_mode != "none":
        trend_n = max(int(p.get("trend_n", 60) or 60), 2)
        ma = close.rolling(trend_n, min_periods=max(10, trend_n // 2)).mean()
        if trend_mode == "below_ma":
            out = out.where(close < ma)
        elif trend_mode == "above_ma":
            out = out.where(close > ma)
        elif trend_mode == "soft_below_ma":
            gap = (ma / close.replace(0, np.nan) - 1.0)
            w = (gap / 0.05).clip(lower=0.0, upper=1.0)
            out = out * w

    vol_mode = str(p.get("vol_gate", "none") or "none")
    if vol_mode != "none":
        vs = max(int(p.get("vol_short", 20) or 20), 5)
        vl = max(int(p.get("vol_long", 60) or 60), vs + 1)
        vlo = float(p.get("vol_gate_lo", 0.5) or 0.0)
        short_vol = ret1.rolling(vs, min_periods=max(5, vs // 2)).std()
        long_vol = ret1.rolling(vl, min_periods=max(10, vl // 2)).std()
        ratio = short_vol / long_vol.replace(0, np.nan)
        rnk = _xs_rank(ratio)
        if vol_mode == "high":
            out = out.where(rnk >= vlo)
        elif vol_mode == "low":
            out = out.where(rnk <= (1.0 - vlo))
        else:
            out = out * _soft_gate(rnk, vlo)

    out = out.replace([np.inf, -np.inf], np.nan)
    if not standardize:
        out = out.where(out.notna().sum(axis=1) >= min_names, np.nan)
        return out

    out = mad_winsor_xs(out, k=float(p.get("winsor_k", 5.0)))
    out = xs_zscore(out)
    out = out.where(out.notna().sum(axis=1) >= min_names, np.nan)
    return out


def cf1_signal(
    close: pd.DataFrame,
    volume: pd.DataFrame,
    *,
    high: pd.DataFrame | None = None,
    low: pd.DataFrame | None = None,
    date: str | None = None,
    params: dict[str, Any] | None = None,
    top_n: int | None = None,
) -> dict[str, Any]:
    p = {**DEFAULT_PARAMS, **(params or {})}
    scores = compute_cf1(close, volume, high=high, low=low, params=p)
    if scores.empty:
        return {"date": date, "scores": {}, "top": []}
    if date is None:
        idx = scores.index[-1]
    else:
        ts = pd.Timestamp(date)
        if getattr(scores.index, "tz", None) is not None and ts.tzinfo is None:
            ts = ts.tz_localize(scores.index.tz)
        hit = scores.index[scores.index <= ts]
        if len(hit) == 0:
            return {"date": date, "scores": {}, "top": []}
        idx = hit[-1]
    row = scores.loc[idx].dropna().sort_values(ascending=False)
    k = int(top_n) if top_n is not None else max(1, int(len(row) * float(p["top_frac"])))
    top = row.head(k)
    return {
        "date": str(pd.Timestamp(idx).date()),
        "asof": str(idx),
        "scores": {str(s): float(v) for s, v in top.items()},
        "top": [str(s) for s in top.index.tolist()],
        "n_valid": int(len(row)),
        "params": {k: p[k] for k in DEFAULT_PARAMS},
    }
