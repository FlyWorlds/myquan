"""策略 vs 买入持有 — 分月收益对比."""
from __future__ import annotations

import akquant as aq
import pandas as pd

from kskj import (
    COMMISSION_RATE,
    END_DATE,
    FILL_CLOSE,
    INITIAL_CASH,
    OpenBreak3Strategy,
    SLIPPAGE,
    STAMP_TAX_RATE,
    START_DATE,
    SYMBOL,
    SYMBOL_NAME,
    fetch_daily,
)


def main() -> None:
    daily = fetch_daily(SYMBOL, START_DATE, END_DATE)
    result = aq.run_backtest(
        data=daily,
        strategy=OpenBreak3Strategy,
        symbols=SYMBOL,
        initial_cash=INITIAL_CASH,
        commission_rate=COMMISSION_RATE,
        stamp_tax_rate=STAMP_TAX_RATE,
        t_plus_one=True,
        lot_size=100,
        fill_policy=FILL_CLOSE,
        slippage=SLIPPAGE,
        timezone="Asia/Shanghai",
        show_progress=False,
    )

    px = daily.copy()
    px["date"] = pd.to_datetime(px["date"])
    if px["date"].dt.tz is None:
        px["date"] = px["date"].dt.tz_localize("Asia/Shanghai")
    close = px.set_index("date").sort_index()["close"]

    c0 = float(close.iloc[0])
    shares = int(INITIAL_CASH * 0.95 / c0 / 100) * 100

    eq = result.equity_curve_daily.copy()
    if eq.index.tz is not None:
        eq.index = eq.index.tz_convert("Asia/Shanghai")
    eq = eq.sort_index()

    # 月末权益 / 收盘价
    eq_m = eq.resample("ME").last().dropna()
    px_m = close.resample("ME").last().dropna()

    # 对齐月份索引
    months = eq_m.index.intersection(px_m.index)
    eq_m = eq_m.loc[months]
    px_m = px_m.loc[months]

    rows: list[dict] = []
    prev_eq = INITIAL_CASH
    prev_bh = shares * float(close.iloc[0])

    for ts in months:
        end_eq = float(eq_m.loc[ts])
        end_px = float(px_m.loc[ts])
        end_bh = shares * end_px

        s_pct = (end_eq / prev_eq - 1.0) * 100.0 if prev_eq > 0 else 0.0
        h_pct = (end_bh / prev_bh - 1.0) * 100.0 if prev_bh > 0 else 0.0
        excess = s_pct - h_pct

        rows.append(
            {
                "月份": ts.strftime("%Y-%m"),
                "策略%": round(s_pct, 2),
                "持有%": round(h_pct, 2),
                "超额%": round(excess, 2),
                "策略权益": round(end_eq, 0),
                "持有权益": round(end_bh, 0),
                "收盘": round(end_px, 2),
                "结果": "赢" if excess > 0.01 else ("平" if abs(excess) <= 0.01 else "输"),
            }
        )
        prev_eq = end_eq
        prev_bh = end_bh

    df = pd.DataFrame(rows)
    out_csv = __import__("pathlib").Path(__file__).with_name("kskj_monthly_vs_bh.csv")
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")

    print(f"=== {SYMBOL_NAME} 分月收益：策略 vs 买入持有 ===")
    print(f"区间: {months[0].strftime('%Y-%m')} ~ {months[-1].strftime('%Y-%m')}")
    print(f"持有基准: {shares}股 期初约95%资金买入不动")
    print()
    print(df.to_string(index=False))
    print()

    win = int((df["超额%"] > 0.01).sum())
    lose = int((df["超额%"] < -0.01).sum())
    flat = len(df) - win - lose
    print(f"月度统计: 跑赢 {win} / 跑输 {lose} / 持平 {flat}  共 {len(df)} 月")
    print(f"策略月均值: {df['策略%'].mean():+.2f}%  持有月均值: {df['持有%'].mean():+.2f}%")
    print(f"已保存: {out_csv.name}")


if __name__ == "__main__":
    main()
