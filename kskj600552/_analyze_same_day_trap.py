"""分析：买入日 high 触买 + low 触止损，是否同日能卖."""
from __future__ import annotations

import akquant as aq
import pandas as pd

from kskj import (
    COMMISSION_RATE,
    END_DATE,
    FILL_CLOSE,
    INITIAL_CASH,
    LOT_SIZE,
    OpenBreak3Strategy,
    SLIPPAGE,
    STAMP_TAX_RATE,
    START_DATE,
    SYMBOL,
    entry_trigger_price,
    fetch_daily,
    stop_trigger_price,
)


def main() -> None:
    daily = fetch_daily(SYMBOL, START_DATE, END_DATE)
    trap_days: list[str] = []
    for _, r in daily.iterrows():
        o, h, low = float(r["open"]), float(r["high"]), float(r["low"])
        ep = entry_trigger_price(o)
        sp = stop_trigger_price(o)
        if h + 1e-12 >= ep and low - 1e-12 <= sp:
            trap_days.append(pd.Timestamp(r["date"]).strftime("%Y-%m-%d"))

    print("=== K线同时满足 high>=买点 且 low<=止损 ===")
    print(f"共 {len(trap_days)} 天")

    result = aq.run_backtest(
        data=daily,
        strategy=OpenBreak3Strategy,
        symbols=SYMBOL,
        initial_cash=INITIAL_CASH,
        commission_rate=COMMISSION_RATE,
        stamp_tax_rate=STAMP_TAX_RATE,
        t_plus_one=True,
        lot_size=LOT_SIZE,
        fill_policy=FILL_CLOSE,
        slippage=SLIPPAGE,
        timezone="Asia/Shanghai",
        show_progress=False,
    )

    exec_df = result.executions_df.copy()
    exec_df["ts"] = pd.to_datetime(exec_df["timestamp"]).dt.tz_convert("Asia/Shanghai")
    exec_df["day"] = exec_df["ts"].dt.strftime("%Y-%m-%d")
    exec_df["side"] = exec_df["side"].str.lower()

    buy_days = set(exec_df.loc[exec_df["side"] == "buy", "day"])
    same_day_sell: list[str] = []
    for day, g in exec_df.groupby("day"):
        sides = set(g["side"])
        if "buy" in sides and "sell" in sides:
            same_day_sell.append(day)

    print("\n=== 回测实际：同日买+卖 ===")
    print(f"共 {len(same_day_sell)} 天")

    trapped: list[tuple[str, str]] = []
    for d in trap_days:
        if d not in buy_days:
            continue
        if d in same_day_sell:
            trapped.append((d, "same_day_sold"))
        else:
            # 找下一次卖出
            sells_after = exec_df[
                (exec_df["side"] == "sell") & (exec_df["day"] > d)
            ].sort_values("ts")
            next_sell = sells_after.iloc[0]["day"] if not sells_after.empty else "none"
            trapped.append((d, f"held_until_{next_sell}"))

    print("\n=== 策略买入日且 K 线双触（买+止损区）===")
    print(f"共 {len(trapped)} 笔")
    same = sum(1 for _, s in trapped if s == "same_day_sold")
    delayed = len(trapped) - same
    print(f"  同日卖出(回测): {same}")
    print(f"  未同日卖出: {delayed}")
    for d, status in trapped[:12]:
        print(f"  {d} -> {status}")


if __name__ == "__main__":
    main()
