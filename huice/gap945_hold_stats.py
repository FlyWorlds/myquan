"""统计持有时「低开 + 9:45 前未翻红」历史出现次数。"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pandas as pd

_MYQUAN_ROOT = Path(__file__).resolve().parents[1]
if str(_MYQUAN_ROOT) not in sys.path:
    sys.path.insert(0, str(_MYQUAN_ROOT))

from strategy import (
    build_gap_down_945_map,
    fetch_daily,
    fetch_minute_1m,
    has_double_yang_before,
    is_yin,
    prev_day_allows_entry,
)
from strategy.open_break import (
    TICK_SIZE,
    bar_close_at_time,
    entry_trigger_price,
    gap_down_flipped_red,
    morning_high_before_gap945,
    stop_trigger_price,
)

SYMBOL = "sh600552"
EM_SYMBOL = "600552"
SYMBOL_NAME = "凯盛科技"
START_DATE = "20200101"
END_DATE = dt.date.today().strftime("%Y%m%d")
THRESHOLD_PCT = 0.025
MIN1_CACHE = Path(__file__).with_name(f"{SYMBOL}_1m_qfq.parquet")


def classify_gap_days(daily: pd.DataFrame, minute: pd.DataFrame) -> pd.DataFrame:
    by_day: dict[str, pd.DataFrame] = {}
    if minute is not None and not minute.empty:
        m = minute.copy()
        m["day"] = m["ts"].dt.strftime("%Y-%m-%d")
        for d, grp in m.groupby("day"):
            by_day[str(d)] = grp.sort_values("ts")

    ts = pd.to_datetime(daily["date"])
    if ts.dt.tz is None:
        ts = ts.dt.tz_localize("Asia/Shanghai")
    df = daily.copy()
    df["day"] = ts.dt.strftime("%Y-%m-%d")
    for col in ("open", "high", "low", "close"):
        df[col] = pd.to_numeric(df[col])

    rows: list[dict] = []
    for i in range(1, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i - 1]
        day = str(row["day"])
        prev_close = float(prev["close"])
        o = float(row["open"])
        h = float(row["high"])
        if prev_close <= 0 or o <= 0 or o + 1e-12 >= prev_close:
            continue

        day_min = by_day.get(day)
        has_1m = day_min is not None and not day_min.empty
        if has_1m:
            day0 = day_min["ts"].dt.normalize().iloc[0]
            mh = morning_high_before_gap945(day_min, open_px=o, day0=day0)
            flipped = gap_down_flipped_red(mh, prev_close)
            exit945 = bar_close_at_time(day_min)
            if flipped:
                cat = "exact_945前已翻红"
            elif exit945 is not None:
                cat = "exact_945前未翻红"
            else:
                cat = "exact_无945K线"
        elif h + 1e-12 < prev_close:
            cat = "推断_945前未翻红(日高<昨收)"
            mh = h
        else:
            cat = "不确定_日高≥昨收(或945后翻红)"
            mh = h

        rows.append(
            {
                "day": day,
                "open": o,
                "prev_close": prev_close,
                "high": h,
                "close": float(row["close"]),
                "gap_pct": (o / prev_close - 1) * 100,
                "category": cat,
                "has_1m": has_1m,
                "morning_high": mh,
            }
        )
    return pd.DataFrame(rows)


def replay_holding_days(daily: pd.DataFrame) -> pd.DataFrame:
    ts = pd.to_datetime(daily["date"])
    if ts.dt.tz is None:
        ts = ts.dt.tz_localize("Asia/Shanghai")
    df = daily.copy()
    df["day"] = ts.dt.strftime("%Y-%m-%d")
    for col in ("open", "high", "low", "close"):
        df[col] = pd.to_numeric(df[col])

    armed = True
    entry_price = None
    buy_day = None
    pos = 0.0
    prev_open = prev_close = prev2_open = prev2_close = None
    holding_days: list[dict] = []

    for i in range(len(df)):
        row = df.iloc[i]
        day = str(row["day"])
        o = float(row["open"])
        h = float(row["high"])
        low = float(row["low"])
        c = float(row["close"])
        prev_c = float(df.iloc[i - 1]["close"]) if i > 0 else None

        entry_px = entry_trigger_price(o, entry_pct=THRESHOLD_PCT, tick=TICK_SIZE)
        stop_px = stop_trigger_price(o, stop_pct=THRESHOLD_PCT, tick=TICK_SIZE)
        hit_entry = h + 1e-12 >= entry_px
        hit_stop = low <= stop_px + 1e-12
        yin = is_yin(o, c)
        bought_today = False

        if (
            armed
            and pos <= 0
            and hit_entry
            and prev_open is not None
            and prev_close is not None
            and prev_day_allows_entry(
                prev_open, prev_close, prev_small_yang_pct=THRESHOLD_PCT
            )
            and not has_double_yang_before(
                prev2_open, prev2_close, prev_open, prev_close
            )
        ):
            pos = 1.0
            armed = False
            entry_price = entry_px
            buy_day = day
            bought_today = True

        sellable = pos > 0 and buy_day != day
        if sellable:
            holding_days.append(
                {
                    "day": day,
                    "buy_day": buy_day,
                    "entry": entry_price,
                    "prev_close": prev_c,
                    "open": o,
                    "high": h,
                    "close": c,
                }
            )

        if pos > 0 and not bought_today and buy_day != day:
            if hit_stop or yin:
                pos = 0.0
                armed = True
                entry_price = None
                buy_day = None

        prev2_open, prev2_close = prev_open, prev_close
        prev_open, prev_close = o, c

    return pd.DataFrame(holding_days)


def main() -> None:
    daily = fetch_daily(SYMBOL, START_DATE, END_DATE)
    minute = fetch_minute_1m(
        sina_symbol=SYMBOL,
        em_symbol=EM_SYMBOL,
        cache_path=MIN1_CACHE,
        start_date=START_DATE,
        end_date=END_DATE,
    )
    gap945_exact = build_gap_down_945_map(daily, minute)
    gap_df = classify_gap_days(daily, minute)
    hold_df = replay_holding_days(daily)
    hold_set = set(hold_df["day"])
    gap_df["holding"] = gap_df["day"].isin(hold_set)

    h = gap_df[gap_df["holding"]].copy()
    certain = h[
        h["category"].isin(
            ["exact_945前未翻红", "推断_945前未翻红(日高<昨收)"]
        )
    ]

    print(f"=== {SYMBOL_NAME}({SYMBOL}) 持有时·低开945前未翻红 统计 ===")
    print(f"区间: {START_DATE} ~ {END_DATE}")
    print(f"1分钟线覆盖: {minute['ts'].dt.strftime('%Y-%m-%d').nunique() if not minute.empty else 0} 个交易日")
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
    print(f"  占可卖持仓日比例: {len(certain)/len(hold_df)*100:.2f}%")
    print(f"  占持有时低开日比例: {len(certain)/len(h)*100:.2f}%" if len(h) else "")
    print()
    print(f"  回测945全清实际触发(需1m): {len([d for d in gap945_exact if d in hold_set])} 天")
    if gap945_exact:
        for d in sorted(gap945_exact):
            in_hold = d in hold_set
            g = gap945_exact[d]
            print(
                f"    {d} open={g['open_px']:.2f} prev={g['prev_close']:.2f} "
                f"exit945={g['exit_px']:.2f} 持有时={'是' if in_hold else '否'}"
            )

    print()
    print("--- 持有时·确定/推断 945前未翻红 明细 ---")
    if certain.empty:
        print("  (无)")
    else:
        merged = certain.merge(hold_df[["day", "buy_day", "entry"]], on="day", how="left")
        for _, r in merged.sort_values("day").iterrows():
            hold_ret = (r["open"] / float(r["entry"]) - 1) * 100 if r["entry"] else 0
            print(
                f"  {r['day']} 买于{r['buy_day']} entry={float(r['entry']):.2f} "
                f"open={r['open']:.2f} prev={r['prev_close']:.2f} high={r['high']:.2f} "
                f"低开{r['gap_pct']:.2f}% 类别={r['category']}"
            )

    print()
    print("--- 持有时·不确定（日高≥昨收，945前后翻红无法区分）---")
    unsure = h[h["category"] == "不确定_日高≥昨收(或945后翻红)"]
    print(f"  共 {len(unsure)} 天")
    for _, r in unsure.sort_values("day").head(20).iterrows():
        ep = hold_df.loc[hold_df["day"] == r["day"], "entry"].iloc[0]
        print(
            f"  {r['day']} entry={float(ep):.2f} open={r['open']:.2f} "
            f"prev={r['prev_close']:.2f} high={r['high']:.2f} 低开{r['gap_pct']:.2f}%"
        )
    if len(unsure) > 20:
        print(f"  ... 其余 {len(unsure)-20} 天略")


if __name__ == "__main__":
    main()
