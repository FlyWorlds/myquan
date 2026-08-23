"""因子12：20 日反转池 → 贴近 5 日高点 Top5（研究候选）。

家族优化里两段式组合的 IS 胜者。2024–2025 费用后夏普未确认，
不能替换因子11。策略六对入选票等权持有。研究回测，不构成投资建议。
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from strategy.near_high_hold import (
    NearHighHoldResult,
    _year_from_prior,
    equal_weight_hold_nav,
    picks_on,
)
from strategy.s1_price_select import weekly_two_stage_gate

DEFAULT_PARAMS: dict[str, Any] = {
    "mom_n": 20,
    "stage1_k": 20,
    "stage2_k": 5,
    "stage2": "near_high",
    "high_n": 5,
    "invert_stage1": True,
    "block_limit_up_buy": True,
    "block_limit_down_sell": True,
    "start": "20200102",
    "end": "20260820",
}


def factor12_rules_text(params: dict[str, Any] | None = None) -> str:
    p = {**DEFAULT_PARAMS, **(params or {})}
    return f"""
================================================================================
因子12 · 反转池近高（研究候选）
================================================================================
宇宙：沪深300 ∪ 中证500 ∪ 中证1000（当前成分缓存，有幸存者偏差）。
一段：本周最后交易日 {p['mom_n']} 日涨幅最低 Top{p['stage1_k']}（反转池）。
二段：池内收盘 / 近 {p['high_n']} 日最高价，取 Top{p['stage2_k']}。
时点：T 收盘算分；本周排名，下一周才持有。无未来函数。
成交：一字涨停开盘不可新开仓；一字跌停封单不可卖。
IS 2020–2023 费用后夏普高于因子11，但 2024–2025 未确认，不替换因子11。
研究模拟，不构成投资建议，不承诺收益。
================================================================================
""".strip()


def weekly_factor12_gate(
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
        high_n=int(p["high_n"]),
        invert_stage1=bool(p.get("invert_stage1", True)),
    )


def factor12_signal(
    close: pd.DataFrame,
    high: pd.DataFrame | None = None,
    *,
    date: str | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    p = {**DEFAULT_PARAMS, **(params or {})}
    gate = weekly_factor12_gate(close, high, params=p)
    if date is None:
        return {"gate": gate, "params": p, "factor_id": "factor12"}
    names = picks_on(gate, date)
    return {
        "factor_id": "factor12",
        "date": pd.Timestamp(date).strftime("%Y-%m-%d"),
        "picks": names,
        "target": names,
        "params": p,
    }


def run_factor12_hold(
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
    gate = weekly_factor12_gate(close, high, params=p)
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
            f"因子12 Top{p['stage2_k']} 等权 {stats.get('start')}～{stats.get('end')} "
            f"{stats['ret_pct']:.1f}% 夏普 {stats['sharpe']:.2f} 回撤 {stats['mdd_pct']:.1f}%"
        )
        print(
            f"一字涨停买不进 {fill_stats.get('skipped_limit_up_buy', 0)}，"
            f"开仓 {fill_stats.get('filled_buy', 0)}，"
            f"跌停卖不出 {fill_stats.get('blocked_limit_down_sell', 0)}"
        )
    return NearHighHoldResult(
        nav=sl,
        stats=stats,
        yearly=yearly,
        config=p,
        gate=gate,
        fill_stats=fill_stats,
    )
