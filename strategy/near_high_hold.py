"""因子11：两段近高选股；策略五：近高 Top5 等权持有。

本周最后交易日：先按 3 日动量取 Top20，再在池内按收盘/近 5 日最高价
取 Top5。名单下一周才生效。策略五对这 5 只等权持有（收盘对收盘）。

原 20/20/k5 见 ORIGINAL_PARAMS。不是因子10，也不是策略四。
研究回测，不构成投资建议。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from strategy.s1_price_select import weekly_two_stage_gate

ORIGINAL_PARAMS: dict[str, Any] = {
    "mom_n": 20,
    "stage1_k": 20,
    "stage2_k": 5,
    "stage2": "near_high",
    "high_n": 20,
    "start": "20200102",
    "end": "20260820",
}
# 因子11 现行定义：2020–2023 period-sweep best period（mom3/high5/k5）。
# 成交：一字涨停开盘不可买入（与策略1 / second_board 默认一致）；一字跌停封单不可卖。
DEFAULT_PARAMS: dict[str, Any] = {
    **ORIGINAL_PARAMS,
    "mom_n": 3,
    "high_n": 5,
    "stage2_k": 5,
    "block_limit_up_buy": True,
    "block_limit_down_sell": True,
}
# 上一轮 5/10/k5 候选，供 opt_validate 对照；不是现行因子11
OPTIMIZED_PARAMS: dict[str, Any] = {
    **ORIGINAL_PARAMS,
    "mom_n": 5,
    "high_n": 10,
    "stage2_k": 5,
}


@dataclass
class NearHighHoldResult:
    nav: pd.Series
    stats: dict[str, float]
    yearly: pd.DataFrame
    config: dict[str, Any]
    gate: dict[str, dict[str, bool]] = field(repr=False)
    fill_stats: dict[str, Any] = field(default_factory=dict)


def near_high_rules_text(params: dict[str, Any] | None = None) -> str:
    p = {**DEFAULT_PARAMS, **(params or {})}
    return f"""
================================================================================
因子11 · 两段近高选股
================================================================================
宇宙：沪深300 ∪ 中证500 ∪ 中证1000（当前成分缓存，有幸存者偏差）。
一段：本周最后交易日收盘，{p['mom_n']} 日涨幅 Top{p['stage1_k']}。
二段：池内收盘 / 近 {p['high_n']} 日最高价，取 Top{p['stage2_k']}（最贴近前高）。
时点：T 收盘算分；本周排名，下一周才持有。无未来函数。
策略五：对入选 {p['stage2_k']} 只等权持有，按收盘涨跌再平衡。
成交：一字涨停开盘不可新开仓（开盘已达涨停价则放弃当日买入，周内未封则可补买）；
      一字跌停封单不可卖，持仓延续。与策略一/second_board 默认一致。
不是因子10（给策略1 开仓用的价格分数），不是策略四（开盘突破+止损）。
研究模拟，不构成投资建议，不承诺收益。
================================================================================
""".strip()


def weekly_near_high_gate(
    close: pd.DataFrame,
    high: pd.DataFrame | None = None,
    *,
    params: dict[str, Any] | None = None,
) -> dict[str, dict[str, bool]]:
    p = {**DEFAULT_PARAMS, **(params or {})}
    return weekly_two_stage_gate(
        close,
        high,
        mom_n=int(p["mom_n"]),
        stage1_k=int(p["stage1_k"]),
        stage2_k=int(p["stage2_k"]),
        stage2=str(p["stage2"]),
        high_n=int(p.get("high_n", DEFAULT_PARAMS["high_n"])),
    )


def picks_on(gate: dict[str, dict[str, bool]], date: str) -> list[str]:
    key = pd.Timestamp(date).strftime("%Y-%m-%d")
    return sorted(sym for sym, mp in gate.items() if bool((mp or {}).get(key)))


def _limit_pct_map(columns) -> dict[str, float]:
    from holdingStocks.watch_config import limit_up_pct_of

    return {str(c): float(limit_up_pct_of(str(c))) for c in columns}


def limit_fill_masks(
    close: pd.DataFrame,
    open_px: pd.DataFrame,
    high: pd.DataFrame,
    low: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """向量化成交约束，与 cannot_buy_limit_up / 一字跌停封单一致。

    返回 (block_buy, block_sell, close_at_limit)，索引对齐 close。
    """
    from strategy.open_break import LIMIT_UP_OPEN_TOL, TICK_SIZE

    cols = list(close.columns)
    pct = np.array([_limit_pct_map([c])[str(c)] for c in cols], dtype=float)
    prev = close.shift(1).to_numpy(dtype=float)
    o = open_px.reindex(index=close.index, columns=close.columns).to_numpy(dtype=float)
    h = high.reindex(index=close.index, columns=close.columns).to_numpy(dtype=float)
    l = low.reindex(index=close.index, columns=close.columns).to_numpy(dtype=float)
    c = close.to_numpy(dtype=float)
    tick = float(TICK_SIZE)
    decimals = max(0, -int(round(np.log10(tick)))) if tick < 1 else 0
    tol = max(tick * 0.51, 1e-8)
    valid = np.isfinite(prev) & (prev > 0) & np.isfinite(o) & np.isfinite(c)
    raw_up = prev * (1.0 + pct)
    limit_up = np.round(np.ceil((raw_up - 1e-12) / tick) * tick, decimals)
    raw_dn = prev * (1.0 - pct)
    limit_dn = np.round(np.floor((raw_dn + 1e-12) / tick) * tick, decimals)
    open_ret = o / prev - 1.0
    open_at = (np.abs(o - limit_up) <= tol) | (open_ret >= pct - LIMIT_UP_OPEN_TOL)
    locked_up = (
        (np.abs(o - limit_up) <= tol)
        & (np.abs(h - limit_up) <= tol)
        & (np.abs(l - limit_up) <= tol)
        & (np.abs(c - limit_up) <= tol)
        & (h >= limit_up - tol)
    )
    close_lu = np.abs(c - limit_up) <= tol
    locked_dn = (
        (np.abs(o - limit_dn) <= tol)
        & (np.abs(h - limit_dn) <= tol)
        & (np.abs(l - limit_dn) <= tol)
        & (np.abs(c - limit_dn) <= tol)
        & (l <= limit_dn + tol)
    )
    idx = close.index
    block_buy = pd.DataFrame(valid & (open_at | locked_up), index=idx, columns=cols)
    block_sell = pd.DataFrame(valid & locked_dn, index=idx, columns=cols)
    close_at_limit = pd.DataFrame(valid & close_lu, index=idx, columns=cols)
    return block_buy, block_sell, close_at_limit


def daily_from_snaps_fill(
    close: pd.DataFrame,
    snap: dict,
    block_buy: pd.DataFrame,
    block_sell: pd.DataFrame,
) -> tuple[pd.Series, dict[str, Any]]:
    """周频名单等权，一字涨停开盘买不进、一字跌停封单卖不出。"""
    rets = close.pct_change()
    cols = list(close.columns)
    ix = {str(c): i for i, c in enumerate(cols)}
    r = rets.to_numpy(dtype=float)
    bb = block_buy.reindex(index=close.index, columns=close.columns).fillna(False).to_numpy(dtype=bool)
    bs = block_sell.reindex(index=close.index, columns=close.columns).fillna(False).to_numpy(dtype=bool)
    weeks = sorted(snap)
    wkey = close.index - pd.to_timedelta(close.index.dayofweek, unit="D")
    held: set[int] = set()
    out = np.zeros(len(close), dtype=float)
    skipped = 0
    blocked_sell = 0
    filled = 0
    week_end_held: dict[Any, set[str]] = {}
    prev = None
    wi = 0
    for i, w in enumerate(wkey):
        while wi < len(weeks) and weeks[wi] < w:
            prev = weeks[wi]
            wi += 1
        names = snap.get(prev, set()) if prev is not None else set()
        target = set()
        for n in names:
            j = ix.get(str(n))
            if j is None or not np.isfinite(r[i, j]):
                continue
            target.add(j)
        for j in list(held - target):
            if bs[i, j]:
                blocked_sell += 1
            else:
                held.discard(j)
        for j in target:
            if j in held:
                continue
            if bb[i, j]:
                skipped += 1
                continue
            held.add(j)
            filled += 1
        js = [j for j in held if np.isfinite(r[i, j])]
        if js:
            out[i] = float(np.mean(r[i, js]))
        week_end_held[w] = {cols[j] for j in held}
    turns = []
    ws = sorted(week_end_held)
    for a, b in zip(ws, ws[1:]):
        sa, sb = week_end_held[a], week_end_held[b]
        if not sa:
            continue
        turns.append(1.0 - len(sa & sb) / max(len(sa), 1))
    daily = pd.Series(out, index=close.index)
    stats = {
        "skipped_limit_up_buy": int(skipped),
        "filled_buy": int(filled),
        "blocked_limit_down_sell": int(blocked_sell),
        "realized_week_turn": float(np.mean(turns)) if turns else float("nan"),
    }
    return daily, stats


def _bar(
    frame: pd.DataFrame | None,
    ts: pd.Timestamp,
    sym: str,
) -> float | None:
    if frame is None or sym not in frame.columns or ts not in frame.index:
        return None
    val = frame.at[ts, sym]
    if pd.isna(val):
        return None
    return float(val)


def equal_weight_hold_nav(
    close: pd.DataFrame,
    gate: dict[str, dict[str, bool]],
    *,
    open_px: pd.DataFrame | None = None,
    high: pd.DataFrame | None = None,
    low: pd.DataFrame | None = None,
    block_limit_up_buy: bool | None = None,
    block_limit_down_sell: bool | None = None,
) -> tuple[pd.Series, dict[str, Any]]:
    """周频名单等权持有。默认一字涨停开盘买不进、一字跌停封单卖不出。"""
    from strategy.open_break import cannot_buy_limit_up, limit_down_state

    c = close.copy()
    idx = pd.to_datetime(c.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    c.index = pd.DatetimeIndex(idx).normalize()
    o = open_px.reindex(index=c.index, columns=c.columns) if open_px is not None else None
    h = high.reindex(index=c.index, columns=c.columns) if high is not None else None
    l = low.reindex(index=c.index, columns=c.columns) if low is not None else None
    if block_limit_up_buy is None:
        block_limit_up_buy = o is not None
    if block_limit_down_sell is None:
        block_limit_down_sell = o is not None and l is not None
    pcts = _limit_pct_map(c.columns) if (block_limit_up_buy or block_limit_down_sell) else {}
    rets = c.pct_change()
    held: set[str] = set()
    out = []
    skipped_buy = 0
    blocked_sell = 0
    filled_buy = 0
    for ts, row in rets.iterrows():
        key = pd.Timestamp(ts).strftime("%Y-%m-%d")
        target = {
            col
            for col in rets.columns
            if bool((gate.get(col) or {}).get(key, False)) and pd.notna(row.get(col))
        }
        if block_limit_down_sell:
            for sym in list(held - target):
                loc = c.index.get_loc(ts)
                prev_c = (
                    float(c.iloc[loc - 1][sym])
                    if loc > 0 and pd.notna(c.iloc[loc - 1][sym])
                    else None
                )
                st = limit_down_state(
                    prev_close=prev_c,
                    open_px=_bar(o, ts, sym) or 0.0,
                    high_px=_bar(h, ts, sym) or 0.0,
                    low_px=_bar(l, ts, sym) or 0.0,
                    close_px=_bar(c, ts, sym) or 0.0,
                    limit_down_pct=pcts.get(str(sym), 0.10),
                )
                if bool(st["locked"]):
                    blocked_sell += 1
                else:
                    held.discard(sym)
        else:
            held &= target
        for sym in target:
            if sym in held:
                continue
            prev_c = None
            loc = c.index.get_loc(ts)
            if loc > 0 and pd.notna(c.iloc[loc - 1][sym]):
                prev_c = float(c.iloc[loc - 1][sym])
            blocked = False
            if block_limit_up_buy and o is not None:
                blocked = cannot_buy_limit_up(
                    prev_close=prev_c,
                    open_px=_bar(o, ts, sym) or 0.0,
                    high_px=_bar(h, ts, sym) or _bar(c, ts, sym) or 0.0,
                    low_px=_bar(l, ts, sym) or _bar(c, ts, sym) or 0.0,
                    close_px=_bar(c, ts, sym) or 0.0,
                    limit_up_pct=pcts.get(str(sym), 0.10),
                )
            if blocked:
                skipped_buy += 1
                continue
            held.add(sym)
            filled_buy += 1
        held &= set(rets.columns)
        names = [n for n in held if pd.notna(row.get(n))]
        out.append(float(row[names].mean()) if names else 0.0)
    nav = (1.0 + pd.Series(out, index=rets.index)).cumprod()
    if len(nav):
        nav.iloc[0] = 1.0
    stats = {
        "skipped_limit_up_buy": skipped_buy,
        "filled_buy": filled_buy,
        "blocked_limit_down_sell": blocked_sell,
        "block_limit_up_buy": bool(block_limit_up_buy),
        "block_limit_down_sell": bool(block_limit_down_sell),
    }
    return nav, stats


def _year_from_prior(nav: pd.Series, year: int) -> float:
    s = nav.dropna().sort_index()
    prev = s[s.index.year < year]
    this = s[s.index.year == year]
    if this.empty:
        return float("nan")
    start = float(prev.iloc[-1]) if len(prev) else float(this.iloc[0])
    if start <= 0:
        return float("nan")
    return (float(this.iloc[-1]) / start - 1.0) * 100.0


def factor11_signal(
    close: pd.DataFrame,
    high: pd.DataFrame | None = None,
    *,
    date: str | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """截面信号：返回周频近高名单。给定 date 时只返回当日 5 只。"""
    p = {**DEFAULT_PARAMS, **(params or {})}
    gate = weekly_near_high_gate(close, high, params=p)
    if date is None:
        return {"gate": gate, "params": p, "factor_id": "factor11"}
    names = picks_on(gate, date)
    return {
        "factor_id": "factor11",
        "date": pd.Timestamp(date).strftime("%Y-%m-%d"),
        "picks": names,
        "target": names,
        "params": p,
    }


def run_near_high_hold(
    *,
    close: pd.DataFrame | None = None,
    high: pd.DataFrame | None = None,
    open_px: pd.DataFrame | None = None,
    low: pd.DataFrame | None = None,
    start: str | None = None,
    end: str | None = None,
    verbose: bool = True,
    **overrides: Any,
) -> NearHighHoldResult:
    from strategy.strategies.strategy4.portfolio import window_metrics
    from strategy.strategies.strategy4.run_two_stage import load_combined_ohlc

    p = {**DEFAULT_PARAMS, **overrides}
    if start is not None:
        p["start"] = start
    if end is not None:
        p["end"] = end
    if close is None:
        ohlc = load_combined_ohlc()
        close, high = ohlc["close"], ohlc["high"]
        open_px = ohlc.get("open")
        low = ohlc.get("low")
        if verbose:
            print(f"宇宙 {close.shape[1]} 只（沪深300+中证500+中证1000）")
    if high is None:
        high = close
    gate = weekly_near_high_gate(close, high, params=p)
    nav, fill_stats = equal_weight_hold_nav(
        close,
        gate,
        open_px=open_px,
        high=high,
        low=low,
        block_limit_up_buy=bool(p.get("block_limit_up_buy", True)),
        block_limit_down_sell=bool(p.get("block_limit_down_sell", True)),
    )
    start_ts = pd.Timestamp(p["start"])
    end_ts = pd.Timestamp(p["end"])
    sl = nav[(nav.index >= start_ts) & (nav.index <= end_ts)].dropna()
    stats = window_metrics(sl)
    years = sorted({int(y) for y in sl.index.year})
    yearly = pd.DataFrame(
        {"year": years, "ret_pct": [_year_from_prior(sl, y) for y in years]}
    )
    if verbose:
        print(
            f"近高 Top{p['stage2_k']} 等权持有 {stats.get('start')}～{stats.get('end')} "
            f"{stats['ret_pct']:.1f}% 年化 {stats['ann_pct']:.1f}% "
            f"夏普 {stats['sharpe']:.2f} 回撤 {stats['mdd_pct']:.1f}%"
        )
        print(
            f"一字涨停开盘买不进 {fill_stats.get('skipped_limit_up_buy', 0)} 次，"
            f"成交开仓 {fill_stats.get('filled_buy', 0)}，"
            f"一字跌停卖不出 {fill_stats.get('blocked_limit_down_sell', 0)}"
        )
        print(yearly.to_string(index=False))
    return NearHighHoldResult(
        nav=sl,
        stats=stats,
        yearly=yearly,
        config=p,
        gate=gate,
        fill_stats=fill_stats,
    )
