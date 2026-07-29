"""统计持有时「低开 + 9:45 前未翻红」— CLI。"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strategy import (
    KAICHENG,
    build_gap_down_945_map,
    classify_gap_days,
    fetch_daily,
    load_minute,
    replay_holding_days,
)

CFG = replace(
    KAICHENG,
    min1_cache=Path(__file__).with_name(f"{KAICHENG.symbol}_1m_qfq.parquet"),
)


def main() -> None:
    daily = fetch_daily(CFG.symbol, CFG.start_date, CFG.end_date)
    minute = load_minute(CFG)
    gap945_exact = build_gap_down_945_map(daily, minute, exit_mode=CFG.gap945_exit_mode)
    gap_df = classify_gap_days(daily, minute)
    hold_df = replay_holding_days(daily, threshold_pct=CFG.threshold_pct, tick=CFG.tick)
    hold_set = set(hold_df["day"])
    gap_df["holding"] = gap_df["day"].isin(hold_set)

    h = gap_df[gap_df["holding"]].copy()
    certain = h[h["category"].isin(["exact_945前未翻红", "推断_945前未翻红(日高<昨收)"])]

    print(f"=== {CFG.symbol_name}({CFG.symbol}) 持有时·低开945前未翻红 统计 ===")
    print(f"区间: {CFG.start_date} ~ {CFG.end_date}")
    n_days = minute["ts"].dt.strftime("%Y-%m-%d").nunique() if not minute.empty else 0
    print(f"1分钟线覆盖: {n_days} 个交易日")
    print()
    print("【全市场低开日】")
    print(f"  低开日合计: {len(gap_df)}")
    for cat, n in gap_df["category"].value_counts().items():
        print(f"    {cat}: {n}")
    print()
    print("【策略持有时（T+1 可卖）】")
    print(f"  可卖持仓日合计: {len(hold_df)}")
    print(f"  其中低开日: {len(h)}")
    if len(h):
        for cat, n in h["category"].value_counts().items():
            print(f"    {cat}: {n}")
    print()
    print(f"  确定+推断「945前未翻红」: {len(certain)} 天")
    if len(hold_df):
        print(f"  占可卖持仓日比例: {len(certain)/len(hold_df)*100:.2f}%")
    if len(h):
        print(f"  占持有时低开日比例: {len(certain)/len(h)*100:.2f}%")
    print()
    n_hold_gap = len([d for d in gap945_exact if d in hold_set])
    print(f"  回测945全清实际触发(需1m): {n_hold_gap} 天")
    for d in sorted(gap945_exact):
        g = gap945_exact[d]
        print(
            f"    {d} open={g['open_px']:.2f} prev={g['prev_close']:.2f} "
            f"exit945={g['exit_px']:.2f} 持有时={'是' if d in hold_set else '否'}"
        )

    print()
    print("--- 持有时·确定/推断 945前未翻红 明细 ---")
    if certain.empty:
        print("  (无)")
    else:
        merged = certain.merge(hold_df[["day", "buy_day", "entry"]], on="day", how="left")
        for _, r in merged.sort_values("day").iterrows():
            print(
                f"  {r['day']} 买于{r['buy_day']} entry={float(r['entry']):.2f} "
                f"open={r['open']:.2f} prev={r['prev_close']:.2f} high={r['high']:.2f} "
                f"低开{r['gap_pct']:.2f}% 类别={r['category']}"
            )


if __name__ == "__main__":
    main()
