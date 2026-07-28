"""策略 vs 买入持有 对比."""
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
        lot_size=LOT_SIZE,
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

    c0, c1 = float(close.iloc[0]), float(close.iloc[-1])
    shares = int(INITIAL_CASH * 0.95 / c0 / 100) * 100
    bh_end = shares * c1
    bh_ret = (bh_end / INITIAL_CASH - 1) * 100

    eq = result.equity_curve_daily.copy()
    if eq.index.tz is not None:
        eq.index = eq.index.tz_convert("Asia/Shanghai")
    eq = eq.sort_index()
    strat_end = float(eq.iloc[-1])
    strat_ret = (strat_end / INITIAL_CASH - 1) * 100

    m = result.metrics_df
    max_dd = float(m.loc["max_drawdown_pct", "value"]) if "max_drawdown_pct" in m.index else float("nan")

    print("=== 全期：策略 vs 买入持有 ===")
    print(f"标的: {SYMBOL_NAME} ({SYMBOL})")
    print(f"区间: {close.index[0].date()} ~ {close.index[-1].date()}")
    print(f"初始资金: {INITIAL_CASH:,.0f}")
    print()
    print(f"{'':12} {'期末资产':>14} {'累计收益':>10} {'最大回撤':>10}")
    print(f"{'策略':12} {strat_end:>14,.2f} {strat_ret:>+9.2f}% {max_dd:>9.2f}%")
    print(
        f"{'买入持有':12} {bh_end:>14,.2f} {bh_ret:>+9.2f}%"
        f"  ({shares}股 {c0:.2f}->{c1:.2f})"
    )
    print(f"{'超额(策略-持有)':12} {strat_end - bh_end:>+14,.2f} {strat_ret - bh_ret:>+9.2f} pp")
    print(f"策略/持有倍数: {strat_end / bh_end:.2f}x")
    print()

    years = sorted(set(eq.index.year) | set(close.index.year))
    rows: list[dict] = []
    for y in years:
        eq_y = eq[eq.index.year == y]
        px_y = close[close.index.year == y]
        if eq_y.empty or px_y.empty:
            continue
        prev_eq = eq[eq.index.year < y]
        base_eq = float(prev_eq.iloc[-1]) if not prev_eq.empty else float(eq_y.iloc[0])
        end_eq = float(eq_y.iloc[-1])
        s_pct = (end_eq / base_eq - 1) * 100

        c1y = float(px_y.iloc[-1])
        prev_px = close[close.index.year < y]
        base_c = float(prev_px.iloc[-1]) if not prev_px.empty else float(px_y.iloc[0])
        h_pct = (c1y / base_c - 1) * 100
        h_end = shares * c1y

        rows.append(
            {
                "年份": y,
                "策略收益%": round(s_pct, 2),
                "持有收益%": round(h_pct, 2),
                "超额%": round(s_pct - h_pct, 2),
                "策略权益": round(end_eq, 0),
                "持有权益": round(h_end, 0),
                "跑输/跑赢": "跑赢" if s_pct > h_pct else ("持平" if abs(s_pct - h_pct) < 0.01 else "跑输"),
            }
        )

    print("=== 分年对比 ===")
    print(pd.DataFrame(rows).to_string(index=False))
    print()
    win_years = sum(1 for r in rows if r["超额%"] > 0)
    print(f"分年跑赢持有: {win_years}/{len(rows)} 年")


if __name__ == "__main__":
    main()
