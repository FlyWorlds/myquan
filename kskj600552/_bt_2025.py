"""2025 至今策略回测摘要."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import akquant as aq
import pandas as pd

_PATH = Path(__file__).with_name("kskj.py")
spec = importlib.util.spec_from_file_location("kskj", _PATH)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

START = "20250101"
END = m.END_DATE


def main() -> None:
    daily = m.fetch_daily(m.SYMBOL, START, END)
    c0 = float(daily.iloc[0]["close"])
    c1 = float(daily.iloc[-1]["close"])
    bh_pct = (c1 / c0 - 1) * 100
    shares_bh = int(m.INITIAL_CASH / c0 / 100) * 100
    bh_end = shares_bh * c1

    result = aq.run_backtest(
        data=daily,
        strategy=m.OpenBreak3Strategy,
        symbols=m.SYMBOL,
        initial_cash=m.INITIAL_CASH,
        commission_rate=m.COMMISSION_RATE,
        stamp_tax_rate=m.STAMP_TAX_RATE,
        t_plus_one=True,
        lot_size=m.LOT_SIZE,
        fill_policy=m.FILL_CLOSE,
        slippage=m.SLIPPAGE,
        timezone="Asia/Shanghai",
        show_progress=False,
    )

    metrics = result.metrics_df

    def met(name: str) -> float:
        return float(metrics.loc[name, "value"]) if name in metrics.index else float("nan")

    eq = result.equity_curve_daily.copy()
    if eq.index.tz is not None:
        eq.index = eq.index.tz_convert("Asia/Shanghai")
    eq = eq.sort_index()
    end_eq = float(eq.iloc[-1])
    strat_pct = (end_eq / m.INITIAL_CASH - 1) * 100

    exec_df = result.executions_df.copy()
    if not exec_df.empty:
        exec_df["ts"] = pd.to_datetime(exec_df["timestamp"]).dt.tz_convert("Asia/Shanghai")

    tr = result.trades_df if hasattr(result, "trades_df") else pd.DataFrame()

    print("=" * 52)
    print(f"{m.SYMBOL_NAME} ({m.SYMBOL})  策略回测 {START} ~ {END}")
    print("=" * 52)
    print(f"区间: {daily['date'].iloc[0]} -> {daily['date'].iloc[-1]}  ({len(daily)} bars)")
    print(f"初始资金: {m.INITIAL_CASH:,.0f}")
    print(f"期末市值: {end_eq:,.2f}")
    print(f"总盈亏:   {met('total_pnl'):+,.2f}")
    print(f"累计收益: {strat_pct:+.2f}%")
    print(f"最大回撤: {met('max_drawdown_pct'):.2f}%")
    print(f"夏普:     {met('sharpe_ratio'):.4f}")
    print(f"闭环交易: {int(met('closed_trade_count'))}  胜率: {met('win_rate'):.1f}%")
    print()
    print("--- 买入持有对比 ---")
    print(f"首收->末收: {c0:.2f} -> {c1:.2f}  收益 {bh_pct:+.2f}%")
    print(f"持有期末:   {bh_end:,.2f}  ({shares_bh}股)")
    print(f"超额:       {end_eq - bh_end:+,.2f}  ({strat_pct - bh_pct:+.2f} pp)")
    print()

    px = daily.copy()
    px["date"] = pd.to_datetime(px["date"])
    if px["date"].dt.tz is None:
        px["date"] = px["date"].dt.tz_localize("Asia/Shanghai")

    for y in sorted(set(eq.index.year)):
        eq_y = eq[eq.index.year == y]
        if eq_y.empty:
            continue
        prev = eq[eq.index.year < y]
        base = float(prev.iloc[-1]) if len(prev) else m.INITIAL_CASH
        end = float(eq_y.iloc[-1])
        pct = (end / base - 1) * 100
        px_y = px[px["date"].dt.year == y]
        prev_px = px[px["date"].dt.year < y]
        if not px_y.empty:
            pc1 = float(px_y.iloc[-1]["close"])
            bpx = float(prev_px.iloc[-1]["close"]) if len(prev_px) else float(px_y.iloc[0]["close"])
            bhp = (pc1 / bpx - 1) * 100
        else:
            bhp = float("nan")
        n_buy = n_sell = 0
        if not exec_df.empty:
            mask = exec_df["ts"].dt.year == y
            side = exec_df.loc[mask, "side"].astype(str).str.lower()
            n_buy = int((side == "buy").sum())
            n_sell = int((side == "sell").sum())
        print(
            f"{y}年: 策略 {pct:+.2f}%  持有 {bhp:+.2f}%  "
            f"权益 {base:,.0f}->{end:,.0f}  买{n_buy}/卖{n_sell}"
        )

    print()
    print("--- 分月策略收益 ---")
    eq_m = eq.resample("ME").last().dropna()
    rows: list[dict] = []
    prev_v = m.INITIAL_CASH
    for ts, v in eq_m.items():
        if ts.year < 2025:
            prev_v = float(v)
            continue
        pct = (float(v) / prev_v - 1) * 100
        rows.append({"month": ts.strftime("%Y-%m"), "equity": round(v, 0), "ret%": round(pct, 2)})
        prev_v = float(v)
    print(pd.DataFrame(rows).to_string(index=False))

    if tr is not None and not tr.empty:
        pnl_col = next((c for c in ("net_pnl", "pnl") if c in tr.columns), None)
        close_col = next(
            (c for c in ("exit_time", "close_time", "end_time") if c in tr.columns), None
        )
        if pnl_col and close_col:
            cts = pd.to_datetime(tr[close_col])
            if getattr(cts.dt, "tz", None) is not None:
                cts = cts.dt.tz_convert("Asia/Shanghai")
            else:
                cts = cts.dt.tz_localize("Asia/Shanghai")
            t = tr[cts >= pd.Timestamp("2025-01-01", tz="Asia/Shanghai")]
            if not t.empty:
                pnls = pd.to_numeric(t[pnl_col], errors="coerce")
                print()
                print("--- 闭环交易 ---")
                print(
                    f"笔数 {len(t)}  合计 {pnls.sum():+,.0f}  "
                    f"赢 {(pnls > 0).sum()}  输 {(pnls <= 0).sum()}"
                )
                print(
                    f"均笔 {pnls.mean():+,.0f}  "
                    f"最大赢 {pnls.max():+,.0f}  最大亏 {pnls.min():+,.0f}"
                )


if __name__ == "__main__":
    main()
