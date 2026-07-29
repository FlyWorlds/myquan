"""945 全清 vs 关闭 — 收益对比 CLI。"""

from __future__ import annotations

import logging
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strategy import (
    CERTAIN_CATS,
    KAICHENG,
    build_gap_map,
    classify_gap_days,
    compare_gap945_on_off,
    fetch_daily,
    format_metric,
    load_minute,
    per_event_compare,
    replay_holding_days,
    yearly_equity_diff,
)

CFG = replace(
    KAICHENG,
    gap945_use_proxy=True,
    min1_cache=Path(__file__).with_name(f"{KAICHENG.symbol}_1m_qfq.parquet"),
)


def main() -> None:
    logging.getLogger("akquant").setLevel(logging.WARNING)
    logging.getLogger("akquant.strategy").setLevel(logging.WARNING)
    logging.getLogger("akquant.backtest").setLevel(logging.WARNING)

    daily = fetch_daily(CFG.symbol, CFG.start_date, CFG.end_date)
    minute = load_minute(CFG)
    gap_map = build_gap_map(CFG, daily, minute)
    gap_df = classify_gap_days(daily, minute)
    hold_df = replay_holding_days(daily, threshold_pct=CFG.threshold_pct, tick=CFG.tick)
    gap_df["holding"] = gap_df["day"].isin(set(hold_df["day"]))

    res_sell, res_hold = compare_gap945_on_off(CFG, daily, gap_map)
    ev = per_event_compare(
        daily, gap_map, hold_df, gap_df, threshold_pct=CFG.threshold_pct
    )
    n = len(ev)
    sell_wins = int((ev["diff_pct"] > 0).sum()) if n else 0
    hold_wins = int((ev["diff_pct"] < 0).sum()) if n else 0

    print(f"=== {CFG.symbol_name} 945全清 vs 不卖 收益对比 ===")
    print(f"区间: {CFG.start_date} ~ {CFG.end_date}")
    print()
    print("【全区间回测】")
    ret_on = format_metric(res_sell, "total_return_pct")
    ret_off = format_metric(res_hold, "total_return_pct")
    eq_on = format_metric(res_sell, "end_market_value")
    eq_off = format_metric(res_hold, "end_market_value")
    print(f"  945开启: 累计 {ret_on:.2f}%  期末 {eq_on:,.0f}")
    print(f"  945关闭: 累计 {ret_off:.2f}%  期末 {eq_off:,.0f}")
    print(f"  差额: {ret_on - ret_off:+.2f} pp，期末 {eq_on - eq_off:+,.0f} 元")
    print()

    ydiff = yearly_equity_diff(res_sell, res_hold, initial_cash=CFG.initial_cash)
    if not ydiff.empty:
        print("【分年权益差价】")
        for _, r in ydiff.iterrows():
            print(
                f"  {int(r['year'])}  945开={r['end_945_on']:,.0f}  "
                f"945关={r['end_945_off']:,.0f}  差={r['diff_yuan']:+,.0f}  "
                f"收益差={r['diff_ret_pp']:+.2f}pp"
            )
    print()

    print(f"【单次事件】确定945前未翻红 {n} 次，945更优 {sell_wins}，不卖更优 {hold_wins}")
    if n:
        print(f"  平均差额: {ev['diff_pct'].mean():+.2f} pp")
        for _, r in ev.sort_values("diff_pct", ascending=False).iterrows():
            print(
                f"  {r['day']} 945→{r['pnl945_pct']:+.2f}% | "
                f"不卖→{r['pnl_no945_pct']:+.2f}% | 差{r['diff_pct']:+.2f}%"
            )


if __name__ == "__main__":
    main()
