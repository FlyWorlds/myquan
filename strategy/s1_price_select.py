"""因子10 · 策略1 价格选股（周频冻结，不是日频开关）。

T 日收盘用当日及以前的 OHLC 算 raw；周频：本周最后一个交易日收盘排名，
下一周才允许因子1 开新仓。无未来函数。

经济逻辑：两只置顶票空窗长，用价格位置/趋势找「正在走或贴近前高」的票，
让援军战法有票可做。日频动能 Top5 已否，本因子不按日切名单。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

DEFAULT_PARAMS: dict[str, Any] = {
    "high_n": 20,
    "trend_n": 60,
    "mom_n": 20,
    "persist_n": 20,
}
FACTOR_COLS = ("near_high", "trend", "mom", "persist", "composite")


def _to_day(ts) -> str:
    t = pd.Timestamp(ts)
    if t.tzinfo is not None:
        t = t.tz_localize(None)
    return t.strftime("%Y-%m-%d")


def compute_price_select(
    daily: pd.DataFrame,
    *,
    params: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """单票日线附加价格选股 raw；exec 列为 raw.shift(1)，供日频 IC。"""
    p = {**DEFAULT_PARAMS, **(params or {})}
    out = daily.copy()
    c = out["close"].astype(float)
    h = out["high"].astype(float) if "high" in out.columns else c
    low = out["low"].astype(float) if "low" in out.columns else c
    high_n = int(p["high_n"])
    trend_n = int(p["trend_n"])
    mom_n = int(p["mom_n"])
    persist_n = int(p["persist_n"])

    roll_high = h.rolling(high_n, min_periods=high_n).max()
    roll_low = low.rolling(high_n, min_periods=high_n).min()
    sma = c.rolling(trend_n, min_periods=trend_n).mean()
    near_high = c / roll_high.replace(0.0, np.nan)
    width = (roll_high - roll_low).replace(0.0, np.nan)
    range_pos = (c - roll_low) / width
    trend = c / sma.replace(0.0, np.nan) - 1.0
    mom = c / c.shift(mom_n) - 1.0
    persist = (c.diff() > 0).astype(float).rolling(persist_n, min_periods=persist_n).mean()

    out["px_near_high"] = near_high
    out["px_range_pos"] = range_pos
    out["px_trend"] = trend
    out["px_mom"] = mom
    out["px_persist"] = persist
    for col in ("px_near_high", "px_range_pos", "px_trend", "px_mom", "px_persist"):
        out[f"{col}_exec"] = out[col].shift(1)
    return out


def panel_price_factors(dailies: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for sym, daily in dailies.items():
        df = compute_price_select(daily)
        part = df[
            [
                "date",
                "close",
                "px_near_high",
                "px_trend",
                "px_mom",
                "px_persist",
                "px_range_pos",
            ]
        ].copy()
        part["symbol"] = sym
        rows.append(part)
    panel = pd.concat(rows, ignore_index=True)
    panel["_d"] = pd.to_datetime(panel["date"]).dt.tz_localize(None).dt.normalize()
    for col in ("px_near_high", "px_trend", "px_mom", "px_persist"):
        panel[f"{col}_rk"] = panel.groupby("_d")[col].rank(pct=True, method="average")
    panel["px_composite"] = panel[
        ["px_near_high_rk", "px_trend_rk", "px_mom_rk"]
    ].mean(axis=1)
    return panel.drop(columns=["_d"])


def weekly_topk_allowed(
    panel: pd.DataFrame,
    *,
    value_col: str,
    k: int = 5,
    always: set[str] | None = None,
    extra_k: int | None = None,
) -> dict[str, dict[str, bool]]:
    """本周最后交易日收盘排名 → 下一周开仓名单。

    always: 每周强制入选（置顶票）。
    extra_k: 从其余票再取 Top extra_k；None 则总名额为 k（含 always）。
    """
    df = panel.copy()
    df["_d"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.normalize()
    df = df.dropna(subset=[value_col])
    if df.empty:
        return {}
    week = df["_d"] - pd.to_timedelta(df["_d"].dt.dayofweek, unit="D")
    df["_w"] = week
    always = {str(x) for x in (always or set())}
    weeks = sorted(df["_w"].unique())
    allowed: dict[str, dict[str, bool]] = {}
    symbols = sorted(df["symbol"].astype(str).unique())

    snap_by_week: dict[Any, set[str]] = {}
    for w, g in df.groupby("_w"):
        last = g["_d"].max()
        g_last = g[g["_d"] == last]
        rest = g_last[~g_last["symbol"].astype(str).isin(always)]
        if extra_k is not None:
            n = max(0, min(int(extra_k), len(rest)))
            extra = set(rest.nlargest(n, value_col)["symbol"].astype(str)) if n else set()
            picked = always | extra
        else:
            n = max(1, min(int(k), len(g_last)))
            picked = set(g_last.nlargest(n, value_col)["symbol"].astype(str))
            picked |= always
        snap_by_week[w] = picked

    dates = sorted(df["_d"].unique())
    week_of = {d: d - pd.to_timedelta(int(pd.Timestamp(d).dayofweek), unit="D") for d in dates}
    for d in dates:
        w = week_of[d]
        prev = None
        for cand in weeks:
            if cand < w:
                prev = cand
            else:
                break
        picked = snap_by_week.get(prev, always)
        key = pd.Timestamp(d).strftime("%Y-%m-%d")
        for sym in symbols:
            allowed.setdefault(sym, {})[key] = sym in picked
    return allowed


def weekly_mom_gate_from_close(
    close: pd.DataFrame,
    *,
    mom_n: int = 20,
    k: int = 5,
) -> dict[str, dict[str, bool]]:
    """宽表收盘价 → 本周最后交易日 20 日动量排名 → 下一周入选。

    close: DatetimeIndex × symbol。不读拟合池。
    """
    c = close.copy()
    idx = pd.to_datetime(c.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    c.index = pd.DatetimeIndex(idx).normalize()
    c = c.sort_index()
    mom = c / c.shift(int(mom_n)) - 1.0
    week = c.index - pd.to_timedelta(c.index.dayofweek, unit="D")
    snap: dict[Any, set[str]] = {}
    for w, g in mom.groupby(week):
        last = g.iloc[-1].dropna()
        if last.empty:
            continue
        n = max(1, min(int(k), len(last)))
        snap[w] = set(str(x) for x in last.nlargest(n).index)
    weeks = sorted(snap)
    allowed: dict[str, dict[str, bool]] = {}
    symbols = [str(x) for x in c.columns]
    for d in c.index:
        w = d - pd.to_timedelta(int(d.dayofweek), unit="D")
        prev = None
        for cand in weeks:
            if cand < w:
                prev = cand
            else:
                break
        picked = snap.get(prev, set())
        key = pd.Timestamp(d).strftime("%Y-%m-%d")
        for sym in symbols:
            allowed.setdefault(sym, {})[key] = sym in picked
    return allowed


def _normalize_wide(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    idx = pd.to_datetime(out.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    out.index = pd.DatetimeIndex(idx).normalize()
    return out.sort_index()


def weekly_two_stage_gate(
    close: pd.DataFrame,
    high: pd.DataFrame | None = None,
    *,
    mom_n: int = 20,
    stage1_k: int = 20,
    stage2_k: int = 5,
    stage2: str = "near_high",
    high_n: int = 20,
    invert_stage1: bool = False,
) -> dict[str, dict[str, bool]]:
    """周频两段：先动量 Top stage1_k，再按第二因子收到 stage2_k。

    invert_stage1=True 时一段取动量最低（反转池）。
    stage2:
      near_high — 贴近 high_n 日高点
      persist — 20 日上涨日占比
      not_climax — 动量池内 5 日涨幅更低（避免已经拉直）
    """
    c = _normalize_wide(close)
    h = _normalize_wide(high) if high is not None else c
    h = h.reindex(index=c.index, columns=c.columns)
    hn = max(2, int(high_n))
    mom = c / c.shift(int(mom_n)) - 1.0
    near = c / h.rolling(hn, min_periods=hn).max().replace(0.0, np.nan)
    persist = (c.diff() > 0).astype(float).rolling(20, min_periods=20).mean()
    roc5 = c / c.shift(5) - 1.0
    week = c.index - pd.to_timedelta(c.index.dayofweek, unit="D")
    snap: dict[Any, set[str]] = {}
    for w, g in mom.groupby(week):
        last_d = g.index[-1]
        last = g.iloc[-1].dropna()
        if last.empty:
            continue
        n1 = max(1, min(int(stage1_k), len(last)))
        pool = list(
            (last.nsmallest(n1) if invert_stage1 else last.nlargest(n1)).index
        )
        if stage2 == "persist":
            score = persist.loc[last_d, pool]
            pick = score.dropna().nlargest(min(int(stage2_k), len(pool)))
        elif stage2 == "not_climax":
            score = -roc5.loc[last_d, pool]
            pick = score.dropna().nlargest(min(int(stage2_k), len(pool)))
        else:
            score = near.loc[last_d, pool]
            pick = score.dropna().nlargest(min(int(stage2_k), len(pool)))
        snap[w] = set(str(x) for x in pick.index)
    weeks = sorted(snap)
    allowed: dict[str, dict[str, bool]] = {}
    symbols = [str(x) for x in c.columns]
    for d in c.index:
        w = d - pd.to_timedelta(int(d.dayofweek), unit="D")
        prev = None
        for cand in weeks:
            if cand < w:
                prev = cand
            else:
                break
        picked = snap.get(prev, set())
        key = pd.Timestamp(d).strftime("%Y-%m-%d")
        for sym in symbols:
            allowed.setdefault(sym, {})[key] = sym in picked
    return allowed


def price_select_rules_text(params: dict[str, Any] | None = None) -> str:
    p = {**DEFAULT_PARAMS, **(params or {})}
    return f"""
================================================================================
因子10 · 策略1 价格选股
================================================================================
字段：日频 OHLC。T 收盘算分，本周最后交易日排名，下一周才允许因子1 新开仓。
分量：近20日高点位置、相对{p['trend_n']}日均线、{p['mom_n']}日动量、
      {p['persist_n']}日上涨日占比；综合分为前三项截面分位平均。
用途：补置顶票空窗。不是日频 TopK，也不替换因子1 买卖规则。
================================================================================
""".strip()
