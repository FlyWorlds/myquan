"""分析 2015-05-29 策略是否买入及后续走势。"""
from __future__ import annotations

import pandas as pd
import akshare as ak

SYMBOL = "sh600552"
ENTRY_PCT = 0.025
STOP_PCT = 0.025
PREV_SMALL_YANG_PCT = 0.025
TARGET = "2015-05-29"


def fetch(start: str, end: str) -> pd.DataFrame:
    raw = ak.stock_zh_a_daily(symbol=SYMBOL, start_date=start, end_date=end, adjust="qfq")
    df = raw.copy()
    if "date" not in df.columns and "日期" in df.columns:
        df = df.rename(columns={"日期": "date"})
    df["date"] = pd.to_datetime(df["date"])
    for c in ("open", "high", "low", "close"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.sort_values("date").reset_index(drop=True)


def is_yang(o: float, c: float) -> bool:
    return c > o


def prev_allows(po: float, pc: float) -> bool:
    if po <= 0:
        return False
    if pc <= po:
        return True
    return (pc / po - 1) < PREV_SMALL_YANG_PCT


def double_yang(p2o, p2c, po, pc) -> bool:
    if None in (p2o, p2c, po, pc) or p2o <= 0 or po <= 0:
        return False
    return is_yang(p2o, p2c) and is_yang(po, pc)


def entry_px(o: float) -> float:
    return round(o * (1 + ENTRY_PCT), 2)


def stop_px(o: float) -> float:
    return round(o * (1 - STOP_PCT), 2)


def main() -> None:
    df = fetch("20150501", "20150731")
    target = pd.Timestamp(TARGET)
    window = df[
        (df["date"] >= target - pd.Timedelta(days=10))
        & (df["date"] <= target + pd.Timedelta(days=30))
    ]
    print("=== 2015-05 前后日线 (前复权) ===")
    for _, r in window.iterrows():
        d = r["date"].strftime("%Y-%m-%d")
        o, h, l, c = r["open"], r["high"], r["low"], r["close"]
        yang = "阳" if c > o else ("阴" if c < o else "平")
        chg = (c / o - 1) * 100 if o > 0 else 0
        print(f"{d}  O={o:.2f} H={h:.2f} L={l:.2f} C={c:.2f}  {yang} 日内{chg:+.2f}%")

    match = df[df["date"] == target]
    if match.empty:
        print(f"\n无 {TARGET} 数据")
        return

    i = int(match.index[0])
    row = df.iloc[i]
    prev = df.iloc[i - 1] if i >= 1 else None
    prev2 = df.iloc[i - 2] if i >= 2 else None
    o, h, l, c = row["open"], row["high"], row["low"], row["close"]
    ep, sp = entry_px(o), stop_px(o)
    hit_entry = h >= ep - 1e-12
    hit_stop = l <= sp + 1e-12

    print(f"\n=== {TARGET} 策略判定 ===")
    print(f"开盘={o:.2f} 最高={h:.2f} 最低={l:.2f} 收盘={c:.2f}")
    print(f"买点 open+2.5% = {ep:.2f}  触及: {hit_entry}")
    print(f"止损 open-2.5% = {sp:.2f}  触及: {hit_stop}")

    p2o = p2c = None
    if prev is not None:
        po, pc = prev["open"], prev["close"]
        if prev2 is not None:
            p2o, p2c = prev2["open"], prev2["close"]
            print(f"前二日: O={p2o:.2f} C={p2c:.2f}")
        print(f"前一日: O={po:.2f} C={pc:.2f}  允许={prev_allows(po, pc)}  双阳={double_yang(p2o, p2c, po, pc)}")

    can_buy = (
        hit_entry
        and prev is not None
        and prev_allows(prev["open"], prev["close"])
        and not double_yang(p2o, p2c, prev["open"], prev["close"])
    )
    if can_buy:
        print(f"结论: 策略会买入 @ {ep:.2f}")
    else:
        reasons = []
        if not hit_entry:
            reasons.append("未触及开盘+2.5%")
        if prev is not None and not prev_allows(prev["open"], prev["close"]):
            reasons.append("前日形态不符")
        if prev is not None and double_yang(p2o, p2c, prev["open"], prev["close"]):
            reasons.append("前面双阳")
        print("结论: 策略不会买入 — " + "；".join(reasons))

    # 同日双触：先买后能否止损
    if hit_entry and hit_stop:
        print("\n=== 同日双触 (high 触买 + low 触止损) ===")
        print("买入日 T+1：即使 low 打到止损，引擎也不会当日卖出")
        print(f"  买入 @ {ep:.2f}，当日最低 {l:.2f} <= 止损线 {sp:.2f}")

    if not can_buy:
        return

    print("\n=== 买入后后续 (T+1，按策略规则) ===")
    shares = int(95000 / ep / 100) * 100
    print(f"约 {shares} 股 @ {ep:.2f} (10万×95%)")
    buy_day = target
    in_pos = True
    entry = ep
    for j in range(i + 1, min(i + 30, len(df))):
        r = df.iloc[j]
        d = r["date"].strftime("%Y-%m-%d")
        o, h, l, c = r["open"], r["high"], r["low"], r["close"]
        sp_day = stop_px(o)
        hit_stop_day = l <= sp_day + 1e-12
        yin = c < o
        yang = c > o
        if not in_pos:
            break
        if hit_stop_day:
            days = (r["date"] - buy_day).days
            pnl = (sp_day / entry - 1) * 100
            print(f"{d} 止损 @ {sp_day:.2f} (low={l:.2f}) 持有{days}天 约{pnl:+.2f}%")
            in_pos = False
        elif yin:
            days = (r["date"] - buy_day).days
            pnl = (c / entry - 1) * 100
            print(f"{d} 阴线卖 @ {c:.2f} 持有{days}天 约{pnl:+.2f}%")
            in_pos = False
        elif yang:
            print(f"{d} 阳线持有 close={c:.2f} 浮盈{(c/entry-1)*100:+.2f}%")

    if in_pos:
        print("30 个交易日内未触发卖出")


if __name__ == "__main__":
    main()
